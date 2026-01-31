"""Unit tests for Nautobot client."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent.tools.nautobot_client import NautobotClient


@pytest.mark.unit
class TestNautobotClient:
    """Test suite for NautobotClient."""

    def test_init(self, mock_settings):
        """Test client initialization."""
        client = NautobotClient()
        assert client.url == mock_settings.nautobot_url
        assert client.token == mock_settings.nautobot_api_token

    def test_init_with_custom_params(self):
        """Test client initialization with custom parameters."""
        client = NautobotClient(url="http://custom:8000", token="custom-token")
        assert client.url == "http://custom:8000"
        assert client.token == "custom-token"

    @patch("agent.tools.nautobot_client.api")
    def test_get_device_success(self, mock_api, mock_device_data):
        """Test getting a device successfully."""
        # Setup mock
        mock_device = Mock()
        mock_device.name = mock_device_data["name"]
        mock_device.id = mock_device_data["id"]
        mock_device.status = Mock()
        mock_device.status.__str__ = Mock(return_value=mock_device_data["status"])
        mock_device.device_type = Mock()
        mock_device.device_type.__str__ = Mock(return_value=mock_device_data["device_type"])
        mock_device.site = Mock()
        mock_device.site.__str__ = Mock(return_value=mock_device_data["site"])
        mock_device.primary_ip4 = Mock()
        mock_device.primary_ip4.__str__ = Mock(return_value=mock_device_data["primary_ip4"])
        mock_device.serial = mock_device_data["serial"]
        mock_device.platform = Mock()
        mock_device.platform.__str__ = Mock(return_value=mock_device_data["platform"])

        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.get.return_value = mock_device
        mock_api.return_value = mock_api_instance

        # Test
        client = NautobotClient()
        result = client.get_device("test-router-01")

        # Assertions
        assert result["name"] == mock_device_data["name"]
        assert result["id"] == mock_device_data["id"]
        assert "error" not in result

    @patch("agent.tools.nautobot_client.api")
    def test_get_device_not_found(self, mock_api):
        """Test getting a device that doesn't exist."""
        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.get.return_value = None
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.get_device("nonexistent-device")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @patch("agent.tools.nautobot_client.api")
    def test_get_device_exception(self, mock_api):
        """Test exception handling in get_device."""
        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.get.side_effect = Exception("API Error")
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.get_device("test-device")

        assert "error" in result
        assert "API Error" in result["error"]

    @patch("agent.tools.nautobot_client.api")
    def test_list_devices(self, mock_api, mock_device_list):
        """Test listing devices."""
        # Setup mocks
        mock_devices = []
        for device_data in mock_device_list:
            mock_device = Mock()
            mock_device.name = device_data["name"]
            mock_device.id = device_data["id"]
            mock_device.status = Mock()
            mock_device.status.__str__ = Mock(return_value=device_data["status"])
            mock_device.device_type = Mock()
            mock_device.device_type.__str__ = Mock(return_value=device_data["device_type"])
            mock_device.site = Mock()
            mock_device.site.__str__ = Mock(return_value=device_data["site"])
            mock_device.primary_ip4 = Mock()
            mock_device.primary_ip4.__str__ = Mock(return_value=device_data["primary_ip4"])
            mock_devices.append(mock_device)

        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.filter.return_value = mock_devices
        mock_api.return_value = mock_api_instance

        # Test
        client = NautobotClient()
        result = client.list_devices()

        # Assertions
        assert len(result) == len(mock_device_list)
        assert result[0]["name"] == "router-01"
        assert result[1]["name"] == "switch-01"

    @patch("agent.tools.nautobot_client.api")
    def test_list_devices_with_site_filter(self, mock_api):
        """Test listing devices with site filter."""
        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.filter.return_value = []
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.list_devices(site="HQ", limit=100)

        mock_api_instance.dcim.devices.filter.assert_called_once_with(
            site="HQ", limit=100
        )
        assert isinstance(result, list)

    @patch("agent.tools.nautobot_client.api")
    def test_create_device(self, mock_api):
        """Test creating a device."""
        mock_device = Mock()
        mock_device.name = "new-device"
        mock_device.id = "12345"
        mock_device.status = Mock()
        mock_device.status.__str__ = Mock(return_value="active")

        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.create.return_value = mock_device
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.create_device(
            name="new-device",
            device_type="Cisco ISR",
            site="HQ",
            serial="ABC123",
        )

        assert result["created"] is True
        assert result["name"] == "new-device"
        assert "error" not in result

    @patch("agent.tools.nautobot_client.api")
    def test_update_device(self, mock_api):
        """Test updating a device."""
        mock_device = Mock()
        mock_device.name = "test-device"
        mock_device.id = "12345"
        mock_device.update = Mock()

        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.get.return_value = mock_device
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.update_device(name="test-device", status="planned")

        assert result["updated"] is True
        assert "error" not in result
        mock_device.update.assert_called_once()

    @patch("agent.tools.nautobot_client.api")
    def test_get_device_config_context(self, mock_api):
        """Test getting device configuration context."""
        mock_device = Mock()
        mock_device.config_context = {"ntp_servers": ["10.0.0.1"]}

        mock_api_instance = Mock()
        mock_api_instance.dcim.devices.get.return_value = mock_device
        mock_api.return_value = mock_api_instance

        client = NautobotClient()
        result = client.get_device_config_context("test-device")

        assert "config_context" in result
        assert result["config_context"]["ntp_servers"] == ["10.0.0.1"]
