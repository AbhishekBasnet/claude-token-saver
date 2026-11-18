# Prompt: after a Claude Code update breaks something

Doctor will tell you when an update or another plugin breaks a mod. To get Claude Code to fix it, open the repo, run `claude`, and paste:

```
A Claude Code update (or another plugin) broke token-saver.
1. Run /mods doctor and tests/run_selftest.py and show me the failures.
2. Check `claude --version`, read the current release notes and hooks/plugin docs,
   and find what changed (event names, input/output fields, tool names, status line).
3. Update docs/API-NOTES.md with the new version and what changed.
4. Fix the affected mods with the smallest possible change, update their EXPECTS
   and fixtures, re-run the self-test, and re-enable any mod Doctor turned off
   only after it passes.
5. Show me the diff and results, then commit.
```
