#!/usr/bin/env python3
"""Test-only hook: belongs to mod 'handoff' and always raises. Used to check
Doctor's circuit breaker. Not registered in hooks.json."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import token_saver_common as ts  # noqa: E402

EXPECTS = {"event": "SessionStart", "fields": {"session_id": "str"}}


def handle(event, ctx):
    raise TimeoutError("haiku did not answer in 45s (injected)")


if __name__ == "__main__":
    sys.exit(ts.run_hook("handoff", EXPECTS, handle))
