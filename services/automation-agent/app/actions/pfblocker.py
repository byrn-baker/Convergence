"""pfBlockerNG / pfSense action executor.

Targets pfSense Plus 25.11. Three execution paths are tried in order;
the first to succeed wins. Unconfigured paths are skipped silently.

  Path A — REST API v2 (preferred when an API key is available):
    POST https://{pfsense_host}/api/v2/firewall/alias/entry
    Auth: Authorization: Bearer {api_key}
    Manages a firewall alias (PFSENSE_FIREWALL_ALIAS).
    Requires: PFSENSE_HOST + PFSENSE_API_KEY
    Setup:
      1. System > API > Keys — create a key, assign to admin user.
      2. Firewall > Aliases — create Host alias "AutoAgent_Block_v4".
      3. Firewall > Rules — add a block rule with Source = AutoAgent_Block_v4.

  Path B — XML-RPC exec_php (no API key required):
    POST https://{pfsense_host}/xmlrpc.php
    Appends the CIDR to a pfBlockerNG custom list file and triggers a sync.
    Requires: PFSENSE_HOST + PFSENSE_XMLRPC_PASS
    Setup:
      pfBlockerNG > IP > IPv4 Custom Lists — add list "pfBlockerNG_AutoAgent_v4".

  Path C — SSH pfctl (emergency fallback):
    Connects with paramiko and runs pfctl -T add.
    Runtime-only — does not survive a reboot or config reload.
    Requires: PFSENSE_HOST + PFSENSE_SSH_KEY_PATH

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

_XMLRPC_TIMEOUT = 30.0  # seconds — applied to all XML-RPC connections

# Serialises all XML-RPC alias writes so that concurrent approve-all calls
# don't race on the pfSense read-modify-write config cycle (last writer wins).
import asyncio as _asyncio
_xmlrpc_write_lock = _asyncio.Lock()


async def _xmlrpc_exec_php(php_code: str) -> str:
    """Run PHP on pfSense via XML-RPC exec_php; return the PHP echo output.

    On this pfSense version exec_php prepends any PHP echo/print output to
    the HTTP response body *before* the XML-RPC envelope, so xmlrpc.client
    cannot parse the response.  This function uses httpx directly:

      1. Sends a raw XML-RPC POST with HTTP Basic Auth (avoids '@' in URL).
      2. Splits PHP echo output from the XML-RPC envelope.
      3. Checks the envelope for fault codes.
      4. Returns the PHP echo output as a stripped string (may be "").

    Raises RuntimeError on HTTP error, auth failure, or XML-RPC fault.
    """
    import httpx
    from xml.etree import ElementTree as ET
    from xml.sax.saxutils import escape as xml_escape

    url = f"https://{settings.pfsense_host}/xmlrpc.php"
    xml_body = (
        '<?xml version="1.0"?>'
        '<methodCall>'
        '<methodName>pfsense.exec_php</methodName>'
        '<params><param>'
        f'<value><string>{xml_escape(php_code)}</string></value>'
        '</param></params>'
        '</methodCall>'
    )

    async with httpx.AsyncClient(
        verify=settings.pfsense_verify_ssl,
        timeout=_XMLRPC_TIMEOUT,
    ) as client:
        resp = await client.post(
            url,
            content=xml_body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            auth=(settings.pfsense_xmlrpc_user, settings.pfsense_xmlrpc_pass),
        )

    if resp.status_code == 401:
        raise RuntimeError(
            "Authentication failed — check PFSENSE_XMLRPC_USER / PFSENSE_XMLRPC_PASS"
        )
    if not resp.is_success:
        raise RuntimeError(
            f"HTTP {resp.status_code} from pfSense xmlrpc.php: {resp.text[:200]}"
        )

    body = resp.text

    # pfSense prepends PHP echo output before the XML-RPC envelope
    xml_start = body.find("<?xml")
    if xml_start < 0:
        raise RuntimeError(
            f"No XML-RPC response in pfSense reply: {body[:200]!r}"
        )

    echo_output = body[:xml_start].strip()
    xml_part = body[xml_start:]

    # Check for XML-RPC fault
    try:
        root = ET.fromstring(xml_part)
        if root.find(".//fault") is not None:
            code_val, msg_val = "?", "?"
            for member in root.findall(".//struct/member"):
                name = member.findtext("name", "")
                if name == "faultCode":
                    code_val = member.findtext("value/int", "?")
                elif name == "faultString":
                    msg_val = member.findtext("value/string", "?")
            raise RuntimeError(f"XML-RPC fault {code_val}: {msg_val}")
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid XML in pfSense response: {exc}") from exc

    return echo_output


# Default target list / alias name.
# XML-RPC "alias" mode  → must match a Firewall Alias (Firewall > Aliases).
# XML-RPC "pfblockerng" → must match a pfBlockerNG IPv4 Custom List name.
# Overridden at runtime by settings.pfsense_firewall_alias.
PFBLOCKER_CUSTOM_LIST = "AutoAgent_Block_v4"


@dataclass
class PfBlockerAction:
    """Structured, serialisable representation of a proposed pfSense action."""

    action_type: str        # "pfblocker_add" | "no_action"
    target_list: str        # alias name (REST API) or pfBlockerNG list name (XML-RPC/SSH)
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
    """Add an IP/CIDR to pfSense via REST API → XML-RPC → SSH (first success wins).

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
            "[DRY-RUN] Would add %s to '%s' on %s | reason: %s",
            action.value,
            action.target_list,
            host,
            action.reason,
        )
        result["success"] = True
        result["method"] = "dry_run"
        result["message"] = (
            f"DRY-RUN: would add {action.value} to '{action.target_list}' "
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

    # ---- Try each path in priority order --------------------------------
    for attempt_fn, label in [
        (_rest_api_add, "rest_api"),
        (_xmlrpc_add, "xmlrpc"),
        (_ssh_add, "ssh"),
    ]:
        try:
            attempt_result = await attempt_fn(action)
            if attempt_result.get("success"):
                result.update(attempt_result)
                result["method"] = label
                logger.info(
                    "pfSense action succeeded via %s: %s → %s",
                    label, action.value, action.target_list,
                )
                return result
            logger.warning(
                "%s attempt failed: %s — trying next method",
                label, attempt_result.get("message"),
            )
        except NotImplementedError:
            logger.debug("%s not configured; skipping", label)
        except Exception as exc:
            logger.warning("%s attempt raised: %s — trying next method", label, exc)

    result["message"] = (
        "All execution paths failed. Set PFSENSE_XMLRPC_PASS for XML-RPC, "
        "PFSENSE_API_KEY for REST API, or PFSENSE_SSH_KEY_PATH for SSH."
    )
    return result


async def setup_pfsense_prereqs() -> dict[str, Any]:
    """Create the firewall alias and WAN block rule in pfSense if they don't exist.

    Uses XML-RPC exec_php — same credentials as the alias mode.
    Idempotent: safe to call multiple times.

    Returns a dict with:
        success (bool), dry_run (bool), message (str),
        alias  ("created" | "exists" | "skipped"),
        rule   ("created" | "exists" | "skipped")
    """
    import json

    alias_name = settings.pfsense_firewall_alias
    result: dict[str, Any] = {
        "dry_run": settings.dry_run,
        "alias": "unknown",
        "rule": "unknown",
        "success": False,
        "message": "",
    }

    if settings.dry_run:
        result.update({"success": True, "alias": "skipped", "rule": "skipped"})
        result["message"] = (
            f"DRY_RUN=true — would create alias '{alias_name}' "
            f"and WAN block rule on {settings.pfsense_host or '(unconfigured)'}"
        )
        return result

    if not settings.pfsense_host:
        result["message"] = "PFSENSE_HOST not set — cannot run setup"
        return result

    if not settings.pfsense_xmlrpc_pass:
        result["message"] = "PFSENSE_XMLRPC_PASS not set — cannot run setup via XML-RPC"
        return result

    # Build PHP that creates alias + WAN block rule (idempotent)
    php_code = (
        'global $config; '
        'require_once("/etc/inc/functions.inc"); '
        'require_once("/etc/inc/filter.inc"); '
        f'$aname = "{alias_name}"; '
        '$status = ["alias" => "exists", "rule" => "exists"]; '
        # ---- alias ----
        '$aliases = function_exists("config_get_path") '
        '    ? config_get_path("aliases/alias", []) '
        '    : ($config["aliases"]["alias"] ?? []); '
        '$found = false; '
        'foreach ($aliases as $a) { if ($a["name"] === $aname) { $found = true; break; } } '
        'if (!$found) { '
        '    $na = ["name" => $aname, "type" => "host", "address" => "", '
        '           "detail" => "", "descr" => "AutoAgent managed block list"]; '
        '    $aliases[] = $na; '
        '    if (function_exists("config_set_path")) { '
        '        config_set_path("aliases/alias", $aliases); '
        '    } else { $config["aliases"]["alias"] = $aliases; } '
        '    $status["alias"] = "created"; '
        '} '
        # ---- WAN block rule ----
        '$rules = function_exists("config_get_path") '
        '    ? config_get_path("filter/rule", []) '
        '    : ($config["filter"]["rule"] ?? []); '
        '$rfound = false; '
        'foreach ($rules as $r) { '
        '    if (isset($r["source"]["address"]) && $r["source"]["address"] === $aname '
        '        && ($r["type"] ?? "") === "block") { $rfound = true; break; } '
        '} '
        'if (!$rfound) { '
        '    $ts = (string)time(); '
        '    $nr = ['
        '        "type" => "block", '
        '        "interface" => "wan", '
        '        "ipprotocol" => "inet", '
        '        "source" => ["address" => $aname], '
        '        "destination" => ["any" => ""], '
        '        "descr" => "Block AutoAgent threat IPs (Convergence auto-created)", '
        '        "tracker" => $ts, '
        '        "created" => ["time" => $ts, "username" => "convergence-autoagent"], '
        '    ]; '
        # Insert before the first WAN rule so it is evaluated first on WAN
        '    $insert = count($rules); '
        '    foreach ($rules as $i => $r) { if (($r["interface"] ?? "") === "wan") { $insert = $i; break; } } '
        '    array_splice($rules, $insert, 0, [$nr]); '
        '    if (function_exists("config_set_path")) { '
        '        config_set_path("filter/rule", $rules); '
        '    } else { $config["filter"]["rule"] = $rules; } '
        '    $status["rule"] = "created"; '
        '} '
        'if ($status["alias"] === "created" || $status["rule"] === "created") { '
        '    write_config("AutoAgent: bootstrap alias and block rule"); '
        '    filter_configure(); '
        '} '
        'echo json_encode($status);'
    )

    try:
        rpc_out = await _xmlrpc_exec_php(php_code)
        parsed: dict = json.loads(rpc_out) if rpc_out else {}
        result.update(parsed)
        result["success"] = True
        result["message"] = (
            f"Setup complete on {settings.pfsense_host} — "
            f"alias: {parsed.get('alias')}, rule: {parsed.get('rule')}"
        )
        logger.info(
            "pfSense prereq setup: alias=%s rule=%s on %s",
            parsed.get("alias"), parsed.get("rule"), settings.pfsense_host,
        )
    except json.JSONDecodeError:
        result["message"] = f"Unexpected (non-JSON) output from pfSense PHP: {rpc_out!r}"
        logger.error("pfSense setup: non-JSON output: %r", rpc_out)
    except Exception as exc:
        result["message"] = f"Setup failed: {exc}"
        logger.error("pfSense prereq setup failed: %s", exc)

    return result


async def rollback_pfblocker_add(action: PfBlockerAction) -> dict[str, Any]:
    """Remove an IP/CIDR from pfSense (undo a previous add).

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
            action.value, action.target_list,
        )
        result["success"] = True
        result["message"] = (
            f"DRY-RUN: would remove {action.value} from '{action.target_list}'"
        )
        return result

    if not settings.pfsense_host:
        result["message"] = "PFSENSE_HOST not configured; cannot rollback"
        return result

    for attempt_fn, label in [
        (_rest_api_delete, "rest_api"),
        (_xmlrpc_delete, "xmlrpc"),
        (_ssh_delete, "ssh"),
    ]:
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
        f"All rollback paths failed for {action.value}. "
        f"Manual: remove {action.value} from '{action.target_list}' in pfSense."
    )
    logger.error(
        "ROLLBACK FAILED for %s from '%s' — manual intervention required",
        action.value, action.target_list,
    )
    return result


# ---------------------------------------------------------------------------
# Path A — pfSense Plus REST API v2
# ---------------------------------------------------------------------------


def _check_api_response(resp: Any, operation: str) -> None:
    """Raise RuntimeError with the pfSense API error body if response is not 2xx."""
    if resp.is_success:
        return
    try:
        body = resp.json()
        msg = body.get("message") or body.get("code") or str(body)
    except Exception:
        msg = resp.text[:500]
    raise RuntimeError(
        f"pfSense API '{operation}' failed (HTTP {resp.status_code}): {msg}"
    )


async def _rest_api_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to a pfSense firewall alias via REST API v2."""
    import httpx

    if not settings.pfsense_api_key:
        raise NotImplementedError("PFSENSE_API_KEY not set; skipping REST API path")

    base = f"https://{settings.pfsense_host}/api/v2"
    headers = {
        "Authorization": f"Bearer {settings.pfsense_api_key}",
        "Content-Type": "application/json",
    }
    alias = settings.pfsense_firewall_alias

    logger.info(
        "REST API v2: adding %s to alias '%s' on %s",
        action.value, alias, settings.pfsense_host,
    )

    async with httpx.AsyncClient(verify=settings.pfsense_verify_ssl, timeout=30.0) as client:
        resp = await client.post(
            f"{base}/firewall/alias/entry",
            headers=headers,
            json={
                "name": alias,
                "address": action.value,
                "detail": action.reason[:255],
            },
        )
        _check_api_response(resp, f"add {action.value} to alias '{alias}'")

        apply_resp = await client.post(
            f"{base}/firewall/apply",
            headers=headers,
            json={},
        )
        _check_api_response(apply_resp, "apply firewall changes")

    logger.info("REST API v2: added %s to alias '%s' and applied", action.value, alias)
    return {
        "success": True,
        "method": "rest_api_v2",
        "message": (
            f"REST API v2: added {action.value} to alias '{alias}' "
            f"on {settings.pfsense_host} and applied"
        ),
        "rollback_command": (
            f"DELETE /api/v2/firewall/alias/entry "
            f"{{name: {alias}, address: {action.value}}}"
        ),
    }


async def _rest_api_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from a pfSense firewall alias via REST API v2 (rollback)."""
    import httpx

    if not settings.pfsense_api_key:
        raise NotImplementedError("PFSENSE_API_KEY not set; skipping REST API path")

    base = f"https://{settings.pfsense_host}/api/v2"
    headers = {
        "Authorization": f"Bearer {settings.pfsense_api_key}",
        "Content-Type": "application/json",
    }
    alias = settings.pfsense_firewall_alias

    async with httpx.AsyncClient(verify=settings.pfsense_verify_ssl, timeout=30.0) as client:
        resp = await client.delete(
            f"{base}/firewall/alias/entry",
            headers=headers,
            json={"name": alias, "address": action.value},
        )
        _check_api_response(resp, f"remove {action.value} from alias '{alias}'")

        apply_resp = await client.post(
            f"{base}/firewall/apply",
            headers=headers,
            json={},
        )
        _check_api_response(apply_resp, "apply firewall changes after delete")

    return {
        "success": True,
        "method": "rest_api_v2",
        "message": (
            f"REST API v2: removed {action.value} from alias '{alias}' "
            f"on {settings.pfsense_host} and applied"
        ),
    }


# ---------------------------------------------------------------------------
# Path B — XML-RPC exec_php
# ---------------------------------------------------------------------------


async def _xmlrpc_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to pfSense via XML-RPC exec_php.

    Sub-mode is controlled by settings.pfsense_xmlrpc_target:
      "alias"      — edits a plain Firewall Alias via pfSense PHP config API
                     (write_config + filter_configure).  Persistent, no pfBlockerNG needed.
      "pfblockerng" — appends to a pfBlockerNG IPv4 Custom List file and calls sync_cron.
    """
    if not settings.pfsense_xmlrpc_pass:
        raise NotImplementedError("PFSENSE_XMLRPC_PASS not set; skipping XML-RPC path")

    if settings.pfsense_xmlrpc_target == "alias":
        return await _xmlrpc_alias_add(action)
    return await _xmlrpc_pfblockerng_add(action)


async def _xmlrpc_alias_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to a pfSense Firewall Alias via XML-RPC exec_php.

    Uses pfSense's PHP config API (config_get_path / write_config / filter_configure)
    so the block is persistent and survives reboots without requiring pfBlockerNG.

    The alias must already exist under Firewall > Aliases (Type: Host).
    The block rule (Source = alias → Action = Block) must also be in place.
    """
    alias = action.target_list
    cidr = action.value
    reason = action.reason[:120].replace('"', '\\"').replace("'", "\\'")

    php_code = (
        'global $config; '
        'require_once("/etc/inc/functions.inc"); '
        'require_once("/etc/inc/filter.inc"); '
        f'$aname = "{alias}"; '
        f'$cidr  = "{cidr}"; '
        f'$note  = "{reason}"; '
        '$updated = false; '
        '$aliases = function_exists("config_get_path") '
        '    ? config_get_path("aliases/alias", []) '
        '    : ($config["aliases"]["alias"] ?? []); '
        'foreach ($aliases as $idx => &$a) { '
        '    if ($a["name"] !== $aname) continue; '
        '    $addrs = array_values(array_filter(preg_split(\'/\\s+/\', trim($a["address"] ?? "")))); '
        '    if (!in_array($cidr, $addrs)) { '
        '        $addrs[] = $cidr; '
        '        $a["address"] = implode(" ", $addrs); '
        '        $dets = explode("||", $a["detail"] ?? ""); '
        '        while (count($dets) < count($addrs) - 1) { $dets[] = ""; } '
        '        $dets[] = $note; '
        '        $a["detail"] = implode("||", $dets); '
        '    } '
        '    if (function_exists("config_set_path")) { config_set_path("aliases/alias/$idx", $a); } '
        '    else { $config["aliases"]["alias"][$idx] = $a; } '
        '    $updated = true; '
        '    break; '
        '} '
        'if ($updated) { write_config("AutoAgent: block $cidr"); filter_configure(); } '
        'echo $updated ? "ok" : "alias_not_found";'
    )

    logger.info("XML-RPC alias: adding %s to alias '%s' on %s", cidr, alias, settings.pfsense_host)
    async with _xmlrpc_write_lock:
        echo_out = await _xmlrpc_exec_php(php_code)

    if echo_out.strip() == "alias_not_found":
        raise RuntimeError(
            f"Alias '{alias}' not found in pfSense config. "
            "Run POST /api/automation/setup-pfsense to create it automatically."
        )
    logger.info("XML-RPC alias add succeeded for %s → '%s'", cidr, alias)
    return {
        "success": True,
        "method": "xmlrpc_alias",
        "message": f"xmlrpc alias: added {cidr} to alias '{alias}' and applied filter",
        "rollback_command": f"Remove {cidr} from Firewall > Aliases > {alias}",
    }


async def _xmlrpc_pfblockerng_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to a pfBlockerNG custom list via XML-RPC exec_php."""
    list_path = f"/var/db/pfblockerng/custom/{action.target_list}.txt"
    php_code = (
        f'$f = "{list_path}"; '
        f'$line = "{action.value}\\n"; '
        f'$existing = file_exists($f) ? file_get_contents($f) : ""; '
        f'if (strpos($existing, "{action.value}") === false) {{ '
        f'  file_put_contents($f, $line, FILE_APPEND | LOCK_EX); '
        f'}} '
        f'require_once("/usr/local/pkg/pfblockerng/pfblockerng.inc"); '
        f'pfblockerng_sync_cron();'
    )

    logger.info("XML-RPC pfblockerng: adding %s → %s", action.value, action.target_list)
    await _xmlrpc_exec_php(php_code)
    logger.info("XML-RPC pfblockerng add succeeded for %s → %s", action.value, action.target_list)
    return {
        "success": True,
        "method": "xmlrpc_pfblockerng",
        "message": (
            f"xmlrpc: appended {action.value} to {list_path} "
            f"and triggered pfblockerng_sync_cron"
        ),
        "rollback_command": (
            f"php -r 'require_once(\"/usr/local/pkg/pfblockerng/pfblockerng.inc\"); "
            f"$f=\"{list_path}\"; "
            f"$c=file_get_contents($f); "
            f"file_put_contents($f, str_replace(\"{action.value}\\n\",\"\",$c));'"
        ),
    }


async def _xmlrpc_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from pfSense via XML-RPC exec_php (rollback)."""
    if not settings.pfsense_xmlrpc_pass:
        raise NotImplementedError("PFSENSE_XMLRPC_PASS not set; skipping XML-RPC path")

    if settings.pfsense_xmlrpc_target == "alias":
        return await _xmlrpc_alias_delete(action)
    return await _xmlrpc_pfblockerng_delete(action)


async def _xmlrpc_alias_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from a pfSense Firewall Alias via XML-RPC exec_php (rollback)."""
    alias = action.target_list
    cidr = action.value

    php_code = (
        'global $config; '
        'require_once("/etc/inc/functions.inc"); '
        'require_once("/etc/inc/filter.inc"); '
        f'$aname = "{alias}"; '
        f'$cidr  = "{cidr}"; '
        '$aliases = function_exists("config_get_path") '
        '    ? config_get_path("aliases/alias", []) '
        '    : ($config["aliases"]["alias"] ?? []); '
        'foreach ($aliases as $idx => $a) { '
        '    if ($a["name"] !== $aname) continue; '
        '    $addrs = array_values(array_filter(preg_split(\'/\\s+/\', trim($a["address"] ?? "")))); '
        '    $dets  = array_values(explode("||", $a["detail"] ?? "")); '
        '    $na = []; $nd = []; '
        '    foreach ($addrs as $i => $addr) { '
        '        if (trim($addr) === $cidr) continue; '
        '        $na[] = $addr; '
        '        if (isset($dets[$i])) $nd[] = $dets[$i]; '
        '    } '
        '    $a["address"] = implode(" ", $na); '
        '    $a["detail"]  = implode("||", $nd); '
        '    if (function_exists("config_set_path")) { config_set_path("aliases/alias/$idx", $a); } '
        '    else { $config["aliases"]["alias"][$idx] = $a; } '
        '    break; '
        '} '
        'write_config("AutoAgent: unblock $cidr"); filter_configure();'
    )

    async with _xmlrpc_write_lock:
        await _xmlrpc_exec_php(php_code)
    return {
        "success": True,
        "method": "xmlrpc_alias",
        "message": f"xmlrpc alias: removed {cidr} from alias '{alias}' and applied filter",
    }


async def _xmlrpc_pfblockerng_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from a pfBlockerNG custom list via XML-RPC exec_php (rollback)."""
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

    await _xmlrpc_exec_php(php_code)
    return {
        "success": True,
        "method": "xmlrpc_pfblockerng",
        "message": (
            f"xmlrpc: removed {action.value} from {list_path} "
            f"and triggered pfblockerng_sync_cron"
        ),
    }


# ---------------------------------------------------------------------------
# Path C — SSH pfctl (emergency fallback)
# ---------------------------------------------------------------------------


async def _ssh_add(action: PfBlockerAction) -> dict[str, Any]:
    """Add IP/CIDR to a pfSense pf table via SSH (emergency fallback).

    Runtime-only — does not survive a reboot or pfSense config reload.
    """
    import asyncio
    import paramiko

    key_path = settings.pfsense_ssh_key_path
    if not key_path:
        raise NotImplementedError("PFSENSE_SSH_KEY_PATH not set; skipping SSH path")

    host = settings.pfsense_ssh_host or settings.pfsense_host

    logger.info(
        "SSH: connecting to %s@%s (key=%s)",
        settings.pfsense_ssh_user, host, key_path,
    )

    def _ssh_exec() -> int:
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
        cmd = f"pfctl -t {action.target_list} -T add {action.value}"
        _stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        err = stderr.read().decode().strip()
        client.close()
        if exit_code != 0:
            raise RuntimeError(
                f"SSH command failed (exit={exit_code}): {cmd!r} — stderr: {err}"
            )
        return exit_code

    try:
        exit_code = await asyncio.get_event_loop().run_in_executor(None, _ssh_exec)
        logger.info(
            "SSH add succeeded for %s → %s (exit=%s)",
            action.value, action.target_list, exit_code,
        )
        return {
            "success": True,
            "method": "ssh",
            "message": (
                f"ssh: pfctl -t {action.target_list} -T add {action.value} "
                f"(runtime only — does not survive reboot)"
            ),
            "rollback_command": (
                f"pfctl -t {action.target_list} -T delete {action.value}"
            ),
        }
    except Exception as exc:
        raise RuntimeError(f"SSH execution failed: {exc}") from exc


async def _ssh_delete(action: PfBlockerAction) -> dict[str, Any]:
    """Remove IP/CIDR from a pfSense pf table via SSH (rollback)."""
    import asyncio
    import paramiko

    key_path = settings.pfsense_ssh_key_path
    if not key_path:
        raise NotImplementedError("PFSENSE_SSH_KEY_PATH not set; skipping SSH path")

    host = settings.pfsense_ssh_host or settings.pfsense_host

    def _ssh_exec() -> int:
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
        cmd = f"pfctl -t {action.target_list} -T delete {action.value}"
        _stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        return exit_code

    exit_code = await asyncio.get_event_loop().run_in_executor(None, _ssh_exec)
    return {
        "success": True,
        "method": "ssh",
        "message": (
            f"ssh: pfctl -t {action.target_list} -T delete {action.value} "
            f"(exit={exit_code})"
        ),
    }
