# Project Restructure: NetClaw-First Architecture

**Date:** 2026-04-05
**Decision:** NetClaw is the primary project. Convergence becomes the infrastructure deployment that NetClaw operates.

---

## Why NetClaw-First

NetClaw was designed as a standalone network engineering workstation with:
- Its own install process (`install.sh` — 53 steps)
- Its own config directory (`~/.openclaw/`)
- Its own workspace (`~/.openclaw/workspace/skills/`)
- Its own device inventory (`testbed/testbed.yaml`)
- Its own deployment notes (`TOOLS.md`)
- 36 MCP servers, 124 skills, pyATS, GAIT, SOUL

Convergence tried to stuff all of this into a Docker container as a submodule. The result:
- `install.sh` fails silently (`|| true`)
- `openclaw onboard` never runs
- 34 of 36 MCP servers are unregistered
- The testbed points to sandbox devices
- We rebuilt capabilities NetClaw already had

The correct model: NetClaw runs as the AI brain. Convergence provides the telemetry infrastructure that NetClaw monitors.

---

## New Repository Structure

```
/home/ubuntu/netclaw/                    # NetClaw — the primary project (existing repo)
├── mcp-servers/                         # 36+ MCP servers (including new pfsense-mcp)
├── workspace/skills/                    # 124+ skills (including new Convergence skills)
├── testbed/testbed.yaml                 # pyATS device inventory (YOUR devices)
├── config/openclaw.json                 # MCP server definitions (submodule default)
├── SOUL.md, TOOLS.md, IDENTITY.md       # Agent personality + deployment notes
├── scripts/install.sh                   # Full installation (53 steps)
└── ...

/home/ubuntu/Convergence/                # Convergence — infrastructure deployment
├── docker-compose.yml                   # Telemetry stack + data services ONLY
├── config/
│   ├── otel-collector/                  # SNMP, syslog, NetFlow ingestion
│   ├── victoriametrics/                 # Prometheus scrape config
│   ├── grafana/provisioning/            # Datasources, dashboard provisioning
│   ├── loki/                            # Log aggregation config
│   ├── promtail/                        # Log shipping pipeline
│   └── alertmanager/                    # Alert routing
├── dashboards/                          # 9 Grafana dashboard JSON files
├── services/
│   ├── threat-intel/                    # IP enrichment pipeline (stays)
│   ├── automation-agent/                # pfSense blocking engine (stays)
│   └── convergence-scheduler/           # NEW: cron + Discord (replaces net-ops-team)
├── data/                                # GeoIP, OTEL exports
├── scripts/                             # Setup scripts
├── Makefile                             # Stack management
└── .env                                 # All credentials

~/.openclaw/                             # NetClaw runtime config (managed by openclaw CLI)
├── openclaw.json                        # Gateway config + registered MCP servers
├── workspace/                           # → symlink or copy from netclaw/workspace
│   └── skills/
│       ├── (124 upstream skills)
│       ├── convergence-noc-watch/       # Convergence-specific
│       ├── convergence-security-monitor/
│       └── convergence-interface-reconciler/
├── agents/main/                         # Agent sessions
├── identity/                            # Device pairing keys
└── devices/                             # Paired devices
```

---

## What Changes

### Convergence docker-compose.yml — Remove NetClaw Container

The netclaw container is removed from docker-compose. NetClaw runs natively on the host.

docker-compose.yml keeps:
- otel-collector
- victoriametrics
- grafana
- loki
- promtail
- alertmanager
- redis
- threat-intel
- automation-agent
- convergence-scheduler (NEW — replaces net-ops-team)

docker-compose.yml removes:
- netclaw (runs natively)
- net-ops-team (replaced by NetClaw skills + convergence-scheduler)

### NetClaw Runs Natively

```bash
cd /home/ubuntu/netclaw
./scripts/install.sh              # Full 53-step install
openclaw onboard                  # Interactive: configure provider, gateway
openclaw gateway run              # Start the gateway (or systemd service)
```

The REST proxy sidecar runs alongside:
```bash
python3 mcp-servers/netclaw-proxy/netclaw_proxy.py &
```

Or both via a simple wrapper script.

### MCP Servers Registered Properly

After `openclaw onboard`, register the servers needed for this deployment:

```bash
# Infrastructure MCP servers (query the Convergence stack)
openclaw mcp set grafana-mcp '{...}'
openclaw mcp set prometheus-mcp '{...}'

# Source of truth
openclaw mcp set nautobot-mcp '{...}'

# Device access
openclaw mcp set pyats-mcp '{...}'

# Security
openclaw mcp set nmap-mcp '{...}'
openclaw mcp set pfsense-mcp '{...}'

# Convergence integration
openclaw mcp set convergence-mcp '{...}'

# Audit trail
openclaw mcp set gait-mcp '{...}'
```

### pyATS Testbed Updated

```yaml
# testbed/testbed.yaml
devices:
  HomeSwitch01:
    alias: "Home Switch 01"
    type: switch
    os: iosxe
    platform: cat3850
    credentials:
      default:
        username: "%ENV{SWITCH_SSH_USER}"
        password: "%ENV{SWITCH_SSH_PASS}"
      enable:
        password: "%ENV{SWITCH_SSH_ENABLE_PASS}"
    connections:
      cli:
        protocol: ssh
        ip: 192.168.3.2
        port: 22
        arguments:
          connection_timeout: 60

  HomeSwitch02:
    alias: "Home Switch 02"
    type: switch
    os: iosxe
    platform: cat3850
    credentials:
      default:
        username: "%ENV{SWITCH_SSH_USER}"
        password: "%ENV{SWITCH_SSH_PASS}"
      enable:
        password: "%ENV{SWITCH_SSH_ENABLE_PASS}"
    connections:
      cli:
        protocol: ssh
        ip: 192.168.3.3
        port: 22
        arguments:
          connection_timeout: 60
```

### TOOLS.md Updated

Add the actual network details to NetClaw's deployment notes:

```markdown
## Network Devices
- HomeSwitch01 → 192.168.3.2, Cisco WS-C3850-48P, IOS-XE
- HomeSwitch02 → 192.168.3.3, Cisco WS-C3850-48P, IOS-XE
- pfSense-FW01 → 192.168.3.1:440, Netgate pfSense Plus 25.11

## Subnets
- 192.168.1.0/24 — LAN
- 192.168.3.0/24 — Management
- 192.168.100.0/24 — Servers
- 192.168.102.0/24 — IoT/Media

## Convergence Stack (Docker on this host)
- VictoriaMetrics → http://localhost:8428
- Grafana → http://localhost:3000
- Loki → http://localhost:3100
- threat-intel → http://localhost:8001
- automation-agent → http://localhost:8002
- Nautobot → https://192.168.3.253

## Known Devices (check Nautobot for full inventory)
- SynologyNAS01 → 192.168.100.22 (NAS — multi-VLAN traffic is normal)
- SynologyNAS02 → 192.168.100.23 (NAS — multi-VLAN traffic is normal)
```

---

## The Convergence-Specific Skills

These live in NetClaw's workspace alongside the 124 upstream skills:

### convergence-noc-watch
- **Uses:** grafana-mcp (PromQL + LogQL), prometheus-mcp, nautobot-mcp, pfsense-mcp
- **Does:** Device reachability, interface utilization, error rates, firewall block rate, syslog critical events
- **Replaces:** NOC Officer + Network Engineer agents

### convergence-security-monitor
- **Uses:** grafana-mcp (LogQL), convergence-mcp (threat-intel + automation), nautobot-mcp, pfsense-mcp
- **Does:** Threat hunting, NetFlow analysis, internal host validation against Nautobot, automated blocking
- **Replaces:** Security Expert + Security Engineer agents

### convergence-interface-reconciler
- **Uses:** pyats-mcp, nautobot-mcp, pfsense-mcp
- **Does:** MAC table collection, DHCP/ARP correlation, port description enrichment, admin state sync, inventory diff
- **Replaces:** Interface Reconciler agent

### synology-nas-monitor (upstream skill, already written)
- **Uses:** prometheus-mcp
- **Does:** Synology SNMP health checks

### pfsense-firewall-ops (upstream skill, already written)
- **Uses:** pfsense-mcp
- **Does:** pfSense management and analysis

---

## convergence-scheduler (the only new service)

Replaces the entire net-ops-team container. ~100 lines:

```python
# Cron schedule:
# Every 10 min: POST to NetClaw REST proxy with monitoring prompt
# Every 1 hour: POST shift report prompt, post to Discord
# Parse response for findings, post WARNING/CRITICAL to Discord
```

This goes in `Convergence/services/convergence-scheduler/`.

---

## Implementation: Git Branch Strategy

### On the Convergence repo:

```bash
cd /home/ubuntu/Convergence
git checkout main
git checkout -b refactor/netclaw-first

# Changes on this branch:
# 1. Remove netclaw submodule
# 2. Remove net-ops-team service
# 3. Remove netclaw from docker-compose.yml
# 4. Add convergence-scheduler service
# 5. Move convergence-mcp and netclaw-proxy to a shared location
# 6. Update docs
```

### On the NetClaw repo:

```bash
cd /home/ubuntu/netclaw
git checkout -b feature/convergence-deployment

# Changes on this branch:
# 1. Add pfsense-mcp server (already done)
# 2. Add pfsense-firewall-ops skill (already done)
# 3. Add synology-nas-monitor skill (already done)
# 4. Add convergence-specific skills
# 5. Update testbed with real devices
# 6. Update TOOLS.md with network details
# 7. Add convergence-mcp to mcp-servers/ (or keep in Convergence repo)
```

---

## Execution Order for Next Session

### Phase 1: Set up NetClaw properly (30 min)
1. `cd /home/ubuntu/netclaw`
2. Update testbed.yaml with real devices
3. Update TOOLS.md with network details
4. Run `openclaw gateway run` (if not already running via Docker — decide approach)
5. Register the 8 MCP servers needed
6. Test each one

### Phase 2: Write Convergence skills (1 hour)
1. convergence-noc-watch/SKILL.md
2. convergence-security-monitor/SKILL.md
3. convergence-interface-reconciler/SKILL.md
4. Test each via `openclaw agent --message "Run convergence-noc-watch"`

### Phase 3: Build convergence-scheduler (30 min)
1. Create services/convergence-scheduler/
2. Wire up: cron → REST proxy → NetClaw → Discord
3. Test end-to-end

### Phase 4: Cut over (30 min)
1. Stop net-ops-team
2. Start convergence-scheduler
3. Verify Discord notifications
4. Remove net-ops-team from docker-compose

### Phase 5: Clean up git (30 min)
1. Create branches
2. Commit changes
3. Remove submodule from Convergence
4. PR upstream skills to netclaw repo

---

## Open Decision: NetClaw in Docker or Native?

### Option A: Keep NetClaw in Docker (but fix it)
- Pros: Everything in one `docker compose up`
- Cons: Fighting the install process, manual MCP registration, testbed in container
- Approach: Create a `setup-convergence.sh` that runs inside the container after start

### Option B: Run NetClaw natively on the host
- Pros: Proper install, proper onboard, proper MCP registration, testbed on host filesystem
- Cons: Two things to manage (docker compose + openclaw gateway)
- Approach: `openclaw gateway run` as systemd service or tmux session

### Recommendation: Option B
NetClaw was designed to run natively. The Docker approach has caused every problem we've hit:
- install.sh failures
- MCP registration issues
- Testbed pointing to wrong devices
- Config schema mismatches between submodule and deployment

Run NetClaw natively. Let Docker handle the infrastructure (OTEL, VM, Loki, Grafana, Redis, threat-intel, automation-agent, scheduler). This is the clean separation.

The MCP servers that need to talk to Docker services (Grafana, VictoriaMetrics, Loki) use `localhost:PORT` since the Docker ports are mapped to the host. The MCP servers that talk to network devices (pyATS, pfSense) use the device IPs directly from the host network.
