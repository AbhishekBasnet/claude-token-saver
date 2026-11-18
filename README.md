# token-saver

A Claude Code plugin that saves tokens. Haiku reads big files for your main model, sub-agents run on cheaper models, and a status line shows when your prompt cache goes cold.

Tested with Claude Code 2.1.327 on Fedora Linux. Needs Python 3.10+ (standard library only).

## Install

```
/plugin marketplace add AbhishekBasnet/claude-token-saver
/plugin install token-saver@token-saver
```

## What it does

- **Input Router:** Haiku digests big `.md`, `.txt`, `.log`, `.json` and `.srt` files and MCP results. It never touches source code.
- **Sub-agent router:** simple sub-agents run on Haiku and coding ones on Sonnet.
- **Cache Clock:** a status line that counts down until the cache goes cold. `/keepwarm on` keeps it warm.
- **Handoff:** `/handoff`, then `/clear`, continues in a fresh session.
- **Effort Optimizer:** suggests a better effort level for each prompt.
- **Doctor:** `/mods doctor` checks that everything still works after updates.

## Commands

| Command | What it does |
|---|---|
| `/mods` | list mods; `/mods off <mod>`, `/mods pause` |
| `/savings` | tokens saved per mod |
| `/handoff` | write a handoff doc for a fresh session |
| `/keepwarm on` | keep the prompt cache warm while you're away |

## Measured

- Big file read: about 60% fewer input tokens (~163k → ~66k), with the same answer.
- Sub-agent "find files" task: ~$0.003 on Haiku instead of ~$0.05 on Sonnet (est.).
- Keep Warm: the cache was still warm after 70 minutes (40k tokens read from cache instead of rewritten).
- Effort Optimizer: no measurable saving yet.

## Turn it off

`/mods off <mod>` turns off one mod. `/plugin uninstall token-saver@token-saver` removes the plugin.

## License

MIT
