# token-saver

**Claude Code mods that stop paying for tokens you don't need, plus a doctor that tells you when anything breaks.**

Big files and connector results get digested by Haiku before they reach your context. Sub-agents run on the cheapest model that can do the job. A status line shows when your prompt cache goes cold, and can keep it warm while you're away. `/handoff` moves a long chat into a fresh session without losing the thread.

Tested with Claude Code 2.1.327 on Fedora Linux 45 (Python 3.15). Python standard library only. One plugin, installed at user scope.

---

## The mods

| Mod | What it does | Model calls |
|---|---|---|
| **Switchboard** `/mods`, `/savings` | Turn mods on or off, pause all for a session, change settings, see what each mod saved | none (answered without a model turn) |
| **Handoff** `/handoff` | Warns at 250k context, writes a detailed handoff doc, loads it after `/clear` | your model, in a side fork |
| **Cache Clock** + Keep Warm | Pinned line: `● cache 47m · ctx 84k`, `◐ cache 4m`, `○ cold`. Optional pings keep the cache warm | none (pings: your model, in a fork) |
| **Sub-agent router** | Runs each sub-agent on Haiku, Sonnet or your main model, by task | heuristics, Haiku if unclear |
| **Input Router** | Haiku digests big reading material and MCP results; your model gets the digest, line ranges and the path | Haiku |
| **Effort Optimizer** | Suggests a better effort level per prompt (toast), or sets it per request in auto mode | heuristics, Haiku if unclear |
| **Doctor** `/mods doctor` | Detects Claude Code updates, conflicting plugins, changed hook input and failing mods; turns off a mod that keeps failing | none |

### Switchboard
`/mods` lists every mod. `/mods off input_router` turns one off, `/mods pause` pauses all of them for this session, and `/mods set input_router.threshold_tokens 4000` changes a setting. `/savings [today|7d|all|session]` shows tokens and an estimated $ per mod. Both commands answer without a model turn: measured at 0 input and 0 output tokens.

### Handoff
`/handoff` asks if there is anything critical to pass on. Your own model then writes the doc in a tool-less fork over the cached conversation, so the doc never enters the chat. It covers goal, state, decisions, files, commands, open problems, next steps, and the questions to ask you first. Run `/clear` and the new session loads it automatically. A Stop hook warns once your context passes 250k tokens.

### Cache Clock and Keep Warm
After each reply, the clock counts down your cache TTL (60 min on a subscription, or 5 min in usage overage). It turns `◐` in the last 10 minutes and `○` once the cache is cold, at which point the next message rewrites the whole context to cache. `/keepwarm on` pings about 5 min before expiry, at most 8 times per idle stretch, and each ping is logged with its cost. A ping is a one-line question to your own model in a side fork. `/keepwarm status`, `/keepwarm off`.

### Sub-agent router
Searches, listings, summaries and lookups go to Haiku. Writing code or tests goes to Sonnet. Security reviews, architecture and root-cause debugging stay on your main model. It never routes a sub-agent to a model above your main one, and never touches a sub-agent whose model you set yourself. A card under the sub-agent's row shows the choice and the reason. `allow_opus: false` caps routing at Sonnet.

### Input Router
When Claude `Read`s a big `.md .txt .srt .vtt .log .csv .json .yaml .html ...` file (over 2,000 tokens), Haiku reads it first. Your model gets a digest focused on your request, the most relevant line ranges, and the path. **It never digests source code, PDFs, `.git/` or lockfiles.** It also passes the file through in full when:
- the Read already uses `offset`/`limit`
- your prompt says "verbatim", "exact", "whole file" or similar
- you're about to edit the file
- you pressed "read full instead" on the card

If Read stopped at its own token cap, the digest covers the whole file. MCP results get a free clean-up first (empty fields, base64, avatar URLs). If they are still large they're digested too, and the raw result is saved for exact lookups.

### Effort Optimizer
Free keyword rules classify each prompt; Haiku is asked only when they're unclear. All of this runs in the background, so your prompt is never delayed. In `suggest` mode (the default) a toast says, for example: `effort is high; this looks like a low task ("rename"). Run /effort low to switch.` In auto mode (`/mods set effort_optimizer.mode auto`) it sets the level on every request of that turn and says so.

### Doctor
On every session start it checks the Claude Code version. After an update it re-runs the self-test and lists the release notes that touch hooks, plugins or tools. It also:
- flags other plugins hooking the same tools or commands;
- logs hook input that changed shape;
- turns off a mod after 3 errors in a session or 10 in a day, and says why.

`/mods doctor` shows the full report.

---

## Results

Measured in this build on 2026-11-18, mostly in `claude -p` sessions. The $ figures are API-equivalent estimates from list prices. On a subscription they're quota, not money.

| Mod | Task | Without | With | Notes |
|---|---|---|---|---|
| Input Router | Find one decision in a 3,600-line meeting transcript (`.srt`), Sonnet, 2 runs each | ~163k input tokens per run; the read added ~14.5k tokens to the context | ~66k per run; the digest is ~0.6k | Same answer every run. Claude used the digest's line ranges to Read just the right lines. Each later message carries ~14k fewer tokens. |
| Input Router (MCP) | 60-issue tracker result, find one issue | ~11k tokens (est.) | 275-315 token digest | Correct answer in 3 turns. The free pre-clean removed 8% here. |
| Sub-agent router | "find all API routes" sub-agent, Sonnet main, 3 runs | $0.040-$0.062 at Sonnet prices (est.) | $0.0021-$0.0032 on Haiku (est.) | Real usage from the sub-agent's transcript |
| Keep Warm | 40k-token prefix, next message at +70 min (60 min TTL) | 11,938 read from cache, **39,008 rewritten** | **40,492 read from cache**, 10,660 written | One ping at +50 min read 40,492 from cache and wrote 7,704 |
| Handoff | Handoff doc for a ~20k-token test session | n/a | doc ~2,350 tokens | The fork read 20,032 tokens from cache; the session's own `/handoff` turn used 0 tokens. Not yet measured on a long (250k) session. |
| Effort Optimizer | Rename at `--effort high`, plus a 4-prompt session | 700-731 output tokens; session $0.1049 | 667-669 at low; session $0.1050 | **No measurable saving** on these tasks |
| `/mods`, `/savings` | One command | n/a | 0 tokens | Display-only, no model turn |

`/savings` reads your own log at `~/.claude/token-saver/savings.jsonl`. Token counts marked "est." are len/4 estimates, which run about 2x low on markdown with paths.

---

## Install

You need Claude Code 2.1.327 or newer and Python 3.10+.

```
/plugin marketplace add AbhishekBasnet/claude-token-saver
/plugin install token-saver@token-saver
```

The repository is private, so you need access to it and GitHub set up on your machine. From a local clone, use `claude plugin marketplace add <path-to-clone>` instead. It installs at user scope, so it is active in every project. `/mods` confirms it loaded.

Uninstall: `/plugin uninstall token-saver@token-saver`. Your settings and logs stay in `~/.claude/token-saver/`.

## Design principles

- **Fail open:** if a mod errors or times out, the event passes through unchanged.
- **Fail loud:** Doctor says when something broke, instead of letting a mod quietly stop working.
- **Never hide code:** the Input Router only digests reading material.
- **Always an escape hatch:** `/mods off <mod>`, `/mods pause`, Read with `offset`/`limit`, or say "verbatim".
- **Measured, not guessed:** savings are logged, and estimates are labelled as estimates.
- **Stdlib only:** Python 3 standard library, plus one small TypeScript shim that Claude Code runs itself.

## How it's built

Every decision lives in Python stdlib hooks (`plugins/token-saver/hooks`, `lib`). A thin TypeScript shim (`hooks/shim.tsx`) handles only what classic hooks can't:
- slash commands with no model turn
- the pinned status line
- toasts
- the info card under a tool row
- per-request effort
- model calls on the session's own client (`$.model.complete`, `$.model.fork`)

`docs/API-NOTES.md` records what was verified against the real API, and how.

Tests:

```bash
python3 tests/run_selftest.py               # 91 cases, Python only (also runs in CI)
claude plugin test plugins/token-saver      # shim tests on the real engine
claude plugin validate plugins/token-saver
```

## Known limitations

- **Smaller models can miss details.** Turn off the Input Router (`/mods off input_router`) for work where exact wording matters, or say "verbatim".
- **PDFs are never digested.** Text extraction would need a non-stdlib tool (`sudo dnf install poppler-utils`), so they always pass through.
- **Effort Optimizer:** no saving was measurable on the tasks tried. Auto mode is off by default. The first time a session switches level, it writes a separate cache entry.
- **Keep Warm costs a little per ping.** At Opus prices a 40k-token context costs about $0.01 to read, plus whatever new turns it writes. It only pays off if you come back within the pings. How often that happens wasn't measured, so no net saving is claimed.
- **Input Router on long turns:** if one turn has produced more than about 4 MB of transcript, the prompt used to focus the digest may not be found, and the digest falls back to the file's general content.
- **Cache Clock** notes a warm-cache hit after a gap as *observed*, not as a saving: the clock itself doesn't cause it.
- **Sub-agent cards** are drawn in the interactive UI. In `claude -p` only the logs show the routing.
- Background model calls still use your subscription quota, just less of it.

## Credits

Inspired by Ben AI's video on token-saving Claude mods. Specs, design and Linux build are my own.

## License

MIT
