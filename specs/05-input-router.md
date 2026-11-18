# 05 · Input Router

**One line:** big documents and connector results get read by Haiku first; the main model gets a focused digest plus the path to the full thing.

## Why

Whatever Claude reads lands in the conversation in full and is re-sent with every later message. One question about a long transcript means the whole transcript rides along for the rest of the session — even if five lines mattered.

## When it triggers

- Tool is `Read` (MCP results: see below).
- Estimated size > `threshold_tokens` (default 2000).
- File type is **reading material**: `.txt .md .srt .vtt .log .csv .tsv .json .jsonl .xml .html .yaml .yml` (`.pdf` only if text extraction is cheap; otherwise skip).

## When it must NOT trigger

- The `Read` call already has `offset`/`limit` — Claude is deliberately reading a slice. **This is the escape hatch.**
- Source code: `.py .go .dart .ts .tsx .js .rs .java .kt .swift .c .cpp .h .sh .sql .proto .tf .hcl` and similar. Claude must see real code, and `Edit` requires a real `Read` first.
- Anything under `.git/`, lockfiles, and files Claude is about to edit.
- The user's latest prompt contains "whole file", "full file", "exact", "verbatim", or "line by line" (case-insensitive).
- Mod disabled or session paused.

## What it does — `Read`

1. Collect context: the user's latest prompt (from the transcript) and Claude's stated reason for the read if available.
2. Send Haiku the file content (chunk if huge: summarise chunks, then merge) plus the task. Ask for:
   - a **task-focused digest** — key facts, numbers, names, decisions; quotes ≤ 2 lines each where wording matters
   - **line ranges** of the most relevant sections, e.g. `L120–L180: pricing discussion`
   - a **"Not covered / may need full read"** line when unsure
3. Deliver the digest instead of the raw file using what the real hook API supports (e.g. `PreToolUse` deny-with-reason, or input rewritten to a digest file). The message must include:
   ```
   [Input Router] Haiku digest of <path> (~N → ~M tokens). Full file unchanged at <path>.
   To read exact text, call Read again with offset/limit for the line ranges above.
   ```
4. Log the saving.

## MCP / connector results

Only if the real API lets a `PostToolUse` hook replace MCP output (e.g. `updatedMCPToolOutput`):

1. **Free pre-clean, no AI:** strip null/empty fields, base64 blobs, avatar/image URLs, duplicated metadata, long unreferenced IDs/hashes. Log this saving separately.
2. Still over threshold → Haiku digest with the user's task, same format as above.
3. Save the raw result to `~/.claude/token-saver/cache/<session>/<timestamp>-<tool>.json` and include that path so Claude can `Read` it with offset/limit.

If replacing MCP output isn't supported, report it and skip this part.

## Acceptance

- ~20k-token `.md` or `.srt` → digest delivered, path given, saving logged.
- 3k-token `.py` → passes through untouched.
- `Read` with `offset`/`limit` → untouched.
- Prompt containing "verbatim" → untouched.
- Forced Haiku timeout → passes through; error in `debug.log`.
