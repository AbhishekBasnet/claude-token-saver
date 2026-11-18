"""Effort Optimizer: suggest (or, in auto mode, set) the effort level per prompt.

Never blocks a prompt: the shim calls this after the prompt is on its way.
  1. free heuristics (conversational prompts are skipped outright);
  2. when they are unclear, the shim asks Haiku via $.model.complete with the
     prompt built here, then calls back with the model's JSON;
  3. decide(): act only when recommended != current and confidence >= 0.7,
     never the same suggestion twice in a row in one session.
Plain text, no emoji.
"""
from __future__ import annotations

import json
import re

import token_saver_common as ts

LEVELS = ["low", "medium", "high", "xhigh", "max"]
MIN_CONFIDENCE = 0.7

_CONVERSATIONAL = re.compile(
    r"^\s*(thanks?( you)?|thx|ty|ok(ay)?|k|yes|yep|yeah|no|nope|sure|cool|great|nice|perfect|good|"
    r"sounds good|looks good|lgtm|do it|go( ahead)?|continue|proceed|next|done|got it|right|agreed|"
    r"yes,? do it|ok,? do it|go on|carry on|keep going|that works|makes sense)[\s.!]*$", re.I)

_RULES = {
    "max": [r"\bprod(uction)?\b.{0,40}\b(config|database|db|deploy|migration|outage|incident)",
            r"\bmigrat\w+ .{0,30}\b(database|db|schema|data)\b", r"\bsecurity (audit|review)\b",
            r"\b(end[- ]to[- ]end|autonomous(ly)?|overnight)\b.{0,40}\b(build|implement|finish|complete)"],
    "high": [r"\barchitect", r"\bdesign\b.{0,40}\b(system|architecture|pipeline|schema|api)",
             r"\b(ci/?cd|pipeline|kubernetes|k8s|helm|terraform|ansible|docker[- ]compose|networking|load balancer)\b",
             r"\brefactor\b.{0,40}\b(across|all|whole|entire|codebase|modules|files)\b",
             r"\b(multi[- ]file|across (the )?(codebase|repo|modules))\b", r"\b(race condition|deadlock|memory leak|heisenbug)\b",
             r"\btricky\b", r"\binfra(structure)?\b"],
    "medium": [r"\b(implement|add)\b.{0,30}\b(feature|endpoint|function|command|option|support)\b",
               r"\b(write|add) (unit |integration )?tests?\b", r"\bdebug\b", r"\bexplain\b", r"\bwhy (does|is|did)\b",
               r"\bfix (the |this |a )?(bug|error|failing|crash)"],
    "low": [r"\brename\b", r"\btypo\b", r"\b(re)?format(ting)?\b", r"\bindent", r"\blint\b",
            r"\b(add|update|fix) (a |the )?(comment|docstring)", r"\bwhat (is|does|are)\b",
            r"\bhow do i\b", r"\bquick(ly)?\b", r"\bsmall (change|tweak|fix)\b", r"\bone[- ]line\b",
            r"\bchange .{1,40} to\b", r"\bbump (the )?version\b"],
}

CLASSIFY_SYSTEM = ("You choose the reasoning effort level for an AI coding assistant's next turn. "
                   "Reply with JSON only, no prose.")
CLASSIFY_PROMPT = """Effort levels:
- low: small edits, renames, formatting, quick factual questions, single-file tweaks, tasks where the user wants to stay in the loop
- medium: normal feature work, moderate debugging, writing tests, explaining code
- high: multi-file refactors, tricky bugs, architecture decisions, infra/DevOps changes (Kubernetes, Terraform, CI pipelines, networking)
- xhigh: hard multi-step coding or agentic work that needs sustained care
- max: genuinely hard long-running autonomous tasks, high-risk changes (prod config, migrations, security)

Current effort: {current}

The assistant's previous reply (truncated):
<previous>
{last_reply}
</previous>

The user's new prompt:
<prompt>
{prompt}
</prompt>

Answer with JSON: {{"recommended": "low|medium|high|xhigh|max", "confidence": 0.0-1.0, "reason": "one short line"}}"""


def heuristic(prompt: str) -> dict:
    """{"skip": True} | {"recommended", "confidence", "reason"} | {"unclear": True}"""
    p = (prompt or "").strip()
    if not p or p.startswith("/") or _CONVERSATIONAL.match(p):
        return {"skip": True}
    low = p.lower()
    hits = {}
    for level, pats in _RULES.items():
        for pat in pats:
            m = re.search(pat, low)
            if m:
                hits.setdefault(level, re.sub(r"\s+", " ", m.group(0)).strip()[:40])
                break
    if len(hits) == 1:
        (level, word), = hits.items()
        return {"recommended": level, "confidence": 0.8, "reason": f'"{word}"', "method": "heuristic"}
    if len(hits) > 1:
        # The highest-stakes signal wins when it is a high-risk one; otherwise ask the model.
        if "max" in hits:
            return {"recommended": "max", "confidence": 0.75, "reason": f'"{hits["max"]}"', "method": "heuristic"}
        return {"unclear": True}
    if len(p.split()) < 6:
        return {"skip": True}              # short, no signal: not worth a model call
    return {"unclear": True}


def model_prompt(prompt: str, current: str | None, transcript_path: str | None) -> str:
    last = (ts.read_transcript(transcript_path).get("last_reply") if transcript_path else None) or "(none)"
    return CLASSIFY_PROMPT.format(current=current or "unknown", last_reply=last[-6000:], prompt=prompt[:6000])


def parse_model(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        rec = str(d.get("recommended", "")).lower()
        if rec not in LEVELS:
            return None
        return {"recommended": rec, "confidence": float(d.get("confidence", 0)),
                "reason": str(d.get("reason", ""))[:120], "method": "haiku"}
    except (ValueError, TypeError):
        return None


def decide(session: str | None, current: str | None, c: dict, mode: str) -> dict:
    """{"text"?: one line for the user, "apply"?: level (auto mode)}."""
    rec, conf = c.get("recommended"), float(c.get("confidence", 0))
    if not current or current not in LEVELS or not rec or rec == current or conf < MIN_CONFIDENCE:
        return {}
    why = c.get("reason") or ""
    if mode != "auto":
        # Suggest mode: never show the same suggestion twice in a row. (Auto mode
        # acts on every prompt: a repeat there is a new change, not a repeated nag.)
        st = ts.session_state(session)
        key = f"{current}->{rec}"
        if st.get("effort_last_suggestion") == key:
            return {}
        st["effort_last_suggestion"] = key
        if session:
            ts.save_session_state(session, st)
    if mode == "auto":
        if LEVELS.index(rec) < LEVELS.index(current):
            ts.log_saving("effort_optimizer", session, None, None, None, f"effort {current} -> {rec} ({why})",
                          kind="effort_lowered", effort_from=current, effort_to=rec, method=c.get("method"))
        return {"apply": rec,
                "text": f"token-saver: effort {current} -> {rec} for this prompt ({why}). /mods set effort_optimizer.mode suggest to stop."}
    return {"text": f"token-saver: effort is {current}; this looks like a {rec} task ({why}). Run /effort {rec} to switch."}
