#!/usr/bin/env python3
"""Input Router (PostToolUse on Read and mcp__*): digest big reading material."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "PostToolUse", "fields": {"session_id": "str", "tool_name": "str", "tool_input": "dict"}}


def handle(event, ctx):
    if os.environ.get("TOKEN_SAVER_DUMP_EVENTS"):
        with open(ts.path("cache", "last-posttooluse.json"), "w") as f:
            json.dump(event, f, indent=1)
    import input_router
    if event.get("tool_name") == "Read":
        return input_router.on_read(event, ctx.mod_cfg)
    if str(event.get("tool_name", "")).startswith("mcp__"):
        return input_router.on_mcp(event, ctx.mod_cfg)
    return None


if __name__ == "__main__":
    sys.exit(ts.run_hook("input_router", EXPECTS, handle))
