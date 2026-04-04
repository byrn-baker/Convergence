"""
SSH tool for pushing configuration to Cisco IOS-XE switches.

Uses netmiko in a thread executor so it doesn't block the asyncio event loop.
Supports:
  - Reading MAC address table and interface status (for enrichment)
  - Writing interface descriptions (to both switch and Nautobot)
  - Writing interface admin state (shutdown / no shutdown)

MAC address format from IOS: aabb.ccdd.eeff (dot-notation)
Normalized to: aa:bb:cc:dd:ee:ff (colon-notation, lowercase) for DHCP lookup.
Interface name expansion: Gi1/0/1 → GigabitEthernet1/0/1
"""
import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

# Thread pool for synchronous netmiko calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="switch_ssh")

# Abbreviated → full interface name prefixes
_IOS_IFACE_EXPAND = [
    ("tengigabitethernet", "TenGigabitEthernet"),
    ("gigabitethernet", "GigabitEthernet"),
    ("fastethernet", "FastEthernet"),
    ("port-channel", "Port-channel"),
    ("vlan", "Vlan"),
    ("loopback", "Loopback"),
    ("tunnel", "Tunnel"),
    ("te", "TenGigabitEthernet"),
    ("gi", "GigabitEthernet"),
    ("fa", "FastEthernet"),
    ("po", "Port-channel"),
    ("vl", "Vlan"),
    ("lo", "Loopback"),
    ("tu", "Tunnel"),
]


def _expand_iface(abbrev: str) -> str:
    """Expand a Cisco abbreviated interface name to the full form."""
    lower = abbrev.lower().strip()
    for short, full in _IOS_IFACE_EXPAND:
        if lower.startswith(short):
            rest = abbrev[len(short):]
            return f"{full}{rest}"
    return abbrev


def _normalize_mac(ios_mac: str) -> str:
    """Convert IOS dot-notation MAC (aabb.ccdd.eeff) to colon-notation (aa:bb:cc:dd:ee:ff)."""
    cleaned = ios_mac.replace(".", "").replace(":", "").lower()
    if len(cleaned) != 12:
        return ios_mac.lower()
    return ":".join(cleaned[i:i+2] for i in range(0, 12, 2))


def _connect(ip: str):
    """Create a netmiko ConnectHandler. Called in thread executor."""
    try:
        from netmiko import ConnectHandler
    except ImportError:
        raise RuntimeError("netmiko is not installed — add it to requirements.txt")

    conn_params = {
        "device_type": "cisco_ios",
        "host": ip,
        "username": settings.switch_ssh_user,
        "password": settings.switch_ssh_pass,
        "timeout": 15,
        "session_timeout": 30,
        "fast_cli": True,
    }
    if settings.switch_ssh_enable_pass:
        conn_params["secret"] = settings.switch_ssh_enable_pass

    conn = ConnectHandler(**conn_params)
    if settings.switch_ssh_enable_pass:
        conn.enable()
    return conn


def _get_mac_table_sync(ip: str) -> list[dict]:
    """
    Run `show mac address-table dynamic` and parse results.
    Returns list of {vlan, mac, port} where mac is colon-notation and port is full name.
    """
    try:
        conn = _connect(ip)
        output = conn.send_command("show mac address-table dynamic")
        conn.disconnect()
    except Exception as e:
        logger.warning("SSH mac-table failed for %s: %s", ip, e)
        return [{"error": str(e)}]

    entries = []
    # Line format: "  10    aabb.ccdd.eeff    DYNAMIC     Gi1/0/1"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit():
            try:
                vlan = int(parts[0])
                mac = _normalize_mac(parts[1])
                port = _expand_iface(parts[3])
                entries.append({"vlan": vlan, "mac": mac, "port": port})
            except (ValueError, IndexError):
                continue
    return entries


def _get_interface_status_sync(ip: str) -> dict[str, dict]:
    """
    Run `show interfaces status` and parse results.
    Returns {full_interface_name: {vlan, status, connected, admin_up}}
    status values from IOS: connected, notconnect, disabled, err-disabled, sfpAbsent
    admin_up: True unless status == "disabled"
    """
    try:
        conn = _connect(ip)
        output = conn.send_command("show interfaces status")
        conn.disconnect()
    except Exception as e:
        logger.warning("SSH interface-status failed for %s: %s", ip, e)
        return {"error": str(e)}

    result = {}
    # Header: Port  Name  Status  Vlan  Duplex  Speed  Type
    # Skip header lines (contain "Port" or dashes)
    for line in output.splitlines():
        if not line or line.startswith(" ") and "Port" in line:
            continue
        # Detect data lines: start with abbreviated port name
        m = re.match(
            r"^(\S+)\s+(.*?)\s+(connected|notconnect|disabled|err-disabled|sfpAbsent|monitoring|faulty)\s+(\S+)\s+",
            line,
        )
        if m:
            port_abbrev = m.group(1)
            status = m.group(3)
            vlan_raw = m.group(4)
            full_name = _expand_iface(port_abbrev)
            # vlan_raw could be a number, "trunk", "routed", etc.
            vlan = None
            if vlan_raw.isdigit():
                vlan = int(vlan_raw)
            result[full_name] = {
                "vlan": vlan,
                "status": status,
                "connected": status == "connected",
                "admin_up": status != "disabled",
            }
    return result


def _push_description_sync(ip: str, interface_name: str, description: str) -> dict:
    """Push `interface description` to a single switch port and write to NVRAM."""
    try:
        conn = _connect(ip)
        commands = [
            f"interface {interface_name}",
            f" description {description}",
        ]
        conn.send_config_set(commands)
        conn.save_config()
        conn.disconnect()
        return {"ok": True, "interface": interface_name, "description": description}
    except Exception as e:
        logger.error("SSH push_description failed for %s %s: %s", ip, interface_name, e)
        return {"error": str(e)}


def _push_admin_state_sync(ip: str, interface_name: str, enabled: bool) -> dict:
    """Push shutdown or no shutdown to a switch port and write to NVRAM."""
    try:
        conn = _connect(ip)
        commands = [
            f"interface {interface_name}",
            " no shutdown" if enabled else " shutdown",
        ]
        conn.send_config_set(commands)
        conn.save_config()
        conn.disconnect()
        action = "no shutdown" if enabled else "shutdown"
        return {"ok": True, "interface": interface_name, "action": action}
    except Exception as e:
        logger.error("SSH push_admin_state failed for %s %s: %s", ip, interface_name, e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Async wrappers (run sync netmiko in thread pool)
# ---------------------------------------------------------------------------

async def get_mac_address_table(ip: str) -> list[dict]:
    """Async: run `show mac address-table dynamic` and return parsed entries."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _get_mac_table_sync, ip)


async def get_interface_status(ip: str) -> dict[str, dict]:
    """Async: run `show interfaces status` and return {interface: {vlan, status, admin_up}}."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _get_interface_status_sync, ip)


async def push_interface_description(ip: str, interface_name: str, description: str) -> dict:
    """Async: push interface description to switch and write to NVRAM."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, _push_description_sync, ip, interface_name, description
    )


async def push_interface_admin_state(ip: str, interface_name: str, enabled: bool) -> dict:
    """Async: push shutdown/no shutdown to switch and write to NVRAM."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, _push_admin_state_sync, ip, interface_name, enabled
    )
