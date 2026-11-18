# 03 · Cache Clock

**One line:** a status-line countdown showing when this session's prompt cache goes cold.

## Why

Claude re-reads the whole conversation on every message. While the prompt cache is warm, that re-read is billed at a small fraction of normal input price. When the cache expires, the next message pays full price for the entire context. Nothing in the UI tells you when that happens.

## Behaviour

### Clock
- On each assistant reply (`Stop`), write `last_activity` for the session to
  `~/.claude/token-saver/cache/clock-<session>.json`.
- **Status line segment** — append to the user's existing status line, never overwrite it (show the diff before changing it):

  | State | Display |
  |---|---|
  | > 10 min left | `● cache 47m` (green) |
  | ≤ 10 min left | `● cache 4m` (yellow) |
  | expired | `○ cold` (blue/grey) |

  Also show context size when available: `ctx 84k`.
- TTL comes from `cache_clock.ttl_minutes` in config.

### Keep Warm (optional, off by default)
`/keepwarm on|off`

**Investigate before building and report findings:** is there a real way to refresh the cache of the *live* interactive session? (e.g. a hidden ping in the mods API, or `claude -p --resume <session>` — and does that actually hit the same cache prefix?) Verify with `cache_read_input_tokens` in the transcript usage.

- If it works: a background timer pings ~5 min before expiry, max 8 pings (configurable), stops when the session ends, logs each ping's cost.
- If it can't be done reliably: **don't build it.** Ship the clock only and explain why in the README.

### Savings
When the user sends a message on a warm cache after a gap > 10 min, log an estimated saving:
`context_tokens × (1 − cached_price_ratio)` — labelled as an estimate.

## Acceptance

- After a reply, the status line shows the full TTL counting down.
- Faked timestamp → yellow, then cold.
- An existing custom status line still shows everything it did before.
