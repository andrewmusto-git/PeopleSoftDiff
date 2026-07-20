#!/usr/bin/env bash
# Autonomous test-and-fix loop driver.
#
# Usage:
#   ./tools/oaa_test_loop/run_loop.sh <slug> [--max-iter N] [--no-dry-run]
#
# The loop:
#   1. Regenerates tests (introspect SDK + analyze connector AST + read CSV samples)
#   2. Runs pytest
#   3. On failure, prints the JSON failure report and exits with code 1
#      (the caller — Claude Code or a human — applies fixes, then re-invokes)
#   4. On pass, runs the connector with --dry-run --save-json and verifies exit 0
#
# This script is intentionally non-interactive. Loop iteration counting is
# done by the *caller* (Claude reads .test_loop_state.json between iterations).

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SLUG=""
MAX_ITER=15
RUN_DRY_RUN=1
ARGS=()

while (( $# )); do
    case "$1" in
        --max-iter) MAX_ITER="$2"; shift 2;;
        --no-dry-run) RUN_DRY_RUN=0; shift;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0;;
        *)
            if [[ -z "$SLUG" ]]; then SLUG="$1"; else ARGS+=("$1"); fi
            shift;;
    esac
done

if [[ -z "$SLUG" ]]; then
    echo "error: connector slug required" >&2
    sed -n '2,16p' "$0" >&2
    exit 2
fi

CONNECTOR_DIR="${REPO_ROOT}/integrations/${SLUG}"
if [[ ! -d "$CONNECTOR_DIR" ]]; then
    echo "error: connector dir not found: ${CONNECTOR_DIR}" >&2
    exit 2
fi

STATE_FILE="${CONNECTOR_DIR}/.test_loop_state.json"

# Iteration state — initialize on first call, increment on subsequent.
ITER=1
if [[ -f "$STATE_FILE" ]]; then
    ITER=$(python3 -c "import json,sys; print(json.load(open('${STATE_FILE}')).get('iteration',1)+1)" 2>/dev/null || echo 1)
fi

echo "================================================================"
echo " oaa_test_loop: slug=${SLUG}  iteration=${ITER}/${MAX_ITER}"
echo "================================================================"

if (( ITER > MAX_ITER )); then
    echo "error: max iterations (${MAX_ITER}) exhausted without green tests" >&2
    exit 1
fi

# Pick python for harness (we run introspection here, not in the connector venv,
# so we use the repo-level python that has oaaclient installed).
HARNESS_PY="${HARNESS_PYTHON:-python3}"

cd "$REPO_ROOT"
"$HARNESS_PY" -m tools.oaa_test_loop "${SLUG}" "${ARGS[@]}"
PYTEST_EXIT=$?

# Persist iteration counter regardless of outcome
python3 - <<PYEOF
import json, time
from pathlib import Path
state_path = Path("${STATE_FILE}")
state = {}
if state_path.exists():
    try: state = json.loads(state_path.read_text())
    except Exception: state = {}
state["iteration"] = ${ITER}
state["last_exit"] = ${PYTEST_EXIT}
state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
state["max_iter"] = ${MAX_ITER}
state_path.write_text(json.dumps(state, indent=2))
PYEOF

if [[ $PYTEST_EXIT -ne 0 ]]; then
    echo
    echo "---- FAILURES (iteration ${ITER}) ----"
    python3 -c "
import json, sys
r = json.load(open('${CONNECTOR_DIR}/.test_report.json'))
for f in r.get('failures', []):
    print(f\"  ✗ {f['nodeid']}\")
    msg = f.get('message','').strip()
    if msg: print(f\"      {msg}\")
print()
print('See ${CONNECTOR_DIR}/.test_report.json for full output.')
"
    exit 1
fi

echo
echo "[loop] tests green — running dry-run for ${SLUG}"
if [[ $RUN_DRY_RUN -eq 0 ]]; then
    echo "[loop] --no-dry-run flag set, skipping dry-run."
    exit 0
fi

VENV_PY="${CONNECTOR_DIR}/venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    echo "[loop] no venv at ${VENV_PY}; using system python3 for dry-run"
    VENV_PY="python3"
fi

SCRIPT="${CONNECTOR_DIR}/${SLUG}.py"
[[ -f "$SCRIPT" ]] || SCRIPT=$(ls "${CONNECTOR_DIR}"/*.py 2>/dev/null | head -1)
if [[ -z "$SCRIPT" ]]; then
    echo "[loop] no connector script found; skipping dry-run"
    exit 0
fi

cd "$CONNECTOR_DIR"
"$VENV_PY" "$SCRIPT" \
    --data-dir "${CONNECTOR_DIR}/samples" \
    --dry-run --save-json \
    --log-level DEBUG
DRY_EXIT=$?

if [[ $DRY_EXIT -eq 0 ]]; then
    echo
    echo "[loop] dry-run exit 0 — connector is green ✅"
    # Mark green in state
    python3 - <<PYEOF
import json
from pathlib import Path
p = Path("${STATE_FILE}")
state = json.loads(p.read_text()) if p.exists() else {}
state["green"] = True
state["green_at_iteration"] = ${ITER}
p.write_text(json.dumps(state, indent=2))
PYEOF
else
    echo
    echo "[loop] dry-run failed with exit ${DRY_EXIT} — investigate connector logic"
    exit $DRY_EXIT
fi
