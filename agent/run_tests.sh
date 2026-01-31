#!/bin/bash
# Comprehensive test runner for Convergence Agent

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if virtual environment is activated
check_venv() {
    if [[ -z "$VIRTUAL_ENV" ]]; then
        print_warning "Virtual environment not activated"
        echo "Activating venv..."
        if [ -d "venv" ]; then
            source venv/bin/activate
        else
            print_error "No virtual environment found. Run ./setup.sh first"
            exit 1
        fi
    fi
    print_success "Virtual environment active"
}

# Check if dependencies are installed
check_dependencies() {
    print_header "Checking Dependencies"
    if ! python -c "import pytest" 2>/dev/null; then
        print_warning "Test dependencies not installed"
        echo "Installing dev dependencies..."
        pip install -e ".[dev]"
    fi
    print_success "All dependencies installed"
}

# Run linting
run_lint() {
    print_header "Running Linters"

    echo "Running Ruff..."
    if ruff check agent/; then
        print_success "Ruff passed"
    else
        print_error "Ruff found issues"
        return 1
    fi

    echo ""
    echo "Running Black..."
    if black --check agent/; then
        print_success "Black passed"
    else
        print_warning "Black formatting issues found. Run 'black agent/' to fix"
        return 1
    fi

    echo ""
    echo "Running mypy..."
    if mypy agent/ 2>&1 | grep -q "Success"; then
        print_success "Mypy passed"
    else
        print_warning "Mypy found type issues"
        # Don't fail on mypy for now
    fi
}

# Run unit tests
run_unit_tests() {
    print_header "Running Unit Tests"
    if pytest tests/unit/ -v --cov=agent --cov-report=term-missing --cov-report=html; then
        print_success "Unit tests passed"
        return 0
    else
        print_error "Unit tests failed"
        return 1
    fi
}

# Run integration tests
run_integration_tests() {
    print_header "Running Integration Tests"

    # Check if integration tests should run
    if [[ "$RUN_INTEGRATION_TESTS" != "true" ]]; then
        print_warning "Integration tests skipped (set RUN_INTEGRATION_TESTS=true to run)"
        return 0
    fi

    # Check if docker-compose services are running
    if ! docker-compose ps | grep -q "Up"; then
        print_warning "Docker services not running. Starting services..."
        cd ..
        docker-compose up -d
        echo "Waiting for services to be healthy..."
        sleep 30
        cd agent
    fi

    if pytest tests/integration/ -v; then
        print_success "Integration tests passed"
        return 0
    else
        print_error "Integration tests failed"
        return 1
    fi
}

# Run security scans
run_security() {
    print_header "Running Security Scans"

    echo "Running Bandit security scanner..."
    if bandit -r agent/ -ll 2>&1 | tee bandit-report.txt; then
        print_success "No critical security issues found"
    else
        print_warning "Security issues found. Check bandit-report.txt"
    fi

    echo ""
    echo "Running Safety dependency checker..."
    if safety check 2>&1 | tee safety-report.txt; then
        print_success "No known vulnerabilities in dependencies"
    else
        print_warning "Vulnerabilities found. Check safety-report.txt"
    fi
}

# Generate coverage report
show_coverage() {
    print_header "Coverage Report"

    if [ -f "htmlcov/index.html" ]; then
        echo "HTML coverage report generated at: htmlcov/index.html"
        echo ""
        echo "To view:"
        echo "  - macOS:   open htmlcov/index.html"
        echo "  - Linux:   xdg-open htmlcov/index.html"
        echo "  - Windows: start htmlcov/index.html"
        echo ""
    fi

    # Show coverage summary
    if [ -f ".coverage" ]; then
        coverage report --show-missing
    fi
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════╗"
    echo "║         Convergence Agent Test Suite                 ║"
    echo "╚═══════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    check_venv
    check_dependencies

    # Parse command line arguments
    RUN_ALL=true
    RUN_LINT=false
    RUN_UNIT=false
    RUN_INTEGRATION=false
    RUN_SECURITY=false

    if [ $# -eq 0 ]; then
        RUN_ALL=true
    else
        RUN_ALL=false
        for arg in "$@"; do
            case $arg in
                lint) RUN_LINT=true ;;
                unit) RUN_UNIT=true ;;
                integration) RUN_INTEGRATION=true ;;
                security) RUN_SECURITY=true ;;
                all) RUN_ALL=true ;;
                *)
                    echo "Unknown argument: $arg"
                    echo "Usage: $0 [lint|unit|integration|security|all]"
                    exit 1
                    ;;
            esac
        done
    fi

    # Track failures
    FAILED=0

    # Run requested tests
    if [ "$RUN_ALL" = true ] || [ "$RUN_LINT" = true ]; then
        if ! run_lint; then
            FAILED=$((FAILED + 1))
        fi
        echo ""
    fi

    if [ "$RUN_ALL" = true ] || [ "$RUN_UNIT" = true ]; then
        if ! run_unit_tests; then
            FAILED=$((FAILED + 1))
        fi
        echo ""
    fi

    if [ "$RUN_ALL" = true ] || [ "$RUN_INTEGRATION" = true ]; then
        if ! run_integration_tests; then
            FAILED=$((FAILED + 1))
        fi
        echo ""
    fi

    if [ "$RUN_ALL" = true ] || [ "$RUN_SECURITY" = true ]; then
        if ! run_security; then
            FAILED=$((FAILED + 1))
        fi
        echo ""
    fi

    # Show coverage if unit tests were run
    if [ "$RUN_ALL" = true ] || [ "$RUN_UNIT" = true ]; then
        show_coverage
    fi

    # Summary
    print_header "Test Summary"
    if [ $FAILED -eq 0 ]; then
        print_success "All tests passed!"
        exit 0
    else
        print_error "$FAILED test suite(s) failed"
        exit 1
    fi
}

# Run main
main "$@"
