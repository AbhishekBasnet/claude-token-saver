# 04 · Sub-agent Model Selector

**One line:** every sub-agent runs on the cheapest model that can do its job.

## Why

By default, sub-agents run on the same model as the main session. Ten exploration sub-agents on Opus cost ten times Opus — even when most of them are just finding files or summarising pages.

## Behaviour

- **Trigger:** before the sub-agent tool runs (`PreToolUse` on the Task/Agent tool — check its real name and that its input accepts a `model` field).
- **Explicit model set already → leave it alone.**
- **Classify** the sub-agent's prompt/description. Free heuristics first; call Haiku only when unclear.

| Route | Typical tasks |
|---|---|
| **haiku** | finding/listing files, grep-style searches, reading & summarising docs or logs, extracting lists or numbers, simple web lookups |
| **sonnet** | writing ordinary code, reviewing a few files, research needing synthesis, writing tests, explaining code |
| **opus** (keep) | architecture & design, security review, debugging across many files, prod/infra config changes, final verification of high-stakes work |

  If `allow_opus` is `false`, the ceiling is sonnet.

- Set the model via `updatedInput` (or the mods equivalent) and show one line:
  ```
  🔀 sub-agent "find all API routes" → haiku
  ```
- **Savings:** if real sub-agent usage is readable after it finishes (`SubagentStop` / transcript), log actual tokens and the price difference. Otherwise log the routing with tokens `n/a`.
- **Works with Input Router:** large reads inside sub-agents should still be digested. Make sure the recursion guard only applies to the mods' own inner `claude -p` calls, not to normal sub-agents.

## Acceptance

- A request that spawns an exploration sub-agent → routed to haiku.
- A security-review sub-agent → stays on opus.
- A sub-agent call with an explicit model → untouched.
- `/mods off subagent_router` → all sub-agents use the default again.
