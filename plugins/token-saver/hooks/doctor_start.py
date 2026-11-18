#!/usr/bin/env python3
"""Doctor (SessionStart): update detection + self-test, conflict scan.
Always on (not a switchable mod). Fails open like every hook."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "SessionStart", "fields": {"session_id": "str", "cwd": "str"}}


def handle(event, ctx):
    import doctor
    notice = doctor.on_session_start(event)
    return {"systemMessage": notice} if notice else None


if __name__ == "__main__":
    sys.exit(ts.run_hook("doctor", EXPECTS, handle, check_enabled=False))
