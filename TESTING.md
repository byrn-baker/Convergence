# Testing Guide for Convergence

This document describes the testing strategy, setup, and execution for the Convergence project.

## Table of Contents
- [Overview](#overview)
- [Test Structure](#test-structure)
- [Running Tests](#running-tests)
- [CI/CD Pipeline](#cicd-pipeline)
- [Writing Tests](#writing-tests)
- [Coverage](#coverage)

## Overview

Convergence uses a comprehensive testing approach with:
- **Unit Tests**: Test individual functions and classes in isolation
- **Integration Tests**: Test interactions with external services (Nautobot, databases)
- **End-to-End Tests**: Test complete workflows
- **CI/CD**: Automated testing on every push and PR

### Testing Stack
- **pytest**: Test framework
- **pytest-cov**: Coverage reporting
- **pytest-asyncio**: Async test support
- **unittest.mock**: Mocking and patching
- **GitHub Actions**: CI/CD automation

## Test Structure

```
agent/
├── tests/
│   ├── conftest.py              # Shared fixtures and configuration
│   ├── unit/                    # Unit tests
│   │   ├── test_nautobot_client.py
│   │   ├── test_nautobot_apps.py
│   │   ├── test_device_tools.py
│   │   └── ...
│   ├── integration/             # Integration tests
│   │   ├── test_nautobot_integration.py
│   │   └── ...
│   └── fixtures/                # Test data and fixtures
├── pytest.ini                   # Pytest configuration
└── pyproject.toml              # Test dependencies
```

## Running Tests

### Prerequisites

```bash
cd agent
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Specific test file
pytest tests/unit/test_nautobot_client.py

# Specific test function
pytest tests/unit/test_nautobot_client.py::TestNautobotClient::test_init

# Tests with specific marker
pytest -m unit
pytest -m integration
pytest -m "not slow"
```

### Run with Coverage

```bash
# Generate coverage report
pytest --cov=agent --cov-report=html --cov-report=term

# View HTML coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Run with Verbose Output

```bash
pytest -v  # Verbose
pytest -vv  # Extra verbose
pytest -s  # Show print statements
pytest --tb=short  # Short traceback
```

### Run Integration Tests

Integration tests require running services (Nautobot, PostgreSQL, Redis).

**Option 1: Use docker-compose**

```bash
# Start services
docker-compose up -d

# Run integration tests
cd agent
RUN_INTEGRATION_TESTS=true pytest tests/integration/

# Stop services
docker-compose down
```

**Option 2: Manual setup**

```bash
# Set environment variable
export RUN_INTEGRATION_TESTS=true

# Run tests
pytest tests/integration/
```

## CI/CD Pipeline

### GitHub Actions Workflow

The project uses GitHub Actions for automated testing. The workflow runs on:
- Every push to `main` and `develop` branches
- Every pull request
- Manual trigger via workflow_dispatch

### Workflow Jobs

1. **Lint**: Code quality checks
   - Ruff linter
   - Black formatter
   - mypy type checker

2. **Unit Tests**: Fast isolated tests
   - Runs on Python 3.12 and 3.13
   - Generates coverage report
   - Uploads to Codecov

3. **Integration Tests**: Tests with services
   - Starts PostgreSQL and Redis
   - Starts Nautobot container
   - Runs integration test suite

4. **Docker Build**: Infrastructure tests
   - Validates docker-compose.yml
   - Builds all images
   - Tests service health checks

5. **Security Scan**: Security analysis
   - Bandit for security issues
   - Safety for dependency vulnerabilities

6. **Documentation**: Doc validation
   - Checks for required docs
   - Validates README links

7. **Release**: Automatic releases
   - Creates releases on main branch
   - Tags with version from pyproject.toml

### Running CI Locally

Use [act](https://github.com/nektos/act) to run GitHub Actions locally:

```bash
# Install act
# macOS: brew install act
# Linux: See https://github.com/nektos/act#installation

# Run all jobs
act

# Run specific job
act -j test-unit
act -j lint
```

## Writing Tests

### Unit Test Example

```python
import pytest
from unittest.mock import Mock, patch
from agent.tools.my_module import MyClass

@pytest.mark.unit
class TestMyClass:
    """Test suite for MyClass."""

    def test_init(self, mock_settings):
        """Test initialization."""
        obj = MyClass()
        assert obj.config == mock_settings

    @patch("agent.tools.my_module.external_api")
    def test_method_with_mock(self, mock_api):
        """Test method with external dependency."""
        mock_api.return_value = {"status": "success"}

        obj = MyClass()
        result = obj.my_method()

        assert result["status"] == "success"
        mock_api.assert_called_once()

    def test_error_handling(self):
        """Test error handling."""
        obj = MyClass()

        with pytest.raises(ValueError):
            obj.invalid_operation()
```

### Integration Test Example

```python
import pytest
import os

@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Integration tests require RUN_INTEGRATION_TESTS=true"
)
class TestNautobotIntegration:
    """Integration tests for Nautobot."""

    def test_real_api_call(self):
        """Test actual API call to Nautobot."""
        from agent.tools.nautobot_client import NautobotClient

        client = NautobotClient()
        result = client.list_devices(limit=1)

        assert isinstance(result, list)
```

### Using Fixtures

```python
def test_with_mock_device(mock_device_data):
    """Test using the mock_device_data fixture."""
    assert mock_device_data["name"] == "test-router-01"
    assert mock_device_data["status"] == "active"

def test_with_mock_connection(mock_ssh_connection):
    """Test using the mock_ssh_connection fixture."""
    mock_ssh_connection.send_command("show version")
    mock_ssh_connection.send_command.assert_called_once()
```

### Test Markers

Use markers to categorize tests:

```python
@pytest.mark.unit  # Unit test
@pytest.mark.integration  # Integration test
@pytest.mark.slow  # Slow test (>1 second)
@pytest.mark.network  # Requires network access
@pytest.mark.nautobot  # Requires Nautobot instance
```

## Coverage

### Coverage Goals
- **Overall Coverage**: ≥80%
- **Critical Modules**: ≥90%
  - agent/tools/nautobot_client.py
  - agent/tools/nautobot_apps.py
  - agent/agents/network_agent.py

### Viewing Coverage

```bash
# Terminal report
pytest --cov=agent --cov-report=term-missing

# HTML report
pytest --cov=agent --cov-report=html
open htmlcov/index.html

# XML report (for CI)
pytest --cov=agent --cov-report=xml
```

### Coverage Configuration

Coverage settings are in `pytest.ini`:
- Minimum coverage: 80%
- Source: `agent/` directory
- Omit: tests, __pycache__, venv

## Best Practices

### Do's ✅
- Write tests for all new features
- Use descriptive test names
- Keep tests fast (mock external calls)
- Test edge cases and error conditions
- Use fixtures for common setup
- Run tests before committing
- Maintain ≥80% coverage

### Don'ts ❌
- Don't test external libraries
- Don't write flaky tests
- Don't mock too much (test real logic)
- Don't skip tests without reason
- Don't commit failing tests
- Don't ignore CI failures

## Troubleshooting

### Tests Failing Locally

```bash
# Clear pytest cache
pytest --cache-clear

# Reinstall dependencies
pip install -e ".[dev]" --force-reinstall

# Check environment variables
env | grep NAUTOBOT
```

### Integration Tests Not Running

```bash
# Verify services are running
docker-compose ps

# Check Nautobot health
curl http://localhost:8000/health/

# Enable integration tests
export RUN_INTEGRATION_TESTS=true
```

### Coverage Not Generated

```bash
# Install coverage plugin
pip install pytest-cov

# Verify pytest-cov is installed
pytest --version

# Run with coverage explicitly
pytest --cov=agent --cov-report=html
```

## Continuous Improvement

### Adding New Tests

When adding new features:
1. Write tests first (TDD approach)
2. Ensure tests pass locally
3. Check coverage increases
4. Add integration tests if needed
5. Update this documentation

### Improving Test Speed

- Mock external API calls
- Use in-memory databases for tests
- Parallelize test execution: `pytest -n auto`
- Mark slow tests: `@pytest.mark.slow`
- Skip slow tests: `pytest -m "not slow"`

### Monitoring Test Health

Track metrics:
- Test execution time
- Test failure rate
- Coverage trends
- Flaky test detection

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock guide](https://docs.python.org/3/library/unittest.mock.html)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)
- [GitHub Actions](https://docs.github.com/en/actions)

## Getting Help

- Check test logs: `pytest -v --tb=long`
- Run specific test with prints: `pytest -s tests/unit/test_file.py::test_function`
- Open an issue with test failures
- Review CI logs in GitHub Actions
