# .claude/

Project-level Claude Code configuration directory. Files here are automatically picked up by Claude Code and apply to every conversation within this workspace.

## Structure

```
.claude/
├── README.md           — This file
├── settings.json       — Tool permissions, hooks, and environment config
└── commands/           — Custom slash commands (skills) for this project
    ├── README.md
    ├── dry-run.md      — /dry-run  → triggers OAA Dry-Run Tester workflow
    └── new-connector.md — /new-connector → triggers Veza OAA Agent workflow
```

## How it fits together

| File/Folder | What it controls |
|---|---|
| `../CLAUDE.md` | Always-on instructions: agent workflows, rules, trigger phrases |
| `settings.json` | Which tools are allowed, hooks that fire on tool events, env vars |
| `commands/*.md` | Slash commands the user can type (e.g. `/dry-run`) |

Changes here take effect immediately — no restart needed.
