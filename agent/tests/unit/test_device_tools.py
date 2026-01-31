"""Unit tests for Device Tools."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent.tools.device_tools import DeviceTools


@pytest.mark.unit
class TestDeviceTools:
    """Test suite for DeviceTools."""

    def test_init(self, mock_settings):
        """Test DeviceTools initialization."""
        tools = DeviceTools()
        assert tools.username == mock_settings.network_username
        assert tools.password == mock_settings.network_password

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        tools = DeviceTools(
            username="custom-user",
            password="custom-pass",
            enable_password="enable-pass",
        )
        assert tools.username == "custom-user"
        assert tools.password == "custom-pass"
        assert tools.enable_password == "enable-pass"

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_connect_success(self, mock_connect_handler):
        """Test successful device connection."""
        mock_connection = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        connection = tools._connect("192.168.1.1", "cisco_ios")

        assert connection is not None
        mock_connect_handler.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_connect_failure(self, mock_connect_handler):
        """Test failed device connection."""
        mock_connect_handler.side_effect = Exception("Connection timeout")

        tools = DeviceTools()
        connection = tools._connect("192.168.1.1", "cisco_ios")

        assert connection is None

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_run_command_success(self, mock_connect_handler):
        """Test successful command execution."""
        mock_connection = Mock()
        mock_connection.send_command.return_value = "Command output"
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.run_command("192.168.1.1", "show version")

        assert result["success"] is True
        assert result["output"] == "Command output"
        assert result["host"] == "192.168.1.1"
        assert result["command"] == "show version"
        mock_connection.disconnect.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_run_command_connection_failure(self, mock_connect_handler):
        """Test command execution with connection failure."""
        mock_connect_handler.side_effect = Exception("Connection failed")

        tools = DeviceTools()
        result = tools.run_command("192.168.1.1", "show version")

        assert result["success"] is False
        assert "error" in result

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_run_command_execution_error(self, mock_connect_handler):
        """Test command execution with command error."""
        mock_connection = Mock()
        mock_connection.send_command.side_effect = Exception("Command failed")
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.run_command("192.168.1.1", "invalid command")

        assert result["success"] is False
        assert "error" in result
        mock_connection.disconnect.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_get_device_facts_cisco_ios(self, mock_connect_handler):
        """Test getting device facts from Cisco IOS."""
        mock_connection = Mock()
        mock_connection.send_command.side_effect = [
            "Cisco IOS Software, Version 15.2",
            "Processor board ID ABC123",
            "uptime is 30 days",
        ]
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.get_device_facts("192.168.1.1", "cisco_ios")

        assert result["host"] == "192.168.1.1"
        assert result["device_type"] == "cisco_ios"
        assert "Cisco IOS Software" in str(result.values())
        mock_connection.disconnect.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_get_device_facts_connection_error(self, mock_connect_handler):
        """Test get_device_facts with connection error."""
        mock_connect_handler.side_effect = Exception("Connection failed")

        tools = DeviceTools()
        result = tools.get_device_facts("192.168.1.1")

        assert "error" in result

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_get_interfaces(self, mock_connect_handler, sample_interfaces_output):
        """Test getting interface information."""
        mock_connection = Mock()
        mock_connection.send_command.return_value = sample_interfaces_output
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.get_interfaces("192.168.1.1", "cisco_ios")

        assert result["success"] is True
        assert result["host"] == "192.168.1.1"
        assert "GigabitEthernet0/0/0" in result["interfaces"]
        mock_connection.disconnect.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_get_interfaces_arista(self, mock_connect_handler):
        """Test getting interfaces from Arista device."""
        mock_connection = Mock()
        mock_connection.send_command.return_value = "Ethernet1 up up"
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.get_interfaces("192.168.1.1", "arista_eos")

        assert result["success"] is True
        mock_connection.send_command.assert_called_with("show ip interface brief")

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_backup_config(self, mock_connect_handler, sample_config):
        """Test backing up device configuration."""
        mock_connection = Mock()
        mock_connection.send_command.return_value = sample_config
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.backup_config("192.168.1.1", "cisco_ios")

        assert result["success"] is True
        assert result["host"] == "192.168.1.1"
        assert "hostname test-router-01" in result["config"]
        mock_connection.disconnect.assert_called_once()

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_backup_config_nxos(self, mock_connect_handler):
        """Test backing up config from NX-OS device."""
        mock_connection = Mock()
        mock_connection.send_command.return_value = "hostname switch-01"
        mock_connection.disconnect = Mock()
        mock_connect_handler.return_value = mock_connection

        tools = DeviceTools()
        result = tools.backup_config("192.168.1.1", "cisco_nxos")

        assert result["success"] is True
        mock_connection.send_command.assert_called_with("show running-config")

    @patch("agent.tools.device_tools.ConnectHandler")
    def test_backup_config_error(self, mock_connect_handler):
        """Test backup config with error."""
        mock_connect_handler.side_effect = Exception("Backup failed")

        tools = DeviceTools()
        result = tools.backup_config("192.168.1.1")

        assert result["success"] is False
        assert "error" in result
