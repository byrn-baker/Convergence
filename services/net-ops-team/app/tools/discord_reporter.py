import httpx

from ..models import AgentRole, Finding, Severity, ShiftReport

# Grafana dashboard links per agent role and finding type.
# Keys match AgentRole values. Used to add "View Dashboard" links to alerts.
_DASHBOARD_LINKS = {
    AgentRole.SECURITY_EXPERT.value: ("pfSense Firewall Security", "d/pfsense-firewall-security"),
    AgentRole.SECURITY_ENGINEER.value: ("Threat Analysis", "d/security-threat-analysis"),
    AgentRole.NETWORK_ENGINEER.value: ("Interface Utilization", "d/convergence-interface-utilization"),
    AgentRole.NOC_OFFICER.value: ("Network Overview", "d/convergence-network-overview"),
    AgentRole.NAS_ENGINEER.value: ("NAS Health", "d/convergence-nas-health"),
    AgentRole.INTERFACE_RECONCILER.value: ("Network Device Health", "d/net-device-health"),
}

_GRAFANA_BASE = "http://localhost:3000"


def _dashboard_url(role_value: str) -> str | None:
    link = _DASHBOARD_LINKS.get(role_value)
    if not link:
        return None
    _, path = link
    return f"{_GRAFANA_BASE}/{path}"


def _dashboard_label(role_value: str) -> str:
    link = _DASHBOARD_LINKS.get(role_value)
    return link[0] if link else "Dashboard"


def _report_color(report: ShiftReport) -> int:
    if report.escalations > 0:
        return 0xe74c3c  # red
    if report.open_issues > 0:
        return 0xf1c40f  # yellow
    return 0x2ecc71  # green


def _finding_color(finding: Finding) -> int:
    if finding.severity == Severity.CRITICAL:
        return 0xe74c3c
    if finding.severity == Severity.WARNING:
        return 0xf1c40f
    return 0x2ecc71


async def post_shift_report(report: ShiftReport, webhook_url: str) -> bool:
    """Post an hourly shift report to Discord.

    Only CRITICAL and WARNING findings are shown — INFO findings are suppressed.
    If everything is healthy, posts a brief all-clear with dashboard links.
    """
    if not webhook_url:
        return False

    actionable = [f for f in report.findings if f.severity != Severity.INFO]
    criticals = [f for f in actionable if f.severity == Severity.CRITICAL]
    warnings = [f for f in actionable if f.severity == Severity.WARNING]

    fields = []

    if not actionable:
        fields.append({
            "name": "Status",
            "value": "All systems healthy — no issues detected this cycle.",
            "inline": False,
        })
    else:
        # Group by role, show only CRITICAL + WARNING
        grouped: dict[str, list[Finding]] = {}
        for f in actionable:
            grouped.setdefault(f.role.value, []).append(f)

        for role, role_findings in grouped.items():
            role_crits = [f for f in role_findings if f.severity == Severity.CRITICAL]
            role_warns = [f for f in role_findings if f.severity == Severity.WARNING]
            label = role.replace("_", " ").title()

            lines = []
            for f in role_crits:
                lines.append(f"🔴 **{f.device}**: {f.summary}")
            for f in role_warns:
                lines.append(f"🟡 **{f.device}**: {f.summary}")

            url = _dashboard_url(role)
            if url:
                dash = _dashboard_label(role)
                lines.append(f"[→ {dash}]({url})")

            fields.append({
                "name": label,
                "value": "\n".join(lines)[:1024],
                "inline": False,
            })

    # Dashboard quick-links footer field
    dash_links = " | ".join(
        f"[{label}]({_GRAFANA_BASE}/{path})"
        for label, path in _DASHBOARD_LINKS.values()
    )
    fields.append({"name": "Dashboards", "value": dash_links[:1024], "inline": False})

    description = (
        f"**Escalations:** {report.escalations} | "
        f"**Warnings:** {len(warnings)} | "
        f"**INFO suppressed** (use Grafana for full details)"
    )

    embed = {
        "title": "🏢 NET-OPS SHIFT REPORT",
        "color": _report_color(report),
        "description": description,
        "fields": fields,
        "footer": {"text": "Convergence · Agents monitoring · Grafana for visualization"},
        "timestamp": report.timestamp.isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"embeds": [embed]})
            return resp.status_code in (200, 204)
    except Exception:
        return False


async def post_alert(finding: Finding, webhook_url: str) -> bool:
    """Post an immediate CRITICAL or WARNING alert to Discord.

    Includes a link to the relevant Grafana dashboard.
    """
    if not webhook_url:
        return False

    icon = "🔴" if finding.severity == Severity.CRITICAL else "🟡"
    url = _dashboard_url(finding.role.value)
    dash_label = _dashboard_label(finding.role.value)

    fields = [
        {"name": "Agent", "value": finding.role.value.replace("_", " ").title(), "inline": True},
        {"name": "Device", "value": finding.device, "inline": True},
        {"name": "Details", "value": finding.details[:1024], "inline": False},
    ]
    if url:
        fields.append({"name": "Dashboard", "value": f"[{dash_label}]({url})", "inline": False})

    embed = {
        "title": f"{icon} {finding.severity.value} — {finding.device}",
        "color": _finding_color(finding),
        "description": finding.summary,
        "fields": fields,
        "footer": {"text": "Convergence NET-OPS Team"},
        "timestamp": finding.timestamp.isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"embeds": [embed]})
            return resp.status_code in (200, 204)
    except Exception:
        return False
