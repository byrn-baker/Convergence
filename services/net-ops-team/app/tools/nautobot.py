"""
Nautobot 3.x API client for the NET-OPS team agents.

Uses GraphQL for all reads (richer, single-call for full device/interface data)
and REST for writes (create/update/delete), using correct Nautobot 3.x field structures.

Key Nautobot 3.x differences from older versions:
- `status` is a related object (UUID), not a string — use STATUS_IDS dict
- `type` in REST uses lowercase slugs ("1000base-t"), GraphQL returns enum ("A_1000BASE_T")
- IDs are UUIDs (strings), not integers
- `device` in REST create payload uses {"id": uuid}
"""
import httpx

from ..config import settings

# Status UUIDs for dcim.interface — queried from /api/extras/statuses/
# These are stable per-instance (set at DB creation), so safe to cache here.
STATUS_IDS = {
    "active":           "635427b7-eef4-4af0-9ee0-cf4d89fd58e4",
    "decommissioning":  "4c7b3393-c48a-4ea0-92ff-68b307fc9c53",
    "failed":           "8ba455d6-2a8a-4653-9f0b-feee3d5a5797",
    "maintenance":      "3eba616c-ab63-4b2c-a825-ad691e7e6187",
    "planned":          "02246e06-4d88-43ad-af40-a86a24c85a9f",
}


def _headers():
    return {
        "Authorization": f"Token {settings.nautobot_token}",
        "Content-Type": "application/json",
    }


def _client():
    return httpx.AsyncClient(verify=settings.nautobot_verify_ssl, timeout=15.0)


async def graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against Nautobot. Returns the data dict or {"error": ...}."""
    try:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        async with _client() as client:
            resp = await client.post(
                f"{settings.nautobot_url}/api/graphql/",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                return {"error": result["errors"]}
            return result.get("data", {})
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Device queries
# ---------------------------------------------------------------------------

async def get_devices() -> list[dict]:
    """Get all devices from Nautobot with their primary IPs."""
    data = await graphql("""
    {
        devices {
            id
            name
            status { name }
            device_type { model manufacturer { name } }
            primary_ip4 { address }
            location { name }
            platform { name }
        }
    }
    """)
    if "error" in data:
        return [{"error": data["error"]}]
    return data.get("devices", [])


async def get_device(device_name: str) -> dict | None:
    """Get a single device by name. Returns None if not found."""
    data = await graphql("""
    query ($name: [String]) {
        devices(name: $name) {
            id name
            status { name }
            device_type { model manufacturer { name } }
            primary_ip4 { address }
        }
    }
    """, {"name": [device_name]})
    if "error" in data:
        return {"error": data["error"]}
    devices = data.get("devices", [])
    return devices[0] if devices else None


# ---------------------------------------------------------------------------
# Interface queries (GraphQL — full data in one call)
# ---------------------------------------------------------------------------

async def get_interfaces(device_name: str) -> list[dict]:
    """
    Get all interfaces for a device.
    Returns list of dicts with: id, name, enabled, type, description, mac_address, status.
    """
    data = await graphql("""
    query ($device: [String]) {
        interfaces(device: $device) {
            id
            name
            enabled
            type
            description
            mac_address
            status { name id }
            mode
            mtu
            lag { name }
            untagged_vlan { name vid }
        }
    }
    """, {"device": [device_name]})
    if "error" in data:
        return [{"error": data["error"]}]
    return data.get("interfaces", [])


async def get_interface_by_name(device_name: str, interface_name: str) -> dict | None:
    """Get a specific interface by device and interface name."""
    ifaces = await get_interfaces(device_name)
    if ifaces and "error" in ifaces[0]:
        return ifaces[0]
    for iface in ifaces:
        if iface.get("name") == interface_name:
            return iface
    return None


# ---------------------------------------------------------------------------
# IPAM queries
# ---------------------------------------------------------------------------

async def get_ip_addresses(prefix: str | None = None, device_name: str | None = None) -> list[dict]:
    """Get IP addresses, optionally filtered by prefix or device."""
    query = """
    query ($prefix: [String]) {
        ip_addresses(parent: $prefix) {
            address
            status { name }
            dns_name
            interfaces {
                name
                device { name }
            }
        }
    }
    """
    data = await graphql(query, {"prefix": prefix})
    if "error" in data:
        return [{"error": data["error"]}]
    return data.get("ip_addresses", [])


async def get_prefixes() -> list[dict]:
    """Get all IP prefixes from Nautobot IPAM."""
    data = await graphql("""
    {
        prefixes {
            id prefix
            status { name }
            vrfs { name }
            location { name }
            description
        }
    }
    """)
    if "error" in data:
        return [{"error": data["error"]}]
    return data.get("prefixes", [])


# ---------------------------------------------------------------------------
# Interface writes (REST — GraphQL is read-only in Nautobot)
# ---------------------------------------------------------------------------

async def create_interface(
    device_id: str,
    name: str,
    type_value: str = "1000base-t",
    enabled: bool = True,
    description: str = "",
    status: str = "active",
) -> dict:
    """
    Create an interface on a device.
    device_id: UUID of the device (from get_device result).
    type_value: REST slug e.g. "1000base-t", "10gbase-t", "other", "virtual", "lag".
    status: one of "active", "planned", "maintenance", "decommissioning", "failed".
    """
    try:
        payload = {
            "device": {"id": device_id},
            "name": name,
            "type": type_value,
            "enabled": enabled,
            "description": description,
            "status": {"id": STATUS_IDS.get(status, STATUS_IDS["active"])},
        }
        async with _client() as client:
            resp = await client.post(
                f"{settings.nautobot_url}/api/dcim/interfaces/",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


async def update_interface(interface_id: str, **fields) -> dict:
    """
    PATCH an interface. Supported fields: name, enabled, description, type, mtu.
    For status changes pass status="active" (will be converted to UUID).
    """
    try:
        payload = {}
        for k, v in fields.items():
            if k == "status":
                payload["status"] = {"id": STATUS_IDS.get(v, STATUS_IDS["active"])}
            else:
                payload[k] = v
        async with _client() as client:
            resp = await client.patch(
                f"{settings.nautobot_url}/api/dcim/interfaces/{interface_id}/",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}


async def set_interface_status(interface_id: str, status: str = "active") -> dict:
    """Set interface status. status: 'active', 'planned', 'maintenance', 'decommissioning', 'failed'."""
    return await update_interface(interface_id, status=status)
