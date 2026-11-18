#!/usr/bin/env python3
"""Handoff (Stop): warn once when context passes the threshold, then every +50k."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "Stop", "fields": {"session_id": "str", "transcript_path": "str"}}


def handle(event, ctx):
    if event.get("agent_id"):          # a sub-agent's stop: not the main context
        return None
    import handoff
    return handoff.on_stop(event, ctx.mod_cfg)


if __name__ == "__main__":
    sys.exit(ts.run_hook("handoff", EXPECTS, handle))
