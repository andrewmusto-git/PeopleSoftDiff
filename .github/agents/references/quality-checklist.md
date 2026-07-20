# Output Summary & Quality Checklist

## Step 3 — Output Summary

After generating all five files, provide:

1. **File tree** of everything created
2. **One-command install invocation** (ready to copy-paste once the GitHub URL is known):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/install_<system_name>.sh | bash
   ```
3. **Example run command** using the generated CLI args:
   ```bash
   cd /opt/<system-slug>-veza/scripts
   source venv/bin/activate
   python3 <system_name>.py --env-file .env --dry-run
   ```
4. **What appears in Veza** — provider name, datasource name, entity types visible in Access Graph

---

## Step 3a — Automated Validation (Dry-Run)

After generating all artifacts and presenting the output summary, **automatically delegate to the `OAA Dry-Run Tester` sub-agent** to validate the generated integration. This runs Mode A (local dry-run) — no Veza credentials are needed and there are no side effects.

### When to run

- **Run automatically** when `./integrations/<system_slug>/samples/` contains data files (not just `SAMPLES.md`).
- **Skip** if `samples/` is empty or contains only the `SAMPLES.md` placeholder. Note in the output summary that automated validation was skipped because no sample data is available.

### How to delegate

Invoke the `OAA Dry-Run Tester` sub-agent with a prompt that **pre-supplies all parameters** so it does not prompt interactively:

> Run a local dry-run for the `<system_slug>` integration.
> - **Integration**: `./integrations/<system_slug>/`
> - **Script**: `<system_slug>.py`
> - **Mode**: Local dry-run (Mode A)
> - **Data directory**: `./integrations/<system_slug>/samples/`
> - **Log level**: DEBUG
> - **Provider name**: (use script default)
> - **Datasource name**: (use script default)
>
> Do not ask any interactive questions — all parameters are provided above.

### Interpreting results

| Dry-run result | Action |
|---|---|
| **Exit code 0** | Mark auto-validated checklist items (below) as passed. Include entity counts and JSON payload path in the output summary. |
| **Exit code non-zero** | Report the full error output to the user. Flag which checklist items failed. Do NOT attempt to auto-fix the generated code — let the user decide how to proceed. |

---

## Quality Checklist

Verify each file before marking the task complete. Items marked **🤖 auto** are validated by the dry-run step above (when samples exist); items marked **👁️ manual** require code review.

- [ ] 🤖 auto — Python script runs with `python3 <script>.py --help` without errors
- [ ] 👁️ manual — All credentials read from env/args — none hardcoded
- [ ] 👁️ manual — SQL queries use parameterized form — no string interpolation
- [ ] 👁️ manual — Installer supports both RHEL (`dnf`/`yum`) and Ubuntu (`apt`)
- [ ] 👁️ manual — Installer supports `--non-interactive` mode with env vars
- [ ] 👁️ manual — `.env.example` has placeholder values only — no real credentials
- [ ] 👁️ manual — README includes both interactive and non-interactive install instructions
- [ ] 👁️ manual — README includes a cron scheduling example
- [ ] 👁️ manual — README includes a troubleshooting section
- [ ] 👁️ manual — Logging uses `logging` module throughout — no bare `print()` (startup banner excepted)
- [ ] 👁️ manual — `push_application()` is called with `create_provider=True` so the provider is created automatically if it does not exist
- [ ] 🤖 auto — `--dry-run` skips Veza push and exits cleanly
- [ ] 🤖 auto — If `samples/` contained files, generated field names match sample data exactly
- [ ] 👁️ manual — If `samples/` was empty, `samples/SAMPLES.md` placeholder was created
