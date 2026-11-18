#!/usr/bin/env python3
"""Handoff (SessionStart): after /clear inject LATEST.md; on startup offer it."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "SessionStart", "fields": {"session_id": "str", "source": "str", "cwd": "str"}}


def handle(event, ctx):
    import handoff
    return handoff.on_session_start(event)


if __name__ == "__main__":
    sys.exit(ts.run_hook("handoff", EXPECTS, handle))
