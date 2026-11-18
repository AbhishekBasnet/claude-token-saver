# Prompt: build everything

Open a terminal in the repo folder, run `claude`, and paste:

```
You're building the token-saver mods in this repo.

1. Read BUILD.md, specs/00-foundation.md and specs/07-doctor.md fully, then skim the other specs.
2. Do "Step −1" in BUILD.md: check my installed Claude Code version, read the current
   docs for plugins, mods, hooks, slash commands, status line and marketplaces, and write
   docs/API-NOTES.md marking each spec ✅ / ⚠️ / ❌ with the reason and fallback.
   Show it to me and wait.
3. Then follow the build order in BUILD.md one step at a time. For each step: build,
   run the acceptance tests, show me the results with token numbers where possible,
   commit, and wait for my OK.

Rules:
- I'm on Fedora 45 KDE Plasma with a Claude subscription (no API key). Python stdlib only.
  If a system tool is needed, give me the dnf command instead of installing it.
- Install at user scope so the mods work in every project.
- Fail open: a broken mod must never block my work.
- If anything in a spec isn't possible with the real API, tell me before building it.
- Don't invent numbers in the README. Only what you measured.
```
