# Phase 10: Collapse net-ops-team Into NetClaw

**Status:** Planned
**Depends on:** Phase 9 (convergence-mcp server)
**Goal:** Retire the net-ops-team container. All AI monitoring runs through NetClaw.

---

## Architecture After Migration

```
┌─────────────────────────────────────────────────────────────┐
│                    NetClaw (OpenClaw Gateway)                 │
│                                                              │
│  NEW MCP Servers (contributed to netclaw repo):              │
│    pfsense-mcp     — XML-RPC: DHCP, ARP, aliases, rules     │
│                                                              │
│  NEW Skills (contributed to netclaw repo):                   │
│    pfsense-firewall-ops    — pfSense management + analysis   │
│    synology-nas-monitor    — Synology SNMP health checks     │
│                                                              │
│  NEW Skills (Convergence-specific, in config/netclaw/):      │
│    convergence-noc-watch          — scheduled health monitor │
│    convergence-security-monitor   — threat hunting + blocking│
│    convergence-interface-reconciler — Nautobot ↔ switch sync │
│                                                              │
│  EXISTING MCP Servers (already working):                     │
│    grafana-mcp, prometheus-mcp, nautobot-mcp, batfish-mcp   │
│    convergence-mcp (Phase 9B — threat-intel + automation)    │
│                                                              │
│  EXISTING Skills (already working):                          │
│    grafana-observability, prometheus-monitoring, nautobot-sot │
│    pyats-health-check, pyats-security, pyats-network         │
│    nmap-network-scan, syslog-receiver                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        threat-intel  automation   convergence-scheduler
        (unchanged)   (unchanged)  (NEW — cron + Discord)
```

---

## What Gets Created

### 1. pfsense-mcp (NEW MCP Server → upstream netclaw repo)

**Why:** pfSense XML-RPC is used by the security expert (investigate_host), the interface reconciler (DHCP/ARP lookups), and the automation agent (block actions). No MCP server exists for pfSense anywhere.

**Source:** Port from `services/net-ops-team/app/tools/pfsense.py`

**Tools:**

| Tool | Description | Source |
|------|-------------|--------|
| `pfsense_get_dhcp_leases` | Active DHCP leases (IP, MAC, hostname) | pfsense.py `get_dhcp_leases()` |
| `pfsense_get_arp_table` | ARP table (IP → MAC mappings) | pfsense.py `get_arp_table()` |
| `pfsense_get_interfaces` | WAN/LAN/OPT interface status | New |
| `pfsense_get_firewall_aliases` | List firewall aliases and their contents | New |
| `pfsense_get_firewall_rules` | List firewall rules by interface | New |
| `pfsense_get_system_info` | Version, uptime, CPU, memory | New |
| `pfsense_get_gateway_status` | Gateway monitoring status | New |
| `pfsense_get_states` | Active connection state table | New |

**Transport:** stdio (FastMCP)
**Auth:** `PFSENSE_HOST`, `PFSENSE_USER`, `PFSENSE_PASS` env vars
**Read-only:** Yes — no write operations (blocking goes through automation-agent via convergence-mcp)

```
netclaw/mcp-servers/pfsense-mcp/
├── pfsense_mcp_server.py
├── requirements.txt
└── README.md
```

### 2. pfsense-firewall-ops (NEW Skill → upstream netclaw repo)

**Why:** Generic pfSense management skill usable by anyone running pfSense.

**Covers:**
- Firewall rule audit (what rules exist, are they ordered correctly)
- DHCP/ARP device identification (what device is at this IP/MAC)
- Gateway health monitoring
- Connection state analysis (top talkers, state table size)
- Interface status and traffic summary

**Uses:** pfsense-mcp + grafana-observability (for Loki syslog/filterlog queries)

```
netclaw/workspace/skills/pfsense-firewall-ops/SKILL.md
```

### 3. synology-nas-monitor (NEW Skill → upstream netclaw repo)

**Why:** Synology NAS SNMP monitoring is useful to anyone with Synology devices. No NetClaw skill exists for this.

**Source:** Port from `services/net-ops-team/app/team/nas_engineer.py`

**Covers:**
- System temperature monitoring (WARNING >45°C, CRITICAL >55°C)
- Power supply status
- Per-disk health and temperature
- RAID volume status (Normal/Degraded/Crashed)
- Storage utilization (Volume-level, not Storage Pool)
- Uptime monitoring

**Uses:** prometheus-mcp (PromQL queries against VictoriaMetrics)

**Key knowledge from NAS engineer that must be preserved:**
- Storage Pool showing 0 free bytes is NORMAL (capacity allocated to Volumes)
- Only Volume entries reflect actual user-available space
- Empty metric results = SNMP not configured, not a failure

```
netclaw/workspace/skills/synology-nas-monitor/SKILL.md
```

### 4. convergence-noc-watch (Convergence-specific Skill)

**Replaces:** NOC Officer + Network Engineer agents

**What it does:**
- Device reachability check (SNMP uptime metrics via prometheus-mcp)
- Interface utilization monitoring with thresholds (>70% WARNING, >90% CRITICAL)
- Interface error rate monitoring
- Firewall block rate baseline comparison
- Syslog critical event detection (via grafana-mcp Loki tools)

**Uses:** prometheus-mcp, grafana-observability, nautobot-sot, pfsense-mcp

**Key knowledge to preserve from NOC Officer + Network Engineer:**
- WS-C3850-48P combo uplinks: Gi1/1/x disabled when Te1/1/x active = normal
- Interface speeds: GigabitEthernet = 1G, TenGigabitEthernet = 10G
- Always lookup_port_description in Nautobot before reporting bandwidth findings
- Empty metric results ≠ outage, just metric not available

```
Convergence/config/netclaw/workspace/skills/convergence-noc-watch/SKILL.md
```

### 5. convergence-security-monitor (Convergence-specific Skill)

**Replaces:** Security Expert + Security Engineer agents

**What it does:**
- Firewall block rate and top blocked IP analysis
- Threat intel cross-reference (via convergence-mcp)
- NetFlow analysis for C2 beaconing, data exfiltration, lateral movement
- Internal host validation against Nautobot before flagging
- Automated block submission for confirmed threats (via convergence-mcp)
- NetClaw investigation for hosts needing deeper analysis (pyATS SSH)

**Uses:** grafana-observability (Loki), prometheus-mcp, convergence-mcp, nautobot-sot, pfsense-mcp, pyats-security

**Key knowledge to preserve:**
- ALWAYS check Nautobot before flagging internal hosts
- NAS devices talking to multiple VLANs = normal
- IoT devices on mDNS/AirPlay ports (5353, 7000, 7100) = normal
- Block /24 subnets when multiple IPs from same range, not individual /32s
- Max 3 block submissions per cycle
- Never block internal IPs (RFC1918)
- NetFlow attributes are OTLP JSON format with specific key paths

```
Convergence/config/netclaw/workspace/skills/convergence-security-monitor/SKILL.md
```

### 6. convergence-interface-reconciler (Convergence-specific Skill)

**Replaces:** Interface Reconciler agent

**What it does:**
- MAC address table collection (pyATS `show mac address-table dynamic`)
- DHCP/ARP correlation for device identification (pfsense-mcp)
- Port description enrichment: "VLAN{vid} | {hostname} | {ip}"
- Description write to switch (pyATS config) + Nautobot (nautobot-mcp or REST)
- Admin state sync: Nautobot enabled → switch shutdown/no shutdown
- Inventory diff: SNMP interfaces vs Nautobot interfaces

**Uses:** pyats-network, pyats-config-mgmt, nautobot-sot, pfsense-mcp, prometheus-mcp

**Key knowledge to preserve:**
- Description format: exactly "VLAN10 | hostname | 192.168.x.x"
- Don't overwrite trunk/uplink port descriptions
- Nautobot is authoritative for admin state
- Skip Null0, StackPort1, StackPort2 in inventory diff
- Don't touch Gi1/1/x if Te1/1/x active (combo uplinks)

```
Convergence/config/netclaw/workspace/skills/convergence-interface-reconciler/SKILL.md
```

### 7. convergence-scheduler (NEW lightweight service)

**Replaces:** net-ops-team `main.py` (APScheduler + Discord bot)

**What it does:**
- Runs on a cron schedule (every 10 minutes)
- Sends a prompt to NetClaw via the REST proxy: "Run convergence-noc-watch, convergence-security-monitor, and convergence-interface-reconciler"
- Parses the response for findings
- Posts WARNING/CRITICAL findings to Discord (with 30-min dedup)
- Posts hourly shift reports to Discord

**What it does NOT do:**
- No LLM calls — it's a scheduler, not an AI agent
- No tool definitions — NetClaw handles all tool use
- No system prompts — NetClaw's SOUL + skills handle reasoning

**This is ~100 lines of Python** — APScheduler + httpx to the REST proxy + Discord webhook.

```
Convergence/services/convergence-scheduler/
├── app/
│   ├── main.py          # FastAPI + APScheduler
│   ├── config.py        # Pydantic settings
│   └── discord.py       # Discord webhook posting
├── Dockerfile
└── requirements.txt
```

---

## What Gets Retired

| File/Module | Replacement |
|---|---|
| `services/net-ops-team/app/team/noc_officer.py` | convergence-noc-watch skill |
| `services/net-ops-team/app/team/network_engineer.py` | convergence-noc-watch skill |
| `services/net-ops-team/app/team/security_expert.py` | convergence-security-monitor skill |
| `services/net-ops-team/app/team/security_engineer.py` | convergence-security-monitor skill |
| `services/net-ops-team/app/team/nas_engineer.py` | synology-nas-monitor skill |
| `services/net-ops-team/app/team/interface_reconciler.py` | convergence-interface-reconciler skill |
| `services/net-ops-team/app/team/supervisor.py` | convergence-scheduler service |
| `services/net-ops-team/app/llm_client.py` | NetClaw's built-in LLM client |
| `services/net-ops-team/app/tools/victoriametrics.py` | prometheus-mcp |
| `services/net-ops-team/app/tools/loki.py` | grafana-mcp (Loki tools) |
| `services/net-ops-team/app/tools/nautobot.py` | nautobot-mcp |
| `services/net-ops-team/app/tools/switch_ssh.py` | pyATS skills |
| `services/net-ops-team/app/tools/pfsense.py` | pfsense-mcp |
| `services/net-ops-team/app/tools/netclaw.py` | Not needed (NetClaw IS the agent) |
| `services/net-ops-team/app/tools/discord_reporter.py` | convergence-scheduler discord.py |
| `mcp-servers/netclaw-proxy/` | Still needed for convergence-scheduler |

---

## What Stays Unchanged

| Component | Why |
|---|---|
| threat-intel service | Data pipeline, not an AI agent. Fetches IPs, calls APIs, computes scores. |
| automation-agent service | Execution engine with GAIT audit trail. Receives block requests, proposes actions, executes with approval. |
| convergence-mcp server | Bridge between NetClaw and Convergence services. Already built in Phase 9B. |
| netclaw-proxy | REST proxy for programmatic access from convergence-scheduler. |
| All infrastructure (OTEL, VM, Loki, Grafana, Redis) | Telemetry stack is unchanged. |

---

## Fork Strategy: Don't Fork

NetClaw is at `automateyournetwork/netclaw`. The correct approach:

**Contribute upstream (generic, useful to anyone):**
- `mcp-servers/pfsense-mcp/` — pfSense XML-RPC MCP server
- `workspace/skills/pfsense-firewall-ops/` — pfSense management skill
- `workspace/skills/synology-nas-monitor/` — Synology SNMP monitoring skill

**Keep in Convergence repo (deployment-specific):**
- `config/netclaw/workspace/skills/convergence-*` — skills that reference Convergence service URLs
- `mcp-servers/convergence-mcp/` — MCP server for Convergence-specific APIs
- `mcp-servers/netclaw-proxy/` — REST proxy sidecar
- `services/convergence-scheduler/` — cron + Discord notifications

**Why not fork:**
- Skills use env vars for deployment-specific values — the skill procedures are generic
- TOOLS.md holds deployment notes (device IPs, VLANs, etc.) — this is per-instance
- Forking means maintaining a divergent codebase and missing upstream updates
- The submodule pattern already supports this: netclaw/ is upstream, config/netclaw/ is local

---

## Implementation Order

### ~~Session 1: pfsense-mcp server~~ ✅ COMPLETE
1. Created `netclaw/mcp-servers/pfsense-mcp/pfsense_mcp_server.py`
2. Ported XML-RPC tools + added new tools (8 total)
3. Registered in openclaw.json via `openclaw mcp set`
4. Tested and working

### ~~Session 2: Skills (upstream)~~ ✅ COMPLETE
1. Wrote `pfsense-firewall-ops/SKILL.md`
2. Wrote `synology-nas-monitor/SKILL.md`
3. Tested via NetClaw chat

### ~~Session 3: Skills (Convergence-specific) + convergence-scheduler~~ ✅ COMPLETE
1. Wrote `convergence-noc-watch/SKILL.md` in `config/netclaw/workspace/skills/`
2. Wrote `convergence-security-monitor/SKILL.md` in `config/netclaw/workspace/skills/`
3. Wrote `convergence-interface-reconciler/SKILL.md` in `config/netclaw/workspace/skills/`
4. Built `services/convergence-scheduler/` — FastAPI + APScheduler + Discord webhook
5. Added to `docker-compose.yml` on port 8004
6. See `docs/PHASE10_SESSION2_3_STATUS.md` for details

### ~~Session 4: Cutover~~ ✅ COMPLETE
1. Stopped net-ops-team container
2. Started convergence-scheduler
3. Removed net-ops-team from docker-compose.yml and Docker images
4. Fixed REST proxy (`--json` hang, Popen kill-on-timeout)
5. Configured Ollama Cloud direct API (`openai-completions` provider, `https://ollama.com/v1`)
6. Removed broken fallback model, bumped timeouts to 900s
7. First successful poll cycle: 18 findings (CRITICAL: LAN down, threat level; WARNING: scanning, telnet exposure)

### Session 5: Upstream contribution
1. PR pfsense-mcp to automateyournetwork/netclaw
2. PR pfsense-firewall-ops skill
3. PR synology-nas-monitor skill
