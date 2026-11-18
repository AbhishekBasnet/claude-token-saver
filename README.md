# token-saver

**Six Claude Code mods that stop paying for tokens you don't need, plus a seventh that tells you when anything breaks.**

Big files get summarised by a cheaper model before they hit your context. Sub-agents run on the cheapest model that can do the job. You can see when your prompt cache goes cold, and you can move to a fresh session before a long chat gets expensive.

<!-- GIF: hero / overview -->

> **Status:** spec-first. Each mod is defined as a spec that Claude Code builds and tests on your machine. Built and tested on Fedora Linux.

---

## The mods

| # | Mod | What it does | Uses AI? |
|---|---|---|---|
| 1 | **Switchboard** `/mods` + `/savings` | Toggle any mod, pause all for a session, see what each mod saved | No |
| 2 | **Handoff** `/handoff` | Warns at 250k tokens, writes a detailed handoff doc, auto-loads it in a fresh session | Main model |
| 3 | **Cache Clock** | Status-line countdown until your prompt cache goes cold | No |
| 4 | **Sub-agent Model Selector** | Routes each sub-agent to Haiku / Sonnet / Opus by task difficulty | Heuristics, Haiku if unclear |
| 5 | **Input Router** | Haiku reads big docs, logs and connector results; your main model gets a focused digest | Haiku |
| 6 | **Effort Optimizer** | Suggests low / medium / high / max effort for each prompt | Sonnet |
| 7 | **Doctor** `/mods doctor` | Detects Claude Code updates, conflicts with other plugins and broken hooks; auto-disables a failing mod and tells you why | No |

### 1 · Switchboard + `/savings`
<!-- GIF: /mods and /savings -->
Every mod reads one config file. `/mods off input_router` turns a mod off and `/mods pause` pauses all of them for the current session. `/savings` shows tokens saved per mod for today, the last 7 days or all time. → [spec](specs/01-switchboard-savings.md)

### 2 · Handoff
<!-- GIF: handoff -->
Long chats cost more per message and get worse answers. Auto-compact waits until the context window is nearly full and keeps only a short summary. `/handoff` writes a detailed doc covering goal, decisions, files, commands, open problems and next steps. Run `/clear` and the fresh session loads that doc automatically. → [spec](specs/02-handoff.md)

### 3 · Cache Clock
<!-- GIF: cache clock -->
While the prompt cache is warm, re-reading your conversation is cheap. Once it expires, the next message pays full price for the whole context. Cache Clock puts a countdown in your status line so you know when that will happen. → [spec](specs/03-cache-clock.md)

### 4 · Sub-agent Model Selector
<!-- GIF: sub-agent routing -->
Sub-agents run on your main model by default, so ten Opus sub-agents get used for work like finding files. This mod sends simple work to Haiku, normal work to Sonnet, and keeps hard or risky work on Opus. → [spec](specs/04-subagent-router.md)

### 5 · Input Router
<!-- GIF: input router -->
When Claude reads a big document, the whole thing stays in context for every later message. The Input Router has Haiku read it first. Your main model gets a task-focused digest, line ranges, and the path to the full file. **Source code is never summarised**, and reading with `offset`/`limit` always gets the real text. → [spec](specs/05-input-router.md)

### 6 · Effort Optimizer
<!-- GIF: effort optimizer -->
Max effort on a rename wastes tokens, and low effort on an infra change under-delivers. This mod reads each prompt and suggests a better effort level when the current one looks wrong. You decide whether to switch. → [spec](specs/06-effort-optimizer.md)

### 7 · Doctor
<!-- GIF: doctor -->
Mods depend on Claude Code internals, and an update or another plugin can break them without any warning. Doctor notices when Claude Code updates and re-tests every mod. It also flags other plugins hooking the same events, catches hook input that changed shape, and turns off any mod that keeps failing. `/mods doctor` shows a health report at any time. → [spec](specs/07-doctor.md)

---

## Results

Measured on my own workflows. *(Fill in after building. Don't publish numbers you didn't measure.)*

| Mod | Task | Without | With | Saved |
|---|---|---|---|---|
| Input Router | | | | |
| Sub-agent Selector | | | | |
| Handoff | | | | |
| Cache Clock | | | | |

---

## Install

**Requirements:** Claude Code with mods/plugin support (update first: `claude update`), Python 3, a Claude subscription. Background model calls go through `claude -p`, so no API key is needed.

```bash
git clone https://github.com/<you>/token-saver.git ~/token-saver
cd ~/token-saver
claude
```

Then paste the prompt from [`prompts/build-all.md`](prompts/build-all.md). Claude Code builds one mod at a time, tests it and waits for your OK. To build a single mod instead, use [`prompts/build-one.md`](prompts/build-one.md). If an update breaks something, use [`prompts/after-update.md`](prompts/after-update.md).

Mods install at **user scope**, so they're active in every project.

## Design principles

- **Fail open:** if a mod errors or times out, Claude Code behaves as if the mod weren't installed.
- **Fail loud:** Doctor tells you when something broke, instead of letting a mod quietly stop working.
- **Never hide code:** the Input Router only summarises reading material, never source files.
- **Always an escape hatch:** `/mods off <mod>`, `/mods pause`, or say "verbatim" to get raw content.
- **Measured, not guessed:** every saving is logged to `~/.claude/token-saver/savings.jsonl`, and estimates are labelled as estimates.
- **Stdlib only:** Python 3 standard library, nothing extra to install.

## Repo layout

```
BUILD.md                 # instructions Claude Code follows
specs/                   # one spec per mod
  00-foundation.md
  01-switchboard-savings.md
  02-handoff.md
  03-cache-clock.md
  04-subagent-router.md
  05-input-router.md
  06-effort-optimizer.md
  07-doctor.md
prompts/                 # copy-paste prompts (build-all, build-one, after-update)
```

## Known limitations

- Smaller models can miss details. Turn off the Input Router (`/mods off input_router`) for work where precision matters.
- Some behaviour depends on what the current mods API allows, such as switching effort automatically, keeping the cache warm, or replacing MCP output. Where it doesn't, the mod falls back to a suggestion or skips that feature.
- Background model calls still use your subscription quota, just less of it.

## Credits

Inspired by Ben AI's video on token-saving Claude mods. Specs, design and Linux build are my own.

## License

MIT
