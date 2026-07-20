# .claude/commands/

Custom slash commands for this project. Each `.md` file here becomes a `/command-name` you can type in Claude Code.

## How commands work

- File name → slash command: `dry-run.md` becomes `/dry-run`
- When you type `/dry-run`, Claude Code loads the file contents as the prompt and executes it
- Commands can reference agent workflows defined in `CLAUDE.md`
- Commands are project-scoped — they only appear when working inside this workspace

## Commands in this project

| File | Command | What it does |
|---|---|---|
| `dry-run.md` | `/dry-run` | Enters the OAA Dry-Run Tester workflow (Mode A by default) |
| `new-connector.md` | `/new-connector` | Enters the Veza OAA Agent workflow to build a new integration |

## Writing a new command

Create a `.md` file in this directory. The body is the prompt Claude receives when the command is invoked. You can:

- Reference workflows in `CLAUDE.md` by name
- Accept arguments via `$ARGUMENTS` (e.g. `/dry-run --mode lab`)
- Chain into sub-workflows by describing delegation logic

### Template

```markdown
<!-- commands/my-command.md -->
Follow the <Workflow Name> workflow defined in CLAUDE.md.

Arguments provided by the user: $ARGUMENTS

Start at Step 1 unless the arguments already answer the first questions.
```

## Naming conventions

Use lowercase hyphenated names that match the action, not the agent:
- `dry-run.md` not `oaa-dry-run-tester.md`
- `new-connector.md` not `veza-oaa-agent.md`
