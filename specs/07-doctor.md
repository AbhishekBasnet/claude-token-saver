# 07 · Doctor (update & conflict guard)

**One line:** tells you when a Claude Code update, another mod, or a bug breaks token-saver, and turns off the broken part before it costs you anything.

## Why

Mods hook into Claude Code internals: event names, the shape of hook input JSON, tool names, the status line. A Claude Code update can change any of these, and other plugins can hook the same events. When that happens, mods usually fail **silently**: they stop saving tokens, or fight another plugin. Doctor makes those failures loud.

Build this **right after the Switchboard** (step 2) so it watches every mod built after it.

## 1. Update detection

- On `SessionStart`, run `claude --version` (cached; at most once per session) and compare it to `~/.claude/token-saver/state.json → last_seen_version`.
- If the version changed:
  1. Show one line: `🩺 Claude Code updated 2.1.287 → 2.1.301. Running token-saver self-test…`
  2. Run the **self-test** (section 4) in the background with a 60 s budget.
  3. Report the result in one line (`✅ all 6 mods passed`) or a short list of failures with the fix suggestion.
  4. Save the new version and the result.
- Also link the changelog: if the docs have release notes for the new version, list any lines mentioning `hook`, `plugin`, `mod`, `statusline`, `Task`/`Agent` tool, or `Read`. These are the likely breakers.

## 2. Schema drift detection (runtime)

Every hook script declares what it expects, for example:

```python
EXPECTS = {"event": "PreToolUse", "tool_name": "Read", "fields": ["tool_input.file_path", "session_id", "transcript_path"]}
```

- The shared helper checks each incoming event against `EXPECTS`. If a required field is missing or has the wrong type, then:
  - pass through unchanged (fail open)
  - record a `schema_drift` entry in `~/.claude/token-saver/health.jsonl` with the mod, the missing field, and the Claude Code version
- If a tool the mod depends on stops appearing entirely (e.g. the sub-agent tool was renamed), Doctor reports it as `tool not seen in N sessions`.

## 3. Conflict detection

On `SessionStart` (cached, re-check only when settings files change; compare mtimes), scan:

- `~/.claude/settings.json`, `~/.claude/settings.local.json`
- the project's `.claude/settings.json` and `.claude/settings.local.json`
- hooks and mods of every other enabled plugin (read their manifests and hook configs)

Flag:

| Conflict | Example | Severity |
|---|---|---|
| Another hook **modifies input** on the same event + tool | another plugin's `PreToolUse` on `Read` returning `updatedInput` | ⚠️ high: results depend on run order |
| Another hook **blocks/denies** the same tool | a guard plugin denying `Read` on large files | ⚠️ high |
| Another **status line** command | user's custom statusline | ℹ️ info: Cache Clock must append, not replace |
| Another hook sets the **model** for sub-agents | another router plugin | ⚠️ high: disable one of them |
| Another `SessionStart` that injects context | another handoff/memory plugin | ℹ️ info: both load; may duplicate |
| Duplicate slash command name | another `/handoff` or `/savings` | ⚠️ medium: rename ours with a prefix |

Report once per new conflict, in plain words, with a suggested fix (which to turn off, or how to rename).

## 4. Self-test

`/mods doctor` runs it on demand; update detection runs it automatically.

- For each mod, feed **recorded sample event JSON** (fixtures in `tests/fixtures/`) through its hook script with a dry-run flag. No real model calls: stub `call_model` to return canned output.
- Check: exit code, output JSON is valid for the current hook API, the expected decision was made (e.g. `.py` passes through, big `.srt` gets routed).
- Also run one **live** smoke check per event type if possible (e.g. confirm a `Stop` event actually reached Cache Clock in this session) and report events that never fire.
- Output:

```
🩺 token-saver doctor — Claude Code 2.1.301
  switchboard        ✅
  handoff            ✅
  cache_clock        ⚠️  status line overwritten by another plugin (see conflicts)
  subagent_router    ❌  sub-agent tool input has no "model" field → mod disabled
  input_router       ✅
  effort_optimizer   ✅  (suggest mode only: auto not supported)
conflicts: 1 · schema drift: 1 · errors last 24h: 3
```

## 5. Circuit breaker

- Count errors and timeouts per mod (from `debug.log` / `health.jsonl`).
- If a mod fails **3 times in one session** or **10 times in 24 h**, then:
  - auto-disable it in `config.json` (`"enabled": false, "disabled_by": "doctor", "reason": "…"`)
  - tell the user once: `🩺 Disabled input_router after 3 errors (Haiku timeout). /mods doctor for details · /mods on input_router to re-enable.`
- Never auto-re-enable. The user decides.

## 6. Health in `/mods` and `/savings`

- `/mods` shows a health column (✅ / ⚠️ / ❌ / disabled-by-doctor).
- `/savings` notes when a mod was off during the period, so the numbers aren't misleading.

## Acceptance

- Fake a version change in `state.json` → self-test runs and reports on the next session start.
- Add a dummy plugin with a `PreToolUse` hook on `Read` → conflict reported with a fix suggestion.
- Feed a hook an event with a missing field → passes through, `schema_drift` logged, Doctor reports it.
- Make a mod throw 3 times → auto-disabled, one notice shown, `/mods` shows why.
- Doctor itself failing must never break the session (fail open).
