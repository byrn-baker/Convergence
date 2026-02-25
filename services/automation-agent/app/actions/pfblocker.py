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

    for attempt_fn, label in [(_xmlrpc_delete, "xmlrpc"), (_ssh_delete, "ssh")]:
        try:
            attempt_result = await attempt_fn(action)
            if attempt_result.get("success"):
                result.update(attempt_result)
                logger.info(
                    "Rollback succeeded via %s: %s removed from %s",
                    label, action.value, action.target_list,
                )
                return result
        except NotImplementedError:
            pass
        except Exception as exc:
            logger.warning("Rollback %s attempt failed: %s", label, exc)

    result["message"] = (
        f"All rollback methods failed for {action.value}. "
        f"Manual: pfctl -t {action.target_list} -T delete {action.value}"
    )
    logger.error(
        "ROLLBACK FAILED for %s from '%s' — manual intervention required",
        action.value, action.target_list,
    )
    return result


# ---------------------------------------------------------------------------
# Integration — XML-RPC (primary) and SSH (fallback)
#
# Both functions require DRY_RUN=false and PFSENSE_HOST to be set.
# XML-RPC also requires PFSENSE_XMLRPC_PASS.
# SSH requires PFSENSE_SSH_KEY_PATH to be a readable private key file.
#
# pfBlockerNG custom list file path on pfSense:
#   /var/db/pfblockerng/custom/{list_name}.txt
# The list MUST already exist in pfBlockerNG > IP > IPv4 > Custom Lists.
# ---------------------------------------------------------------------------


async def _xmlrpc_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to pfBlockerNG via pfSense XML-RPC exec_php.

    Uses pfSense's built-in /xmlrpc.php endpoint with the exec_php method
    to append the CIDR to the custom list file and trigger a pfBlockerNG sync.
    The sync persists the block across pfBlockerNG reloads.

    Requirements:
        PFSENSE_HOST, PFSENSE_XMLRPC_USER, PFSENSE_XMLRPC_PASS must be set.
        SSL verification is controlled by PFSENSE_VERIFY_SSL (default False
        for self-signed certs common in home/SOHO pfSense installs).
    """
    import ssl
    import xmlrpc.client
    import asyncio

    if not settings.pfsense_xmlrpc_pass:
        raise ValueError(
            "PFSENSE_XMLRPC_PASS is not set. "
            "Set it in .env to enable XML-RPC integration."
        )

    # Build SSL context — self-signed certs are common on home pfSense installs
    ctx = ssl.create_default_context()
    if not settings.pfsense_verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    # XML-RPC URI includes basic auth credentials
    uri = (
        f"https://{settings.pfsense_xmlrpc_user}:{settings.pfsense_xmlrpc_pass}"
        f"@{settings.pfsense_host}/xmlrpc.php"
    )

    # PHP snippet: append CIDR to the custom list file then trigger pfB sync.
    # file_put_contents with FILE_APPEND | LOCK_EX is atomic on pfSense FreeBSD.
    # pfb_sync() queues a background reload that completes within ~30 seconds.
    list_path = f"/var/db/pfblockerng/custom/{action.target_list}.txt"
    php_code = (
        f'$f = "{list_path}"; '
        f'$line = "{action.value}\\n"; '
        # Avoid writing duplicates
        f'$existing = file_exists($f) ? file_get_contents($f) : ""; '
        f'if (strpos($existing, "{action.value}") === false) {{ '
        f'  file_put_contents($f, $line, FILE_APPEND | LOCK_EX); '
        f'}} '
        f'require_once("/usr/local/pkg/pfblockerng/pfblockerng.inc"); '
        f'pfblockerng_sync_cron();'
    )

    logger.info(
        "XML-RPC: connecting to %s as %s",
        settings.pfsense_host,
        settings.pfsense_xmlrpc_user,
    )

    # xmlrpc.client is synchronous — run in a thread to avoid blocking the event loop
    def _rpc_call() -> None:
        proxy = xmlrpc.client.ServerProxy(uri, context=ctx, allow_none=True)
        # pfsense.exec_php returns the PHP output (usually empty on success)
        result = proxy.pfsense.exec_php(php_code)
        return result

    try:
        rpc_result = await asyncio.get_event_loop().run_in_executor(None, _rpc_call)
        logger.info(
            "XML-RPC add succeeded for %s → %s (rpc_output=%r)",
            action.value,
            action.target_list,
            rpc_result,
        )
        return {
            "success": True,
            "method": "xmlrpc",
            "message": f"xmlrpc: appended {action.value} to {list_path} and triggered pfb_sync",
            "rollback_command": (
                f"php -r 'require_once(\"/usr/local/pkg/pfblockerng/pfblockerng.inc\"); "
                f"$f=\"{list_path}\"; "
                f"$c=file_get_contents($f); "
                f"file_put_contents($f, str_replace(\"{action.value}\\n\",\"\",$c));'"
            ),
        }
    except xmlrpc.client.Fault as exc:
        raise RuntimeError(f"XML-RPC fault {exc.faultCode}: {exc.faultString}") from exc
    except Exception as exc:
        raise RuntimeError(f"XML-RPC call failed: {exc}") from exc


async def _xmlrpc_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from pfBlockerNG via pfSense XML-RPC exec_php (rollback)."""
    import ssl
    import xmlrpc.client
    import asyncio

    if not settings.pfsense_xmlrpc_pass:
        raise ValueError("PFSENSE_XMLRPC_PASS is not set")

    ctx = ssl.create_default_context()
    if not settings.pfsense_verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    uri = (
        f"https://{settings.pfsense_xmlrpc_user}:{settings.pfsense_xmlrpc_pass}"
        f"@{settings.pfsense_host}/xmlrpc.php"
    )
    list_path = f"/var/db/pfblockerng/custom/{action.target_list}.txt"
    php_code = (
        f'$f = "{list_path}"; '
        f'if (file_exists($f)) {{ '
        f'  $c = file_get_contents($f); '
        f'  $c = str_replace("{action.value}\\n", "", $c); '
        f'  file_put_contents($f, $c, LOCK_EX); '
        f'}} '
        f'require_once("/usr/local/pkg/pfblockerng/pfblockerng.inc"); '
        f'pfblockerng_sync_cron();'
    )

    def _rpc_call() -> None:
        proxy = xmlrpc.client.ServerProxy(uri, context=ctx, allow_none=True)
        return proxy.pfsense.exec_php(php_code)

    await asyncio.get_event_loop().run_in_executor(None, _rpc_call)
    return {
        "success": True,
        "method": "xmlrpc",
        "message": f"xmlrpc: removed {action.value} from {list_path} and triggered pfb_sync",
    }


async def _ssh_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to pfSense via SSH using paramiko.

    Runs: pfctl -t {target_list} -T add {value}

    This adds to the **runtime pf table** immediately (< 1 second) but does
    NOT persist across pfBlockerNG reloads. Best for short-TTL emergency blocks.
    For persistent blocks, prefer the XML-RPC path which writes to the list file.

    Requirements:
        PFSENSE_SSH_HOST (or PFSENSE_HOST), PFSENSE_SSH_USER,
        PFSENSE_SSH_KEY_PATH (path to private key inside the container).
    """
    import asyncio

    import paramiko

    host = settings.pfsense_ssh_host or settings.pfsense_host
    key_path = settings.pfsense_ssh_key_path

    logger.info(
        "SSH: connecting to %s@%s (key=%s)",
        settings.pfsense_ssh_user,
        host,
        key_path,
    )

    def _ssh_exec() -> tuple[int, str, str]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            username=settings.pfsense_ssh_user,
            key_filename=key_path,
            timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )
        # Two commands: runtime pf table add + append to custom list file for persistence
        commands = [
            f"pfctl -t {action.target_list} -T add {action.value}",
            f"echo '{action.value}' >> /var/db/pfblockerng/custom/{action.target_list}.txt",
        ]
        outputs = []
        for cmd in commands:
            _stdin, stdout, stderr = client.exec_command(cmd)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            outputs.append((cmd, exit_code, out, err))
            if exit_code != 0:
                client.close()
                raise RuntimeError(
                    f"SSH command failed (exit={exit_code}): {cmd!r} — stderr: {err}"
                )
        client.close()
        return outputs

    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _ssh_exec)
        summary = "; ".join(f"'{r[0]}' exit={r[1]}" for r in results)
        logger.info("SSH add succeeded for %s → %s: %s", action.value, action.target_list, summary)
        return {
            "success": True,
            "method": "ssh",
            "message": f"ssh: pfctl add {action.value} to {action.target_list} — {summary}",
            "rollback_command": (
                f"pfctl -t {action.target_list} -T delete {action.value} && "
                f"sed -i '' '/{action.value.replace('.', r'\\.')}/d' "
                f"/var/db/pfblockerng/custom/{action.target_list}.txt"
            ),
        }
    except Exception as exc:
        raise RuntimeError(f"SSH execution failed: {exc}") from exc


async def _ssh_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from pfSense runtime pf table and list file via SSH (rollback)."""
    import asyncio
    import paramiko

    host = settings.pfsense_ssh_host or settings.pfsense_host

    def _ssh_exec() -> list:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            username=settings.pfsense_ssh_user,
            key_filename=settings.pfsense_ssh_key_path,
            timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )
        escaped = action.value.replace(".", r"\.").replace("/", r"\/")
        commands = [
            f"pfctl -t {action.target_list} -T delete {action.value}",
            f"sed -i '' '/{escaped}/d' /var/db/pfblockerng/custom/{action.target_list}.txt",
        ]
        results = []
        for cmd in commands:
            _stdin, stdout, stderr = client.exec_command(cmd)
            exit_code = stdout.channel.recv_exit_status()
            results.append((cmd, exit_code, stderr.read().decode().strip()))
        client.close()
        return results

    results = await asyncio.get_event_loop().run_in_executor(None, _ssh_exec)
    summary = "; ".join(f"exit={r[1]}" for r in results)
    return {
        "success": True,
        "method": "ssh",
        "message": f"ssh: removed {action.value} from {action.target_list} — {summary}",
    }
