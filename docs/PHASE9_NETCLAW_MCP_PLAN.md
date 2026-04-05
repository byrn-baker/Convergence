# Phase 9: NetClaw MCP Integration — Plan

**Status:** Planned
**Depends on:** Phase 8 (unified LLM client, closed-loop threat response)

---

## Problem Statement

The Convergence platform has two AI systems that can't talk to each other:

1. **net-ops-team** — 6 specialized agents (security expert, NOC officer, network engineer, etc.) that monitor the network every 5 minutes, find threats, and can submit block actions to the automation-agent. They use VictoriaMetrics, Loki, Nautobot, and pfSense tools. They run on Ollama Cloud (qwen3-coder:480b).

2. **NetClaw** — a CCIE-level network engineering agent built on the OpenClaw framework with 100+ skills, pyATS device access, and MCP servers for Nautobot, Grafana, Prometheus, GNS3, and more. It also runs on Ollama Cloud (qwen3-coder:480b) as of Phase 8.

The security expert finds threats but can't ask NetClaw to investigate. NetClaw has deep device access but doesn't know what the security expert found. The interface reconciler writes to Nautobot but NetClaw has its own Nautobot MCP server doing similar work independently.

**Example of the gap (real Discord alerts from Phase 8):**

The security expert posts:
> 🔴 CRITICAL — all
> [RECOMMENDATION] Investigate Host 192.168.100.130
> Action: Perform forensic analysis on host 192.168.100.130.

But it can't actually investigate — it doesn't have SSH access to switches, can't run pyATS commands, can't check pfSense connection states. NetClaw has all of these capabilities but doesn't know about the threat.

---

## Architecture Goal

```
┌─────────────────────────────────────────────────────────────────┐
│                     net-ops-team agents                          │
│  Security Expert · NOC Officer · Network Engineer · etc.        │
│                                                                  │
│  Tools: VictoriaMetrics · Loki · Nautobot · pfSense             │
│       + request_netclaw_investigation (NEW — WebSocket client)  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket (ws://netclaw:18789)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     NetClaw (OpenClaw Gateway)                   │
│  CCIE Senior Network Architect · pyATS · 100+ skills            │
│                                                                  │
│  MCP Servers:                                                    │
│    nautobot-mcp · grafana-mcp · prometheus-mcp (existing)       │
│  + convergence-mcp (NEW)                                        │
│      submit_block_action · get_threat_intel · query_metrics     │
│      query_logs · get_pending_blocks · investigate_host         │
└─────────────────────────────────────────────────────────────────┘
```

Two integration directions:

**Direction A: net-ops-team → NetClaw (WebSocket client)**
The security expert sends investigation requests to NetClaw via the OpenClaw gateway WebSocket API. NetClaw uses its pyATS skills, SSH access, and MCP tools to investigate, then returns findings.

**Direction B: NetClaw → Convergence (MCP server)**
NetClaw gains access to Convergence's data plane via a new MCP server. It can query threat intel, submit block actions, check metrics/logs, and investigate hosts — all through the same MCP protocol it already uses for Nautobot and Grafana.

---

## Phase 9A: WebSocket Client (net-ops-team → NetClaw)

### What We Know

- The OpenClaw gateway runs at `ws://netclaw:18789` inside the Docker network
- `openclaw agent --agent main --message "..." --timeout 120` sends a prompt and returns a response (tested and working in Phase 8)
- The gateway uses WebSocket with JSON-RPC style messages
- Auth is set to `mode: none` in our config

### Implementation Plan

1. **Reverse-engineer the WebSocket protocol**
   - Run `openclaw agent --message "test" --json --verbose` and capture the WebSocket frames
   - Or read the OpenClaw source at `/usr/local/lib/node_modules/openclaw/` inside the container
   - Identify: connection handshake, message format, session management, response streaming

2. **Create `services/net-ops-team/app/tools/netclaw.py`**
   - Async WebSocket client using `websockets` library
   - `async def ask_netclaw(prompt: str, timeout: int = 120) -> str`
   - Connects to `ws://netclaw:18789`, sends the prompt, collects the streamed response, returns the final text
   - Handles: connection errors (NetClaw down), timeouts (long investigations), rate limiting (don't flood NetClaw)

3. **Add `request_netclaw_investigation` tool to security expert**
   ```python
   {
       "name": "request_netclaw_investigation",
       "description": (
           "Send an investigation request to NetClaw, the CCIE-level network "
           "engineering agent. NetClaw has SSH/pyATS access to all network devices, "
           "can run show commands, check interface status, trace MAC addresses "
           "through the switching fabric, and perform packet-level analysis. "
           "Use this for: investigating suspicious hosts, tracing connections, "
           "checking device configs, or any task requiring direct device access."
       ),
       "input_schema": {
           "type": "object",
           "properties": {
               "task": {"type": "string", "description": "What to investigate"},
               "context": {"type": "string", "description": "Threat context"},
               "ip": {"type": "string", "description": "IP to investigate"},
           },
           "required": ["task"],
       },
   }
   ```

4. **Update security expert system prompt**
   ```
   INVESTIGATION PROTOCOL:
   - For suspicious internal hosts: first use investigate_host (DHCP/ARP/Nautobot)
   - If the host needs deeper investigation (SSH, show commands, config check):
     use request_netclaw_investigation to send the task to the CCIE agent
   - Include the threat context so NetClaw knows what to look for
   ```

5. **Add `websockets` to requirements.txt**

### Dependencies
- `websockets>=12.0` Python package
- NetClaw container running and healthy
- OpenClaw gateway WebSocket protocol documentation (or reverse-engineering)

### Risks
- WebSocket protocol may change between OpenClaw versions (mitigate: pin submodule version)
- Long-running investigations may timeout (mitigate: configurable timeout, async polling)
- NetClaw may be busy with another task (mitigate: queue or retry logic)

---

## Phase 9B: Convergence MCP Server (NetClaw → Convergence)

### What MCP Servers Are

MCP (Model Context Protocol) is the standard NetClaw uses for tool access. Each MCP server is a small process that exposes tools via JSON-RPC over stdio. NetClaw's `openclaw.json` registers MCP servers, and the OpenClaw framework automatically discovers and presents their tools to the agent.

NetClaw already has MCP servers for:
- `nautobot-mcp` — Nautobot GraphQL/REST
- `grafana-mcp` — Grafana dashboard queries
- `prometheus-mcp` — PromQL queries against VictoriaMetrics
- `suzieq-mcp` — Network observability
- `batfish-mcp` — Network config analysis
- `gnmi-mcp` — gNMI streaming telemetry
- `gns3-mcp` — GNS3 lab management

### Implementation Plan

1. **Create `mcp-servers/convergence-mcp/`**
   ```
   mcp-servers/convergence-mcp/
   ├── convergence_mcp_server.py    # MCP server (Python, stdio JSON-RPC)
   ├── requirements.txt             # httpx, mcp (if using the MCP Python SDK)
   └── README.md
   ```

2. **Tools to expose:**

   | Tool | Description | Endpoint |
   |------|-------------|----------|
   | `get_threat_intel_report` | Full threat intel report with scored IPs | `GET threat-intel:8000/api/report` |
   | `get_blocked_ips` | Top blocked IPs with threat scores | `GET threat-intel:8000/api/infinity/blocked_ips` |
   | `get_outbound_suspicious` | Suspicious outbound destinations | `GET threat-intel:8000/api/infinity/outbound_suspicious` |
   | `submit_block_action` | Submit IP for blocking via automation pipeline | `POST automation-agent:8000/api/automation/submit` |
   | `get_pending_approvals` | List pending block actions | `GET automation-agent:8000/api/automation/pending` |
   | `approve_block` | Approve a pending block action | `POST automation-agent:8000/api/automation/approve/{id}` |
   | `get_netops_report` | Latest NET-OPS team findings | `GET net-ops-team:8000/api/v1/report/latest` |
   | `query_metrics` | PromQL query against VictoriaMetrics | `GET victoriametrics:8428/api/v1/query` |
   | `query_logs` | LogQL query against Loki | `GET loki:3100/loki/api/v1/query_range` |
   | `investigate_host` | DHCP/ARP/Nautobot lookup for an internal IP | Calls pfSense XML-RPC + Nautobot GraphQL |

3. **Register in NetClaw's openclaw.json:**
   ```json
   {
     "mcpServers": {
       "convergence-mcp": {
         "command": "python3",
         "args": ["-u", "/app/mcp-servers/convergence-mcp/convergence_mcp_server.py"],
         "env": {
           "THREAT_INTEL_URL": "http://threat-intel:8000",
           "AUTOMATION_AGENT_URL": "http://automation-agent:8000",
           "NET_OPS_TEAM_URL": "http://net-ops-team:8000",
           "VICTORIAMETRICS_URL": "http://victoriametrics:8428",
           "LOKI_URL": "http://loki:3100"
         }
       }
     }
   }
   ```

4. **Mount the MCP server into the NetClaw container**
   Add a volume mount in docker-compose.yml:
   ```yaml
   netclaw:
     volumes:
       - ./mcp-servers/convergence-mcp:/app/mcp-servers/convergence-mcp:ro
   ```

5. **Install dependencies inside the NetClaw container**
   Either add to the Dockerfile or use a pip install in the MCP server's startup.

### What This Enables

Once the MCP server is registered, NetClaw can natively:

- **"Check the threat intel report and tell me what's hitting my network"** — calls `get_threat_intel_report`, analyzes the scored IPs, cross-references with its own device knowledge
- **"Block IP 5.187.35.26 on pfSense"** — calls `submit_block_action`, goes through the full automation pipeline with GAIT audit trail
- **"Investigate why 192.168.100.130 is talking to a known C2 server"** — calls `investigate_host` for the MAC/hostname, then uses its own pyATS skills to SSH into the switch and trace the connection
- **"Show me the last hour of firewall logs for this IP"** — calls `query_logs` with a LogQL query
- **"What did the NOC team find in the last cycle?"** — calls `get_netops_report`

NetClaw becomes a full participant in the Convergence security workflow, not an isolated agent.

---

## Implementation Order

### Session 1: Phase 9A (WebSocket client)
1. Reverse-engineer the OpenClaw gateway WebSocket protocol
2. Build `tools/netclaw.py` WebSocket client
3. Add `request_netclaw_investigation` tool to security expert
4. Test: security expert finds threat → asks NetClaw to investigate → incorporates findings
5. Commit and document

### Session 2: Phase 9B (MCP server)
1. Build `convergence_mcp_server.py` with the tool set above
2. Mount into NetClaw container, register in openclaw.json
3. Test: ask NetClaw directly "what threats are hitting my network?" — it calls the MCP tools
4. Test: ask NetClaw "block this IP" — it calls submit_block_action via MCP
5. Commit and document

### Session 3: Bidirectional workflow
1. Security expert finds threat → asks NetClaw to investigate (9A)
2. NetClaw investigates → finds evidence → calls submit_block_action via MCP (9B)
3. Automation agent executes the block with full GAIT audit trail
4. End-to-end: threat detected → investigated → blocked → audited, no human in the loop for high-confidence threats

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `services/net-ops-team/app/tools/netclaw.py` | WebSocket client for OpenClaw gateway |
| `mcp-servers/convergence-mcp/convergence_mcp_server.py` | MCP server exposing Convergence tools to NetClaw |
| `mcp-servers/convergence-mcp/requirements.txt` | Python dependencies (httpx, mcp SDK) |
| `mcp-servers/convergence-mcp/README.md` | Setup and tool documentation |

### Modified Files
| File | Change |
|------|--------|
| `services/net-ops-team/app/team/security_expert.py` | Add `request_netclaw_investigation` tool |
| `services/net-ops-team/requirements.txt` | Add `websockets>=12.0` |
| `config/netclaw/openclaw.json` | Register `convergence-mcp` server |
| `docker-compose.yml` | Mount MCP server volume into netclaw container |
| `docker/netclaw.Dockerfile` | Install convergence-mcp dependencies |

### Not Modified
| File | Why |
|------|-----|
| `netclaw/` (submodule) | We don't own this repo — all integration is external |

---

## Open Questions for Next Session

1. **WebSocket protocol format** — need to capture the exact JSON-RPC messages the OpenClaw gateway expects. Can do this by running `openclaw agent --verbose` or reading the OpenClaw source inside the container.

2. **MCP SDK version** — OpenClaw may expect a specific MCP protocol version. Check what version the existing MCP servers (nautobot-mcp, etc.) use.

3. **NetClaw session management** — should the security expert reuse a single NetClaw session (persistent context) or create a new one per investigation? Persistent sessions mean NetClaw remembers prior findings; new sessions are cleaner but lose context.

4. **Rate limiting** — NetClaw on the 480b cloud model can handle one request at a time. If 5 agents all want investigations simultaneously, we need a queue. Redis task queue (Option 3 from the earlier discussion) might be needed as a backpressure mechanism even with the WebSocket approach.

5. **Credential isolation** — the convergence-mcp server will need access to internal service URLs. These are Docker-internal (not exposed to the internet) but should still be passed via env vars, not hardcoded.
