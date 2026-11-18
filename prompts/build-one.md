# Prompt: build a single mod

Steps 0–2 (foundation, switchboard, doctor) are required first. After that you can build any one mod on its own.

Open a terminal in the repo folder, run `claude`, and paste — replacing the spec name:

```
Read BUILD.md, specs/00-foundation.md, specs/07-doctor.md and specs/02-handoff.md.
If docs/API-NOTES.md or steps 0–2 (foundation, switchboard, doctor) don't exist yet,
do those first and wait for my OK after each.
Then build only this mod, add its Doctor fixtures, run its acceptance tests and
/mods doctor, show me the results and commit.
```

Spec names: `02-handoff`, `03-cache-clock`, `04-subagent-router`, `05-input-router`, `06-effort-optimizer`.
