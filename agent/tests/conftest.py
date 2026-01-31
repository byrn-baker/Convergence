"""Pytest configuration and fixtures for Convergence Agent tests."""

import pytest
from unittest.mock import Mock, MagicMock, patch
import httpx
from typing import Generator

from agent.config import Settings


@pytest.fixture
def mock_settings() -> Settings:
    """Provide mock settings for testing."""
    return Settings(
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        nautobot_url="http://localhost:8000",
        nautobot_api_token="test-token-12345",
        network_username="test-user",
        network_password="test-password",
        agent_model="gpt-4",
        agent_temperature=0.1,
        agent_max_iterations=10,
    )


@pytest.fixture(autouse=True)
def patch_settings(reset_env_vars: None) -> Generator[None, None, None]:
    """Patch settings to use test environment variables."""
    # Force settings to reload from environment
    from agent.config import settings

    # Create a new settings instance with test values
    test_settings = Settings(
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        nautobot_url="http://localhost:8000",
        nautobot_api_token="test-token-12345",
        network_username="test-user",
        network_password="test-password",
        agent_model="gpt-4",
        agent_temperature=0.1,
        agent_max_iterations=10,
    )

    # Patch all the settings modules
    with patch("agent.config.settings", test_settings), \
         patch("agent.tools.device_tools.settings", test_settings), \
         patch("agent.tools.nautobot_client.settings", test_settings), \
         patch("agent.tools.nautobot_apps.settings", test_settings):
        yield


@pytest.fixture
def mock_nautobot_api() -> Generator[Mock, None, None]:
    """Mock Nautobot API responses."""
    with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
        # Mock successful API responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = Mock()

        mock_get.return_value = mock_response
        mock_post.return_value = mock_response

        yield {"get": mock_get, "post": mock_post}


@pytest.fixture
def mock_device_data() -> dict:
    """Provide sample device data for testing."""
    return {
        "name": "test-router-01",
        "id": "12345",
        "status": "active",
        "device_type": "Cisco ISR 4451",
        "site": "HQ",
        "primary_ip4": "192.168.1.1",
        "serial": "ABC123XYZ",
        "platform": "cisco_ios",
    }


@pytest.fixture
def mock_device_list() -> list[dict]:
    """Provide sample device list for testing."""
    return [
        {
            "name": "router-01",
            "id": "1",
            "status": "active",
            "device_type": "Cisco ISR",
            "site": "HQ",
            "primary_ip4": "192.168.1.1",
        },
        {
            "name": "switch-01",
            "id": "2",
            "status": "active",
            "device_type": "Cisco Catalyst",
            "site": "HQ",
            "primary_ip4": "192.168.1.2",
        },
    ]


@pytest.fixture
def mock_onboarding_task() -> dict:
    """Provide sample onboarding task data."""
    return {
        "id": "task-12345",
        "ip_address": "192.168.1.100",
        "platform": "cisco_ios",
        "status": "completed",
        "device_name": "test-device-01",
        "created": "2026-01-31T10:00:00Z",
    }


@pytest.fixture
def mock_ssh_connection() -> Generator[Mock, None, None]:
    """Mock SSH connection for device testing."""
    with patch("netmiko.ConnectHandler") as mock_connect:
        mock_connection = Mock()
        mock_connection.send_command.return_value = "Mock command output"
        mock_connection.disconnect = Mock()
        mock_connect.return_value = mock_connection

        yield mock_connection


@pytest.fixture
def mock_langgraph_agent() -> Mock:
    """Mock LangGraph agent for testing."""
    mock_agent = Mock()
    mock_agent.ainvoke = MagicMock()
    mock_agent.invoke = MagicMock()
    return mock_agent


@pytest.fixture
def sample_config() -> str:
    """Provide sample device configuration."""
    return """!
hostname test-router-01
!
interface GigabitEthernet0/0/0
 ip address 192.168.1.1 255.255.255.0
 no shutdown
!
end
"""


@pytest.fixture
def sample_interfaces_output() -> str:
    """Provide sample interface command output."""
    return """Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0/0   192.168.1.1     YES manual up                    up
GigabitEthernet0/0/1   unassigned      YES unset  administratively down down
"""


@pytest.fixture(autouse=True)
def reset_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset environment variables for each test."""
    # Set test environment variables
    monkeypatch.setenv("NAUTOBOT_URL", "http://localhost:8000")
    monkeypatch.setenv("NAUTOBOT_API_TOKEN", "test-token-12345")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("NETWORK_USERNAME", "test-user")
    monkeypatch.setenv("NETWORK_PASSWORD", "test-password")


@pytest.fixture
def mock_httpx_client() -> Generator[Mock, None, None]:
    """Mock httpx client for API testing."""
    with patch("httpx.Client") as mock_client:
        mock_instance = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()

        mock_instance.get.return_value = mock_response
        mock_instance.post.return_value = mock_response
        mock_client.return_value.__enter__.return_value = mock_instance

        yield mock_instance


@pytest.fixture
def integration_test_enabled() -> bool:
    """Check if integration tests should run (requires running services)."""
    import os
    return os.getenv("RUN_INTEGRATION_TESTS", "false").lower() == "true"


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test (deselect with '-m \"not unit\"')"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "e2e: mark test as an end-to-end test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow (takes more than 1s)"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection to skip integration tests by default."""
    skip_integration = pytest.mark.skip(
        reason="Integration tests require RUN_INTEGRATION_TESTS=true"
    )
    for item in items:
        if "integration" in item.keywords:
            if not config.getoption("--run-integration", default=False):
                item.add_marker(skip_integration)
