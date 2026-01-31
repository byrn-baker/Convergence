"""Nautobot Apps integration tools for AI agent."""

from typing import Any, Optional, List
from langchain_core.tools import tool
import httpx

from agent.config import settings


class NautobotAppsClient:
    """Client for interacting with Nautobot Apps APIs."""

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        """Initialize Nautobot Apps client.

        Args:
            url: Nautobot URL (defaults to settings)
            token: API token (defaults to settings)
        """
        self.url = url or settings.nautobot_url
        self.token = token or settings.nautobot_api_token
        self.headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
        }


    def onboard_device(
        self,
        ip_address: str,
        platform: str,
        site: Optional[str] = None,
        role: Optional[str] = None,
    ) -> dict[str, Any]:
        """Onboard a network device using Nautobot Device Onboarding app.

        This tool leverages the Device Onboarding app to automatically discover
        and add a device to Nautobot. The app will connect to the device, gather
        facts, and create the device record with interfaces.

        Args:
            ip_address: Device IP address or hostname
            platform: Device platform (cisco_ios, arista_eos, juniper_junos, etc.)
            site: Site name for the device (optional)
            role: Device role (optional)

        Returns:
            Dictionary with onboarding task ID and status
        """
        try:
            endpoint = f"{self.url}/api/plugins/device-onboarding/onboarding/"
            payload = {
                "ip_address": ip_address,
                "platform": platform,
            }
            if site:
                payload["site"] = site
            if role:
                payload["role"] = role

            response = httpx.post(endpoint, json=payload, headers=self.headers, timeout=30.0)
            response.raise_for_status()

            data = response.json()
            return {
                "success": True,
                "task_id": data.get("id"),
                "status": data.get("status"),
                "message": f"Device onboarding initiated for {ip_address}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def get_onboarding_status(self, task_id: str) -> dict[str, Any]:
        """Get the status of a device onboarding task.

        Args:
            task_id: Onboarding task ID

        Returns:
            Dictionary with task status and details
        """
        try:
            endpoint = f"{self.url}/api/plugins/device-onboarding/onboarding/{task_id}/"
            response = httpx.get(endpoint, headers=self.headers, timeout=15.0)
            response.raise_for_status()

            data = response.json()
            return {
                "success": True,
                "task_id": task_id,
                "status": data.get("status"),
                "device_name": data.get("device_name"),
                "ip_address": data.get("ip_address"),
                "completed": data.get("status") in ["completed", "failed"],
                "error": data.get("error_message"),
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def bulk_onboard_devices(
        self, device_list: List[dict[str, str]]
    ) -> dict[str, Any]:
        """Onboard multiple devices in bulk.

        Args:
            device_list: List of device dictionaries with keys:
                - ip_address: Device IP
                - platform: Device platform
                - site (optional): Site name
                - role (optional): Device role

        Returns:
            Dictionary with task IDs and summary
        """
        results = []
        for device in device_list:
            result = self.onboard_device(
                ip_address=device["ip_address"],
                platform=device["platform"],
                site=device.get("site"),
                role=device.get("role"),
            )
            results.append(result)

        successful = sum(1 for r in results if r.get("success"))
        return {
            "total": len(device_list),
            "successful": successful,
            "failed": len(device_list) - successful,
            "results": results,
        }


    def list_onboarding_tasks(
        self, status: Optional[str] = None, limit: int = 50
    ) -> dict[str, Any]:
        """List device onboarding tasks.

        Args:
            status: Filter by status (pending, running, completed, failed)
            limit: Maximum number of tasks to return

        Returns:
            List of onboarding tasks
        """
        try:
            endpoint = f"{self.url}/api/plugins/device-onboarding/onboarding/"
            params = {"limit": limit}
            if status:
                params["status"] = status

            response = httpx.get(endpoint, headers=self.headers, params=params, timeout=15.0)
            response.raise_for_status()

            data = response.json()
            tasks = data.get("results", [])

            return {
                "success": True,
                "count": len(tasks),
                "tasks": [
                    {
                        "id": task.get("id"),
                        "ip_address": task.get("ip_address"),
                        "device_name": task.get("device_name"),
                        "platform": task.get("platform"),
                        "status": task.get("status"),
                        "created": task.get("created"),
                    }
                    for task in tasks
                ],
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def get_golden_config(self, device_name: str) -> dict[str, Any]:
        """Get golden (intended) configuration for a device.

        This uses the Golden Config app to retrieve the intended configuration
        for a device based on templates and config context.

        Args:
            device_name: Device name in Nautobot

        Returns:
            Dictionary with golden configuration
        """
        try:
            endpoint = f"{self.url}/api/plugins/golden-config/golden-config/"
            params = {"device": device_name}

            response = httpx.get(endpoint, headers=self.headers, params=params, timeout=15.0)
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            if results:
                config = results[0]
                return {
                    "success": True,
                    "device": device_name,
                    "golden_config": config.get("intended_config"),
                    "last_updated": config.get("last_updated"),
                }
            return {
                "success": False,
                "error": f"Golden config not found for {device_name}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def compare_config(self, device_name: str) -> dict[str, Any]:
        """Compare running config with golden config for a device.

        Uses Golden Config app to detect configuration drift.

        Args:
            device_name: Device name in Nautobot

        Returns:
            Dictionary with config comparison results
        """
        try:
            endpoint = f"{self.url}/api/plugins/golden-config/config-compliance/"
            params = {"device": device_name}

            response = httpx.get(endpoint, headers=self.headers, params=params, timeout=15.0)
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            if results:
                compliance = results[0]
                return {
                    "success": True,
                    "device": device_name,
                    "compliant": compliance.get("compliance"),
                    "diff": compliance.get("diff"),
                    "last_checked": compliance.get("last_updated"),
                }
            return {
                "success": False,
                "error": f"No compliance data found for {device_name}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
