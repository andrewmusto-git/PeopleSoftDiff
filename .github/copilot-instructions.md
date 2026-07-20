# Veza OAA Agent — Copilot Instructions

This repository contains tooling to build and test Veza OAA (Open Authorization API) connectors. OAA connectors collect identity and permission data from external systems and push it into Veza's Access Graph.

## Available Agents

Two agents are defined in `.github/agents/`:

### Veza OAA Agent (`veza-oaa-integration.agent.md`)
Builds a production-ready OAA connector for a new data source from scratch. Generates all deployment artifacts: Python integration script, Bash installer, requirements, `.env.example`, README, and preflight validation script.

**Use when:** building a new connector, integrating a new system, modeling identity/permission data for Veza.

### OAA Dry-Run Tester (`oaa-dry-run.agent.md`)
Discovers, sets up, and runs an existing integration script — either as a local dry-run or as a real push to a lab/test Veza environment. Does not modify code.

**Use when:** testing or validating an existing integration, running with sample data, pushing to a lab environment.

## Reference Materials

Shared reference docs for both agents live in `.github/agents/references/`:
- `references.md` — Veza SDK docs, community connector examples, logging template
- `artifacts.md` — Full specification for all generated artifacts
- `quality-checklist.md` — Post-generation validation checklist and dry-run delegation protocol

## Project Structure

```
integrations/
└── <system-slug>/          # one directory per integration
    ├── <slug>.py           # main connector script
    ├── install_<slug>.sh   # one-command installer
    ├── preflight.sh        # pre-deployment validation
    ├── requirements.txt
    ├── .env.example
    ├── README.md
    └── samples/            # sample source data for dry-run testing
```
