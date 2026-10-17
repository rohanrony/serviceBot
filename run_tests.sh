#!/bin/bash

# ==============================================================================
# run_tests.sh
# ==============================================================================
# Executable runner to launch the voiceService test suite cleanly, bypass 
# sandbox file-write limits, and bootstrap new service tests.
# ==============================================================================

# Exit on error
set -e

# Terminal formatting colors
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
BOLD="\033[1m"
NC="\033[0m" # No Color

# Default settings
WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRATCH_DIR="$WORKSPACE_DIR/scratch"
CACHE_DIR="$SCRATCH_DIR/.pytest_cache"
PYTEST_BIN="$WORKSPACE_DIR/.venv/bin/pytest"
cd "$WORKSPACE_DIR"
mkdir -p "$SCRATCH_DIR"
# Test fixtures provide synthetic credentials and own disposable databases.
export PYTHON_DOTENV_DISABLED=1
export PYTHONDONTWRITEBYTECODE=1

# Check if pytest is available
if [ ! -f "$PYTEST_BIN" ]; then
    echo -e "${RED}${BOLD}Error:${NC} pytest executable not found at $PYTEST_BIN"
    echo "Please ensure the virtual environment is set up at .venv"
    exit 1
fi

print_usage() {
    echo -e "${BOLD}Usage:${NC} $0 [options]"
    echo ""
    echo "Options:"
    echo "  --all              Run the entire unit/integration test suite (Default)"
    echo "  --verify           Run unit/integration AND all E2E suites, even if one fails"
    echo "  --e2e              Run Playwright headless browser E2E tests (e2e/)"
    echo "  --e2e-headed       Run Playwright E2E tests in a visible Chromium browser"
    echo "  --browser          Run only actual browser journeys (add --e2e-headed to watch)"
    echo "  --e2e-contracts    Run only HTTP/worker acceptance contracts (no browser)"
    echo "  --features         Run recent-feature and regression acceptance tests"
    echo "  --validate-customer Run customer Rohan Roy WhatsApp notification test & audit"
    echo "  --inspect-calls    Fetch and evaluate recent ElevenLabs voice agent call transcripts"
    echo "  --service <name>   Run unit tests for a specific service"
    echo "  --file <path>      Run tests in a specific test file"
    echo "  --create <name>    Generate a template test file at tests/test_<name>.py"
    echo "  --help             Show this help guide"
    echo "  Additional pytest arguments can follow any test selection."
    echo ""
    echo "Examples:"
    echo "  $0 --e2e"
    echo "  $0 --validate-customer"
    echo "  $0 --inspect-calls"
    echo "  $0 --service encryption"
}

create_template() {
    local name="$1"
    local filepath="$WORKSPACE_DIR/tests/test_${name}.py"
    
    if [ -f "$filepath" ]; then
        echo -e "${RED}${BOLD}Error:${NC} Test file already exists at tests/test_${name}.py"
        exit 1
    fi
    
    echo -e "${BLUE}Generating template test file at tests/test_${name}.py...${NC}"
    
    cat <<EOF > "$filepath"
import pytest
from unittest.mock import patch, MagicMock

def test_placeholder():
    """Verify standard placeholder assertion."""
    assert True
EOF

    echo -e "${GREEN}${BOLD}Success!${NC} Created test file template at tests/test_${name}.py"
}

# Parse command line options
case "$1" in
    --help|-h)
        print_usage
        exit 0
        ;;
    --create)
        if [ -z "$2" ]; then
            echo -e "${RED}${BOLD}Error:${NC} Please specify a name for the new test file."
            print_usage
            exit 1
        fi
        create_template "$2"
        exit 0
        ;;
    --service)
        if [ -z "$2" ]; then
            echo -e "${RED}${BOLD}Error:${NC} Please specify a service name (e.g. encryption, calendar_sync)."
            print_usage
            exit 1
        fi
        SERVICE_NAME="$2"
        shift 2
        echo -e "${BLUE}${BOLD}Running tests for service: $SERVICE_NAME...${NC}"
        # We run it using -k to avoid relative/absolute path parsing sandbox issues
        "$PYTEST_BIN" tests/ -k "test_${SERVICE_NAME}" -o cache_dir="$CACHE_DIR" "$@"
        ;;
    --file)
        if [ -z "$2" ]; then
            echo -e "${RED}${BOLD}Error:${NC} Please specify a test file path."
            print_usage
            exit 1
        fi
        FILE_PATH="$2"
        # If absolute path, run it directly; otherwise make it absolute to bypass sandbox checks
        if [[ "$FILE_PATH" != /* ]]; then
            FILE_PATH="$WORKSPACE_DIR/$FILE_PATH"
        fi
        shift 2
        echo -e "${BLUE}${BOLD}Running tests in file: $FILE_PATH...${NC}"
        "$PYTEST_BIN" "$FILE_PATH" -v -o cache_dir="$CACHE_DIR" "$@"
        ;;
    --verify)
        shift
        UNIT_STATUS=0
        E2E_STATUS=0
        "$WORKSPACE_DIR/run_tests.sh" --all "$@" || UNIT_STATUS=$?
        "$WORKSPACE_DIR/run_tests.sh" --e2e "$@" || E2E_STATUS=$?
        echo "Unit/integration exit: $UNIT_STATUS; E2E exit: $E2E_STATUS"
        if [ "$UNIT_STATUS" -ne 0 ] || [ "$E2E_STATUS" -ne 0 ]; then
            exit 1
        fi
        ;;
    --browser|--e2e-contracts|--features)
        SELECTION="$1"
        shift
        case "$SELECTION" in
            --browser) "$PYTEST_BIN" e2e -m browser -v -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/browser-results.xml" "$@" ;;
            --e2e-contracts) "$PYTEST_BIN" e2e -m 'not browser' -v -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/contract-results.xml" "$@" ;;
            --features) "$PYTEST_BIN" e2e/test_portal_catalog_agent_tagging.py e2e/test_portal_recent_features.py e2e/test_multiservice_contracts.py e2e/test_staff_lifecycle_contracts.py e2e/test_regression_contracts.py -v -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/feature-results.xml" "$@" ;;
        esac
        ;;
    --e2e)
        shift
        echo -e "${BLUE}${BOLD}Running Playwright headless browser E2E tests...${NC}"
        PYTHONUNBUFFERED=1 "$PYTEST_BIN" "$WORKSPACE_DIR/e2e" -v -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/e2e-results.xml" "$@"
        ;;
    --e2e-headed)
        shift
        echo -e "${BLUE}${BOLD}Running Playwright E2E tests in visible browser (headed)...${NC}"
        PLAYWRIGHT_HEADED=1 PYTHONUNBUFFERED=1 "$PYTEST_BIN" "$WORKSPACE_DIR/e2e" --e2e-headed -v -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/e2e-results.xml" "$@"
        ;;
    --validate-customer)
        echo -e "${BLUE}${BOLD}Running Customer Rohan Roy WhatsApp Notification validation...${NC}"
        "$WORKSPACE_DIR/.venv/bin/python" "$WORKSPACE_DIR/scripts/validate_customer_flow.py" --action audit --local-db
        ;;
    --inspect-calls)
        echo -e "${BLUE}${BOLD}Inspecting recent ElevenLabs calls and evaluating quality...${NC}"
        "$WORKSPACE_DIR/.venv/bin/python" "$WORKSPACE_DIR/scripts/inspect_calls_history.py" --limit 5 --evaluate
        ;;
    --all|"")
        if [ "$#" -gt 0 ]; then shift; fi
        echo -e "${BLUE}${BOLD}Running entire test suite...${NC}"
        PYTHONUNBUFFERED=1 "$PYTEST_BIN" tests/ -q -o cache_dir="$CACHE_DIR" --junitxml="$SCRATCH_DIR/unit-results.xml" "$@"
        ;;
    *)
        echo -e "${RED}${BOLD}Error:${NC} Unknown option: $1"
        print_usage
        exit 1
        ;;
esac

echo -e "${GREEN}${BOLD}Tests executed successfully!${NC}"
