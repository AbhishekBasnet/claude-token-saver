"""Handoff: threshold warning, handoff document storage, auto-load.

The document itself is written by the session's own model through the shim's
$.model.fork (a tool-less question over the live transcript, served from its
prompt cache), so the doc never enters the main conversation. This module
holds the prompt, stores the result and loads it into the next session.
Plain text output, no emoji.
"""
from __future__ import annotations

import os
import re
import time

import token_saver_common as ts

MAX_AGE_STARTUP_S = 24 * 3600
WARN_STEP = 50_000

SECTIONS = [
    "Goal", "Current state", "Decisions made (and why)", "Files", "Commands & environment",
    "Open problems", "Next steps", "Skills, MCP tools, links & docs used",
    "Preferences the user showed this session",
]

PROMPT = """Write a handoff document so a fresh session with no memory of this conversation can continue the work without losing anything. It replaces this whole conversation, so it must be clearly better than a /compact summary.

Output ONLY the markdown document, starting with the line "# Handoff". Use exactly these sections, in this order, as "## " headings:

## Goal
What we are ultimately trying to do, and why.
## Current state
What is done and verified working; what is half-done. Name exact files, functions, commits.
## Decisions made (and why)
Each decision with its reason, including options we rejected and why they were rejected.
## Files
Created / modified / important files: full path and a one-line purpose each.
## Commands & environment
How to run, build and test (exact commands); env vars, ports, containers, versions, OS details.
## Open problems
Failing tests, exact error messages (verbatim, in code blocks), suspicions about causes.
## Next steps
Ordered, concrete, each one actionable on its own.
## Skills, MCP tools, links & docs used
Tools, docs, URLs and references that mattered.
## Preferences the user showed this session
Style, constraints, things they asked for or against (verbatim where it matters).

Rules: be specific (exact names, paths, numbers, error strings); no vague phrases like "various files"; say "unknown" rather than guessing; keep secrets and API keys out of the document."""


def project_slug(cwd: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd or os.getcwd()))[:150]


def handoff_dir(cwd: str | None) -> str:
    return ts.path("handoffs", project_slug(cwd))


def latest_path(cwd: str | None) -> str:
    return os.path.join(handoff_dir(cwd), "LATEST.md")


# ---------------------------------------------------------------- save -----

def save(session: str | None, cwd: str | None, doc: str, context_tokens: int,
         fork_usage: dict | None = None) -> str:
    doc = (doc or "").strip()
    if not doc.startswith("#"):
        raise ValueError("model reply is not a markdown handoff document")
    missing = [s for s in SECTIONS if f"## {s}".lower() not in doc.lower()]
    d = handoff_dir(cwd)
    os.makedirs(d, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    header = (f"<!-- token-saver handoff | project: {os.path.abspath(cwd or os.getcwd())} | "
              f"session: {session} | written: {ts.now_iso()} -->\n\n")
    body = header + doc + "\n"
    p = os.path.join(d, f"{stamp}.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(d, "LATEST.md"), "w", encoding="utf-8") as f:
        f.write(body)
    doc_tokens = ts.estimate_tokens(doc)
    # A fresh session still carries the system prompt + tools: use the context of
    # this session's first reply as that baseline, so the saving is not overstated.
    baseline = first_context(session, cwd)
    after = doc_tokens + (baseline or 0)
    u = fork_usage or {}
    cost = (f"fork: {u.get('cache_read_input_tokens', 0):,} cached + {u.get('input_tokens', 0):,} uncached in, "
            f"{u.get('output_tokens', 0):,} out")
    ts.log_saving("handoff", session, cwd, int(context_tokens or 0), after,
                  f"handoff {os.path.basename(p)}: per later message ({cost})",
                  fork_usage=u, doc_tokens=doc_tokens, baseline_tokens=baseline)
    base_txt = f"{baseline:,} fresh-session baseline + " if baseline else ""
    text = (f"Handoff saved: {p}\n"
            f"  context now {int(context_tokens or 0):,} tokens -> next session ~{after:,} "
            f"({base_txt}~{doc_tokens:,} doc, est.)\n"
            f"  {cost}")
    if missing:
        text += f"\n  warning: sections missing: {', '.join(missing)}"
    text += "\nRun /clear (or start a new session here): it will load automatically."
    return text


def first_context(session: str | None, cwd: str | None) -> int | None:
    """Context size of this session's first reply (system prompt + tools + first
    prompt), read from the transcript Claude Code keeps for the project."""
    if not session:
        return None
    tdir = os.environ.get("TOKEN_SAVER_PROJECTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "projects")
    tpath = os.path.join(tdir, project_slug(cwd), f"{session}.jsonl")
    if not os.path.exists(tpath):
        return None
    try:
        import json
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"assistant"' not in line or '"usage"' not in line:
                    continue
                d = json.loads(line)
                u = (d.get("message") or {}).get("usage")
                if d.get("type") == "assistant" and not d.get("isSidechain") and isinstance(u, dict):
                    return (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                            + u.get("cache_creation_input_tokens", 0))
    except Exception as e:
        ts.debug(f"[handoff] baseline: {e}")
    return None


# ---------------------------------------------------------------- load -----

def _consume(cwd: str | None) -> tuple[str, str] | None:
    """Read LATEST.md and rename it so it never loads twice. (text, written-time)."""
    lp = latest_path(cwd)
    if not os.path.exists(lp):
        return None
    with open(lp, encoding="utf-8") as f:
        text = f.read()
    written = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(lp)))
    os.replace(lp, os.path.join(os.path.dirname(lp), f"loaded-{time.strftime('%Y%m%d-%H%M%S')}.md"))
    return text, written


def context_block(text: str, written: str) -> str:
    return (f"[Handoff] Continuing from previous session ({written}). Read this first:\n\n{text}")


def load_now(cwd: str | None) -> tuple[str, str | None]:
    """/handoff load: (message for the user, context for the model or None)."""
    got = _consume(cwd)
    if not got:
        return "No handoff waiting for this project.", None
    text, written = got
    return (f"Loaded handoff from {written} (~{ts.estimate_tokens(text):,} tokens). "
            "Claude reads it with your next message."), context_block(text, written)


def on_session_start(event: dict) -> dict | None:
    source = event.get("source")
    cwd = event.get("cwd")
    lp = latest_path(cwd)
    if not os.path.exists(lp):
        return None
    if source == "clear":
        text, written = _consume(cwd)
        return {
            "systemMessage": f"handoff: loaded handoff from {written} (~{ts.estimate_tokens(text):,} tokens).",
            "hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": context_block(text, written)},
        }
    if source == "startup":
        age = time.time() - os.path.getmtime(lp)
        if age < MAX_AGE_STARTUP_S:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(lp)))
            return {"systemMessage": f"handoff: a handoff from {when} is waiting for this project. "
                                     "Run /handoff load to continue from it."}
    return None


# ---------------------------------------------------------------- warning --

def on_stop(event: dict, cfg: dict) -> dict | None:
    sid = event.get("session_id")
    usage = ts.last_usage(event.get("transcript_path"))
    if not usage:
        return None
    ctx = usage["context_tokens"]
    threshold = int(cfg.get("threshold_tokens", 250_000))
    if ctx < threshold:
        return None
    st = ts.session_state(sid)
    last = int(st.get("handoff_warned_at", 0))
    if last and ctx < last + WARN_STEP:
        return None
    st["handoff_warned_at"] = ctx
    ts.save_session_state(sid, st)
    return {"systemMessage": f"handoff: context at {ctx // 1000}k tokens. "
                             "Run /handoff to continue in a fresh session."}
