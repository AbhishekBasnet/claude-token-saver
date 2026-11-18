# 01 · Switchboard (`/mods`) + `/savings`

**One line:** turn any mod on/off from one command, and see exactly what each one saved.

Build this first — every other mod reads its config and writes to its savings log.

## Config — `~/.claude/token-saver/config.json`

Create with these defaults if missing:

```json
{
  "input_router":     { "enabled": true, "threshold_tokens": 2000, "model": "haiku" },
  "effort_optimizer": { "enabled": true, "model": "sonnet", "mode": "suggest" },
  "subagent_router":  { "enabled": true, "allow_opus": true },
  "cache_clock":      { "enabled": true, "ttl_minutes": 60, "keep_warm": false },
  "handoff":          { "enabled": true, "threshold_tokens": 250000 }
}
```

`ttl_minutes`: verify the real prompt-cache TTL for subscription Claude Code in the docs (commonly reported: 1 h on subscription, 5 min on API). Use the verified value and report what you found.

## `/mods`

| Command | Effect |
|---|---|
| `/mods` | table of every mod: on/off + key settings |
| `/mods on <mod>` / `/mods off <mod>` | toggle a mod |
| `/mods set <mod>.<key> <value>` | e.g. `/mods set input_router.model sonnet` |
| `/mods pause` | disable **all** mods for the current session only |
| `/mods resume` | re-enable for this session |
| `/mods reset` | restore defaults (ask to confirm) |

Changes apply on the next event — hooks read config every time. Validate input: unknown mod or key → helpful error listing valid options.

## `/savings`

Reads `savings.jsonl` and prints:

- Totals for **today / last 7 days / all time**
- Per mod: events, tokens saved (before − after), estimated $ saved at current Opus input pricing (look it up; label as estimate)
- Top 5 biggest single savings with their `detail`
- `/savings session` → current session only

Example output:

```
Token Saver — last 7 days
mod               events   tokens saved   est. $
input_router          41        612,300    ~$3.06
subagent_router       18             n/a       —
handoff                3        596,000    ~$2.98
cache_clock           12        402,000    ~$1.40
-----------------------------------------------
total                         1,610,300    ~$7.44   (estimates)
```

## Acceptance

- `/mods off input_router` → next large read passes through untouched.
- `/mods pause` in one session doesn't affect another open session.
- `/savings` with an empty log → friendly "nothing saved yet" message, no crash.
