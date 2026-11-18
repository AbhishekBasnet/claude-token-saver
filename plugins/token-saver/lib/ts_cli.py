#!/usr/bin/env python3
"""Command-line entry the TypeScript shim calls via $.process.run.
Prints JSON. Never raises (fail open)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import token_saver_common as ts


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "shim-loaded":
        st = ts.load_state()
        st["shim_loaded_at"] = ts.now_iso()
        if len(argv) > 1:
            st["shim_version"] = argv[1]
        ts.save_state(st)
        return {"ok": True}
    return {"ok": False, "error": f"unknown command {cmd!r}"}


if __name__ == "__main__":
    try:
        print(json.dumps(main(sys.argv[1:])))
    except Exception as e:
        ts.record_error("shim", e)
        print(json.dumps({"ok": False, "error": str(e)}))
