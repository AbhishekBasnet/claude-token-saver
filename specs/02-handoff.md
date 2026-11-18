# 02 · Handoff

**One line:** move to a fresh, cheap session before a long chat gets expensive and sloppy — without losing anything.

## Why

Every message re-sends the whole conversation. Past a few hundred thousand tokens, each message costs more and answer quality drops (context rot). Auto-compact only kicks in when the window is almost full, and its summary is short and lossy. A detailed handoff doc + a fresh session is usually cheaper *and* better.

## Behaviour

### Threshold warning
When the session's context passes `threshold_tokens` (default 250k — read real usage from the transcript), show once:

```
📦 Context at 252k tokens. Run /handoff to continue in a fresh session.
```

Show again only every +50k.

### `/handoff` (any time)
1. Re-read the current session transcript.
2. Write a detailed handoff doc to
   `~/.claude/token-saver/handoffs/<project-slug>/<timestamp>.md` and copy it to `LATEST.md` in the same folder.
3. Required sections:
   - **Goal** — what we're ultimately trying to do
   - **Current state** — what's done and working
   - **Decisions made (and why)** — including options we rejected
   - **Files** — created / modified / important, with paths and a one-line purpose each
   - **Commands & environment** — how to run, build, test; env vars, ports, containers
   - **Open problems** — failing tests, exact error messages, suspicions
   - **Next steps** — ordered and concrete
   - **Skills, MCP tools, links & docs used**
   - **Preferences the user showed this session** (style, constraints)
4. Be specific: exact names, paths, error strings. It must be clearly better than `/compact`.
5. Finish with: `Handoff saved. Run /clear (or start a new session) — it will load automatically.`

### Auto-load
- On `SessionStart` with source `clear`: inject `LATEST.md` as context, headed
  `[Handoff] Continuing from previous session (<timestamp>). Read this first:`
- On `startup`: only if `LATEST.md` for this project exists, is < 24 h old, **and** the user confirms.
- After loading, rename `LATEST.md` → `loaded-<timestamp>.md` so it never loads twice.

### Savings
Log `tokens_before` = old context size, `tokens_after` = handoff doc size.

## Acceptance

- After a real working session, `/handoff` produces a doc with every section filled with specifics.
- `/clear` → new session starts with the handoff injected; `LATEST.md` renamed.
- Running in a project with no handoff → nothing injected.
