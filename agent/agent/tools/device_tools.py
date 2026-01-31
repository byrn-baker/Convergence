"""Network device interaction tools."""

from typing import Any, Optional
from netmiko import ConnectHandler
from langchain_core.tools import tool

from agent.config import settings


class DeviceTools:
    """Tools for interacting with network devices."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        enable_password: Optional[str] = None,
    ):
        """Initialize device tools.

        Args:
            username: Device username (defaults to settings)
            password: Device password (defaults to settings)
            enable_password: Enable password (defaults to settings)
        """
        self.username = username or settings.network_username
        self.password = password or settings.network_password
        self.enable_password = enable_password or settings.network_enable_password

    def _connect(
        self, host: str, device_type: str = "cisco_ios"
    ) -> Optional[ConnectHandler]:
        """Establish SSH connection to device.

        Args:
            host: Device IP or hostname
            device_type: Netmiko device type

        Returns:
            Netmiko connection object or None if failed
        """
        try:
            connection = ConnectHandler(
                device_type=device_type,
                host=host,
                username=self.username,
                password=self.password,
                secret=self.enable_password,
            )
            return connection
        except Exception as e:
            print(f"Connection error to {host}: {e}")
            return None


    def run_command(
        self, host: str, command: str, device_type: str = "cisco_ios"
    ) -> dict[str, Any]:
        """Run a command on a network device via SSH.

        Args:
            host: Device IP or hostname
            command: Command to execute
            device_type: Netmiko device type (default: cisco_ios)

        Returns:
            Dictionary with command output or error
        """
        connection = self._connect(host, device_type)
        if not connection:
            return {"error": f"Failed to connect to {host}", "success": False}

        try:
            output = connection.send_command(command)
            connection.disconnect()
            return {"host": host, "command": command, "output": output, "success": True}
        except Exception as e:
            connection.disconnect()
            return {"error": str(e), "success": False}


    def get_device_facts(self, host: str, device_type: str = "cisco_ios") -> dict[str, Any]:
        """Gather basic device facts (version, serial, uptime, etc.).

        Args:
            host: Device IP or hostname
            device_type: Netmiko device type

        Returns:
            Dictionary with device facts
        """
        commands = {
            "cisco_ios": [
                "show version | include Version",
                "show version | include Serial",
                "show version | include uptime",
            ],
            "cisco_nxos": [
                "show version | include Software",
                "show version | include Hardware",
                "show system uptime",
            ],
            "arista_eos": ["show version"],
        }

        connection = self._connect(host, device_type)
        if not connection:
            return {"error": f"Failed to connect to {host}", "success": False}

        try:
            facts = {"host": host, "device_type": device_type}

            for command in commands.get(device_type, commands["cisco_ios"]):
                output = connection.send_command(command)
                facts[command] = output

            connection.disconnect()
            return facts
        except Exception as e:
            connection.disconnect()
            return {"error": str(e)}


    def get_interfaces(self, host: str, device_type: str = "cisco_ios") -> dict[str, Any]:
        """Get interface information from device.

        Args:
            host: Device IP or hostname
            device_type: Netmiko device type

        Returns:
            Dictionary with interface information
        """
        commands = {
            "cisco_ios": "show ip interface brief",
            "cisco_nxos": "show interface brief",
            "arista_eos": "show ip interface brief",
        }

        command = commands.get(device_type, commands["cisco_ios"])
        connection = self._connect(host, device_type)

        if not connection:
            return {"error": f"Failed to connect to {host}", "success": False}

        try:
            output = connection.send_command(command)
            connection.disconnect()
            return {"host": host, "interfaces": output, "success": True}
        except Exception as e:
            connection.disconnect()
            return {"error": str(e), "success": False}


    def backup_config(self, host: str, device_type: str = "cisco_ios") -> dict[str, Any]:
        """Backup device running configuration.

        Args:
            host: Device IP or hostname
            device_type: Netmiko device type

        Returns:
            Dictionary with configuration content
        """
        commands = {
            "cisco_ios": "show running-config",
            "cisco_nxos": "show running-config",
            "arista_eos": "show running-config",
        }

        command = commands.get(device_type, commands["cisco_ios"])
        connection = self._connect(host, device_type)

        if not connection:
            return {"error": f"Failed to connect to {host}", "success": False}

        try:
            config = connection.send_command(command)
            connection.disconnect()
            return {"host": host, "config": config, "success": True}
        except Exception as e:
            connection.disconnect()
            return {"error": str(e), "success": False}
