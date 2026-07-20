# Artifact Specifications — Veza OAA Integration

This file contains the full specification for all five artifacts generated in Step 2.

> **Note on data samples:** If `./integrations/<system_slug>/samples/` contains files, use them to infer field names, entity attributes, and permission values throughout all artifacts below. If the directory is empty or absent, create `./integrations/<system_slug>/samples/SAMPLES.md` explaining what files to place there (e.g., a 5-row CSV export, a single JSON API response, or a `DESCRIBE TABLE` output).

---

## A. Main Python Script — `<system_name>.py`

```python
#!/usr/bin/env python3
"""
<System Name> to Veza OAA Integration Script
Collects identity and permission data from <System Name> and pushes to Veza.
"""
import argparse
import logging
import os
import sys
from dotenv import load_dotenv
from oaaclient.client import OAAClient, OAAClientError
from oaaclient.templates import CustomApplication, OAAPermission
```

**Required CLI arguments** (always include all of these):
- `--env-file` (default: `.env`)
- `--veza-url` (also reads `VEZA_URL` env var)
- `--veza-api-key` (also reads `VEZA_API_KEY` env var)
- `--provider-name` (default: system name)
- `--datasource-name` (default: system instance identifier)
- `--dry-run` (skip Veza push)
- `--log-level` (DEBUG/INFO/WARNING/ERROR, default: INFO)
- All source-specific args (API URL, CSV path, DB connection, etc.)

**Credential precedence** — CLI arg → env var → .env file:
```python
def load_config(args):
    if args.env_file and os.path.exists(args.env_file):
        load_dotenv(args.env_file)
    return {
        "veza_url": args.veza_url or os.getenv("VEZA_URL"),
        "veza_api_key": args.veza_api_key or os.getenv("VEZA_API_KEY"),
        # source-specific credentials follow the same pattern
    }
```

**Data collection** — adapter pattern based on data source type:
- REST API: `requests` with retry logic and proper error handling
- CSV/XLSX: `csv` module or `openpyxl`/`pandas`
- Database: `sqlalchemy` or appropriate driver; always use parameterized queries
- Data lake: `boto3` / `azure-storage-blob` / `google-cloud-storage`

**OAA payload assembly**:
```python
def build_oaa_payload(data, args):
    app = CustomApplication(name=args.datasource_name, application_type=args.provider_name)
    app.add_custom_permission("read",  [OAAPermission.DataRead])
    app.add_custom_permission("write", [OAAPermission.DataRead, OAAPermission.DataWrite])
    app.add_custom_permission("admin", [OAAPermission.DataRead, OAAPermission.DataWrite,
                                        OAAPermission.MetadataRead, OAAPermission.MetadataWrite])
    # Add local users, groups, resources, permissions based on actual data model
    return app
```

**Push to Veza** — match the NetApp reference pattern exactly:
```python
def push_to_veza(veza_url, veza_api_key, provider_name, datasource_name, app, dry_run=False):
    if dry_run:
        logging.info("[DRY RUN] Payload built successfully — skipping push")
        return
    veza_con = OAAClient(url=veza_url, token=veza_api_key)
    try:
        response = veza_con.push_application(
            provider_name=provider_name,
            data_source_name=datasource_name,
            application_object=app,
        )
        if response.get("warnings"):
            for w in response["warnings"]:
                logging.warning("Veza warning: %s", w)
        logging.info("Successfully pushed to Veza")
    except OAAClientError as e:
        logging.error("Veza push failed: %s — %s (HTTP %s)", e.error, e.message, e.status_code)
        if hasattr(e, "details"):
            for d in e.details:
                logging.error("  Detail: %s", d)
        sys.exit(1)
```

Include `if __name__ == "__main__":` with structured logging setup.

---

## B. Bash Installer — `install_<system_name>.sh`

Mirror the NetApp `install_ontap.sh` pattern exactly:

```bash
#!/usr/bin/env bash
# install_<system_name>.sh — One-command installer for <System Name>-Veza OAA integration
set -euo pipefail
```

The installer must:
1. Detect Linux distro — support RHEL/CentOS/Fedora (`dnf`/`yum`) and Ubuntu/Debian (`apt`). Also read `OS_ID` from `/etc/os-release` (`ID=` field) so Amazon Linux (`amzn`) can be handled specially.
2. Install packages **one at a time with a pre-check**, never in a single bulk `dnf install` call — a conflict on one package (e.g. `curl`) will fail the entire command and block `git` from installing:
   ```bash
   _install_pkg() {
       local pkg="$1"
       case "${PKG_MGR}" in
           dnf|yum) "${PKG_MGR}" install -y "${pkg}" >/dev/null ;;
           apt-get) apt-get install -y "${pkg}" >/dev/null ;;
       esac
   }
   command -v git     &>/dev/null || _install_pkg git
   command -v python3 &>/dev/null || _install_pkg python3
   python3 -m pip --version &>/dev/null || _install_pkg python3-pip
   ```
3. **`curl` on Amazon Linux** — `curl-minimal` is pre-installed and conflicts with full `curl`. Skip the curl install if `OS_ID=amzn` and curl is already present:
   ```bash
   if ! command -v curl &>/dev/null; then
       [[ "${OS_ID}" == "amzn" ]] \
           && warn "Skipping curl on Amazon Linux (curl-minimal conflict)" \
           || _install_pkg curl
   fi
   ```
4. **`python3-venv` on Amazon Linux 2023 / RHEL 9+** — `venv` is built into `python3`; `python3-venv` is not a separate package and `dnf` will error. Check first, and use `python3-virtualenv` as the fallback package name for dnf/yum:
   ```bash
   if ! python3 -m venv --help &>/dev/null; then
       case "${PKG_MGR}" in
           dnf|yum) _install_pkg python3-virtualenv ;;
           apt-get) _install_pkg python3-venv ;;
       esac
   fi
   ```
5. Check Python ≥ 3.8 and exit with clear message if not met.
6. **Clone with `GIT_TERMINAL_PROMPT=0`** — sparse-checkout flags (`--filter=blob:none --sparse`) trigger credential prompts even on public repos. Use a simple shallow clone into a temp dir, copy integration files, then clean up:
   ```bash
   tmp_dir=$(mktemp -d)
   GIT_TERMINAL_PROMPT=0 git clone --branch "${BRANCH}" --depth 1 --single-branch \
       "${REPO_URL}" "${tmp_dir}" || die "git clone failed"
   cp -f "${tmp_dir}/${INTEGRATION_SUBDIR}"/*.py  "${SCRIPTS_DIR}/"
   cp -f "${tmp_dir}/${INTEGRATION_SUBDIR}/requirements.txt" "${SCRIPTS_DIR}/"
   rm -rf "${tmp_dir}"
   ```
7. Create this directory layout:
   ```
   /opt/VEZA/<system-slug>-veza/
   ├── scripts/
   │   ├── <system_name>.py
   │   ├── requirements.txt
   │   ├── .env               (generated by installer, chmod 600)
   │   └── venv/
   └── logs/
   ```
8. Create a Python venv and install `requirements.txt`.
9. **Interactive prompts must use `/dev/tty`** — when the script runs via `curl | bash`, stdin is the pipe, not the terminal. All `read` calls must redirect from `/dev/tty`:
   ```bash
   IFS= read -r -p "Veza URL: " value </dev/tty
   IFS= read -r -s -p "API key: " secret </dev/tty; echo >/dev/tty
   ```
10. Support non-interactive/CI mode via env vars:
    ```bash
    VEZA_URL=... VEZA_API_KEY=... SOURCE_API_URL=... SOURCE_API_KEY=... \
    bash install_<system_name>.sh --non-interactive
    ```
11. Generate `.env` with `chmod 600` and explanatory comments.
12. Accept flags: `--non-interactive`, `--overwrite-env`, `--install-dir <path>`, `--repo-url <url>`, `--branch <name>`
13. Print final summary: install path, next steps, example run command.

---

## C. Requirements File — `requirements.txt`

Base dependencies always included:
```
oaaclient>=3.0.0
python-dotenv>=1.0.0
requests>=2.31.0
urllib3>=2.0.0
```

Add only what the data source requires:
- CSV/XLSX: `openpyxl>=3.1.0`
- PostgreSQL: `psycopg2-binary`
- Oracle: `cx_Oracle`
- MSSQL: `pymssql`
- MySQL: `pymysql`
- S3: `boto3>=1.34.0`
- ADLS: `azure-storage-blob>=12.19.0`
- GCS: `google-cloud-storage>=2.14.0`

---

## D. Environment Template — `.env.example`

```bash
# <System Name> Source Configuration
SOURCE_API_URL=https://your-source-system.example.com
SOURCE_API_KEY=your_api_key_here
# SOURCE_CSV_PATH=/path/to/data.csv
# SOURCE_DB_URL=postgresql://user:pass@host/db

# Veza Configuration
VEZA_URL=your-company.veza.com
VEZA_API_KEY=your_veza_api_key_here

# OAA Provider Settings (optional overrides)
# PROVIDER_NAME=<System Name>
# DATASOURCE_NAME=<System Name> Instance
```

---

## E. README — `README.md`

Write comprehensive documentation covering all of the following sections:

1. **Overview** — what the script does, which Veza entities it creates, data flow; include the entity model table and OAA permission mapping table
2. **Entity Relationship Map** — a Mermaid diagram showing exactly what the script pushes to Veza; always required

   Generate a `graph LR` diagram with two subgraphs:

   - **Source subgraph** — label it with the source system name; one node per table/endpoint/file the script reads from; node labels show the table/endpoint name and a brief description
   - **Veza subgraph** — label it `🔷 Veza Access Graph — OAA CustomApplication`; include one node per OAA entity type the script creates: `Local User`, `Local Role` (if roles exist), `Application Resource` (if resources exist), `Custom Permission` (listing all permission names defined in `add_custom_permission`)

   Edges:
   - Source → OAA entity: label with `"extract <entity>"`
   - Source → OAA entity for relationship data (e.g. membership table): label with `"<relationship> assignment"`
   - Source → `Custom Permission`: label with `"map flags → permissions"` (or equivalent)
   - Between OAA entities: `Local User -->|"member of"| Local Role`, `Local Role -->|"has permission"| Custom Permission`, `Local User -->|"has permission"| Custom Permission`, `Custom Permission -->|"on resource"| Application Resource`

   Derive every node and edge from the actual script — do not invent tables or entities that the code does not read or create.

   Reference pattern (JDE connector):
   ```mermaid
   graph LR
       subgraph JDE["📊 JDE EnterpriseOne — Source Tables"]
           F0092["F0092 · F0101 · F01151\nUser Master + Address Book + Email"]
           F00926["F00926\nRole Definitions + User Assignments"]
           F9860["F9860 · F00950\nObject Librarian / Programs (fallback)"]
           F00950["F00950\nSecurity Matrix"]
       end

       subgraph Veza["🔷 Veza Access Graph — OAA CustomApplication"]
           LU["Local User"]
           LR["Local Role"]
           AR["Application Resource\n(Program / UBE)"]
           CP["Custom Permission\nview · add · change · delete · run · full_access"]
       end

       F0092  -->|"extract users"| LU
       F00926 -->|"extract roles"| LR
       F00926 -->|"user-role membership"| LU
       F9860  -->|"extract programs"| AR
       F00950 -->|"map flags → permissions"| CP

       LU -->|"member of"| LR
       LR -->|"has permission"| CP
       LU -->|"has permission"| CP
       CP -->|"on resource"| AR
   ```

3. **How It Works** — numbered steps matching the actual code flow
4. **Prerequisites** — OS, Python version, network access, source system API needs, Veza requirements
5. **Quick Start** — one-command installer using `curl -fsSL ... | bash`
6. **Manual Installation** — RHEL and Ubuntu instructions, venv setup, .env config
7. **Usage** — full CLI arguments table (Argument | Required | Values | Default | Description), with examples
8. **Deployment on Linux** — service account creation, file permissions, SELinux (RHEL), cron setup, log rotation:
   - Create dedicated service account: `sudo useradd -r -s /bin/bash -m -d /opt/<slug>-veza <slug>-veza`
   - `chmod 600` on `.env`, `chmod 700` on scripts dir
   - SELinux check (`getenforce`) and `restorecon` guidance for RHEL
   - Wrapper script for cron + `/etc/cron.d/` example
   - Log rotation config
9. **Multiple Instances** (if applicable) — separate .env files, `--env-file` flag, cron staggering
10. **Security Considerations** — credential rotation, file permissions, SELinux/AppArmor
11. **Troubleshooting** — auth failures, connectivity issues, missing modules, Veza push warnings
12. **Changelog** — v1.0 initial release

---

## F. Preflight Validation Script — `preflight_<system_name>.sh`

A self-contained Bash script that validates every prerequisite before running `<system_name>.py`. It must be generated **by reading the Python script** — do not write it from a generic template. The validation logic must match what the script actually does.

read this before creating the preflight script for your reference: - [https://github.com/pvolu-vz/NetApp (`install_ontap.sh`)](https://github.com/pvolu-vz/NetApp/blob/main/preflight.sh)

### How to derive it from the Python script

Before writing a single line of bash, read `<system_name>.py` and extract:

| What to look for | Where in the Python script | What it drives |
|---|---|---|
| `import pyodbc` / `import psycopg2` / etc. | Top-level imports | Package checks + ODBC driver check |
| `load_config()` dict keys and their `os.getenv()` names | `load_config()` function | `.env` variable list and required/optional status |
| `conn_str` or connection URL construction | DB adapter or API session setup | Network connectivity test target and port |
| `requests.get(url)` / `pyodbc.connect()` / `boto3` client | Data loading functions | Authentication test type (HTTP Bearer / DB login / SDK auth) |
| `OAAClient(url=..., token=...)` | `push_to_veza()` | Veza HTTPS reachability + Bearer auth test |
| `python3 --version` or version guards in the code | `sys.version_info` checks | Minimum Python version to enforce |
| `from requirements.txt` | `requirements.txt` | Full package checklist |

### Required validation sections

Generate exactly these eight sections, in order:

#### 1 — System Requirements
- Python version: enforce the minimum from the script (check `sys.version_info` guards; default ≥ 3.9)
- pip3 availability
- Virtual environment detection (warn if not in one)
- OS detection (Linux distro from `/etc/os-release`, macOS)
- curl (required for API auth tests)
- jq (optional, warn if missing)
- **Data-source-specific system deps** — derive from imports:
  - `pyodbc` → check for ODBC driver via `odbcinst -q -d`; warn with install URL if missing
  - `psycopg2` → check PostgreSQL client libs (`pg_config` or `libpq`)
  - `cx_Oracle` → check Oracle Instant Client (`oracle_config` or `LD_LIBRARY_PATH`)
  - `boto3` → check AWS CLI config presence (optional)
  - `azure-storage-blob` → no extra system dep
  - REST/CSV → no extra system dep

#### 2 — Python Dependencies
- Read `requirements.txt` line by line and check each package with `python3 -c "import <pkg>"`
- Print installed version alongside each ✓
- Prefer the local `./venv/bin/python` if it exists; fall back to system `python3`
- On failure, print the install command: `./venv/bin/pip install -r requirements.txt`

#### 3 — Configuration File
- Check `.env` exists; offer to generate a template (Option 10) if missing
- Check file permissions — must be `600`; print `chmod 600` fix if not
- `source` the `.env` file and validate each variable extracted from `load_config()`:
  - **Required** — fail if empty or still a placeholder (`your_*`, `https://your-*`)
  - **Optional** — `print_info` only
  - **Sensitive** (`PASSWORD`, `KEY`, `TOKEN`, `SECRET`) — show only first 8 chars

#### 4 — Network Connectivity
Derive the test target and protocol from the Python script's connection logic:

| Data source type | Protocol | How to detect |
|---|---|---|
| MS SQL Server / PostgreSQL / MySQL / Oracle | TCP to `$DB_HOST:$DB_PORT` | `conn_str` or `create_engine()` URL |
| REST API | HTTPS to the API base URL | `requests.Session()` base URL |
| Veza push | HTTPS to `$VEZA_URL:443` | Always present |
| S3 / ADLS / GCS | HTTPS to the SDK endpoint | `boto3` / Azure SDK / GCS client |

For TCP: use `nc -zw 5 $host $port` → fall back to `bash /dev/tcp/$host/$port` → fall back to `curl telnet://`.  
For HTTPS: use `curl -s -o /dev/null -w "%{http_code}|%{time_total}" -m 10 https://$host`.

#### 5 — API / Database Authentication
Perform a live, minimal authenticated call to confirm credentials actually work:

| Source type | Test call | Success indicator |
|---|---|---|
| MS SQL Server | `pyodbc.connect(conn_str); SELECT @@VERSION` | Row returned without exception |
| PostgreSQL | `psycopg2.connect(...); SELECT version()` | Row returned |
| MySQL | `pymysql.connect(...); SELECT VERSION()` | Row returned |
| Oracle | `cx_Oracle.connect(...); SELECT banner FROM v$version` | Row returned |
| REST API (Bearer) | `GET /api/health` or the first listed API endpoint | HTTP 200 |
| REST API (Basic) | Same endpoint with Basic Auth header | HTTP 200 |
| Veza | `GET https://$VEZA_URL/api/v1/providers` with Bearer token | HTTP 200 |

For DB tests, run the Python snippet inline via a heredoc (`python3 - <<PYEOF`).  
Print `[DEBUG]` lines showing the connection target and masked credentials before each test.

#### 6 — API Endpoint Accessibility
- Veza query endpoint: `POST https://$VEZA_URL/api/v1/assessments/query_spec:nodes` with a minimal `{"query":"nodes{InstanceId first:1}"}` body
- Any additional endpoints the script reads from (e.g. REST API resource endpoints) — derive from `requests.get()` / `requests.post()` calls in the data-loading functions
- Print full JSON response body (pretty-printed via `python3 -c "import sys,json; ..."`) on non-200 responses

#### 7 — Deployment Structure
- Main script (`<slug>.py`) exists, is readable, and is executable if it has a shebang
- `requirements.txt` present
- `logs/` directory exists and is writable (if not, note it will be auto-created on first run)
- Current user — note if not running as the dedicated service account (warn, don't fail)
- Recommended install path `/opt/VEZA/<slug>-veza/scripts/` — info if not there

#### 8 — Summary
```bash
print_header "Validation Summary"
echo -e "${GREEN}Passed:${NC}   $TESTS_PASSED"
echo -e "${RED}Failed:${NC}   $TESTS_FAILED"
echo -e "${YELLOW}Warnings:${NC} $TESTS_WARNING"
```
On zero failures: print the recommended dry-run command.  
On any failure: print `"✗ Some checks failed. Please address the issues above before deployment."` and return exit code 1.

### Standard utilities (always include)

```bash
# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

# Counters — increment inside print_success/print_fail/print_warning
TESTS_PASSED=0; TESTS_FAILED=0; TESTS_WARNING=0

print_success() { echo -e "${GREEN}✓${NC} $1"; ((TESTS_PASSED++)); }
print_fail()    { echo -e "${RED}✗${NC} $1";   ((TESTS_FAILED++));  }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; ((TESTS_WARNING++)); }
print_info()    { echo -e "${BLUE}ℹ${NC} $1"; }
```

### check_env_var helper

```bash
check_env_var() {
    local var_name=$1 var_value=$2 optional=$3
    if [[ -z "$var_value" ]]; then
        [[ "$optional" == "optional" ]] && print_info "$var_name not set (optional)" \
                                        || print_fail "$var_name is not set"
    elif [[ "$var_value" =~ ^your_.* ]]; then
        print_warning "$var_name contains placeholder value"
    else
        if [[ "$var_name" =~ PASSWORD|KEY|TOKEN|SECRET ]]; then
            print_success "$var_name set (${var_value:0:8}...)"
        else
            print_success "$var_name set"
        fi
    fi
}
```

### Interactive menu — 11 fixed options

```
1) System Requirements       7) Deployment Structure
2) Python Dependencies       8) Run ALL Checks (recommended)
3) Configuration File        9) Display Current Configuration
4) Network Connectivity     10) Generate Template .env File
5) API Authentication       11) Install Python Dependencies
6) API Endpoint Access       0) Exit
```

Support `--all` flag for CI/non-interactive execution:
```bash
main() {
    [[ "$1" == "--all" ]] && { run_all_checks; exit $?; }
    # interactive menu loop ...
}
```

### install_dependencies (Option 11)

Always install into a local venv, not system Python:
```bash
VENV_DIR="${SCRIPT_DIR}/venv"
[[ ! -d "$VENV_DIR" ]] && python3 -m venv "$VENV_DIR"
"${VENV_DIR}/bin/pip" install -r "$REQUIREMENTS_FILE"
```

### generate_env_template (Option 10)

Copy the contents of `.env.example` verbatim. Set `chmod 600` after writing.

### Naming and placement

- File: `./integrations/<slug>/preflight.sh`
- Make executable: `chmod +x preflight.sh`
- The script sets `SCRIPT_DIR` from `${BASH_SOURCE[0]}` so it works from any working directory
- Log file: `${SCRIPT_DIR}/preflight_$(date +%Y%m%d_%H%M%S).log` — created at startup
