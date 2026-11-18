# Build progress (for the next session)

Written 2026-11-18 at the end of the first build session. This is the backup if the `/handoff` doc is missing. Read `BUILD.md`, `docs/API-NOTES.md` (all sections) and this file first.

## User's instructions for the rest of the build
- **Finish all remaining steps (4 to 8) without waiting for an OK between steps.** For each step: build, run the acceptance tests, show the results with token numbers, and commit.
- Still **ask before building anything a spec asks for that the real API can't do** (❌), or before changing a spec's behaviour.
- Fedora 45 KDE, Claude subscription (no API key). Python stdlib only, and give a `dnf` command instead of installing anything. User scope install. Fail open.
- **No emoji anywhere** in mod output. Use plain prefixes (`token-saver:`, `doctor:`, `handoff:`).
- **README:** only numbers that were actually measured.
- **Commits:** author `Claude <noreply@anthropic.com>`, committer is the user (repo-local `user.name`/`user.email` = Abhishek / their hotmail). Commit with `git commit --author="Claude <noreply@anthropic.com>" -m "<short one-line message>"`. **No `Co-Authored-By` line.** All earlier commits were rewritten this way on 2026-11-18, before the first push (backup branch `backup-before-identity`).
- **GitHub repo:** must be **private** (step 8).
- **Info card:** when a mod acts on a tool call, show the card under that tool row (built in step 1; `write_card()` in Python, drawn by the shim).

## Done (committed)
| Step | Commit | What |
|---|---|---|
| −1 | 9cdf0a1 | `docs/API-NOTES.md` |
| 0 | ef502d4 | foundation, local marketplace, user-scope install |
| 1 | e977ca3 | `/mods`, `/savings` (0 tokens, display-only), info card |
| 2 | 3820bcc | Doctor (update check + changelog, conflicts, drift, circuit breaker, `/mods doctor`) |
| 3 | 9f1f5e7, 7a409dd | Handoff (`/handoff` via `$.model.fork`, asks for critical notes, "Ask the user first" section, auto-load after `/clear`, 250k warning) |

Tests: `python3 tests/run_selftest.py` (38/38) and `claude plugin test plugins/token-saver` (6/6). `claude plugin validate plugins/token-saver` passes.

## Step 4 (Cache Clock): done (clock + Keep Warm, see API-NOTES 18)
- Done: `/keepwarm ping` in the shim (`$.model.fork` with a tiny prompt, logged by `ts_cli.py keepwarm-log`). `/keepwarm on|off|status` is a stub.
- **Keep Warm experiment running in the background** (started 13:17:04, results around 14:27): `~/.claude/token-saver/cache/keepwarm-exp/result-A.json` (ping at +50 min) and `result-B.json` (control). Both msg1 results: cache_read 9,224 (shared system prompt), cache_write about 38.9k (unique text).
  - If A's "msg2 (+70 min)" shows cache_read ≈ 48k and B's ≈ 9k, the ping refreshes the cache. Then build Keep Warm (timer about 5 min before expiry, max 8 pings, configurable, stops at session end, logs each ping's cost).
  - If not, don't build it. Explain why in the README.
- **Clock: built (session 2, not yet committed: the auto-mode classifier blocked the commit).** `lib/cache_clock.py`, `hooks/cache_clock_stop.py`, shim `refreshClock`/`clockLine` (30 s `$.clock.every`, started in its own try so a command-registration failure can't hide it). Live context from `$.session.usage()`. Warm hits after a >10 min gap are logged with `kind: observed` and no before/after (shown as n/a). `/keepwarm ping` restarts the clock. Tests: self-test 45/45, engine 8/8. Live: the clock file had ctx 22,660, which equals the API usage, and a 60 min TTL.
  - Big transcripts: a 61 MB synthetic one read in 0 ms (last usage) and 8 ms (turn start). A turn with more than 4 MB of tool output skips the observed-hit note (harmless). Add this to the README's Known limitations.
  - Gotcha: the reply's usage can reach the transcript **after** Stop fires. `on_stop` polls up to 1 s.
- The spec 03 savings formula needs the cache-read/input price ratio. For Opus 5.5 it's 0.20/4.00 = 0.05 (prices in `lib/switchboard.py`).

## Step 5 (sub-agent router): done
See API-NOTES section 15. 13 self-test cases. The card under the Agent row is drawn by the existing shim card path (not checked live: `-p` has no UI).

## Remaining steps
- (done) 5 sub-agent router: PreToolUse matcher must be `Agent|Task` (`Task` in `-p`, `Agent` interactive). Uses `updatedInput.model` (sonnet/opus/haiku/fable) and SubagentStop `agent_transcript_path` for real usage. Show a card.
- (done, see API-NOTES 16) 6 Input Router: PostToolUse `Read` + `updatedToolOutput` (not a deny). MCP via `updatedMCPToolOutput`. **Skip PDFs** (user decision). Honour `bypass_once` in session state (set by the card's "read full instead" button). Card with digest.
- (done, see API-NOTES 17) 7 Effort Optimizer: suggest mode via UserPromptSubmit. The transcript `effort` field gives the current level. Levels include `xhigh`. Latency concern: heuristics first, Haiku if unclear, or a non-blocking shim toast. Auto mode only via shim `turn.step`.
- 8 Final: `/mods doctor` all OK, CI workflow, README results (measured only), uninstall and reinstall check, private GitHub repo.

## Gotchas learned
- Doctor conflict scan: tests use `TOKEN_SAVER_CLAUDE_DIR={home}/...` and `TOKEN_SAVER_OUR_HOOKS_FILE`.
- Self-test fixtures can use a `{home}` placeholder. Nested self-test runs only the foundation cases.
- `$.model.fork` returns `nothing-to-fork` until the current process has made one model request.
- len/4 underestimates markdown with paths by about 2x: the handoff doc measured 2,350 real tokens vs a 1,138 estimate.
- `claude plugin validate` type-checks the shim. Use `e.origin?.kind` (origin can be missing in tests).
