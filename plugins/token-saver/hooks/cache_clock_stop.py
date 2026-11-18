#!/usr/bin/env python3
"""Cache Clock (Stop): record when the cache was last touched, for the status line."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "Stop", "fields": {"session_id": "str", "transcript_path": "str"}}


def handle(event, ctx):
    if event.get("agent_id"):          # a sub-agent's stop: its own cache, not the main one
        return None
    import cache_clock
    return cache_clock.on_stop(event, ctx.mod_cfg)


if __name__ == "__main__":
    sys.exit(ts.run_hook("cache_clock", EXPECTS, handle))
