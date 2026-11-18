# BUILD — instructions for Claude Code

You are building **token-saver**, a set of Claude Code mods that cut wasted tokens, packaged as one plugin in a local plugin marketplace. This repo starts as *specs*. You write the code here, in this repo.

## Read first
1. [`specs/00-foundation.md`](specs/00-foundation.md): ground rules, shared state, helper module, background model calls. **Applies to every mod.**
2. [`specs/07-doctor.md`](specs/07-doctor.md): every mod must declare `EXPECTS` and support dry-run so Doctor can test it. Design for this from the start.
3. The spec for the mod you're currently building.

## Step −1: research before code

Before writing anything, check the **installed** Claude Code version (`claude --version`) and read the current docs for plugins, mods, hooks, slash commands, status line and plugin marketplaces. Then write `docs/API-NOTES.md` covering:
- the Claude Code version you verified against
- the exact hook event names and input/output JSON fields each mod will use
- for each spec: ✅ possible as written / ⚠️ possible with changes (say what) / ❌ not possible (say the fallback)

**Show the user API-NOTES.md and wait for OK.** Don't build anything that's ❌ without agreement.

## Build order

Build **one step at a time**. After each step: run that spec's acceptance tests, show the results (with token numbers where possible), commit with a clear message, and **wait for the user's OK** before the next.

| Step | Spec | Why this order |
|---|---|---|
| 0 | [00-foundation](specs/00-foundation.md) | plugin skeleton, local marketplace, user-scope install, shared helpers |
| 1 | [01-switchboard-savings](specs/01-switchboard-savings.md) | every mod reads its config and writes its savings log |
| 2 | [07-doctor](specs/07-doctor.md) | watches every mod built after it: updates, conflicts, schema drift, circuit breaker |
| 3 | [02-handoff](specs/02-handoff.md) | biggest reliable win, no background model calls |
| 4 | [03-cache-clock](specs/03-cache-clock.md) | status line only; Keep Warm only after investigation |
| 5 | [04-subagent-router](specs/04-subagent-router.md) | first mod that changes tool input |
| 6 | [05-input-router](specs/05-input-router.md) | most complex; `Read` first, then MCP |
| 7 | [06-effort-optimizer](specs/06-effort-optimizer.md) | depends on what the real API allows |
| 8 | Final | full self-test, README results, publish-ready |

For every mod built after Doctor: add its fixtures to `tests/fixtures/` and register it with the self-test in the same commit.

## Code layout to produce

```
.claude-plugin/marketplace.json        # makes this repo installable via /plugin marketplace add
plugins/token-saver/
  .claude-plugin/plugin.json
  hooks/                               # hook config + one script per mod
  commands/                            # /mods, /savings, /handoff, /keepwarm
  lib/token_saver_common.py            # shared helpers (config, savings, EXPECTS check, call_model, debug)
tests/
  fixtures/                            # sample hook event JSON per mod
  run_selftest.py                      # same test Doctor runs; also usable in CI
docs/API-NOTES.md
```

The real plugin/mod format in the docs wins over this layout.

## Step 8: Final

1. Run `/mods doctor`. Everything must be ✅, or ⚠️ with a documented reason.
2. Run `tests/run_selftest.py` from the shell; it must pass.
3. Add a GitHub Actions workflow that runs `run_selftest.py` on push (Python only, no Claude needed).
4. Update `README.md`:
   - Install section → `/plugin marketplace add <github-user>/token-saver` then `/plugin install token-saver@token-saver` (use the real marketplace/plugin names)
   - Fill in the **Results** table with numbers you actually measured in this session. Leave cells blank rather than invent.
   - Move anything not built to **Known limitations** with the reason
   - "Tested with Claude Code <version> on Fedora Linux"
5. Uninstall + reinstall from the marketplace to confirm a clean install works.
6. Commit. Tell the user it's ready to push.

**Never claim savings you didn't measure.**
