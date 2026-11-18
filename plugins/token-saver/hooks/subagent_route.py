#!/usr/bin/env python3
"""Sub-agent router (PreToolUse on Agent|Task): pick the cheapest capable model."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "PreToolUse", "tool_name": ["Agent", "Task"],
           "fields": {"session_id": "str", "tool_use_id": "str", "tool_input": "dict",
                      "tool_input.prompt": "str"}}


def handle(event, ctx):
    import subagent_router
    return subagent_router.on_pre_tool_use(event, ctx.mod_cfg)


if __name__ == "__main__":
    sys.exit(ts.run_hook("subagent_router", EXPECTS, handle))
