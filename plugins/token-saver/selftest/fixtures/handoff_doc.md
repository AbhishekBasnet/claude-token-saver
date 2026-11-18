# Handoff
## Goal
Ship the BLUEFIN parser.
## Current state
parse.py passes 12/14 tests.
## Decisions made (and why)
Chose stdlib json over orjson (no extra deps).
## Files
- /tmp/project-a/parse.py: the parser
## Commands & environment
python3 -m pytest -q
## Open problems
KeyError: 'id' in test_nested
## Next steps
1. Guard missing id in parse_item()
## Skills, MCP tools, links & docs used
none
## Preferences the user showed this session
No emoji.
