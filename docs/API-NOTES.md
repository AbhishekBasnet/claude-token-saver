# API notes: what the real Claude Code API allows

**Verified against:** Claude Code **2.1.327** (`claude --version`), Fedora 45, Python 3.15.2, 2026-11-18.
**Sources:** this build's own API declaration (`claude-code.d.ts`, written by the engine for 2.1.327, ~26k lines), the bundled plugin/mod reference, and `claude --help` / `claude plugin --help`. Where a point is still unverified, it says so and names the step that verifies it.

---

## 1. The big finding: two kinds of plugin hooks

2.1.327 has **two** hook systems. Both can ship in one plugin:

| | **Classic command hooks** | **Function-hook mod** |
|---|---|---|
| Language | any command → **Python stdlib** ✅ | TypeScript module run inside Claude Code (no Node or npm needed; nothing to install) |
| Declared in | plugin `hooks/hooks.json` (`PreToolUse`, `Stop`, …) | `hooks/hooks.json` → `"modules": ["./register.ts"]` |
| I/O | JSON on stdin, JSON on stdout (`hookSpecificOutput`) | `on(event, matcher, ($, e, next) => …)` |
| Can do | rewrite tool input, replace tool output, inject context, block | everything classic can do, **plus**: slash commands answered with **no model turn**, a pinned status entry, toasts, **changing effort/model per request** (`turn.step`), `$.model.complete` / `$.model.fork` (model calls without spawning `claude -p`) |
| Testable from shell/CI | yes, pipe fixture JSON in | `claude plugin test` (needs `claude`) |

The specs assume classic hooks plus Python. That covers most of the project, but **four features need the mod side**:

1. **`/mods` and `/savings` with zero tokens.** A classic plugin command is a Markdown prompt, so every `/mods off x` would cost a model turn and the model would have to relay the table. A mod's `$.command.register` answers `{ text }` directly, with no model call.
2. **Cache Clock without touching your status line.** Plugins can't set `statusLine`, so classic would mean editing `~/.claude/settings.json`. A mod's `$.ui.status(text)` pins its own line under the prompt, next to whatever status line you have, and never replaces it.
3. **Effort Optimizer `auto` mode.** Only `turn.step` can change effort. Classic hooks can only suggest.
4. **Cheaper and faster background calls.** `$.model.complete({ model: "haiku" })` runs on the session's own client, with no CLI startup and usage reported back. `$.model.fork` asks a question over the live session **from its prompt cache**. That fork call is the only real Keep Warm mechanism I found.

### ❓ Decision needed: recommended architecture
**Hybrid (recommended):** all decision logic, config, savings, Doctor and self-test stay in **Python stdlib**, as classic hooks. A **thin TypeScript shim** (one file, roughly 150 lines, no logic of its own) does only the four things above, and for each one it calls the Python scripts via `$.process.run`. The shim needs nothing installed. Doctor and `tests/run_selftest.py` test the Python side without Claude.

**Pure Python (spec as written):** `/mods` and `/savings` become Markdown commands, each costing a small model turn. Cache Clock edits your `settings.json` status line. Effort auto mode is ❌. Background calls go through `claude -p`, which is slower and adds latency to every hook that calls a model.

---

## 2. Install and packaging

- The repo itself is the marketplace: `.claude-plugin/marketplace.json` → one plugin, `token-saver`, with `"source": "./plugins/token-saver"`.
- Install at **user scope**: `claude plugin marketplace add ~/Projects/claude-token-saver`, then `claude plugin install token-saver@token-saver --scope user`.
- Because the marketplace is a folder with a relative source, the installed plugin is **read from the repo folder itself**. You edit, then run `/reload-plugins`, with no reinstall. ✅
- After publishing: `/plugin install token-saver --marketplace <owner>/token-saver`.
- Current state: you have no plugins, no hooks and no `statusLine`, so there's nothing to conflict with today. Your `model` is `opus`.

## 3. Hook events and fields each mod uses (classic, stdin JSON)

Base fields on every event: `session_id`, `transcript_path`, `cwd`, `permission_mode?`, `agent_id?` (present only inside a sub-agent), `agent_type?`, `effort?.level` (tool-context events only; also the `CLAUDE_EFFORT` env var).

| Mod | Event | Input fields used | Output used |
|---|---|---|---|
| Handoff (auto-load) | `SessionStart` | `source` ∈ `startup\|resume\|clear\|compact\|fork` | `hookSpecificOutput.additionalContext` |
| Handoff (warning), Cache Clock | `Stop` | `transcript_path` (usage per message) | `systemMessage` shown to the user (verify in step 0) |
| Sub-agent router | `PreToolUse`, matcher `Agent` | `tool_input.{description,prompt,subagent_type,model?}` | `hookSpecificOutput.updatedInput` with `model` |
| Sub-agent savings | `SubagentStop` | `agent_id`, `agent_type`, `agent_transcript_path` (real usage) | none |
| Input Router (Read) | `PostToolUse`, matcher `Read` | `tool_input.{file_path,offset?,limit?,pages?}`, `tool_response` | `hookSpecificOutput.updatedToolOutput` |
| Input Router (MCP) | `PostToolUse`, matcher `mcp__.*` | `tool_name`, `tool_response`, `mcp_server` | `hookSpecificOutput.updatedMCPToolOutput` |
| Effort Optimizer | `UserPromptSubmit` | `prompt`, `source` (`user`/`sdk`/`system`/…) | `systemMessage`, or a toast from the shim |
| Doctor | `SessionStart` | `source`, `model` | `systemMessage` |

Tool facts in this build:
- The sub-agent tool is named **`Agent`** (not `Task`). Its input has `model?: "sonnet" | "opus" | "haiku" | "fable"` **and** `effort?`.
- `Read` input: `file_path`, `offset?`, `limit?`, `pages?`, `allow_large?`.
- Effort levels are **low / medium / high / xhigh / max**. That's five, and the spec lists four.

## 4. Background model calls

- `claude -p --bare` is **not usable**: `--bare` accepts only `ANTHROPIC_API_KEY`, never subscription OAuth.
- Working form: `TOKEN_SAVER_INNER=1 claude -p --model haiku --tools "" --strict-mcp-config --no-session-persistence --output-format json --system-prompt "<short>"`. Our own user-scope hooks still load inside it, so the `TOKEN_SAVER_INNER` guard is required, as the spec says.
- I haven't measured startup latency yet. I'll do that in step 0, because it decides whether Input Router's timeout budget is realistic.
- With the hybrid option, Haiku calls can use `$.model.complete` instead.

## 5. Prompt-cache TTL (for `cache_clock.ttl_minutes`)

This session's harness reports a **1-hour prompt-cache TTL** on your subscription. It drops to **5 minutes** if the account goes into usage overage. `SessionStart` on resume also reports `prompt_cache_likely_expired`, which comes from the engine's own TTL. So the default stays at **60**, with a note that overage means 5. Step 4 verifies this with `cache_read_input_tokens` in the transcript.

---

## 6. Spec-by-spec verdict

### 00 Foundation: ✅
Everything is possible. Changes: background calls use the flags above (no `--bare`). Dry-run, `EXPECTS`, fail-open and the shared state folder all work as written.

### 01 Switchboard + `/savings`: ⚠️
- Config, toggles, per-session pause (keyed by `session_id`) and the savings log are all ✅.
- The `/mods` and `/savings` **commands**: ✅ with zero model tokens via the shim (hybrid). Pure Python makes them Markdown commands that cost one small model turn each and can't read `session_id` reliably for `pause`.
- `$` estimates are labelled as estimates. Opus pricing gets checked at build time, not guessed.

### 02 Handoff: ✅ (small changes)
- `/handoff` must be written by the **main model** (it has the context), so it's a Markdown command whose prompt tells the model to write the doc to the path. That's one turn's output tokens, as intended.
- `SessionStart` `source:"clear"` plus `additionalContext` is ✅. The `startup` case "if the user confirms": hooks can't ask a question at session start. Fallback: inject a one-line *"a handoff from <time> exists; say `load handoff`"* notice, and the full doc loads only on request.
- Threshold warning on `Stop`: ✅, reading real usage from the transcript.

### 03 Cache Clock: ⚠️
- The clock is ✅ via the shim's `$.ui.status` (a separate pinned line, never overwrites your status line, refreshed by a 30 s timer). Pure Python would add a `statusLine` to `settings.json` (you have none, so nothing gets overwritten), and it only refreshes when Claude Code redraws it.
- **Keep Warm:** `claude -p --resume` uses a different system prompt and tools, so it **would not hit the live session's cache prefix** ❌. `$.model.fork` (shim only) *does* read the main thread's cached prefix and should refresh it. I'll measure that with `cache_read_input_tokens` in step 4 before building it. If it doesn't hold up, it won't ship, as the spec says.
- Savings estimate after a gap of more than 10 minutes: ✅ (labelled as an estimate).

### 04 Sub-agent router: ✅
`PreToolUse` on `Agent` → `updatedInput.model`. An explicit `model` is left alone. "Keep opus" means leaving `model` unset so the sub-agent inherits. `subagent_type: "fork"` is ignored by the API, so it's skipped. Real per-sub-agent usage comes from `SubagentStop.agent_transcript_path`. The recursion guard only matches `TOKEN_SAVER_INNER`, so normal sub-agents still get every mod.

### 05 Input Router: ⚠️ (better mechanism than the spec)
- Use **`PostToolUse` + `updatedToolOutput`** instead of a PreToolUse deny. `Read` runs for real, so Claude Code's "file has been read" bookkeeping stays correct, and the model sees the digest. The deny approach would show up as an error and invite retries.
- All the skip rules (offset/limit, source code, `.git`, lockfiles, "verbatim" etc. read from the transcript's latest prompt) are ✅.
- **Cost of the hook:** the read waits for Haiku. The hook `timeout` is set in hooks.json. On timeout the output passes through unchanged and the error is logged.
- MCP via `updatedMCPToolOutput`: ✅.
- `.pdf`: skipped. Text extraction needs a non-stdlib tool (`dnf install poppler-utils` for `pdftotext`), so PDFs pass through unless you want that.

### 06 Effort Optimizer: ⚠️
- Suggest mode: ✅ on `UserPromptSubmit`. Whether `effort.level` is present on that event is unverified (the docs say tool-context events only). Fallback: the shim reads it from `turn.step`, or the session's `--effort` / settings.
- **Auto mode:** ❌ for classic hooks. ✅ only via the shim's `turn.step` rewrite, and that applies *per request*, so the shim has to apply it on every step of the turn.
- ⚠️ **Latency concern:** `UserPromptSubmit` blocks the prompt. A Sonnet call through `claude -p` on every prompt adds several seconds to each message. Proposal: heuristics first, and Haiku (not Sonnet) only when unclear. Or show the suggestion *after* submission via the shim (non-blocking toast). Your call when we reach step 7.
- Add `xhigh` to the levels.

### 07 Doctor: ⚠️
- Version check: compare against `state.json` on `SessionStart`. ✅ (`claude --version`, cached once per session).
- Self-test on update: runs as a detached background process, and the result is shown at the next event (`systemMessage`), because a hook can't print later on its own. ✅
- Schema drift, circuit breaker, conflict scan (settings files plus other plugins' `hooks.json` and manifests under `~/.claude/plugins`): ✅
- Changelog lines: ⚠️ there's no local changelog, so this needs a network fetch of the release notes. Fallback: print the changelog URL plus "run `/release-notes`".
- "Tool not seen in N sessions": ✅ from a small per-session seen-tools record.

---

## 7. Open items to verify while building
- Step 0: `systemMessage` display from a plugin's classic hook, and `claude -p` haiku latency.
- Step 4: cache TTL, and whether `$.model.fork` refreshes the main cache (Keep Warm).
- Step 7: whether `effort.level` is present on `UserPromptSubmit`.

---

## 8. Decisions (user, 2026-11-18)
- Architecture: **hybrid**. Python stdlib does all logic; a thin TypeScript shim handles the four mod-only features.
- Input Router: **skip PDFs** (no `pdftotext` dependency).

## 9. Verified in step 0 (2026-11-18)
- A plugin's `hooks/hooks.json` can hold classic `hooks` and `modules` together. `claude plugin validate` passes.
- Installed at user scope from the folder marketplace. `claude plugin list` shows `Read from: <repo>/plugins/token-saver`, so edits plus `/reload-plugins` take effect without reinstalling.
- In a fresh session from another folder: the classic `SessionStart` hook fired and its `systemMessage` came back as `hook_response`, and the shim ran Python via `$.process.run`.
- `claude -p --model haiku --tools "" …` takes **~2.0–2.4 s** wall time (API ~0.8 s). The overhead is 878 input tokens, and they get cached.
- Prompt cache: usage reports `ephemeral_1h_input_tokens`, and the transcript has `cacheControl … ttl: 1h` and `promptCacheRequested: 1h`, so the **1-hour TTL is confirmed** on this subscription.
- ⚠️ In a `claude -p` session the sub-agent tool is listed as **`Task`**. In this interactive session it's **`Agent`**. The sub-agent router must match `Agent|Task`.
- The transcript's assistant entries carry `message.usage` (real context size) and an `effort` field (`medium` here), which the Effort Optimizer can read.
- Self-test engine and fixtures live in `plugins/token-saver/selftest/` (not `tests/fixtures/`), so Doctor can run them from an installed copy. `tests/run_selftest.py` wraps it for CI.

## 10. UI decisions (user, 2026-11-18)
- **No emoji anywhere.** All one-line messages use plain prefixes (`token-saver:`, `doctor:`), replacing the spec's 🩺 🔀 📦 ⚡ lines.
- **Info card under the tool row.** When a mod acts on a tool call (Input Router on `Read`, sub-agent router on `Agent`/`Task`), the shim draws a small bordered card under that call's row via a `ui.render` hook on `{ component: 'ToolUse' }`, keeping the row (`await next(e)`). Data flow: the Python hook writes `cache/cards/<tool_use_id>.json` (mod, model, file, tokens before→after, ms, path). The shim reads it with `$.fs.read`, keyed by `e.requestId` (= tool_use_id). No card file means the shim draws nothing extra. Buttons: `show digest` (expands it) and `read full instead` (tells the next Read of that file to pass through). Shared card component built in step 1, used by each mod after that.

## 11. Verified in step 1 (2026-11-18)
- `$.command.register` plus a `command.run` hook returning `{ text, isTextDisplayOnly: true }` gives `/mods` and `/savings` with **0 model tokens**. Measured in `claude -p`: input 0, output 0, cost $0, 0 turns.
- Claude Code labels plugin command output with the plugin name, so Python strips its own `token-saver:` prefix to avoid showing it twice.
- `claude plugin validate` also type-checks the shim (it caught a `SessionMessagesResult` deny case). `claude plugin test` runs `selftest/shim.test.tsx` on the real engine. No `tsc` install needed.
- The card is drawn by a `ui.render` hook on `ToolUse`, from `$.state` family `token-saver.card` keyed by `tool_use_id`. The shim fills it in a `tool.call` hook after `next(e)` by reading `cache/cards/<tool_use_id>.json` (Python: `write_card()`). Tested on terminal and desktop surfaces.
- Pricing for the `/savings` $ column: Opus 5.5 at $4.00/M input (list price, cached 2026-11-03), labelled as an API-equivalent estimate.

## 12. Verified in step 2: Doctor (2026-11-18)
- `claude --version` is a native binary that answers in ~0 s, so it's checked on every SessionStart (no caching needed). Doctor's SessionStart hook takes **~30 ms** when nothing changed.
- There's no local changelog. On a version change Doctor GETs `raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` (6 s timeout, fails open, sends nothing but a generic User-Agent) and lists lines from the skipped versions that mention hooks, plugins, mods or the status line (case-insensitive), or `Task`/`Agent`/`Read` (case-sensitive).
- Live: faking `last_seen_version` 2.1.326 then starting a session gave "updated 2.1.326 -> 2.1.327 … self-test passed (24/24)" plus 8 relevant release-note lines, in a session that took 3.4 s wall in total.
- Conflict scan reads `~/.claude/plugins/installed_plugins.json` (`installPath`) together with `enabledPlugins` from the user and project settings, then each plugin's `hooks/hooks.json` (classic hooks plus module source), manifest `hooks`, and `commands/*.md`. It's cached by settings and registry mtimes. A new high/medium conflict is reported once at session start; info-level ones only appear in `/mods doctor`.
- Their `PreToolUse` on tool T conflicts with our Pre *or* Post hook on T (they may deny it). Their `PostToolUse` on T conflicts with our Post on T.
- Circuit breaker: 3 errors in one session or 10 in 24 h disables the mod (`disabled_by: doctor`, `reason`). It shows **one** `systemMessage` from the failing hook (display only; the event still passes through unchanged) and never re-enables on its own.
- Self-test nesting: a self-test started from inside a self-test runs only the foundation cases, which never call Doctor, so it can't recurse.
- Not done live: a real third-party plugin conflict. Installing a dummy plugin into your setup would be invasive, so the self-test covers it with a fixture plugin (`selftest/fixtures/conflict_plugin`).

## 13. Verified in step 3: Handoff (2026-11-18)
- `/handoff` runs `$.model.fork` (tool-less, same model and system prompt, read from the main thread's prompt cache), and Python writes the reply to `handoffs/<project-slug>/<stamp>.md` and `LATEST.md`. The doc **never enters the main conversation**: the session's own `/handoff` turn used 0 tokens.
- Live (Haiku test session, about 20k context): fork input was 20,032 cache-read plus 462 uncached, output 2,485, wall ~14 s. Every required section was filled with specifics.
- `nothing-to-fork` also happens right after a resume or restart until Claude has replied once in that process. The message now says to send a message first.
- Classic `SessionStart` **does** fire with `source: "clear"` after `/clear` (verified in a stream-json session). `additionalContext` injects the doc, and the fresh session answered questions about the old one correctly. `LATEST.md` is renamed to `loaded-<stamp>.md`.
- `startup`: hooks can't ask a question, so a fresh (<24 h) handoff is offered with a notice, and `/handoff load` returns it as command `context` (the model reads it with the next prompt).
- Project slug = cwd with every non-alphanumeric character turned into `-`, which matches Claude Code's own `~/.claude/projects/<slug>` naming.
- **Token accounting:** the doc measured **~2,350 real tokens** (fresh-session context 22,381 vs baseline 20,034). The len/4 estimate gave 1,138, about 2x low for markdown with paths and code. The saving is logged as old context minus (baseline + doc), where the baseline is the session's first-reply context. That keeps the system prompt and tools from counting as saved.
- The test-run entries were removed from the real `savings.jsonl`.

## 14. Verified in step 4: Cache Clock (2026-11-18)
- The pinned line comes from `$.ui.status`, refreshed by `$.clock.every(30000)` (a hot reload stops the old timer). The context size comes live from `$.session.usage()`.
- The reply's usage can reach the transcript **after** the Stop hook (and PreToolUse) fires. Readers poll up to 1 s.
- Big transcripts: reading a 61 MB synthetic transcript took 0 ms (last usage, read backwards) and 8 ms (turn start, last 4 MB).

## 15. Verified in step 5: sub-agent router (2026-11-18)
- Classic `PreToolUse` with `hookSpecificOutput.updatedInput` and **no** permission decision rewrites the arguments and leaves the normal permission flow alone.
- In `claude -p` 2.1.327 the sub-agent tool reported as `Agent` (it was `Task` in step 0). The matcher stays `Agent|Task`.
- SessionStart in `-p` carries **no `model`** field (keys: cwd, hook_event_name, session_id, source, transcript_path). The main model comes from the transcript's latest reply (polled up to 1 s on the first turn), then from SessionStart's `model` when present, then from the settings `model`.
- Live, with Sonnet as the main model: `updatedInput.model = "haiku"` made the sub-agent run on Haiku (its transcript's `message.model`). Three runs of "find all API routes" over a 3-file folder: 2-4 requests, 38k-74k input and 0.6k-1.8k output tokens. Est. cost $0.0021-$0.0032 on Haiku vs $0.040-$0.062 at Sonnet prices. Usage is summed per request id, because one request can span several transcript entries.
- Prices (claude-api reference, cached 2026-11-03), per million tokens, input / output / cache read: Opus 5.5 $4 / $20 / $0.20, Sonnet 5.5 $2 / $10 / $0.10, Haiku 5.5 $0.10 / $0.50 / (not listed; 0.1x input = $0.01 assumed), Fable 5.2 $8 / $40 / $0.20. Cache writes cost 1.25x input (5 min TTL) or 2x input (1 h TTL).
