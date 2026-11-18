#!/usr/bin/env python3
"""Sub-agent router (SubagentStop): log the real usage of a routed sub-agent."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "SubagentStop", "fields": {"session_id": "str", "agent_transcript_path": "str"}}


def handle(event, ctx):
    import subagent_router
    return subagent_router.on_subagent_stop(event)


if __name__ == "__main__":
    sys.exit(ts.run_hook("subagent_router", EXPECTS, handle))
