"""Sub-agent router: run each sub-agent on the cheapest model that can do its job.

PreToolUse on Agent|Task: classify description + prompt (free keyword
heuristics first, Haiku only when they are unclear) and set tool_input.model.
  * an explicit model is never touched
  * subagent_type "fork" is skipped (the API ignores model there)
  * never routes *up*: a route at or above the main model leaves model unset
    (the sub-agent inherits), and allow_opus=false caps the route at sonnet
SubagentStop: read the sub-agent's own transcript for real usage and log the
estimated $ difference against the main model. Tokens are the same either
way, so the entry has no before/after token numbers (shown as n/a).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

import token_saver_common as ts

RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}

# USD per million tokens, Anthropic first-party list prices (claude-api reference,
# cached 2026-11-03). Cache writes: 1.25x input (5 min TTL), 2x input (1 h TTL).
# Haiku 5.5's cache-read price is not listed: 0.1x input is assumed (est.).
PRICES = {
    "opus":   {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "sonnet": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
    "haiku":  {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "fable":  {"input": 8.00, "output": 40.00, "cache_read": 0.20},
}

_OPUS = [
    r"\barchitect", r"\bdesign (the|a|an)\b.{0,30}\b(system|architecture|api|schema)", r"\bsecurity\b",
    r"\bvulnerab", r"\bthreat model", r"\bpentest", r"\bauth\w* (review|audit)",
    r"\broot[- ]cause", r"\brace condition", r"\bdeadlock", r"\bdebug\w* .{0,30}\b(across|multiple|several|many)\b",
    r"\bprod(uction)?\b.{0,30}\b(config|deploy|change|incident)", r"\b(terraform|kubernetes|k8s|helm)\b",
    r"\binfra(structure)? (change|config)", r"\bmigrat\w+ (the )?(database|db|schema|data)",
    r"\bfinal (review|verification|check)", r"\bhigh[- ]stakes",
]
_SONNET = [
    r"\b(write|implement|build|create|add)\s+((a|an|the|new|some|unit|integration|missing|more)\s+){0,3}(code|functions?|class(es)?|modules?|features?|endpoints?|components?|scripts?|tests?)\b",
    r"\brefactor", r"\bfix\b", r"\b(write|add|generate) (unit |integration )?tests?\b", r"\breview\b",
    r"\bexplain\b", r"\bresearch\b", r"\bcompare\b", r"\banaly[sz]e\b", r"\bplan\b", r"\bpropose\b",
]
_HAIKU = [
    r"\bfind\b", r"\blocate\b", r"\blist\b", r"\bsearch\b", r"\bgrep\b", r"\bwhere (is|are|does)\b",
    r"\bwhich files?\b", r"\bsummari[sz]e\b", r"\bsummary\b", r"\bextract\b", r"\bcount\b", r"\blook ?up\b",
    r"\bfetch\b", r"\bread (the |these |this )?(docs?|documentation|logs?|readme|page)", r"\bscan\b",
    r"\bcollect\b", r"\bgather\b", r"\binventory\b",
]

CLASSIFY_SYSTEM = ("You route sub-agent tasks to the cheapest capable model. Reply with exactly one "
                   "lowercase word: haiku, sonnet or opus.")
CLASSIFY_PROMPT = """haiku: finding or listing files, grep-style searches, reading and summarising docs or logs, extracting lists or numbers, simple lookups.
sonnet: writing ordinary code, reviewing a few files, research that needs synthesis, writing tests, explaining code.
opus: architecture and design, security review, debugging across many files, production or infrastructure changes, final verification of high-stakes work.

Sub-agent task:
description: {description}
prompt: {prompt}

Model:"""


def _hits(patterns, text):
    """Matched text of each pattern that hits, e.g. ["root cause"]."""
    out = []
    for p in patterns:
        m = re.search(p, text)
        if m:
            out.append(re.sub(r"\s+", " ", m.group(0)).strip()[:40])
    return out


def heuristic(description: str, prompt: str, subagent_type: str | None) -> tuple[str | None, str]:
    """(route or None when unclear, reason)."""
    text = f"{description}\n{prompt[:4000]}".lower()
    o = _hits(_OPUS, text)
    if o:
        return "opus", f"keyword: \"{o[0]}\""
    s = _hits(_SONNET, text)
    h = _hits(_HAIKU, text)
    if (subagent_type or "").lower() == "explore" and not s:
        return "haiku", "Explore sub-agent (read-only search)"
    if h and not s:
        return "haiku", f"keyword: \"{h[0]}\""
    if s and not h:
        return "sonnet", f"keyword: \"{s[0]}\""
    return None, "unclear (search and write signals)" if (s and h) else "unclear (no signal)"


def classify_with_model(description: str, prompt: str, model: str) -> tuple[str | None, str, int]:
    r = ts.call_model(model, CLASSIFY_SYSTEM,
                      CLASSIFY_PROMPT.format(description=description[:300], prompt=prompt[:1500]), timeout=20)
    if not r.ok:
        return None, f"{model} classifier failed: {r.error}", r.ms
    word = (r.text or "").strip().lower().split()
    route = word[0].strip(".,:") if word else ""
    if route not in ("haiku", "sonnet", "opus"):
        return None, f"{model} classifier gave {r.text!r}", r.ms
    return route, f"{model} classifier", r.ms


def family(model_id: str | None) -> str | None:
    m = (model_id or "").lower()
    for f in ("haiku", "sonnet", "opus", "fable", "mythos"):
        if f in m:
            return "fable" if f == "mythos" else f
    return None


def _settings_model() -> str | None:
    p = os.path.join(os.environ.get("TOKEN_SAVER_CLAUDE_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                     "settings.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("model")
    except Exception:
        return None


def main_model(event: dict) -> str:
    """The session's main model family: the latest main-thread reply (follows /model),
    else what SessionStart reported, else the settings' model, else opus."""
    last = ts.last_usage(event.get("transcript_path"))
    for _ in range(4):              # first turn: the reply carrying this call may not be flushed yet
        if last or not event.get("transcript_path") or not os.path.exists(event["transcript_path"]):
            break
        time.sleep(0.25)
        last = ts.last_usage(event.get("transcript_path"))
    return (family((last or {}).get("model"))
            or family(ts.session_state(event.get("session_id")).get("main_model"))
            or family(_settings_model()) or "opus")


def prompt_key(prompt: str) -> str:
    return hashlib.sha1((prompt or "").strip().encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------- PreToolUse

def on_pre_tool_use(event: dict, cfg: dict) -> dict | None:
    ti = event.get("tool_input")
    if not isinstance(ti, dict):
        return None
    if ti.get("model"):
        return None                                   # explicit choice: leave alone
    stype = ti.get("subagent_type") or ""
    if stype == "fork":
        return None
    desc, prompt = str(ti.get("description") or ""), str(ti.get("prompt") or "")
    sid = event.get("session_id")

    main = main_model(event)

    t0 = time.time()
    route, reason = heuristic(desc, prompt, stype)
    method = "heuristic"
    if route is None:
        route, why, _ms = classify_with_model(desc, prompt, cfg.get("classifier_model", "haiku"))
        method, reason = ("haiku" if route else "none"), (why if route else f"{reason}; {why}")
    ms = int((time.time() - t0) * 1000)
    if route is None:
        ts.health("route_skipped", "subagent_router", session=sid, reason=reason[:200])
        return None
    if route == "opus" and cfg.get("allow_opus", True) is False:
        route, reason = "sonnet", reason + " (allow_opus off: capped at sonnet)"
    if RANK[route] >= RANK.get(main, 2):
        ts.health("route_kept", "subagent_router", session=sid, route=route, main=main, reason=reason[:200])
        return None                                   # inherit the main model: never route up

    st = ts.session_state(sid)
    routes = st.setdefault("subagent_routes", {})
    routes[prompt_key(prompt)] = {"route": route, "main": main, "description": desc[:120],
                                  "reason": reason[:200], "method": method, "ts": ts.now_iso()}
    if len(routes) > 200:                             # keep the state file small
        for k in sorted(routes, key=lambda k: routes[k].get("ts", ""))[:-200]:
            routes.pop(k, None)
    if sid:
        ts.save_session_state(sid, st)

    short = desc if len(desc) <= 48 else desc[:45] + "..."
    ts.write_card(event.get("tool_use_id"), "subagent_router", "sub-agent router",
                  [f'"{short}" -> {route}  (main: {main})', reason[:60], f"{method}, {ms} ms"])
    new_input = dict(ti)
    new_input["model"] = route
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": new_input}}


# ---------------------------------------------------------------- SubagentStop

def _cost(u: dict, fam: str) -> float:
    p = PRICES[fam]
    cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    w1h = int(cc.get("ephemeral_1h_input_tokens", 0) or 0)
    w5m = int(cc.get("ephemeral_5m_input_tokens", 0) or 0)
    wall = int(u.get("cache_creation_input_tokens", 0) or 0)
    if w1h + w5m < wall:                              # no breakdown: assume 5 min writes
        w5m = wall - w1h
    return (int(u.get("input_tokens", 0) or 0) * p["input"] + int(u.get("output_tokens", 0) or 0) * p["output"]
            + int(u.get("cache_read_input_tokens", 0) or 0) * p["cache_read"]
            + w5m * p["input"] * 1.25 + w1h * p["input"] * 2.0) / 1e6


def read_agent_transcript(tpath: str) -> dict:
    """First prompt text, model family, summed usage of every request."""
    out = {"prompt": None, "model": None, "requests": 0,
           "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0,
                     "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}}
    seen = set()
    with open(tpath, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and out["prompt"] is None:
                txt = ts._text_of(msg.get("content"))
                if txt.strip():
                    out["prompt"] = txt
            elif d.get("type") == "assistant" and isinstance(msg.get("usage"), dict):
                rid = msg.get("id") or d.get("requestId") or d.get("uuid")
                if rid in seen:                       # one request can span several entries
                    continue
                seen.add(rid)
                out["model"] = family(msg.get("model")) or out["model"]
                out["requests"] += 1
                u, tot = msg["usage"], out["usage"]
                for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    tot[k] += int(u.get(k, 0) or 0)
                cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
                for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
                    tot["cache_creation"][k] += int(cc.get(k, 0) or 0)
    return out


def on_subagent_stop(event: dict) -> None:
    tpath = event.get("agent_transcript_path")
    if not tpath or not os.path.exists(tpath):
        return None
    sid = event.get("session_id")
    st = ts.session_state(sid)
    routes = st.get("subagent_routes") or {}
    a = read_agent_transcript(tpath)
    rec = routes.get(prompt_key(a["prompt"] or "")) if a["prompt"] else None
    if not rec:
        return None                                   # not one we routed
    ran, main = a["model"] or rec["route"], rec["main"]
    if ran not in PRICES or main not in PRICES:
        return None
    u = a["usage"]
    actual, at_main = _cost(u, ran), _cost(u, main)
    total = u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
    ts.log_saving("subagent_router", sid, event.get("cwd"), None, None,
                  f'sub-agent "{rec["description"][:50]}" on {ran} instead of {main}: '
                  f"${actual:.4f} vs ${at_main:.4f} (est.)",
                  kind="routed", usd_saved_est=round(at_main - actual, 6), usd_actual_est=round(actual, 6),
                  usd_main_est=round(at_main, 6), routed_model=ran, main_model=main,
                  agent_type=event.get("agent_type"), requests=a["requests"],
                  input_tokens_total=total, output_tokens=u["output_tokens"])
    routes.pop(prompt_key(a["prompt"]), None)
    ts.save_session_state(sid, st)
    return None
