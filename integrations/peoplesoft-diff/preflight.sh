#!/usr/bin/env bash
# =============================================================================
# preflight.sh — Pre-deployment validation for PeopleSoft Diff Veza OAA
#
# Validates every prerequisite before running peoplesoft_diff.py.
# Derived from the script's actual imports, load_config() env vars, and
# fetch_employees() connection logic.
#
# Usage:
#   bash preflight.sh            # interactive menu
#   bash preflight.sh --all      # run all checks non-interactively; exit 0/1
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
REQUIREMENTS_FILE="${SCRIPT_DIR}/requirements.txt"
MAIN_SCRIPT="${SCRIPT_DIR}/peoplesoft_diff.py"
ENV_FILE="${SCRIPT_DIR}/.env"

# Timestamped log file
LOG_FILE="${SCRIPT_DIR}/preflight_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "${LOG_FILE}") 2>&1

# ---------------------------------------------------------------------------
# Colors and counters
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNING=0

print_success() { echo -e "${GREEN}✓${NC} $1"; ((TESTS_PASSED++)); }
print_fail()    { echo -e "${RED}✗${NC} $1";   ((TESTS_FAILED++));  }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; ((TESTS_WARNING++)); }
print_info()    { echo -e "${BLUE}ℹ${NC} $1"; }
print_header()  { echo ""; echo -e "${BOLD}--- $1 ---${NC}"; echo ""; }

check_env_var() {
    local var_name="$1" var_value="$2" optional="${3:-required}"
    if [[ -z "${var_value}" ]]; then
        [[ "${optional}" == "optional" ]] \
            && print_info "${var_name} not set (optional)" \
            || print_fail "${var_name} is not set"
    elif [[ "${var_value}" =~ ^your_.* ]] || [[ "${var_value}" =~ ^https://your-.* ]]; then
        print_warning "${var_name} still contains a placeholder value"
    else
        if [[ "${var_name}" =~ PASSWORD|KEY|TOKEN|SECRET ]]; then
            print_success "${var_name} set (${var_value:0:8}...)"
        else
            print_success "${var_name} = ${var_value}"
        fi
    fi
}

# Resolve python binary (prefer venv)
_python() {
    if [[ -x "${VENV_DIR}/bin/python3" ]]; then
        echo "${VENV_DIR}/bin/python3"
    else
        echo "python3"
    fi
}

# ---------------------------------------------------------------------------
# Section 1 — System Requirements
# ---------------------------------------------------------------------------
check_system_requirements() {
    print_header "1. System Requirements"

    # OS detection
    OS_ID="unknown"
    [[ -f /etc/os-release ]] && OS_ID=$(. /etc/os-release 2>/dev/null && echo "${ID:-unknown}")
    print_info "OS: ${OS_ID} ($(uname -s) $(uname -r))"

    # Python version (require >= 3.9)
    if command -v python3 &>/dev/null; then
        PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
        PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
        if [[ "$PY_MAJOR" -ge 3 ]] && [[ "$PY_MINOR" -ge 9 ]]; then
            print_success "Python ${PY_VERSION} (>= 3.9 required)"
        else
            print_fail "Python ${PY_VERSION} is below required 3.9"
        fi
    else
        print_fail "python3 not found in PATH"
    fi

    # pip3
    if command -v pip3 &>/dev/null; then
        print_success "pip3 found ($(pip3 --version 2>&1 | head -1))"
    elif python3 -m pip --version &>/dev/null 2>&1; then
        print_success "python3 -m pip available"
    else
        print_warning "pip3 not found — install python3-pip"
    fi

    # venv module
    if python3 -m venv --help &>/dev/null 2>&1; then
        print_success "python3 venv module available"
    else
        print_fail "python3 venv module not available — install python3-venv or python3-virtualenv"
    fi

    # Virtual environment check
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        print_success "Running inside virtual environment: ${VIRTUAL_ENV}"
    elif [[ -d "${VENV_DIR}" ]]; then
        print_info "Local venv found at ${VENV_DIR} (not currently activated)"
    else
        print_warning "No virtual environment detected — run from within the venv or create it"
    fi

    # curl
    command -v curl &>/dev/null \
        && print_success "curl found ($(curl --version 2>&1 | head -1))" \
        || print_warning "curl not found — network tests will use python3 fallback"

    # jq (optional)
    command -v jq &>/dev/null \
        && print_success "jq found" \
        || print_info "jq not found (optional — JSON responses will not be pretty-printed)"

    # git
    command -v git &>/dev/null \
        && print_success "git found ($(git --version))" \
        || print_warning "git not found — required for installer"
}

# ---------------------------------------------------------------------------
# Section 2 — Python Dependencies
# ---------------------------------------------------------------------------
check_python_dependencies() {
    print_header "2. Python Dependencies"
    local py; py="$(_python)"
    print_info "Using Python binary: ${py}"

    if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
        print_fail "requirements.txt not found at ${REQUIREMENTS_FILE}"
        return
    fi

    # Read requirements.txt and check each package
    while IFS= read -r line || [[ -n "${line}" ]]; do
        # Strip comments and blank lines
        line="${line%%#*}"
        line="${line//[[:space:]]/}"
        [[ -z "${line}" ]] && continue

        # Extract package name (strip version specifier)
        pkg_name="${line%%[>=<!]*}"
        pkg_import="${pkg_name//-/_}"  # hyphen -> underscore for import

        if version_out=$("${py}" -c "import ${pkg_import}; v=getattr(${pkg_import},'__version__',getattr(${pkg_import},'VERSION','?')); print(v)" 2>/dev/null); then
            print_success "${pkg_name} v${version_out}"
        else
            print_fail "${pkg_name} not importable — run: ${py} -m pip install -r ${REQUIREMENTS_FILE}"
        fi
    done < "${REQUIREMENTS_FILE}"
}

# ---------------------------------------------------------------------------
# Section 3 — Configuration File
# ---------------------------------------------------------------------------
check_configuration() {
    print_header "3. Configuration File"

    if [[ ! -f "${ENV_FILE}" ]]; then
        print_fail ".env not found at ${ENV_FILE}"
        print_info "Generate a template with option 10, or:"
        print_info "  cp ${SCRIPT_DIR}/.env.example ${ENV_FILE} && chmod 600 ${ENV_FILE}"
        return
    fi
    print_success ".env exists at ${ENV_FILE}"

    # Check permissions
    perms=$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%A' "${ENV_FILE}" 2>/dev/null || echo "000")
    if [[ "${perms}" == "600" ]]; then
        print_success ".env permissions are 600"
    else
        print_warning ".env permissions are ${perms} — fix with: chmod 600 ${ENV_FILE}"
    fi

    # Source .env (suppress errors for unset variables)
    # shellcheck disable=SC1090
    set +u
    source "${ENV_FILE}" 2>/dev/null || true
    set -u

    print_info "Checking required environment variables:"
    check_env_var "PEOPLESOFT_BASE_URL" "${PEOPLESOFT_BASE_URL:-}"
    check_env_var "PEOPLESOFT_USERNAME" "${PEOPLESOFT_USERNAME:-}"
    check_env_var "PEOPLESOFT_PASSWORD" "${PEOPLESOFT_PASSWORD:-}"
    check_env_var "VEZA_URL"            "${VEZA_URL:-}"
    check_env_var "VEZA_API_KEY"        "${VEZA_API_KEY:-}"

    print_info "Checking optional environment variables:"
    check_env_var "PROVIDER_NAME"    "${PROVIDER_NAME:-}"    "optional"
    check_env_var "DATASOURCE_NAME"  "${DATASOURCE_NAME:-}"  "optional"
}

# ---------------------------------------------------------------------------
# Section 4 — Network Connectivity
# ---------------------------------------------------------------------------
check_network_connectivity() {
    print_header "4. Network Connectivity"

    # Source .env to get connection targets
    set +u
    [[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}" 2>/dev/null || true
    set -u

    # Helper: HTTPS reachability test
    _https_check() {
        local label="$1" url="$2"
        if command -v curl &>/dev/null; then
            result=$(curl -s -o /dev/null -w "%{http_code}|%{time_total}" -m 10 \
                         --max-redirs 3 "${url}" 2>/dev/null || echo "000|?")
            http_code="${result%%|*}"
            latency="${result##*|}"
            if [[ "${http_code}" == "2"* ]] || [[ "${http_code}" == "3"* ]] || \
               [[ "${http_code}" == "4"* ]]; then
                print_success "${label} reachable (HTTP ${http_code}, ${latency}s)"
            else
                print_fail "${label} unreachable (HTTP ${http_code}) — check URL and network"
            fi
        else
            # Fallback via python3
            if python3 -c "import urllib.request; urllib.request.urlopen('${url}', timeout=10)" 2>/dev/null; then
                print_success "${label} reachable"
            else
                print_fail "${label} unreachable — check URL and network"
            fi
        fi
    }

    # PeopleSoft base URL
    if [[ -n "${PEOPLESOFT_BASE_URL:-}" ]]; then
        _https_check "PeopleSoft (${PEOPLESOFT_BASE_URL})" "${PEOPLESOFT_BASE_URL}"
    else
        print_warning "PEOPLESOFT_BASE_URL not set — skipping PeopleSoft connectivity check"
    fi

    # Veza URL
    if [[ -n "${VEZA_URL:-}" ]]; then
        _https_check "Veza (${VEZA_URL})" "${VEZA_URL}/api/v1/providers"
    else
        print_warning "VEZA_URL not set — skipping Veza connectivity check"
    fi
}

# ---------------------------------------------------------------------------
# Section 5 — API Authentication
# ---------------------------------------------------------------------------
check_api_authentication() {
    print_header "5. API Authentication"

    set +u
    [[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}" 2>/dev/null || true
    set -u

    # PeopleSoft Basic auth test — runs a minimal test connection query
    if [[ -n "${PEOPLESOFT_BASE_URL:-}" ]] && \
       [[ -n "${PEOPLESOFT_USERNAME:-}" ]] && \
       [[ -n "${PEOPLESOFT_PASSWORD:-}" ]]; then

        print_info "[DEBUG] Testing PeopleSoft Basic auth at ${PEOPLESOFT_BASE_URL}"
        print_info "[DEBUG] Username: ${PEOPLESOFT_USERNAME} / Password: ${PEOPLESOFT_PASSWORD:0:4}..."

        TEST_BODY='<?xml version="1.0"?>
<QAS_EXEQRY_SYNC_REQ_MSG>
<QAS_EXEQRY_SYNC_REQ>
<QueryName>ZPS_MIM_EMPLID_SPECIFIC_SP</QueryName>
<isConnectedQuery>N</isConnectedQuery>
<OwnerType>PUBLIC</OwnerType>
<BlockSizeKB>0</BlockSizeKB>
<MaxRow>1</MaxRow>
<OutResultType>xmlp</OutResultType>
<OutResultFormat>NONFILE</OutResultFormat>
<Prompts>
<PROMPT>
<UniquePromptName>BIND1</UniquePromptName>
<FieldValue>TEST_PREFLIGHT</FieldValue>
</PROMPT>
</Prompts>
</QAS_EXEQRY_SYNC_REQ>
</QAS_EXEQRY_SYNC_REQ_MSG>'

        PS_ENDPOINT="${PEOPLESOFT_BASE_URL}/PSIGW/RESTListeningConnector/PSFT_HR/ExecuteAdhocQuery.v1/executeadhocquery"

        if command -v curl &>/dev/null; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 30 \
                -u "${PEOPLESOFT_USERNAME}:${PEOPLESOFT_PASSWORD}" \
                -H "Content-Type: text/xml" \
                -X POST \
                --data "${TEST_BODY}" \
                "${PS_ENDPOINT}" 2>/dev/null || echo "000")
            if [[ "${HTTP_CODE}" == "2"* ]]; then
                print_success "PeopleSoft Basic auth succeeded (HTTP ${HTTP_CODE})"
            elif [[ "${HTTP_CODE}" == "401" ]]; then
                print_fail "PeopleSoft auth returned HTTP 401 — check PEOPLESOFT_USERNAME / PEOPLESOFT_PASSWORD"
            elif [[ "${HTTP_CODE}" == "404" ]]; then
                print_fail "Endpoint not found (HTTP 404) — verify PEOPLESOFT_BASE_URL and listener path"
            else
                print_warning "PeopleSoft test returned HTTP ${HTTP_CODE} — may be expected for unknown EMPLID"
            fi
        else
            print_warning "curl not available — skipping live PeopleSoft auth test"
        fi
    else
        print_warning "PeopleSoft credentials not fully configured — skipping auth test"
    fi

    # Veza API key test
    if [[ -n "${VEZA_URL:-}" ]] && [[ -n "${VEZA_API_KEY:-}" ]]; then
        print_info "[DEBUG] Testing Veza API key at ${VEZA_URL}/api/v1/providers"
        print_info "[DEBUG] API Key: ${VEZA_API_KEY:0:8}..."

        if command -v curl &>/dev/null; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 15 \
                -H "Authorization: Bearer ${VEZA_API_KEY}" \
                "${VEZA_URL}/api/v1/providers" 2>/dev/null || echo "000")
            if [[ "${HTTP_CODE}" == "200" ]]; then
                print_success "Veza API key is valid (HTTP 200)"
            elif [[ "${HTTP_CODE}" == "401" ]]; then
                print_fail "Veza API key rejected (HTTP 401) — regenerate in Veza Settings > API Keys"
            elif [[ "${HTTP_CODE}" == "403" ]]; then
                print_fail "Veza API key lacks permission (HTTP 403) — verify OAA write access"
            else
                print_warning "Veza API returned HTTP ${HTTP_CODE}"
            fi
        else
            print_warning "curl not available — skipping live Veza auth test"
        fi
    else
        print_warning "Veza credentials not configured — skipping Veza auth test"
    fi
}

# ---------------------------------------------------------------------------
# Section 6 — API Endpoint Access
# ---------------------------------------------------------------------------
check_api_endpoint_access() {
    print_header "6. API Endpoint Access"

    set +u
    [[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}" 2>/dev/null || true
    set -u

    if [[ -n "${VEZA_URL:-}" ]] && [[ -n "${VEZA_API_KEY:-}" ]]; then
        QUERY_PAYLOAD='{"query":"nodes{InstanceId first:1}"}'
        if command -v curl &>/dev/null; then
            RESP=$(curl -s -w "\n%{http_code}" -m 15 \
                -H "Authorization: Bearer ${VEZA_API_KEY}" \
                -H "Content-Type: application/json" \
                -X POST \
                --data "${QUERY_PAYLOAD}" \
                "${VEZA_URL}/api/v1/assessments/query_spec:nodes" 2>/dev/null || echo -e "\n000")
            HTTP_CODE=$(echo "${RESP}" | tail -1)
            BODY=$(echo "${RESP}" | head -n -1)

            if [[ "${HTTP_CODE}" == "200" ]]; then
                print_success "Veza query endpoint accessible (HTTP 200)"
            else
                print_fail "Veza query endpoint returned HTTP ${HTTP_CODE}"
                if command -v python3 &>/dev/null; then
                    echo "${BODY}" | python3 -c "import sys,json; \
                        d=json.load(sys.stdin); print(json.dumps(d,indent=2))" 2>/dev/null || echo "${BODY}"
                fi
            fi
        else
            print_warning "curl not available — skipping Veza query endpoint test"
        fi
    else
        print_warning "Veza credentials not configured — skipping endpoint test"
    fi
}

# ---------------------------------------------------------------------------
# Section 7 — Deployment Structure
# ---------------------------------------------------------------------------
check_deployment_structure() {
    print_header "7. Deployment Structure"

    # Main script
    if [[ -f "${MAIN_SCRIPT}" ]]; then
        print_success "peoplesoft_diff.py exists at ${MAIN_SCRIPT}"
        [[ -r "${MAIN_SCRIPT}" ]] && print_success "peoplesoft_diff.py is readable" \
                                  || print_fail "peoplesoft_diff.py is not readable"
    else
        print_fail "peoplesoft_diff.py not found at ${MAIN_SCRIPT}"
    fi

    # requirements.txt
    [[ -f "${REQUIREMENTS_FILE}" ]] \
        && print_success "requirements.txt present" \
        || print_fail "requirements.txt not found at ${REQUIREMENTS_FILE}"

    # logs/ directory
    LOGS_DIR="$(dirname "${SCRIPT_DIR}")/logs"
    if [[ -d "${LOGS_DIR}" ]]; then
        if [[ -w "${LOGS_DIR}" ]]; then
            print_success "logs/ directory writable at ${LOGS_DIR}"
        else
            print_warning "logs/ directory not writable — check permissions"
        fi
    else
        print_info "logs/ directory does not exist (will be auto-created on first run)"
    fi

    # venv
    if [[ -d "${VENV_DIR}" ]]; then
        print_success "Virtual environment present at ${VENV_DIR}"
    else
        print_warning "Virtual environment not found — run option 11 to install"
    fi

    # Recommended install path check
    if [[ "${SCRIPT_DIR}" == /opt/VEZA/* ]]; then
        print_success "Script installed in recommended path /opt/VEZA/"
    else
        print_info "Script is at ${SCRIPT_DIR} (recommended: /opt/VEZA/peoplesoft-diff-veza/scripts)"
    fi

    # Running user
    CURRENT_USER=$(id -un)
    if [[ "${CURRENT_USER}" == "peoplesoft-diff-veza" ]]; then
        print_success "Running as dedicated service account: ${CURRENT_USER}"
    else
        print_info "Running as ${CURRENT_USER} (recommended: use dedicated service account 'peoplesoft-diff-veza')"
    fi
}

# ---------------------------------------------------------------------------
# Section 8 — Summary
# ---------------------------------------------------------------------------
print_summary() {
    print_header "Validation Summary"
    echo -e "${GREEN}Passed:${NC}   ${TESTS_PASSED}"
    echo -e "${RED}Failed:${NC}   ${TESTS_FAILED}"
    echo -e "${YELLOW}Warnings:${NC} ${TESTS_WARNING}"
    echo ""
    echo "Log file: ${LOG_FILE}"
    echo ""

    if [[ "${TESTS_FAILED}" -eq 0 ]]; then
        echo -e "${GREEN}All required checks passed.  Recommended next step:${NC}"
        echo "  cd ${SCRIPT_DIR}"
        echo "  $(_python) peoplesoft_diff.py --dry-run --save-json --log-level DEBUG"
    else
        echo -e "${RED}✗ Some checks failed. Please address the issues above before deployment.${NC}"
    fi
}

# ---------------------------------------------------------------------------
# Utility: display current configuration
# ---------------------------------------------------------------------------
display_config() {
    print_header "Current Configuration"
    set +u
    [[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}" 2>/dev/null || true
    set -u

    echo "  PEOPLESOFT_BASE_URL : ${PEOPLESOFT_BASE_URL:-<not set>}"
    echo "  PEOPLESOFT_USERNAME : ${PEOPLESOFT_USERNAME:-<not set>}"
    echo "  PEOPLESOFT_PASSWORD : ${PEOPLESOFT_PASSWORD:+${PEOPLESOFT_PASSWORD:0:4}****}<unset>"
    echo "  VEZA_URL            : ${VEZA_URL:-<not set>}"
    echo "  VEZA_API_KEY        : ${VEZA_API_KEY:+${VEZA_API_KEY:0:8}****}<unset>"
    echo "  PROVIDER_NAME       : ${PROVIDER_NAME:-PeopleSoft HR (default)}"
    echo "  DATASOURCE_NAME     : ${DATASOURCE_NAME:-PeopleSoft Differential (default)}"
}

# ---------------------------------------------------------------------------
# Utility: generate .env template
# ---------------------------------------------------------------------------
generate_env_template() {
    if [[ -f "${ENV_FILE}" ]]; then
        echo -e "${YELLOW}⚠  .env already exists at ${ENV_FILE}${NC}"
        printf "Overwrite? [y/N] "
        read -r answer </dev/tty
        [[ "${answer}" =~ ^[Yy]$ ]] || { echo "Skipped."; return; }
    fi

    EXAMPLE="${SCRIPT_DIR}/.env.example"
    if [[ -f "${EXAMPLE}" ]]; then
        cp "${EXAMPLE}" "${ENV_FILE}"
    else
        cat > "${ENV_FILE}" <<'ENVTEMPLATE'
# PeopleSoft Web Services source
PEOPLESOFT_BASE_URL=https://your-peoplesoft-host.example.com:5043
PEOPLESOFT_USERNAME=your_service_account
PEOPLESOFT_PASSWORD=your_password_here

# Veza target
VEZA_URL=https://your-veza-instance.veza.com
VEZA_API_KEY=your_veza_api_key_here

# OAA Provider settings (optional)
# PROVIDER_NAME=PeopleSoft HR
# DATASOURCE_NAME=PeopleSoft Differential
ENVTEMPLATE
    fi
    chmod 600 "${ENV_FILE}"
    echo -e "${GREEN}✓${NC}  .env template written to ${ENV_FILE} (permissions: 600)"
    echo "    Edit it and fill in real values before running the integration."
}

# ---------------------------------------------------------------------------
# Utility: install Python dependencies
# ---------------------------------------------------------------------------
install_dependencies() {
    print_header "Installing Python Dependencies"
    if [[ ! -d "${VENV_DIR}" ]]; then
        echo "Creating virtual environment at ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}" || { echo "Failed to create venv"; return 1; }
    fi
    "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
    "${VENV_DIR}/bin/pip" install -r "${REQUIREMENTS_FILE}" \
        && echo -e "${GREEN}✓${NC}  Dependencies installed" \
        || echo -e "${RED}✗${NC}  Installation failed"
}

# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------
run_all_checks() {
    echo ""
    echo -e "${BOLD}PeopleSoft Diff — Veza OAA Preflight Validation${NC}"
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""

    check_system_requirements
    check_python_dependencies
    check_configuration
    check_network_connectivity
    check_api_authentication
    check_api_endpoint_access
    check_deployment_structure
    print_summary

    [[ "${TESTS_FAILED}" -eq 0 ]]
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
interactive_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}PeopleSoft Diff Veza OAA — Preflight Menu${NC}"
        echo "  1) System Requirements         7) Deployment Structure"
        echo "  2) Python Dependencies         8) Run ALL Checks (recommended)"
        echo "  3) Configuration File          9) Display Current Configuration"
        echo "  4) Network Connectivity       10) Generate Template .env File"
        echo "  5) API Authentication         11) Install Python Dependencies"
        echo "  6) API Endpoint Access         0) Exit"
        echo ""
        printf "Select option [0-11]: "
        IFS= read -r choice </dev/tty

        TESTS_PASSED=0; TESTS_FAILED=0; TESTS_WARNING=0

        case "${choice}" in
            1)  check_system_requirements ;;
            2)  check_python_dependencies ;;
            3)  check_configuration ;;
            4)  check_network_connectivity ;;
            5)  check_api_authentication ;;
            6)  check_api_endpoint_access ;;
            7)  check_deployment_structure ;;
            8)  run_all_checks; continue ;;
            9)  display_config ;;
            10) generate_env_template ;;
            11) install_dependencies ;;
            0)  echo "Exiting."; exit 0 ;;
            *)  echo "Invalid option: ${choice}" ;;
        esac

        print_summary
    done
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
main() {
    if [[ "${1:-}" == "--all" ]]; then
        run_all_checks
        exit $?
    fi
    interactive_menu
}

main "$@"
