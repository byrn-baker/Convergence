# Phase 7: Network Operations Team (NET-OPS)

**Last Updated:** 2026-04-04
**Status:** Complete — Full multi-agent NET-OPS team operational

### Changelog

| Date | Change |
|------|--------|
| 2026-04-03 | Phase 7 initiated. Fixed NetClaw docker-compose image name. Created missing `config/netclaw/` directory and `openclaw.json` gateway config. Drafted NET-OPS team architecture. |
| 2026-04-03 | Built `services/net-ops-team/` service: FastAPI + APScheduler, all 5 agents (Supervisor, NOC Officer, Network Engineer, Security Engineer, NAS Engineer), Interface Reconciler, Discord bot. |
| 2026-04-04 | Fixed OTEL Collector crash (netflow receiver invalid config). Added NetFlow v5 pipeline: pfSense → OTEL UDP 2055 → file → Promtail → Loki. Added `query_netflow` tool to security agents and NOC Officer. |
| 2026-04-04 | Replaced Grafana Discord alerts with agent-driven Discord reporting. INFO findings suppressed; CRITICAL/WARNING posted immediately + hourly shift reports with Grafana dashboard links. |
| 2026-04-04 | Fixed NAS SNMP: added `timeout: 10s` to SNMP receivers for NAT traversal. Fixed metric names (OTEL unit suffixes). Added Storage Pool vs Volume semantics to NAS Engineer. Fixed Synology NAS dashboard units/thresholds. |
| 2026-04-04 | Added Cisco WS-C3850-48P hardware knowledge to Network Engineer (combo uplink Gi1/1/1-4 / Te1/1/1-4 shared ports). Added bandwidth alert thresholds and port description lookup via Nautobot. |
| 2026-04-04 | Fixed pfSense PHP API compatibility: `system_get_dhcp_leases()` removed in pfSense+; replaced with direct ISC DHCP lease file read. `system_get_arp_table()` replaced with `exec('arp -an')`. |
| 2026-04-04 | Confirmed Nautobot DCIM writes working: Interface Reconciler writes descriptions via PATCH, creates missing interfaces. Nautobot populated with device enrichment (HDHR-10A70D51, etc.). |
| 2026-04-04 | Cleaned up repository: deleted unused `openclaw/` (461MB), `convergence/` Python CLI, `pyproject.toml`. Cleaned Makefile of dead poetry/pytest/mkdocs targets. |

---

## Executive Summary

Phase 7 replaces the single-agent NetClaw approach with a **hierarchical team of specialized AI
network engineers** — the **Network Operations Team (NET-OPS)** — built on the Claude Agent SDK
(Anthropic Python library's native agentic loop pattern).

The core insight: a single general-purpose agent trying to simultaneously watch NOC dashboards,
analyze SNMP data, parse firewall logs, and monitor NAS health produces shallow, unfocused output.
Real NOCs operate in tiers with specialists. The NET-OPS team mirrors that structure:

- An **L1 NOC Watch Officer** provides continuous situational awareness every 5 minutes.
- **L2/L3 specialist engineers** (Network, Security, NAS) run every poll cycle, bringing deep
  expertise and targeted tool access to their domain.
- An **Interface Reconciler** continuously audits Nautobot DCIM against live SNMP data, writing
  corrections automatically and flagging drift for human review.
- **NetClaw (CCIE Senior Network Architect)** remains as the L4 escalation endpoint for complex
  configuration changes, packet-level analysis, and full device access via pyATS.

The team posts CRITICAL and WARNING findings to Discord immediately, sends hourly shift reports,
and links to the relevant Grafana dashboard for each finding type. INFO findings are suppressed
from Discord — they're visible in Grafana only.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DISCORD (Human HQ)                          │
│     Shift reports • CRITICAL/WARNING alerts • Grafana links      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  net-ops-team  (port 8100)                       │
│              Python / Claude Agent SDK / FastAPI                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Supervisor                              │   │
│  │    Polls every 5min • Runs all agents in parallel        │   │
│  │    Composes shift reports • Routes to Discord            │   │
│  └───┬──────────┬──────────┬──────────┬─────────┬───────────┘   │
│      │          │          │          │         │               │
│      ▼          ▼          ▼          ▼         ▼               │
│  ┌───────┐ ┌────────┐ ┌────────┐ ┌───────┐ ┌──────────────┐   │
│  │  NOC  │ │Network │ │Security│ │  NAS  │ │  Interface   │   │
│  │Officer│ │Engineer│ │Engineer│ │Eng.   │ │  Reconciler  │   │
│  │ (L1)  │ │(L2/L3) │ │(L2/L3) │ │(L2/L3)│ │  (L2/L3)    │   │
│  └───────┘ └────────┘ └────────┘ └───────┘ └──────────────┘   │
│                                                                  │
│        Discord Bot (discord.py) — answers ad-hoc questions      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ Escalation (future)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              NetClaw  (port 18789 — OpenClaw Gateway)            │
│          CCIE Senior Network Architect  (L4)                     │
│    Full device config • pyATS • Packet analysis • Skill library  │
└─────────────────────────────────────────────────────────────────┘

              All agents read from shared data plane:

  ┌───────────────────┐  ┌─────────────────┐  ┌────────────────┐
  │  VictoriaMetrics  │  │      Loki       │  │    Nautobot    │
  │  SNMP metrics     │  │  syslog/netflow │  │  SoT / DCIM   │
  │  NetFlow stats    │  │  pfSense logs   │  │  (writes too)  │
  └───────────────────┘  └─────────────────┘  └────────────────┘
```

---

## What Was Built

### Service: `services/net-ops-team/`

```
services/net-ops-team/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py                  # FastAPI + APScheduler (5min polls, hourly reports)
    ├── config.py                # Pydantic settings
    ├── models.py                # Finding, ShiftReport, AgentRole, Severity
    ├── team/
    │   ├── supervisor.py        # Orchestrator — runs all agents, builds ShiftReport
    │   ├── noc_officer.py       # L1 NOC Watch Officer
    │   ├── network_engineer.py  # L2/L3 — switches, interfaces, utilization
    │   ├── security_expert.py   # L2/L3 — pfSense firewall, threat intel
    │   ├── security_engineer.py # L2/L3 — threat correlation, NetFlow hunting
    │   ├── nas_engineer.py      # L2/L3 — Synology NAS health
    │   ├── interface_reconciler.py  # Nautobot DCIM sync, port description enrichment
    │   └── discord_bot.py       # discord.py bot — answers ad-hoc questions
    └── tools/
        ├── victoriametrics.py   # PromQL instant + range query wrapper
        ├── loki.py              # LogQL + NetFlow query wrapper
        ├── pfsense.py           # XML-RPC exec_php (DHCP leases, ARP table)
        ├── nautobot.py          # GraphQL reads + REST writes (interface PATCH/POST)
        └── discord_reporter.py  # Shift reports + immediate CRITICAL/WARNING alerts
```

### Agents and Their Tools

#### NOC Watch Officer (L1)
Runs every poll cycle. Queries VictoriaMetrics (switch uptime, interface errors), Loki (syslog),
NetFlow (traffic anomalies). Reports CRITICAL/WARNING findings and INFO health summaries.

**Tools:** `query_metrics`, `query_logs`, `query_netflow`, `check_snmp_reachability`, `report_finding`

#### Network Engineer (L2/L3)
Checks interface utilization and error rates on both Cisco WS-C3850-48P switches.
Knows hardware specifics: Gi1/1/1-4 and Te1/1/1-4 are shared combo uplink ports — when SFP+
is active on Te1/1/x, the corresponding Gi1/1/x is automatically disabled by IOS (expected behavior, not a fault).
Only reports bandwidth findings when utilization exceeds thresholds (WARNING >70%, CRITICAL >90%).
Looks up Nautobot for port descriptions before reporting any bandwidth finding.

**Tools:** `query_metrics`, `query_logs`, `check_interface_utilization`, `check_snmp_reachability`,
`lookup_port_description`, `diagnose_snmp_failure`, `report_finding`

#### Security Expert (L2/L3)
Analyzes pfSense firewall logs for attack patterns, geo-sourced threats, sustained campaigns.
Uses NetFlow for threat hunting: port scans (one src → many dst ports), brute force (many flows
to port 22/3389/445), C2 beaconing (regular small flows at fixed intervals), exfiltration
(large outbound flows), and lateral movement (unexpected internal-to-internal flows).

**Tools:** `query_metrics`, `query_logs`, `query_netflow`, `report_finding`

#### Security Engineer (L2/L3)
Correlates threat intelligence from the `threat-intel` service with raw firewall events and
NetFlow data. Escalates high-confidence blocking recommendations to `automation-agent`.

**Tools:** `query_metrics`, `query_logs`, `query_netflow`, `report_finding`

#### NAS Engineer (L2/L3)
Monitors both Synology NAS devices (SynologyNAS01/02 at 192.168.100.22/23).

**Key knowledge:**
- OTEL appends unit suffixes: `nas_system_temperature_celsius`, `nas_disk_status_ratio`, etc.
- Storage Pool entries with `free=0` are **normal** — all capacity allocated to Volumes.
  Only `raid_name=~"Volume.*"` entries reflect actual user-available space.
- Checks: system temp (WARNING >45°C, CRITICAL >55°C), power status, per-disk status and temp,
  RAID volume status, volume free space.

**Tools:** `query_nas_metric`, `report_finding`

#### Interface Reconciler (L2/L3)
Runs every poll cycle. Compares SNMP-reported interfaces (from VictoriaMetrics) against
Nautobot inventory. **Auto-writes:**
- Creates missing interfaces in Nautobot (interfaces in SNMP not in Nautobot)
- Updates interface descriptions with DHCP/ARP enrichment:
  `Connected: mylaptop (192.168.3.42, aa:bb:cc:dd:ee:ff)`

**Reports as WARNING (no auto-write):**
- Interfaces in Nautobot not found via SNMP (possibly stale)
- `enabled`/`status` mismatches (requires human decision)

**Tools:** `get_snmp_interfaces`, `get_nautobot_interfaces`, `update_nautobot_interface`,
`create_nautobot_interface`, `get_dhcp_leases`, `get_arp_table`,
`update_nautobot_interface_description`, `report_finding`

#### Discord Bot
Runs alongside the poll cycle. Answers ad-hoc questions from Discord users by routing to the
appropriate agent's `answer_question()` method — each agent has full tool access to answer
arbitrary domain questions in real-time.

---

## NetFlow Pipeline

```
pfSense (Netflow v5, UDP)
    ↓ :2055
OTEL Collector (netflow receiver)
    ↓ file/netflow exporter
/data/netflow/netflow.jsonl
    ↓ Promtail tail
Loki {job="netflow", transport="tcp|udp", flow_type="netflow_v5"}
    ↓ LogQL
Security agents (query_netflow tool)
```

OTLP JSON attributes accessed as:
```
"attributes": [
  {"key": "source.address", "value": {"stringValue": "1.2.3.4"}},
  {"key": "destination.port", "value": {"intValue": 443}},
  {"key": "flow.io.bytes", "value": {"intValue": 1048576}}
]
```

---

## Discord Integration

### Immediate Alerts (per finding)
Posted for every CRITICAL or WARNING finding as it occurs. Embed includes:
- Severity + device in title
- Agent role + one-line summary
- Full details
- Link to the relevant Grafana dashboard

### Hourly Shift Reports
Suppresses INFO findings entirely. If all clear: posts "All systems healthy" with dashboard links.
If issues exist: groups findings by agent role, color-coded (🔴/🟡), with dashboard links.

### Dashboard Links by Role

| Agent | Dashboard |
|-------|-----------|
| Security Expert | pfSense Firewall Security |
| Security Engineer | Threat Analysis |
| Network Engineer | Interface Utilization |
| NOC Officer | Network Overview |
| NAS Engineer | NAS Health |
| Interface Reconciler | Network Device Health |

---

## NetClaw's Role in This Architecture

NetClaw is a specialized AI network engineering agent (CCIE-level) built on the OpenClaw framework.
It runs as a separate Docker service at port 18789 and exposes an OpenClaw Gateway API.

**Current use:** The NET-OPS team is wired to escalate to NetClaw for issues that require:
- Full device configuration access (via pyATS)
- Complex multi-step changes with GAIT audit trail
- Packet capture and protocol-level analysis
- Skill-based operations (100+ skills in `netclaw/workspace/skills/`)

**The `nautobot-dcim-reconcile` skill** in NetClaw's skill library served as the design reference
for the `interface_reconciler.py` agent. The background agent implements the reconciliation
autonomously; the skill provides a manual on-demand alternative accessible via Discord slash command.

**MISSION03 (BGP Mesh):** NetClaw also has in-development capability for BGP peering between
NetClaw instances via ngrok (OPEN-based peer identification, route exchange, mesh IXP model).
This is a future capability for cross-domain AI agent coordination — not yet wired into Convergence.

---

## Known Issues / Status

| # | Item | Status |
|---|------|--------|
| 1 | NetClaw L4 escalation endpoint (`netclaw.py`) | Implemented but not yet actively used — NET-OPS agents run independently |
| 2 | NetClaw testbed.yaml | Needs updating with actual device IPs and credentials |
| 3 | NetClaw MCP server credentials | Not yet configured in docker-compose.yml |
| 4 | NAUTOBOT_URL in NetClaw container | Verify `host.docker.internal:8000` is reachable |
| 5 | Interface Reconciler `enabled`/`status` writes | Reported but NOT auto-written — requires human decision |

---

## Journey Log

| Phase | Date | Milestone | Status |
|-------|------|-----------|--------|
| 1 | 2026-01 | SNMP monitoring — 2x Cisco switches + pfSense. OTel → VictoriaMetrics. Grafana dashboards. | Complete |
| 2 | 2026-01 | Syslog via Promtail → Loki. pfSense RFC 3164 parsing. Nautobot enrichment. | Complete |
| 3 | 2026-02 | Alertmanager + Discord notifications. LogQL Loki Ruler recording rules. | Complete |
| 4 | 2026-02 | Threat intelligence service. AbuseIPDB, GreyNoise, OTX, IPInfo. Composite scoring. AI narratives. | Complete |
| 5 | 2026-03 | Automation agent. GAIT audit trail. Discord bot. pfSense XML-RPC blocking. Redis rate limiter. | Complete |
| 6 | 2026-03 | Ollama LLM provider support. Dual-backend (Anthropic / Ollama). Qwen3 native API. | Complete |
| 7 | 2026-04 | Multi-agent NET-OPS team. NetFlow pipeline. NAS SNMP. Nautobot DCIM writes. Discord revamp. | **Complete** |
