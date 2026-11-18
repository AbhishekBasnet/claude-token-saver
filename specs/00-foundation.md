# 00 · Foundation (shared by every mod)

Build this before any mod. Every mod spec assumes these rules and helpers exist.

## Ground rules

1. **Check the real docs first.** Mods, plugins and hooks change quickly. Before building, read the current Claude Code docs for mods, plugins and hooks (event names, input/output JSON, `updatedInput`, `additionalContext`, `updatedMCPToolOutput`, status line, slash commands) and use what actually exists. If something in a spec can't be done with the real API, **say so and propose the closest working alternative**. Don't fake it.
2. **One plugin, one local marketplace.** Everything lives in this repo as a local plugin marketplace containing one plugin, `token-saver`. Install at **user scope** so it's active in every project and session.
3. **Language:** Python 3 standard library only for hook scripts. Bash is fine for tiny glue. If a system tool is truly needed, print the install command (`dnf`/`apt`/`brew`) instead of installing silently.
4. **Cross-platform:** primary target is Linux (tested on Fedora). Avoid macOS-only (`osascript`, `pbcopy`, `sips`) and Windows-only commands. Use `pathlib` and `~` expansion, never hard-coded `/Users/...` paths.
5. **Fail open.** If any mod errors or times out, Claude Code must behave as if the mod weren't installed. Log the error, pass through unchanged. A mod must never block work.
6. **Fast path.** Hooks run on every event. The "not applicable" path must exit in well under 100 ms.

## Shared state — `~/.claude/token-saver/`

| Path | Purpose |
|---|---|
| `config.json` | on/off flags and settings for every mod (see [01-switchboard-savings](01-switchboard-savings.md)) |
| `savings.jsonl` | one JSON line per saving event |
| `cache/` | temp files, digests, full raw outputs |
| `handoffs/` | handoff documents |
| `debug.log` | errors from any hook |
| `health.jsonl` | schema drift, errors, conflicts (read by Doctor) |
| `state.json` | last seen Claude Code version, last self-test result |

## Shared helper module (`token_saver_common.py`)

Every hook imports this. It provides:

- `load_config()` — reads `config.json`, creates defaults if missing, tolerates a corrupt file (log + defaults).
- `is_enabled(mod, session_id)` — false if the mod is off, the session is paused, or the recursion guard is set.
- `log_saving(mod, session, project, before, after, detail)` — appends to `savings.jsonl`:
  ```json
  {"ts": "ISO8601", "mod": "input_router", "session": "…", "project": "/path", "tokens_before": 18400, "tokens_after": 950, "detail": "notes.srt digest"}
  ```
- `estimate_tokens(text)` — `len(text) / 4`; always labelled as an estimate where shown.
- `read_transcript(path)` — parse the session transcript (JSONL): latest user prompt, last assistant reply, real token usage if present.
- `call_model(model, system, prompt, timeout=45)` — background model call (see below).
- `debug(msg)` — append to `debug.log` with timestamp.
- `check_expects(event, EXPECTS)` — validates incoming hook JSON against the mod's declared `EXPECTS`; on mismatch logs `schema_drift` to `health.jsonl` and tells the caller to pass through. See [07-doctor](07-doctor.md).
- `record_error(mod, err)` — feeds Doctor's circuit breaker.
- **Dry-run support** — every hook script accepts `--dry-run` (reads event JSON from stdin, uses stubbed `call_model`) so Doctor and CI can test it without real model calls.

## Background model calls

Use the CLI on the user's subscription, e.g. `claude -p --model haiku`. No API key needed.

- **Recursion guard:** set `TOKEN_SAVER_INNER=1` in the inner call's environment. Every hook exits immediately when it sees it. Only the mod's *own* inner calls are guarded — normal sub-agents must still get the mods.
- **Keep the inner call light:** no tools, no MCP, short system prompt, no session persistence. Check which CLI flags exist in the installed version and use them.
- **Hard timeout** (default 45 s). On timeout or error → fall back to pass-through and log.

## Acceptance

- Plugin installs at user scope and shows in `/plugin`.
- Corrupt `config.json` → defaults used, error logged, no crash.
- `TOKEN_SAVER_INNER=1` → every hook is a no-op.
