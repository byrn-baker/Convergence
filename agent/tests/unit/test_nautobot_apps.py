"""Unit tests for Nautobot Apps client."""

import pytest
from unittest.mock import Mock, patch
import httpx
from agent.tools.nautobot_apps import NautobotAppsClient


@pytest.mark.unit
class TestNautobotAppsClient:
    """Test suite for NautobotAppsClient."""

    def test_init(self, mock_settings):
        """Test client initialization."""
        client = NautobotAppsClient()
        assert client.url == mock_settings.nautobot_url
        assert client.token == mock_settings.nautobot_api_token
        assert "Authorization" in client.headers

    def test_init_with_custom_params(self):
        """Test client initialization with custom parameters."""
        client = NautobotAppsClient(url="http://custom:8000", token="custom-token")
        assert client.url == "http://custom:8000"
        assert client.token == "custom-token"

    @patch("httpx.post")
    def test_onboard_device_success(self, mock_post, mock_onboarding_task):
        """Test successful device onboarding."""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_onboarding_task
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Test
        client = NautobotAppsClient()
        result = client.onboard_device(
            ip_address="192.168.1.100",
            platform="cisco_ios",
            site="HQ",
        )

        # Assertions
        assert result["success"] is True
        assert result["task_id"] == mock_onboarding_task["id"]
        assert "error" not in result

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "192.168.1.100" in str(call_args)

    @patch("httpx.post")
    def test_onboard_device_http_error(self, mock_post):
        """Test device onboarding with HTTP error."""
        mock_post.side_effect = httpx.HTTPError("Connection failed")

        client = NautobotAppsClient()
        result = client.onboard_device(
            ip_address="192.168.1.100",
            platform="cisco_ios",
        )

        assert result["success"] is False
        assert "error" in result

    @patch("httpx.get")
    def test_get_onboarding_status_success(self, mock_get, mock_onboarding_task):
        """Test getting onboarding task status."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_onboarding_task
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.get_onboarding_status("task-12345")

        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["completed"] is True
        assert result["device_name"] == mock_onboarding_task["device_name"]

    @patch("httpx.get")
    def test_get_onboarding_status_failed_task(self, mock_get):
        """Test getting status of a failed onboarding task."""
        failed_task = {
            "id": "task-12345",
            "status": "failed",
            "error_message": "Connection timeout",
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = failed_task
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.get_onboarding_status("task-12345")

        assert result["success"] is True
        assert result["status"] == "failed"
        assert result["completed"] is True
        assert result["error"] == "Connection timeout"

    def test_bulk_onboard_devices(self, mock_onboarding_task):
        """Test bulk device onboarding."""
        device_list = [
            {"ip_address": "192.168.1.1", "platform": "cisco_ios", "site": "HQ"},
            {"ip_address": "192.168.1.2", "platform": "cisco_ios", "site": "HQ"},
            {"ip_address": "192.168.1.3", "platform": "arista_eos", "site": "Branch"},
        ]

        with patch.object(
            NautobotAppsClient, "onboard_device"
        ) as mock_onboard:
            mock_onboard.return_value = {"success": True, "task_id": "test-id"}

            client = NautobotAppsClient()
            result = client.bulk_onboard_devices(device_list)

            assert result["total"] == 3
            assert result["successful"] == 3
            assert result["failed"] == 0
            assert mock_onboard.call_count == 3

    def test_bulk_onboard_devices_with_failures(self):
        """Test bulk onboarding with some failures."""
        device_list = [
            {"ip_address": "192.168.1.1", "platform": "cisco_ios"},
            {"ip_address": "192.168.1.2", "platform": "cisco_ios"},
        ]

        with patch.object(
            NautobotAppsClient, "onboard_device"
        ) as mock_onboard:
            # First succeeds, second fails
            mock_onboard.side_effect = [
                {"success": True, "task_id": "test-id"},
                {"success": False, "error": "Connection failed"},
            ]

            client = NautobotAppsClient()
            result = client.bulk_onboard_devices(device_list)

            assert result["total"] == 2
            assert result["successful"] == 1
            assert result["failed"] == 1

    @patch("httpx.get")
    def test_list_onboarding_tasks(self, mock_get):
        """Test listing onboarding tasks."""
        tasks_data = {
            "results": [
                {
                    "id": "task-1",
                    "ip_address": "192.168.1.1",
                    "device_name": "router-01",
                    "platform": "cisco_ios",
                    "status": "completed",
                    "created": "2026-01-31T10:00:00Z",
                },
                {
                    "id": "task-2",
                    "ip_address": "192.168.1.2",
                    "device_name": "switch-01",
                    "platform": "cisco_ios",
                    "status": "running",
                    "created": "2026-01-31T10:05:00Z",
                },
            ]
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = tasks_data
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.list_onboarding_tasks(status="completed", limit=50)

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["tasks"]) == 2
        assert result["tasks"][0]["device_name"] == "router-01"

    @patch("httpx.get")
    def test_get_golden_config_success(self, mock_get):
        """Test getting golden configuration."""
        config_data = {
            "results": [
                {
                    "intended_config": "hostname test-device\n",
                    "last_updated": "2026-01-31T10:00:00Z",
                }
            ]
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = config_data
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.get_golden_config("test-device")

        assert result["success"] is True
        assert "hostname test-device" in result["golden_config"]

    @patch("httpx.get")
    def test_get_golden_config_not_found(self, mock_get):
        """Test getting golden config when not found."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.get_golden_config("nonexistent-device")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @patch("httpx.get")
    def test_compare_config(self, mock_get):
        """Test config comparison."""
        compliance_data = {
            "results": [
                {
                    "compliance": True,
                    "diff": "",
                    "last_updated": "2026-01-31T10:00:00Z",
                }
            ]
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = compliance_data
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = NautobotAppsClient()
        result = client.compare_config("test-device")

        assert result["success"] is True
        assert result["compliant"] is True
        assert result["diff"] == ""
