"""Nautobot API client for agent tools."""

from typing import Any, Optional
from pynautobot import api
from langchain_core.tools import tool

from agent.config import settings


class NautobotClient:
    """Client for interacting with Nautobot API."""

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        """Initialize Nautobot client.

        Args:
            url: Nautobot URL (defaults to settings)
            token: API token (defaults to settings)
        """
        self.url = url or settings.nautobot_url
        self.token = token or settings.nautobot_api_token
        self.api = api(url=self.url, token=self.token)


    def get_device(self, name: str) -> dict[str, Any]:
        """Get device information from Nautobot by name.

        Args:
            name: Device name to lookup

        Returns:
            Device information as dictionary
        """
        try:
            device = self.api.dcim.devices.get(name=name)
            if device:
                return {
                    "name": device.name,
                    "id": str(device.id),
                    "status": str(device.status),
                    "device_type": str(device.device_type),
                    "site": str(device.site) if device.site else None,
                    "primary_ip4": str(device.primary_ip4) if device.primary_ip4 else None,
                    "serial": device.serial,
                    "platform": str(device.platform) if device.platform else None,
                }
            return {"error": f"Device {name} not found"}
        except Exception as e:
            return {"error": str(e)}


    def list_devices(self, site: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """List devices from Nautobot, optionally filtered by site.

        Args:
            site: Optional site name to filter by
            limit: Maximum number of devices to return

        Returns:
            List of device information dictionaries
        """
        try:
            filters = {}
            if site:
                filters["site"] = site

            devices = self.api.dcim.devices.filter(**filters, limit=limit)
            return [
                {
                    "name": device.name,
                    "id": str(device.id),
                    "status": str(device.status),
                    "device_type": str(device.device_type),
                    "site": str(device.site) if device.site else None,
                    "primary_ip4": str(device.primary_ip4) if device.primary_ip4 else None,
                }
                for device in devices
            ]
        except Exception as e:
            return [{"error": str(e)}]


    def create_device(
        self,
        name: str,
        device_type: str,
        site: str,
        status: str = "active",
        serial: Optional[str] = None,
        primary_ip4: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new device in Nautobot.

        Args:
            name: Device name
            device_type: Device type name
            site: Site name
            status: Device status (default: active)
            serial: Serial number
            primary_ip4: Primary IPv4 address

        Returns:
            Created device information
        """
        try:
            device_data = {
                "name": name,
                "device_type": device_type,
                "site": site,
                "status": status,
            }
            if serial:
                device_data["serial"] = serial
            if primary_ip4:
                device_data["primary_ip4"] = primary_ip4

            device = self.api.dcim.devices.create(**device_data)
            return {
                "name": device.name,
                "id": str(device.id),
                "status": str(device.status),
                "created": True,
            }
        except Exception as e:
            return {"error": str(e), "created": False}


    def update_device(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Update device information in Nautobot.

        Args:
            name: Device name to update
            **kwargs: Fields to update

        Returns:
            Updated device information
        """
        try:
            device = self.api.dcim.devices.get(name=name)
            if not device:
                return {"error": f"Device {name} not found"}

            device.update(kwargs)
            return {
                "name": device.name,
                "id": str(device.id),
                "updated": True,
            }
        except Exception as e:
            return {"error": str(e), "updated": False}


    def get_device_config_context(self, name: str) -> dict[str, Any]:
        """Get device configuration context from Nautobot.

        Args:
            name: Device name

        Returns:
            Configuration context data
        """
        try:
            device = self.api.dcim.devices.get(name=name)
            if not device:
                return {"error": f"Device {name} not found"}

            return {"config_context": device.config_context}
        except Exception as e:
            return {"error": str(e)}
