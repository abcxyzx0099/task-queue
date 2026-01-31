#!/bin/bash
# Test runner script for task-monitor

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}Running task-monitor test suite...${NC}\n"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Virtual environment not found. Please create one first.${NC}"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Install test dependencies if not already installed
echo -e "${YELLOW}Ensuring test dependencies are installed...${NC}"
pip install -e ".[dev]" -q

# Run tests
echo -e "\n${YELLOW}Running pytest...${NC}\n"
pytest tests/ -v --tb=short "$@"

# Print exit code
EXIT_CODE=$?
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed. Exit code: $EXIT_CODE${NC}"
fi

exit $EXIT_CODE
