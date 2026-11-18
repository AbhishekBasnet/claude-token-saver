#!/usr/bin/env python3
"""Foundation probe (SessionStart): records that classic hooks fire and
shows a one-time 'installed' line. Doctor later reads events_seen."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts

EXPECTS = {"event": "SessionStart", "fields": {"session_id": "str", "source": "str"}}


def handle(event, ctx):
    state = ts.load_state()
    seen = state.setdefault("events_seen", {})
    seen["SessionStart"] = ts.now_iso()
    first = not state.get("welcomed")
    state["welcomed"] = True
    ts.save_state(state)
    ts.load_config()  # creates defaults on first run
    if event.get("model"):          # the session's main model (sub-agent router's fallback)
        sst = ts.session_state(event["session_id"])
        sst["main_model"] = event["model"]
        ts.save_session_state(event["session_id"], sst)
    if first:
        return {"systemMessage": "token-saver: installed. /mods lists the mods (available from step 1)."}
    return None


if __name__ == "__main__":
    sys.exit(ts.run_hook("foundation", EXPECTS, handle, check_enabled=False))
