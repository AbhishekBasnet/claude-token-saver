#!/usr/bin/env python3
"""Command-line entry the TypeScript shim calls via $.process.run.

  ts_cli.py shim-loaded <version>
  ts_cli.py mods    <session_id> <args as typed>
  ts_cli.py savings <session_id> <args as typed>
  ts_cli.py bypass  <session_id> <file_path>     next Read of this file is untouched
  ts_cli.py handoff-prompt <session_id> [notes]   {"text": fork prompt} or ok=false if mod off
  ts_cli.py handoff-save <session_id> <ctx_tokens> <usage_json> [notes]   (doc on stdin)
  ts_cli.py handoff-load <session_id>             {"text", "context"}
  ts_cli.py keepwarm-log <session_id> <usage_json>  log a ping, restart the clock
  ts_cli.py effort-check  <session_id> [current]  (prompt on stdin) {"action": none|ask|classified}
  ts_cli.py effort-model  <session_id>            (Haiku reply on stdin) {"action": none|classified}
  ts_cli.py effort-decide <session_id> <current>  (classification on stdin) {"text"?, "apply"?}

Prints one JSON object: {"ok": bool, "text"?: str, "error"?: str}.
Never raises (fail open).
"""
import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import token_saver_common as ts  # noqa: E402


def _split(s: str) -> list:
    try:
        return shlex.split(s)
    except ValueError:
        return s.split()


def _transcript_for(session):
    """This session's transcript: ~/.claude/projects/<cwd slug>/<session>.jsonl."""
    if not session:
        return None
    import handoff
    tdir = os.environ.get("TOKEN_SAVER_PROJECTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "projects")
    p = os.path.join(tdir, handoff.project_slug(os.getcwd()), f"{session}.jsonl")
    return p if os.path.exists(p) else None


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "shim-loaded":
        st = ts.load_state()
        st["shim_loaded_at"] = ts.now_iso()
        if len(argv) > 1:
            st["shim_version"] = argv[1]
        ts.save_state(st)
        return {"ok": True}
    if cmd in ("mods", "savings"):
        import switchboard
        session = argv[1] if len(argv) > 1 and argv[1] else None
        args = _split(argv[2]) if len(argv) > 2 else []
        fn = switchboard.mods_cmd if cmd == "mods" else switchboard.savings_cmd
        text = fn(args, session)
        # Claude Code already labels command output with the plugin name.
        for prefix in ("token-saver: ", "token-saver "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        return {"ok": True, "text": text}
    if cmd == "bypass":
        session, fpath = argv[1], argv[2]
        st = ts.session_state(session)
        st.setdefault("bypass_once", [])
        if fpath not in st["bypass_once"]:
            st["bypass_once"].append(fpath)
        ts.save_session_state(session, st)
        return {"ok": True, "text": f"next read of {fpath} will be the full file"}
    if cmd.startswith("handoff-"):
        import handoff
        session = argv[1] if len(argv) > 1 and argv[1] else None
        if cmd == "handoff-prompt":
            if not ts.is_enabled("handoff", session):
                return {"ok": False, "text": "handoff is off (or mods are paused). /mods on handoff to use it."}
            return {"ok": True, "text": handoff.prompt_with_notes(argv[2] if len(argv) > 2 else None)}
        if cmd == "handoff-save":
            try:
                usage = json.loads(argv[3]) if len(argv) > 3 else {}
            except ValueError:
                usage = {}
            try:
                text = handoff.save(session, os.getcwd(), sys.stdin.read(), int(argv[2] or 0), usage,
                                    notes=argv[4] if len(argv) > 4 else None)
            except ValueError as e:
                ts.record_error("handoff", e, session)
                return {"ok": False, "text": f"handoff not saved: {e}"}
            return {"ok": True, "text": text}
        if cmd == "handoff-load":
            text, context = handoff.load_now(os.getcwd())
            return {"ok": True, "text": text, "context": context}
    if cmd == "keepwarm-log":
        session = argv[1] if len(argv) > 1 else None
        try:
            u = json.loads(argv[2]) if len(argv) > 2 else {}
        except ValueError:
            u = {}
        ts.health("keepwarm_ping", "cache_clock", session=session, usage=u)
        st = ts.session_state(session) if session else {}
        st["keepwarm_pings"] = int(st.get("keepwarm_pings", 0)) + 1
        if session:
            ts.save_session_state(session, st)
            import cache_clock
            cache_clock.on_keepwarm_ping(session, u)
        return {"ok": True, "text": (f"keep-warm ping: {u.get('cache_read_input_tokens', 0):,} tokens read from cache, "
                                     f"{u.get('input_tokens', 0):,} uncached, {u.get('cache_creation_input_tokens', 0):,} written, "
                                     f"{u.get('output_tokens', 0):,} out")}
    if cmd in ("effort-check", "effort-model", "effort-decide"):
        # check: prompt on stdin -> classification, or "ask" (shim asks Haiku)
        # model: Haiku's reply on stdin -> classification
        # decide <current>: classification JSON on stdin -> text / apply (needs the current level)
        import effort_optimizer as eo
        session = argv[1] if len(argv) > 1 and argv[1] else None
        cfg = ts.load_config().get("effort_optimizer", {})
        if not ts.is_enabled("effort_optimizer", session):
            return {"ok": True, "action": "none"}
        mode = cfg.get("mode", "suggest")
        if cmd == "effort-decide":
            current = argv[2] if len(argv) > 2 and argv[2] else None
            try:
                c = json.loads(sys.stdin.read() or "{}")
            except ValueError:
                c = {}
            return {"ok": True, "action": "done", "current": current, "mode": mode, **eo.decide(session, current, c, mode)}
        if cmd == "effort-check":
            prompt = sys.stdin.read()
            c = eo.heuristic(prompt)
            if c.get("skip"):
                return {"ok": True, "action": "none"}
            if c.get("unclear"):
                cur = argv[2] if len(argv) > 2 and argv[2] else None
                return {"ok": True, "action": "ask", "model": cfg.get("model", "haiku"), "system": eo.CLASSIFY_SYSTEM,
                        "prompt": eo.model_prompt(prompt, cur, _transcript_for(session))}
        else:
            c = eo.parse_model(sys.stdin.read())
            if not c:
                return {"ok": True, "action": "none"}
        return {"ok": True, "action": "classified", "mode": mode, "classification": c}
    if cmd == "keepwarm":
        return {"ok": True, "text": "keep-warm is under investigation (build step 4); only /keepwarm ping works for now."}
    return {"ok": False, "error": f"unknown command {cmd!r}"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1:])))
    except Exception as e:
        ts.record_error("shim", e)
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
