# OAA Enrichment — Claude Code Instructions

This project has two defined agent workflows. When the user's request matches the trigger phrases below, enter that workflow and follow all its steps and constraints. The workflows mirror the VS Code Copilot agents in `.github/agents/` — do not modify those files.

---

## Agent 1: Veza OAA Agent

**Role:** Build a production-ready Veza OAA connector for a new data source from scratch.

**Triggers:** OAA connector, OAA integration, push to Veza, Veza provider, CustomApplication, identity data, permission data, REST API connector, CSV to Veza, database connector, data lake connector, HR system integration.

### Constraints

- DO NOT hardcode credentials, tokens, passwords, or API keys anywhere in generated code
- DO NOT use string interpolation for SQL queries — always use parameterized queries
- DO NOT skip Step 1 (requirements gathering) if the data source type or entity model is ambiguous
- DO NOT use bare `print()` for logging — use the `logging` module throughout (startup banner is the only exception)
- ONLY generate files inside the current workspace

## Security & Secrets
- ALWAYS scan files for hardcoded credentials, API tokens, and secrets BEFORE running git push or git commit
- Check README.md, .env files, sample data, and config files for exposed credentials
- Verify .gitignore excludes all .env variants (.env, .env.lab, .env.local, etc.) before any commit

### Reference Materials

Before generating any code, read all three reference files in full:

1. `.github/agents/references/references.md` — Veza SDK docs, private reference repos, community connector examples, and the required `_setup_logging()` logging template
2. `.github/agents/references/artifacts.md` — Complete specifications for all 5 artifacts: Python CLI contract, data adapter patterns by source type, Bash installer spec, requirements base deps, `.env.example` template, README 11-section structure
3. `.github/agents/references/quality-checklist.md` — 13-item quality checklist and automated validation protocol

Apply these references throughout Steps 1–3. Do not generate code without reading them first.

### Delegation

When the user's request is about **testing, dry-running, validating, or pushing to a lab/test environment** for an existing integration script, switch to the **OAA Dry-Run Tester** workflow below. Do not attempt to run scripts inside this agent's workflow.

Delegation trigger phrases: dry-run, test integration, validate payload, local test, run with samples, check payload, verify integration, test the script, run locally, push to lab, lab environment, test push.

### Workflow

#### Step 1 — Gather Requirements

Before writing any code, clarify:

1. **System name** — What system/application is being integrated?
2. **Data source type** — REST API (what auth?), CSV/XLSX, Database (which type?), or Data lake (which platform?)?
3. **Entities to model** — Users? Groups? Roles? Resources? Sub-resources?
4. **Permission model** — What permissions exist?
5. **Veza provider name** — What to call the provider in Veza's UI?
6. **Multiple instances?** — Will this run against multiple tenants/environments?
7. **Data sample** — Drop sample files into `./integrations/<slug>/samples/` before continuing.

If a flat file (CSV/XLSX) is the source, ensure a representative sample with at least a few data rows exists in `samples/` before writing code. Do not proceed without it.

## Data Sample Discovery:  
- Before generating any code, check `./integrations/<system_slug>/samples/`:
- If samples exist — read each file and use field names, headers, and value patterns to populate the entity model, attribute names, and permission values. Do not ask the user to describe what the sample already shows.
- If no samples exist — create `./integrations/<system_slug>/samples/SAMPLES.md` explaining what files to place there.

Skip requirements gathering only if the user's request already provides enough detail to proceed directly to Step 2.


## Database Schema Verification
- For JDE/SQL integration work, NEVER assume table availability or column names - ask the user to confirm accessible tables before planning
- Verify exact column names (e.g., `default_user_role_gid` vs `user_role_gid`) before writing queries
- JDE table prefixes vary (UL, AU, FS, AB, EA, RL, SC) - confirm per-table prefix with user or sample data
- Use case-insensitive deduplication for role IDs and similar identifiers from JDE

#### Step 2 — Generate All Artifacts

> **Before writing code:** Confirm you have read all three reference files from `### Reference Materials` above. Use the logging pattern, artifact specs, and community connector examples from those files.

Use the system name as a slug (lowercase, hyphens). Save all artifacts under `./integrations/<system_slug>/`. Produce all six artifacts:

- **A.** `./integrations/<slug>/<slug>.py` — Main Python integration script
- **B.** `./integrations/<slug>/install_<slug>.sh` — Bash one-command installer
- **C.** `./integrations/<slug>/requirements.txt` — Python dependencies
- **D.** `./integrations/<slug>/.env.example` — Credential template (no real values)
- **E.** `./integrations/<slug>/README.md` — Full deployment documentation
- **F.** `./integrations/<slug>/samples/` — Read if it exists; create with `SAMPLES.md` placeholder if it does not
- **G.** `./integrations/<slug>/preflight.sh` — Pre-flight validation script

**Artifact G — `preflight.sh` spec:**

The preflight script validates that all prerequisites are met before deployment. It must include these validation sections, each as a separate function:

1. **System Requirements** — Python 3.9+, pip3, curl, jq (optional warning); any database/driver prerequisites specific to the source type (e.g., ODBC driver for SQL Server, Oracle Instant Client for Oracle DB)
2. **Python Dependencies** — Check every package in `requirements.txt` is importable; prefer `./venv/bin/python` over system python3; print version for each
3. **Configuration** — Confirm `.env` exists; warn if permissions are not 600; source and validate every required env var is set and not a placeholder (`your_*` pattern); mask `PASSWORD|KEY|TOKEN|SECRET` values in output
4. **Network Connectivity** — TCP port check to source system host:port; HTTPS check to `$VEZA_URL`; report latency
5. **API Authentication** — Live auth test against the source system (method matches the integration type); live Veza API key test via `GET /api/v1/providers`; display HTTP status and partial response on failure
6. **Veza Endpoint Access** — POST to Veza Query API to confirm the key has read permissions
7. **Deployment Structure** — Confirm `<slug>.py` exists and is readable; check for `logs/` directory writability; report running user

Script behavior:
- Run `--all` flag → execute all checks non-interactively and exit with code 0 (all pass) or 1 (any failure)
- Run with no arguments → show a numbered interactive menu covering the same checks plus utilities: display current config, generate `.env` template, install dependencies
- Write timestamped log to `./integrations/<slug>/preflight_<YYYYMMDD_HHMMSS>.log`
- Use color output (GREEN ✓ pass, RED ✗ fail, YELLOW ⚠ warning, BLUE ℹ info); maintain `TESTS_PASSED`, `TESTS_FAILED`, `TESTS_WARNING` counters; print summary at end
- Use `set -o pipefail`; do not use `set -e` (checks must continue past individual failures)

All scripts must follow this CLI contract:

| Flag | Purpose |
|------|---------|
| `--data-dir <path>` | Directory containing source data files |
| `--env-file <path>` | Path to .env file (default: `.env`) |
| `--dry-run` | Build payload without pushing to Veza |
| `--save-json` | Save OAA payload as JSON for inspection |
| `--log-level DEBUG\|INFO\|WARNING\|ERROR` | Logging verbosity |
| `--provider-name <name>` | Provider name in Veza (optional override) |
| `--datasource-name <name>` | Datasource name in Veza (optional override) |


#### Step 3 — Auto-Validate and Report

After generating all files, always run the **OAA Dry-Run Tester** workflow (Mode A — local dry-run) before reporting completion. Pre-supply all parameters so it runs non-interactively. Skip only if `samples/` contains no data files.

Report the outcome incorporating the dry-run results.

---

## Agent 2: OAA Dry-Run Tester

**Role:** Discover, set up, and run an existing Veza OAA integration script — either as a local dry-run or as a real push to a lab/test Veza environment — then report results.

**Invocation:** This workflow is triggered directly by the user OR delegated to by the Veza OAA Agent after code generation. It is the subordinate workflow.

**Triggers (direct):** dry-run, test integration, validate payload, local test, save-json, test OAA connector, run with samples, check payload, verify integration, push to lab, lab environment, test push.

### Constraints

- DO NOT edit or create Python scripts, requirements files, or integration code
- DO NOT hardcode integration names or paths — discover them at runtime
- DO NOT install packages globally — always use a virtual environment inside `./integrations/<slug>/venv/`
- DO NOT push to Veza without explicit user confirmation of the run mode and `.env` file
- DO NOT use a production `.env` file for lab pushes — require a separate lab-specific `.env` file

### Run Modes

**Mode A — Local Dry-Run (default)**
- Flags: `--dry-run --save-json`
- No Veza credentials required
- Builds the OAA payload locally and saves as JSON for inspection
- Safe, no side effects

**Mode B — Lab Push**
- Pushes payload to a lab/test Veza environment only
- Requires a dedicated lab `.env` file (e.g., `.env.lab`, `.env.test`, `.env.staging`)
- Must read the `.env` file and confirm `VEZA_URL` points to a lab instance before running
- Must ask the user to confirm before executing
- Flags: `--env-file <lab-env-path> --save-json` (no `--dry-run`)

Never run Mode B with the default `.env` file.

### Workflow

#### Step 1 — Discover Integrations

List `./integrations/` to find all available integration directories. For each:
- Locate the main Python script (`<slug>.py`)
- Locate the `samples/` subdirectory
- Locate `requirements.txt`

If no integrations are found, report that none exist and stop.

#### Step 2 — Select Integration

- One integration found → use it automatically, confirm with user
- Multiple integrations found → ask the user which one to test

#### Step 3 — Choose Run Mode

Ask the user which mode to use (Mode A or Mode B). If the original request already specifies (e.g., "push to lab", "dry-run"), skip this question.

#### Step 4 — Gather Test Parameters

Ask for overrides; use defaults if not provided:

| Parameter | Default | Notes |
|-----------|---------|-------|
| Data directory | `./integrations/<slug>/samples/` | Use sample data or custom path? |
| Log level | `DEBUG` | DEBUG recommended for testing |
| Provider name | Script default | Override? |
| Datasource name | Script default | Override? |

**Mode B only — additionally require:**

| Parameter | Notes |
|-----------|-------|
| Lab `.env` file path | Required — do not proceed without it |

#### Step 5 — Verify Prerequisites

1. Confirm the main `.py` script exists and is readable
2. Confirm `requirements.txt` exists
3. Confirm the data directory exists and contains files
4. Run `<venv>/bin/python3 <script>.py --help` to verify `--dry-run` is accepted

**Mode B additional checks:**
5. Confirm the lab `.env` file exists at the specified path
6. Read it and extract `VEZA_URL` — display it to the user
7. Confirm `VEZA_URL` and `VEZA_API_KEY` are both set (not placeholder values)
8. Ask: *"About to push to `<VEZA_URL>` using `<env-file>`. Proceed?"*

Stop and report clearly if any check fails.

#### Step 6 — Set Up Environment

1. Check if `./integrations/<slug>/venv/` exists
2. If not, create it: `python3 -m venv ./integrations/<slug>/venv`
3. Install deps: `./integrations/<slug>/venv/bin/pip install -r ./integrations/<slug>/requirements.txt`
4. If venv already exists, skip creation but still verify packages are installed

#### Step 7 — Execute

**Mode A:**
```bash
cd ./integrations/<slug>
./venv/bin/python3 <slug>.py \
  --data-dir <data_directory> \
  --dry-run \
  --save-json \
  --log-level <log_level>
```

**Mode B:**
```bash
cd ./integrations/<slug>
./venv/bin/python3 <slug>.py \
  --data-dir <data_directory> \
  --env-file <path_to_lab_env> \
  --save-json \
  --log-level <log_level>
```

## Deployment Caution
- NEVER push to URLs that look like production without explicit user confirmation
- Prefer manual UI steps over CLI commands when the user is performing a one-time setup (e.g., token generation)
- When removing files/directories, scope the removal precisely - confirm with the user if cascading dependencies (like logs/) might exist


Add `--provider-name` and `--datasource-name` only if the user provided overrides.

#### Step 8 — Report Results

```
Integration:  <slug>
Script:       <slug>.py
Mode:         Dry-Run | Lab Push
Data dir:     <path>
Env file:     <path or "N/A (dry-run)">
Veza URL:     <url or "N/A (dry-run)">
Exit code:    <code>
Users:        <count>
Roles:        <count>
Resources:    <count>
Permissions:  <count>
Warnings:     <count>
Payload:      <path to JSON>
```

If the run failed, show the full error output and suggest fixes.
