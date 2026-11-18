"""Input Router: big reading material is read by Haiku first; the main model
gets a task-focused digest plus the path to the full thing.

PostToolUse on Read (and mcp__*): the tool runs for real (so Claude Code's
"file was read" bookkeeping stays correct) and the hook replaces what the
model sees via hookSpecificOutput.updatedToolOutput / updatedMCPToolOutput.
Every skip rule passes the result through untouched; so does any failure.
"""
from __future__ import annotations

import json
import os
import re
import time

import token_saver_common as ts

READING_EXT = {".txt", ".md", ".markdown", ".rst", ".srt", ".vtt", ".log", ".csv", ".tsv", ".json",
               ".jsonl", ".ndjson", ".xml", ".html", ".htm", ".yaml", ".yml"}
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock", "gemfile.lock",
             "composer.lock", "pipfile.lock", "go.sum", "uv.lock", "bun.lock", "flake.lock"}
FULL_WORDS = ("whole file", "full file", "entire file", "exact", "verbatim", "line by line", "word for word")
EDIT_WORDS = re.compile(r"\b(edit|modify|change|update|fix|rewrite|replace|patch|refactor|append|add to|remove from)\b")

CHUNK_CHARS = 300_000          # ~75k tokens: keeps each Haiku call under its 100k-token price step
MAX_CHARS = 2_400_000          # ~600k tokens: beyond this, pass through (too slow to digest in a hook)
MODEL_TIMEOUT = 60

SYSTEM = ("You digest documents for another AI assistant that will NOT see the original. "
          "Be faithful: never invent facts. Plain text, no emoji.")
DIGEST_PROMPT = """The assistant opened this file while working on the user's request below. Write a digest that lets it continue the task without the full text.

User's latest request:
<request>
{task}
</request>

File: {path} ({lines} lines){part}

Write, in this order:
1. DIGEST: the key facts, numbers, names, dates, decisions and conclusions relevant to the request (and the main points of the file in general). Quote at most 2 lines at a time, only where exact wording matters.
2. RELEVANT LINES: the line ranges of the most relevant sections, one per line, like "L120-L180: pricing discussion". Use the L-numbers shown in the file.
3. NOT COVERED: one line naming anything the request may need that this digest does not carry (say "nothing" if it is fully covered).

Keep the whole digest under {budget} words.

<file>
{content}
</file>"""
MERGE_PROMPT = """These are digests of consecutive parts of one file ({path}), written for the user's request below. Merge them into one digest with the same three sections (DIGEST, RELEVANT LINES, NOT COVERED). Keep every line range. Under {budget} words.

User's latest request:
<request>
{task}
</request>

{parts}"""

HEADER = "[Input Router] Haiku digest of {path} (~{before:,} -> ~{after:,} tokens, est.). Full file unchanged at {path}."
FOOTER = ("To read exact text, call Read again on {path} with offset/limit for the line ranges above "
          "(a Read with offset/limit is never digested).")


# ---------------------------------------------------------------- skip rules

def skip_reason(event: dict, cfg: dict, prompt: str | None) -> str | None:
    ti = event.get("tool_input") or {}
    path = str(ti.get("file_path") or "")
    if not path:
        return "no file_path"
    if any(ti.get(k) not in (None, "", 0) for k in ("offset", "limit", "pages")):
        return "offset/limit given"
    base = os.path.basename(path).lower()
    ext = os.path.splitext(base)[1]
    if ext == ".pdf":
        return "pdf (skipped by design)"
    if ext not in READING_EXT:
        return f"not reading material ({ext or 'no extension'})"
    if "/.git/" in path.replace("\\", "/") + "/" or base in LOCKFILES or base.endswith(".lock"):
        return ".git or lockfile"
    sst = ts.session_state(event.get("session_id"))
    if path in (sst.get("bypass_once") or []):
        return "bypass_once"
    p = (prompt or "").lower()
    for w in FULL_WORDS:
        if w in p:
            return f'prompt says "{w}"'
    stem = os.path.splitext(base)[0]
    if (base in p or (len(stem) >= 4 and stem in p)) and EDIT_WORDS.search(p):
        return "file is about to be edited"
    return None


def consume_bypass(session: str | None, path: str) -> None:
    if not session:
        return
    sst = ts.session_state(session)
    lst = sst.get("bypass_once") or []
    if path in lst:
        lst.remove(path)
        sst["bypass_once"] = lst
        ts.save_session_state(session, sst)


# ---------------------------------------------------------------- digest

def _numbered(text: str, start: int = 1) -> str:
    return "\n".join(f"L{i}: {l}" for i, l in enumerate(text.split("\n"), start))


def digest(path: str, text: str, task: str, model: str) -> tuple[str | None, str | None, dict]:
    """(digest, error, stats). Chunks large files, then merges."""
    lines = text.split("\n")
    budget = 350 if len(text) < 60_000 else 700
    stats = {"calls": 0, "ms": 0, "usage": []}
    t0 = time.time()

    def call(prompt):
        r = ts.call_model(model, SYSTEM, prompt, timeout=MODEL_TIMEOUT)
        stats["calls"] += 1
        if r.usage:
            stats["usage"].append(r.usage)
        return r

    if len(text) <= CHUNK_CHARS:
        r = call(DIGEST_PROMPT.format(task=task, path=path, lines=len(lines), part="", budget=budget,
                                      content=_numbered(text)))
        stats["ms"] = int((time.time() - t0) * 1000)
        return (r.text.strip(), None, stats) if r.ok and r.text and r.text.strip() else (None, r.error or "empty reply", stats)

    # Chunk on line boundaries, keep absolute line numbers.
    chunks, cur, size, start = [], [], 0, 1
    for i, l in enumerate(lines, 1):
        if size + len(l) > CHUNK_CHARS and cur:
            chunks.append((start, cur))
            cur, size, start = [], 0, i
        cur.append(l)
        size += len(l) + 1
    if cur:
        chunks.append((start, cur))
    parts = []
    for n, (s, ls) in enumerate(chunks, 1):
        r = call(DIGEST_PROMPT.format(task=task, path=path, lines=len(lines), budget=400,
                                      part=f", part {n} of {len(chunks)} (lines {s}-{s + len(ls) - 1})",
                                      content=_numbered("\n".join(ls), s)))
        if not r.ok or not (r.text or "").strip():
            stats["ms"] = int((time.time() - t0) * 1000)
            return None, f"chunk {n}: {r.error or 'empty reply'}", stats
        parts.append(f"--- part {n} (lines {s}-{s + len(ls) - 1}) ---\n{r.text.strip()}")
    r = call(MERGE_PROMPT.format(path=path, task=task, budget=budget, parts="\n\n".join(parts)))
    stats["ms"] = int((time.time() - t0) * 1000)
    if not r.ok or not (r.text or "").strip():
        return None, f"merge: {r.error or 'empty reply'}", stats
    return r.text.strip(), None, stats


# ---------------------------------------------------------------- Read

def _response_text(resp) -> str | None:
    """File text from Read's tool_response, whatever its shape."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        f = resp.get("file")
        if isinstance(f, dict) and isinstance(f.get("content"), str):
            return f["content"]
        for k in ("content", "text", "output"):
            if isinstance(resp.get(k), str):
                return resp[k]
    return None


def on_read(event: dict, cfg: dict) -> dict | None:
    sid = event.get("session_id")
    ti = event.get("tool_input") or {}
    path = str(ti.get("file_path") or "")
    prompt = ts.latest_prompt(event.get("transcript_path"))
    why = skip_reason(event, cfg, prompt)
    if why:
        if why == "bypass_once":
            consume_bypass(sid, path)
        ts.debug(f"[input_router] pass {path}: {why}")
        return None
    resp = event.get("tool_response")
    shown = _response_text(resp)                      # what Read would hand the model
    fobj = resp.get("file") if isinstance(resp, dict) and isinstance(resp.get("file"), dict) else {}
    truncated = bool(fobj.get("truncatedByTokenCap")) or (
        isinstance(fobj.get("numLines"), int) and isinstance(fobj.get("totalLines"), int)
        and fobj["numLines"] < fobj["totalLines"])
    text = shown
    if text is None or truncated:
        # Read stopped at its token cap (or gave no text): digest the whole file, so
        # the digest covers what Claude would otherwise have to page through.
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(MAX_CHARS + 1)
        except Exception as e:
            if text is None:
                ts.debug(f"[input_router] pass {path}: unreadable ({e})")
                return None
    before = ts.estimate_tokens(shown if shown is not None else text)
    if before <= int(cfg.get("threshold_tokens", 2000)):
        return None
    if len(text) > MAX_CHARS:
        ts.debug(f"[input_router] pass {path}: {len(text):,} chars is over the {MAX_CHARS:,} limit")
        return None
    model = cfg.get("model", "haiku")
    d, err, stats = digest(path, text, (prompt or "(not available)")[:3000], model)
    if not d:
        ts.record_error("input_router", f"digest failed for {path}: {err}", sid)
        return None                                   # fail open: the full file goes through
    body = "\n".join([HEADER.format(path=path, before=before, after=ts.estimate_tokens(d)), "", d, "",
                      FOOTER.format(path=path)])
    after = ts.estimate_tokens(body)
    ts.log_saving("input_router", sid, event.get("cwd"), before, after,
                  f"Read {os.path.basename(path)}: {model} digest ({stats['calls']} call(s), {stats['ms'] / 1000:.1f} s)",
                  path=path, model_calls=stats["calls"], ms=stats["ms"], model_usage=stats["usage"], estimate="len/4")
    pct = 100 - int(after * 100 / before) if before else 0
    ts.write_card(event.get("tool_use_id"), "input_router", "input router",
                  [f"{model} digested {os.path.basename(path)}",
                   f"{before:,} -> {after:,} tokens   (-{pct}%, est.)",
                   f"{stats['ms'] / 1000:.1f} s   full file: {path}"],
                  detail=d, path_=path)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": replacement(resp, body)}}


def replacement(resp, body: str):
    """Read's result is structured ({type, file: {content, numLines, ...}}); a plain
    string is ignored, so the digest goes in the same shape."""
    if isinstance(resp, dict) and isinstance(resp.get("file"), dict):
        f = dict(resp["file"])
        n = body.count("\n") + 1
        f.update({"content": body, "numLines": n, "startLine": 1, "totalLines": n, "truncatedByTokenCap": False})
        return {**resp, "file": f}
    return body


# ---------------------------------------------------------------- MCP

_B64 = re.compile(r"^[A-Za-z0-9+/=\s]{400,}$")
_DROP_KEYS = re.compile(r"(avatar|gravatar|thumbnail|icon_?url|image_?url|profile_?image|_links|etag)$", re.I)


def preclean(v, stats: dict):
    """Free, no-AI clean-up: drop null/empty fields, base64 blobs, avatar/image URLs."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if _DROP_KEYS.search(str(k)):
                stats["dropped"] += 1
                continue
            c = preclean(x, stats)
            if c is None or c == "" or c == [] or c == {}:
                stats["dropped"] += 1
                continue
            out[k] = c
        return out
    if isinstance(v, list):
        return [preclean(x, stats) for x in v if x not in (None, "", [], {})]
    if isinstance(v, str):
        if _B64.match(v) and " " not in v[:400]:
            stats["dropped"] += 1
            return f"[base64 data removed, {len(v):,} chars]"
        s = v.strip()
        if (s.startswith("{") or s.startswith("[")) and len(s) > 200:
            try:                                       # JSON inside a text block: clean that too
                return json.dumps(preclean(json.loads(s), stats), ensure_ascii=False)
            except ValueError:
                pass
    return v


def on_mcp(event: dict, cfg: dict) -> dict | None:
    sid = event.get("session_id")
    tool = str(event.get("tool_name") or "mcp")
    resp = event.get("tool_response")
    if resp is None:
        return None
    raw = json.dumps(resp, ensure_ascii=False)
    before = ts.estimate_tokens(raw)
    if before <= int(cfg.get("threshold_tokens", 2000)):
        return None
    prompt = ts.latest_prompt(event.get("transcript_path"))
    p = (prompt or "").lower()
    if any(w in p for w in FULL_WORDS):
        return None
    stats = {"dropped": 0}
    cleaned = preclean(resp, stats)
    cleaned_raw = json.dumps(cleaned, ensure_ascii=False)
    mid = ts.estimate_tokens(cleaned_raw)
    # Keep the raw result so Claude can Read it with offset/limit.
    safe_sid = "".join(c for c in (sid or "nosession") if c.isalnum() or c in "-_")[:80]
    d = ts.path("cache", safe_sid)
    os.makedirs(d, exist_ok=True)
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]", "_", tool)[:80]
    raw_path = os.path.join(d, f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_tool}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(resp, f, indent=1, ensure_ascii=False)
    if mid < before:
        ts.log_saving("input_router", sid, event.get("cwd"), before, mid,
                      f"{tool}: pre-clean (dropped {stats['dropped']} fields, no AI)", kind="mcp_preclean",
                      estimate="len/4")
    if mid <= int(cfg.get("threshold_tokens", 2000)):
        if mid >= before:
            return None
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": cleaned}}
    model = cfg.get("model", "haiku")
    text = json.dumps(cleaned, indent=1, ensure_ascii=False)
    dg, err, st = digest(raw_path, text, (prompt or "(not available)")[:3000], model)
    if not dg:
        ts.record_error("input_router", f"digest failed for {tool}: {err}", sid)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": cleaned}} \
            if mid < before else None
    body = "\n".join([f"[Input Router] Haiku digest of {tool} result (~{before:,} -> ~{ts.estimate_tokens(dg):,} tokens, est.). "
                      f"Full raw result saved at {raw_path}.", "", dg, "",
                      f"To read exact data, call Read on {raw_path} with offset/limit for the line ranges above."])
    after = ts.estimate_tokens(body)
    ts.log_saving("input_router", sid, event.get("cwd"), mid, after,
                  f"{tool}: {model} digest ({st['calls']} call(s), {st['ms'] / 1000:.1f} s)", kind="mcp_digest",
                  path=raw_path, model_usage=st["usage"], estimate="len/4")
    ts.write_card(event.get("tool_use_id"), "input_router", "input router",
                  [f"{model} digested {tool}", f"{before:,} -> {after:,} tokens   (est.)",
                   f"{st['ms'] / 1000:.1f} s   raw: {raw_path}"], detail=dg, path_=None)
    # Same shape as the tool's own result: a list of content blocks (or {content: [...]}).
    blocks = [{"type": "text", "text": body}]
    out = {**resp, "content": blocks} if isinstance(resp, dict) and "content" in resp else blocks
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": out}}
