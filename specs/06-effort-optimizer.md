# 06 · Effort Optimizer

**One line:** suggests the right effort level for each prompt instead of running everything on high/max.

## Why

Higher effort means longer runs, more self-checking and more decisions made without asking. For small or hands-on tasks that's wasted tokens for the same — sometimes worse — result. For complex tasks, low effort under-delivers.

## Behaviour

- **Trigger:** on prompt submit (`UserPromptSubmit` or the mods equivalent).
- **Skip for free:** short conversational prompts (< ~15 words: "thanks", "ok", "yes do it") → no model call.
- Otherwise call Sonnet (configurable) with the new prompt, Claude's last reply (truncated to ~1500 tokens) and the current effort level if readable. JSON only:
  ```json
  {"recommended": "low|medium|high|max", "confidence": 0.0, "reason": "one line"}
  ```
- Classifier guidelines (also check Anthropic's current docs on choosing effort and fold them in):

| Level | Typical tasks |
|---|---|
| **low** | small edits, renames, formatting, quick factual questions, single-file tweaks, tasks where the user wants to stay in the loop |
| **medium** | normal feature work, moderate debugging, writing tests, explaining code |
| **high** | multi-file refactors, tricky bugs, architecture decisions, infra/DevOps changes (Kubernetes, Terraform, CI pipelines, networking) |
| **max** | genuinely hard long-running autonomous tasks, high-risk changes (prod config, migrations, security) |

- Act only when `recommended ≠ current` **and** `confidence ≥ 0.7`.
- **`mode: "suggest"` (default)** — one line, the user decides:
  ```
  ⚡ Effort: on max — this looks like a low task (rename + formatting). Run /effort low to switch.
  ```
- **`mode: "auto"`** — only if the real API lets a hook change effort. Change it and say so in one line. If not possible, report it and keep suggest-only.
- Don't repeat the same suggestion twice in a row in one session.
- In auto mode, log a saving event when effort is lowered (`detail` = from → to; tokens `n/a`).

## Acceptance

- "rename this variable to userId" on high → suggests low.
- "design the CI/CD pipeline and k8s manifests for this repo" on low → suggests high.
- "thanks" → no model call, nothing shown.
