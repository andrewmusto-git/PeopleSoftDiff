#!/usr/bin/env bash
# =============================================================================
# install_peoplesoft_diff.sh — One-command installer for PeopleSoft Diff
#                              Veza OAA Integration
#
# Usage (interactive):
#   bash install_peoplesoft_diff.sh
#
# Usage (non-interactive / CI):
#   PEOPLESOFT_BASE_URL=https://host:5043 \
#   PEOPLESOFT_USERNAME=svc_account       \
#   PEOPLESOFT_PASSWORD=secret            \
#   VEZA_URL=https://your-org.veza.com    \
#   VEZA_API_KEY=api_key                  \
#   bash install_peoplesoft_diff.sh --non-interactive
#
# Flags:
#   --non-interactive   Skip all prompts; read values from env vars above
#   --overwrite-env     Overwrite an existing .env file (default: skip)
#   --install-dir PATH  Override default install location
#   --repo-url URL      Override repository URL
#   --branch NAME       Override repository branch (default: main)
# =============================================================================
set -uo pipefail

# ---------------------------------------------------------------------------
# Milestone tracking
# ---------------------------------------------------------------------------
MILESTONE_TOTAL=8
_milestone_current=0

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

print_milestone() {
    _milestone_current=$((_milestone_current + 1))
    echo ""
    echo -e "${BOLD}${CYAN}━━━ Milestone ${_milestone_current}/${MILESTONE_TOTAL}: $1 ━━━${NC}"
    echo ""
}

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
die()     { echo -e "${RED}✗  ERROR: $*${NC}" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Defaults and argument parsing
# ---------------------------------------------------------------------------
NON_INTERACTIVE=false
OVERWRITE_ENV=false
INSTALL_DIR=""
REPO_URL="https://github.com/andrewmusto-git/PeopleSoftDiff"
BRANCH="main"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=true ;;
        --overwrite-env)   OVERWRITE_ENV=true ;;
        --install-dir)     INSTALL_DIR="$2"; shift ;;
        --repo-url)        REPO_URL="$2"; shift ;;
        --branch)          BRANCH="$2"; shift ;;
        *) warn "Unknown flag: $1" ;;
    esac
    shift
done

INTEGRATION_SLUG="peoplesoft-diff"
INTEGRATION_SUBDIR="integrations/${INTEGRATION_SLUG}"
SCRIPTS_SUBDIR="scripts"
DEFAULT_INSTALL_BASE="/opt/VEZA"
INSTALL_DIR="${INSTALL_DIR:-${DEFAULT_INSTALL_BASE}/${INTEGRATION_SLUG}-veza}"
SCRIPTS_DIR="${INSTALL_DIR}/${SCRIPTS_SUBDIR}"
LOGS_DIR="${INSTALL_DIR}/logs"
VENV_DIR="${SCRIPTS_DIR}/venv"
ENV_FILE="${SCRIPTS_DIR}/.env"

# ---------------------------------------------------------------------------
# Milestone 1 — System Requirements
# ---------------------------------------------------------------------------
print_milestone "Checking system requirements"

# Detect OS
OS_ID=""
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    OS_ID=$(. /etc/os-release && echo "${ID:-unknown}")
fi

PKG_MGR=""
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
elif command -v yum &>/dev/null; then
    PKG_MGR="yum"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt-get"
fi

[[ -z "$PKG_MGR" ]] && warn "Could not detect a supported package manager (dnf/yum/apt-get)"

# Check Python version
if ! command -v python3 &>/dev/null; then
    die "python3 is not installed. Install it first, then re-run."
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 9 ]]; }; then
    die "Python 3.9 or higher is required. Found Python ${PY_VERSION}."
fi
success "Python ${PY_VERSION} detected"

# Check for required tools
command -v git  &>/dev/null || die "git is not installed. Install it first."
success "git found"

command -v pip3 &>/dev/null || warn "pip3 not found in PATH — will use python3 -m pip"
success "System requirements satisfied"

# ---------------------------------------------------------------------------
# Milestone 2 — Installing system packages
# ---------------------------------------------------------------------------
print_milestone "Installing system packages"

_install_pkg() {
    local pkg="$1"
    info "Installing ${pkg}..."
    case "${PKG_MGR}" in
        dnf|yum) sudo "${PKG_MGR}" install -y "${pkg}" >/dev/null 2>&1 || warn "Could not install ${pkg}" ;;
        apt-get) sudo apt-get install -y "${pkg}" >/dev/null 2>&1 || warn "Could not install ${pkg}" ;;
        *) warn "No package manager available — cannot install ${pkg}" ;;
    esac
}

# curl
if ! command -v curl &>/dev/null; then
    if [[ "${OS_ID}" == "amzn" ]]; then
        warn "Skipping curl install on Amazon Linux (curl-minimal may conflict)"
    else
        _install_pkg curl
    fi
fi
command -v curl &>/dev/null && success "curl available"

# python3-venv / python3-virtualenv
if ! python3 -m venv --help &>/dev/null 2>&1; then
    case "${PKG_MGR}" in
        dnf|yum) _install_pkg python3-virtualenv ;;
        apt-get) _install_pkg python3-venv ;;
    esac
fi

if ! python3 -m venv --help &>/dev/null 2>&1; then
    die "python3 venv module is not available. Install python3-venv or python3-virtualenv."
fi
success "python3 venv module available"

# ---------------------------------------------------------------------------
# Milestone 3 — Creating directory structure
# ---------------------------------------------------------------------------
print_milestone "Creating directory structure"

info "Creating install directories under ${INSTALL_DIR}"
sudo mkdir -p "${SCRIPTS_DIR}" "${LOGS_DIR}" \
    || die "Failed to create install directories. Run as root or use sudo."

# Set ownership to current user so subsequent steps don't need sudo
sudo chown -R "$(id -un):$(id -gn)" "${INSTALL_DIR}" 2>/dev/null || true

success "Directory structure created"
info "  Scripts : ${SCRIPTS_DIR}"
info "  Logs    : ${LOGS_DIR}"

# ---------------------------------------------------------------------------
# Milestone 4 — Cloning integration files
# ---------------------------------------------------------------------------
print_milestone "Cloning integration files from repository"

info "Cloning ${REPO_URL} (branch: ${BRANCH})"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

GIT_TERMINAL_PROMPT=0 git clone \
    --branch "${BRANCH}" \
    --depth 1 \
    --single-branch \
    "${REPO_URL}" \
    "${TMP_DIR}" \
    || die "git clone failed. Check that REPO_URL and branch are correct: ${REPO_URL}"

if [[ ! -d "${TMP_DIR}/${INTEGRATION_SUBDIR}" ]]; then
    die "Integration directory not found in repository: ${INTEGRATION_SUBDIR}"
fi

cp -f "${TMP_DIR}/${INTEGRATION_SUBDIR}/peoplesoft_diff.py"  "${SCRIPTS_DIR}/"
cp -f "${TMP_DIR}/${INTEGRATION_SUBDIR}/requirements.txt"     "${SCRIPTS_DIR}/"
cp -f "${TMP_DIR}/${INTEGRATION_SUBDIR}/.env.example"         "${SCRIPTS_DIR}/"

success "Integration files copied to ${SCRIPTS_DIR}"

# ---------------------------------------------------------------------------
# Milestone 5 — Creating Python virtual environment
# ---------------------------------------------------------------------------
print_milestone "Creating Python virtual environment"

if [[ -d "${VENV_DIR}" ]]; then
    info "Virtual environment already exists at ${VENV_DIR}"
else
    info "Creating venv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || die "Failed to create Python virtual environment"
    success "Virtual environment created"
fi

# ---------------------------------------------------------------------------
# Milestone 6 — Installing Python dependencies
# ---------------------------------------------------------------------------
print_milestone "Installing Python dependencies"

info "Upgrading pip..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip \
    || warn "pip upgrade failed — continuing with existing version"

info "Installing requirements.txt..."
"${VENV_DIR}/bin/pip" install --quiet -r "${SCRIPTS_DIR}/requirements.txt" \
    || die "Failed to install Python dependencies"

success "Python dependencies installed"
"${VENV_DIR}/bin/pip" show oaaclient 2>/dev/null | grep -E "^(Name|Version):" | \
    awk '{printf "  %-10s %s\n", $1, $2}' || true

# ---------------------------------------------------------------------------
# Milestone 7 — Generating configuration file
# ---------------------------------------------------------------------------
print_milestone "Generating configuration file (.env)"

if [[ -f "${ENV_FILE}" ]] && [[ "${OVERWRITE_ENV}" != "true" ]]; then
    warn ".env already exists at ${ENV_FILE} — skipping (use --overwrite-env to replace)"
else
    # -----------------------------------------------------------------
    # Collect configuration values
    # -----------------------------------------------------------------
    if [[ "${NON_INTERACTIVE}" == "true" ]]; then
        # Non-interactive: read from environment variables
        [[ -z "${PEOPLESOFT_BASE_URL:-}" ]] && die "PEOPLESOFT_BASE_URL env var is required in --non-interactive mode"
        [[ -z "${PEOPLESOFT_USERNAME:-}" ]]  && die "PEOPLESOFT_USERNAME env var is required in --non-interactive mode"
        [[ -z "${PEOPLESOFT_PASSWORD:-}" ]]  && die "PEOPLESOFT_PASSWORD env var is required in --non-interactive mode"
        [[ -z "${VEZA_URL:-}" ]]              && die "VEZA_URL env var is required in --non-interactive mode"
        [[ -z "${VEZA_API_KEY:-}" ]]          && die "VEZA_API_KEY env var is required in --non-interactive mode"

        PS_BASE_URL="${PEOPLESOFT_BASE_URL}"
        PS_USERNAME="${PEOPLESOFT_USERNAME}"
        PS_PASSWORD="${PEOPLESOFT_PASSWORD}"
        VZ_URL="${VEZA_URL}"
        VZ_API_KEY="${VEZA_API_KEY}"
    else
        # Interactive: prompt via /dev/tty so curl-pipe installs work
        echo ""
        echo -e "${BOLD}Configure PeopleSoft Web Services connection:${NC}"
        echo "  Enter the PeopleSoft HCM base URL including scheme and port."
        echo "  Example: https://your-peoplesoft-host.example.com:5043"
        printf "  PeopleSoft Base URL: "
        IFS= read -r PS_BASE_URL </dev/tty
        PS_BASE_URL="${PS_BASE_URL%/}"  # strip trailing slash

        printf "  PeopleSoft Service Account Username: "
        IFS= read -r PS_USERNAME </dev/tty

        printf "  PeopleSoft Service Account Password: "
        IFS= read -r -s PS_PASSWORD </dev/tty
        echo >/dev/tty

        echo ""
        echo -e "${BOLD}Configure Veza connection:${NC}"
        echo "  Enter your Veza instance URL."
        echo "  Example: https://your-org.veza.com"
        printf "  Veza URL: "
        IFS= read -r VZ_URL </dev/tty
        VZ_URL="${VZ_URL%/}"

        printf "  Veza API Key: "
        IFS= read -r -s VZ_API_KEY </dev/tty
        echo >/dev/tty

        echo ""
    fi

    # -----------------------------------------------------------------
    # Write .env
    # -----------------------------------------------------------------
    cat > "${ENV_FILE}" << EOF
# ============================================================
# PeopleSoft Diff — Veza OAA Integration Configuration
# Generated by installer on $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# NEVER commit this file to version control.
# ============================================================

# PeopleSoft Web Services source
PEOPLESOFT_BASE_URL=${PS_BASE_URL}
PEOPLESOFT_USERNAME=${PS_USERNAME}
PEOPLESOFT_PASSWORD=${PS_PASSWORD}

# Veza target
VEZA_URL=${VZ_URL}
VEZA_API_KEY=${VZ_API_KEY}

# OAA Provider settings (optional overrides)
# PROVIDER_NAME=PeopleSoft HR
# DATASOURCE_NAME=PeopleSoft Differential
EOF

    chmod 600 "${ENV_FILE}"
    success ".env written to ${ENV_FILE} (permissions: 600)"
fi

# ---------------------------------------------------------------------------
# Milestone 8 — Verifying installation
# ---------------------------------------------------------------------------
print_milestone "Verifying installation"

VERIFY_OK=true

if [[ -f "${SCRIPTS_DIR}/peoplesoft_diff.py" ]]; then
    success "peoplesoft_diff.py present"
else
    warn "peoplesoft_diff.py not found in ${SCRIPTS_DIR}"
    VERIFY_OK=false
fi

if [[ -f "${SCRIPTS_DIR}/requirements.txt" ]]; then
    success "requirements.txt present"
else
    warn "requirements.txt not found"
    VERIFY_OK=false
fi

if [[ -d "${VENV_DIR}" ]]; then
    success "Python virtual environment present"
else
    warn "Virtual environment not found at ${VENV_DIR}"
    VERIFY_OK=false
fi

if [[ -f "${ENV_FILE}" ]]; then
    success ".env configuration file present ($(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%A' "${ENV_FILE}" 2>/dev/null || echo '?') permissions)"
else
    warn ".env not found — create it from ${SCRIPTS_DIR}/.env.example before running"
fi

# Quick syntax check
if "${VENV_DIR}/bin/python3" -m py_compile "${SCRIPTS_DIR}/peoplesoft_diff.py" 2>/dev/null; then
    success "peoplesoft_diff.py syntax OK"
else
    warn "peoplesoft_diff.py failed syntax check — check the script"
    VERIFY_OK=false
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  Installation Complete${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
info "Install directory : ${INSTALL_DIR}"
info "Scripts           : ${SCRIPTS_DIR}"
info "Logs              : ${LOGS_DIR}"
info "Virtual env       : ${VENV_DIR}"
info "Configuration     : ${ENV_FILE}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo "  1. Review and confirm .env settings:"
echo "       cat ${ENV_FILE}"
echo ""
echo "  2. Run the integration (dry-run first recommended):"
echo "       cd ${SCRIPTS_DIR}"
echo "       ${VENV_DIR}/bin/python3 peoplesoft_diff.py --dry-run --save-json"
echo ""
echo "  3. Push to Veza:"
echo "       cd ${SCRIPTS_DIR}"
echo "       ${VENV_DIR}/bin/python3 peoplesoft_diff.py"
echo ""
echo "  4. Schedule via cron (example — daily at 06:00):"
echo "       0 6 * * * cd ${SCRIPTS_DIR} && ${VENV_DIR}/bin/python3 peoplesoft_diff.py >> ${LOGS_DIR}/cron.log 2>&1"
echo ""

if [[ "${VERIFY_OK}" == "false" ]]; then
    echo -e "${YELLOW}⚠  One or more verification checks did not pass. Review the warnings above.${NC}"
fi
