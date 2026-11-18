#!/usr/bin/env python3
"""Command-line entry the TypeScript shim calls via $.process.run.

  ts_cli.py shim-loaded <version>
  ts_cli.py mods    <session_id> <args as typed>
  ts_cli.py savings <session_id> <args as typed>
  ts_cli.py bypass  <session_id> <file_path>     next Read of this file is untouched

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
    return {"ok": False, "error": f"unknown command {cmd!r}"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1:])))
    except Exception as e:
        ts.record_error("shim", e)
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
