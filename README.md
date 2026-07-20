# Veza OAA Integration Agent — VS Code Setup Guide

A VS Code workspace that gives you two **GitHub Copilot agents** and two **Claude Code slash commands** for generating production-ready [Veza OAA](https://docs.veza.com/4yItIzMvkpAvMVFAamTf/developers/api/oaa/getting-started) connector scripts from scratch — including the Python integration, Bash installer, preflight validation script, `.env` template, `requirements.txt`, and deployment README.

---

## Prerequisites

| Requirement | Minimum version / notes |
|---|---|
| **VS Code** | 1.99+ (required for `.github/agents/` auto-discovery) |
| **GitHub Copilot extension** | Latest — must be signed in with a **Copilot Pro** (or higher) seat |
| **GitHub Copilot Chat extension** | Latest — agent mode must be enabled (see [Step 3](#3-enable-agent-mode)) |
| **Python** | 3.9+ — only needed to run the generated integrations, not to use the agent |
| **Git** | Any recent version |

---

## 1. Create Your Own Repo from the Template

> **Do not push changes directly to `OAA_Agent`.** It is a shared template. Create your own copy first.

### Option A — GitHub UI (recommended)

1. Go to <https://github.com/pvolu-vz/OAA_Agent>.
2. Click **Use this template → Create a new repository**.
3. Choose an owner and name (e.g. `oaa-workday-connector`), set visibility, then click **Create repository**.
4. Clone your new repo and open it in VS Code:

```bash
git clone https://github.com/<your-org>/<your-repo-name>.git
cd <your-repo-name>
code .
```

### Option B — Terminal only

```bash
# 1. Clone the template into a new directory
git clone https://github.com/pvolu-vz/OAA_Agent.git <your-repo-name>
cd <your-repo-name>

# 2. Remove the original remote so you can't accidentally push back
git remote remove origin

# 3. Create a new empty repo on GitHub (via gh CLI or the web UI), then add it
gh repo create <your-org>/<your-repo-name> --private --source=. --push
# — or manually —
git remote add origin https://github.com/<your-org>/<your-repo-name>.git
git push -u origin main
```

### Open in VS Code (one click)

If you already have the repo cloned, open it with:

[![Open in VS Code](https://img.shields.io/badge/Open%20in-VS%20Code-blue?logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://vscode.git/clone?url%3Dhttps://github.com/pvolu-vz/OAA_Agent.git)

> **Important:** Open the **root folder** of your repo, not a subfolder. VS Code only auto-discovers `.github/agents/` and Claude Code only reads `CLAUDE.md` and `.claude/` when the workspace root contains them.

---

## 2. Repo Structure

```
OAA_Agent/
├── .claude/
│   ├── settings.json               ← Claude Code project settings
│   ├── settings.local.json         ← local overrides (gitignored)
│   ├── README.md                   ← Claude Code setup notes
│   └── commands/
│       ├── new-connector.md        ← /new-connector slash command
│       └── dry-run.md              ← /dry-run slash command
├── .github/
│   ├── copilot-instructions.md     ← Copilot workspace context
│   └── agents/
│       ├── veza-oaa-integration.agent.md   ← OAA builder agent
│       ├── oaa-dry-run.agent.md            ← dry-run / lab push agent
│       └── references/
│           ├── references.md       ← Veza SDK docs & logging template
│           ├── artifacts.md        ← full spec for all 7 generated artifacts
│           └── quality-checklist.md ← 13-item validation checklist
├── CLAUDE.md                       ← Claude Code agent workflow definitions
├── README.md
└── integrations/                   ← generated connector output lands here
    └── <system-slug>/
        ├── <slug>.py               ← main connector script
        ├── install_<slug>.sh       ← one-command Bash installer
        ├── preflight.sh            ← pre-deployment validation script
        ├── requirements.txt
        ├── .env.example
        ├── README.md
        └── samples/                ← sample source data for dry-run testing
```

---

## 3. Enable Agent Mode

1. Open the **Copilot Chat** panel: `⌘ Shift I` (macOS) / `Ctrl Shift I` (Windows/Linux), or click the chat icon in the Activity Bar.
2. In the chat input area, click the **mode selector dropdown** (shows "Ask" by default) and choose **Agent**.
3. Confirm you see agent mode is active — the input bar will show `@` suggestions.

> If you don't see the mode dropdown, update the GitHub Copilot Chat extension to the latest version.

---

## 4. Using the Custom Agents

Two agents are available in Copilot Agent mode. Use the builder to create a new connector; use the dry-run tester to validate or push an existing one.

### Veza OAA Integration Script — builder

Handles the full end-to-end workflow: gathers requirements, reads data samples, generates all integration files, and runs an automatic dry-run quality check.

```
@Veza OAA Integration Script <describe what you're building>
```

### OAA Dry-Run Tester — validator

Discovers existing integrations, sets up the environment, and runs the script as a local dry-run or as a push to a lab/test Veza environment. Does not modify any code.

```
@OAA Dry-Run Tester <integration name or "dry-run" / "push to lab">
```

### Example prompts

```
@Veza OAA Integration Script Build a connector for Workday HCM using OAuth2 client credentials.
Users and groups should map to Veza local users and roles.
```

```
@Veza OAA Integration Script I have a CSV export of our internal Access DB with columns: user_id, resource_name, permission_level.
Build an OAA integration that reads this file and pushes to Veza.
```

```
@Veza OAA Integration Script Create an OAA connector for a PostgreSQL database. I need to model
database roles as Veza roles and tables as resources with SELECT/INSERT/UPDATE/DELETE permissions.
```

```
@OAA Dry-Run Tester Run a dry-run for the workday integration with sample data.
```

```
@OAA Dry-Run Tester Push the workday integration to lab using .env.lab.
```

### What the builder agent does

| Step | What happens |
|---|---|
| **1 — Gather requirements** | If your prompt doesn't answer all required questions (system name, data source type, entity model, permission model), the agent asks before writing any code. |
| **2 — Read data samples** | If you drop sample files into `./integrations/<slug>/samples/` first, the agent reads them automatically to infer field names, entity structure, and permission values. |
| **3 — Generate artifacts** | Creates all 7 files under `./integrations/<system-slug>/`: Python script, Bash installer, `preflight.sh`, `requirements.txt`, `.env.example`, integration-level `README.md`, and `samples/` placeholder. |
| **4 — Auto dry-run** | Delegates to the OAA Dry-Run Tester (Mode A) automatically and reports the result before finishing. |

### Accelerate with data samples

Before invoking the agent, drop a small data sample into the expected path and the agent will use it automatically — no extra prompting needed:

```bash
mkdir -p integrations/<slug>/samples
cp ~/Downloads/export.csv integrations/<slug>/samples/
```

Accepted formats: CSV, XLSX, JSON API response snippets, SQL `DESCRIBE TABLE` output.

---

## 5. Using Claude Code Slash Commands

If you use **Claude Code** (CLI or VS Code extension), two slash commands are available that map directly to the Copilot agents above. Both commands read their full workflow from `CLAUDE.md`.

| Command | What it does |
|---|---|
| `/new-connector` | Runs the Veza OAA Agent workflow — gathers requirements, generates all 7 artifacts, auto-validates with a dry-run |
| `/dry-run` | Runs the OAA Dry-Run Tester workflow — discovers integrations, sets up the venv, and runs locally (Mode A) or pushes to a lab (Mode B) |

Invoke them in the Claude Code chat panel:

```
/new-connector Build a connector for Workday HCM using OAuth2 client credentials.
```

```
/dry-run push to lab using .env.lab
```

Omit arguments to have Claude ask questions interactively. Pass `--dry-run` or `lab` keywords and the workflow selects the correct run mode automatically.

---

## 6. Troubleshooting

**The `@Veza OAA Integration Script` or `@OAA Dry-Run Tester` agent doesn't appear in the `@` picker**
- Confirm VS Code is ≥ 1.99: `Help → About`.
- Confirm you opened the **root** `OAA_Agent/` folder, not a subfolder.
- Reload the window: `⌘ Shift P` → `Developer: Reload Window`.
- Check that `.github/agents/veza-oaa-integration.agent.md` and `.github/agents/oaa-dry-run.agent.md` both exist with valid YAML frontmatter.

**Generated files appear in the wrong location**
- The agent writes all output to `./integrations/<slug>/` relative to the workspace root.
- If files appear elsewhere, confirm the workspace root is `OAA_Agent/` and not a parent folder.

**Claude Code slash commands aren't available**
- Confirm you're running Claude Code (CLI or VS Code extension) and have `CLAUDE.md` at the workspace root.
- Confirm `.claude/commands/new-connector.md` and `.claude/commands/dry-run.md` exist.
- Slash commands are Claude Code–specific and won't appear in Copilot Chat.

**Agent asks too many questions when I've already described the system**
- Include in your first message: system name, data source type + auth method, entity types (users/groups/roles/resources), and permission names. The agent skips the Q&A when all required fields are present.

**Dry-run fails with missing packages**
- The dry-run tester always creates or reuses `./integrations/<slug>/venv/` — it will not use system Python. If the venv is stale, delete it and re-run: `rm -rf ./integrations/<slug>/venv`.
