"""pfBlockerNG / pfSense action executor.

Current state: STUB with DRY_RUN=true default.

The two integration paths are wired up as clearly-marked TODO blocks so the
next iteration can drop in real credentials without restructuring the code:

  Path A — XML-RPC (preferred):
    POST https://{pfsense_host}/xmlrpc.php
    Uses pfSense's built-in fauxapi / exec_php RPC to append an IP/CIDR to a
    pfBlockerNG custom list file and trigger a pfB sync.

  Path B — SSH fallback:
    Connects with paramiko and runs:
      pfctl -t {table} -T add {cidr}
    This adds to a runtime pf table immediately but does NOT persist across
    pfBlockerNG reloads. Good for short-TTL emergency blocks; pair with a
    scheduled pfB CRON to clean up.

Safety guarantees:
  - DRY_RUN=true (default) → log only, return success=True, never touch pfSense.
  - pfsense_host empty       → refuse to execute even if DRY_RUN=false.
  - rollback_pfblocker_add() mirrors execute_pfblocker_add() for the undo path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Name of the pfBlockerNG custom IPv4 list that the agent manages.
# This list must already exist in pfBlockerNG > IP > IPv4 Custom Lists.
PFBLOCKER_CUSTOM_LIST = "pfBlockerNG_AutoAgent_v4"


@dataclass
class PfBlockerAction:
    """Structured, serialisable representation of a proposed pfSense action."""

    action_type: str        # "pfblocker_add" | "no_action"
    target_list: str        # pfBlockerNG custom list name
    value: str              # CIDR, e.g. "1.2.3.4/32"
    reason: str             # Human-readable rationale from Claude
    duration_hours: int = 24
    proposed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.action_type,
            "target_list": self.target_list,
            "value": self.value,
            "reason": self.reason,
            "duration_hours": self.duration_hours,
            "proposed_at": self.proposed_at,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_pfblocker_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add an IP/CIDR to a pfBlockerNG custom list on the pfSense firewall.

    Returns a result dict with keys:
        success (bool), method (str), message (str),
        dry_run (bool), rollback_command (str | None)
    """
    result: dict[str, Any] = {
        "action": action.to_dict(),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": settings.dry_run,
        "success": False,
        "method": None,
        "message": "",
        "rollback_command": None,
    }

    # ---- DRY-RUN -------------------------------------------------------
    if settings.dry_run:
        host = settings.pfsense_host or "pfsense-unconfigured"
        logger.info(
            "[DRY-RUN] Would add %s to list '%s' on %s | reason: %s",
            action.value,
            action.target_list,
            host,
            action.reason,
        )
        result["success"] = True
        result["method"] = "dry_run"
        result["message"] = (
            f"DRY-RUN: pfctl -t {action.target_list} -T add {action.value} "
            f"on {host} (TTL={action.duration_hours}h)"
        )
        result["rollback_command"] = (
            f"pfctl -t {action.target_list} -T delete {action.value}"
        )
        return result

    # ---- LIVE execution guard ------------------------------------------
    if not settings.pfsense_host:
        result["message"] = (
            "PFSENSE_HOST is not configured. Set it in .env to enable live actions."
        )
        logger.error("pfSense host not configured; refusing live execution")
        return result

    # ---- Try XML-RPC first, SSH as fallback ----------------------------
    for attempt_fn, label in [(_xmlrpc_add, "xmlrpc"), (_ssh_add, "ssh")]:
        try:
            attempt_result = await attempt_fn(action)
            if attempt_result.get("success"):
                result.update(attempt_result)
                result["method"] = label
                logger.info(
                    "pfSense action succeeded via %s: %s → %s",
                    label,
                    action.value,
                    action.target_list,
                )
                return result
            logger.warning(
                "%s attempt failed: %s — trying next method",
                label,
                attempt_result.get("message"),
            )
        except NotImplementedError:
            logger.debug("%s not yet implemented; skipping", label)
        except Exception as exc:
            logger.warning("%s attempt raised: %s — trying next method", label, exc)

    result["message"] = (
        "All execution methods failed. See logs. "
        "Implement _xmlrpc_add() or _ssh_add() in pfblocker.py."
    )
    return result


async def rollback_pfblocker_add(action: PfBlockerAction) -> dict[str, Any]:
    """Remove an IP/CIDR from a pfBlockerNG custom list (undo a previous add).

    Mirrors execute_pfblocker_add() exactly — same DRY_RUN and host guards.
    """
    result: dict[str, Any] = {
        "action": action.to_dict(),
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": settings.dry_run,
        "success": False,
        "message": "",
    }

    if settings.dry_run:
        logger.info(
            "[DRY-RUN] Would rollback %s from '%s'",
            action.value,
            action.target_list,
        )
        result["success"] = True
        result["message"] = (
            f"DRY-RUN: Would run pfctl -t {action.target_list} "
            f"-T delete {action.value}"
        )
        return result

    if not settings.pfsense_host:
        result["message"] = "PFSENSE_HOST not configured; cannot rollback"
        return result

    # TODO: implement live rollback via XML-RPC / SSH (mirror of execute)
    result["message"] = (
        "Live rollback not yet implemented. "
        f"Manual step: pfctl -t {action.target_list} -T delete {action.value}"
    )
    logger.warning(
        "ROLLBACK NEEDED for %s from list '%s' — implement manually",
        action.value,
        action.target_list,
    )
    return result


# ---------------------------------------------------------------------------
# Integration stubs (replace with real code when credentials are available)
# ---------------------------------------------------------------------------


async def _xmlrpc_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP via pfSense XML-RPC exec_php.

    TODO — replace the NotImplementedError body with:

        import xmlrpc.client, ssl
        ctx = ssl.create_default_context()
        if not settings.pfsense_verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        proxy = xmlrpc.client.ServerProxy(
            f"https://{settings.pfsense_xmlrpc_user}:{settings.pfsense_xmlrpc_pass}"
            f"@{settings.pfsense_host}/xmlrpc.php",
            context=ctx,
        )
        # Append IP to custom list file and trigger pfB reload
        php = (
            f'$f = "/var/db/pfblockerng/custom/{action.target_list}.txt"; '
            f'file_put_contents($f, "{action.value}\\n", FILE_APPEND | LOCK_EX); '
            f'require_once("/usr/local/pkg/pfblockerng/pfblockerng.inc"); '
            f'pfb_sync();'
        )
        proxy.pfsense.exec_php(php)
        return {"success": True, "message": f"xmlrpc: added {action.value}"}
    """
    raise NotImplementedError("XML-RPC integration not yet implemented")


async def _ssh_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP via pfSense SSH using paramiko.

    TODO — replace the NotImplementedError body with:

        import paramiko
        host = settings.pfsense_ssh_host or settings.pfsense_host
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            username=settings.pfsense_ssh_user,
            key_filename=settings.pfsense_ssh_key_path,
            timeout=15,
        )
        cmd = f"pfctl -t {action.target_list} -T add {action.value}"
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        if exit_code != 0:
            raise RuntimeError(stderr.read().decode())
        return {"success": True, "message": f"ssh: pfctl add {action.value} exit={exit_code}"}
    """
    raise NotImplementedError("SSH integration not yet implemented")
