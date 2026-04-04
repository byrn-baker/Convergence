# The Convergence Journey

*A living log of decisions, dead ends, pivots, and progress in building a home network AI platform.*

---

## Why This Exists

It started with a simple frustration: a home network with two Cisco switches and a pfSense
firewall, and no good way to know what was actually happening on it. Sure, pfSense has its
dashboard. The Cisco switches have their CLI. But correlating events across devices meant logging
into each one separately, mentally stitching together timestamped CLI output — the kind of thing
that's fine until something breaks at 11pm and you're guessing.

The goal was modest at first: get metrics into Grafana so I could see everything in one place.
It grew from there.

---

## Phase 1 — Just Make It Observable (January 2026)

The foundation: OpenTelemetry Collector pulling SNMP from both Cisco switches
(192.168.3.2 HomeSwitch01, 192.168.3.3 HomeSwitch02) and the pfSense firewall
(192.168.100.1). VictoriaMetrics for time-series storage. Grafana on top.

The name "Convergence" came from this: all the telemetry converging into a single pane of glass.

First dashboard showing interface utilization across all three devices felt genuinely satisfying.
SNMP is old and crusty but it works, and the OTel SNMP receiver handled the Cisco MIBs cleanly.

Nautobot integration came in here too — the idea being that device inventory shouldn't be
hardcoded. Every metric should carry proper metadata: hostname, IP, vendor, model, role. Worth
the extra complexity.

**What worked:** OTel + VictoriaMetrics is a solid, lightweight stack. No Prometheus scrape
config gymnastics. The SNMP receiver just works.

**What didn't:** First attempt at pfSense SNMP required figuring out which OIDs pfSense actually
exposes (it uses net-snmp under the hood, not a purpose-built network MIB). Some trial and error.

---

## Phase 2 — Logs Matter Too (January 2026)

Metrics tell you "interface Gi0/1 had high utilization at 14:32." Logs tell you *why* the
switch sent a syslog message at 14:32 saying a spanning tree topology change occurred.

Added Promtail → Loki for log aggregation. pfSense syslog (RFC 3164 format) is messy — the
message format varies depending on which pfSense process generated it. Wrote custom Promtail
pipeline stages to extract structured labels from the raw syslog stream.

The payoff: Grafana panels linking metric anomalies with correlated log events from the same
timeframe. Suddenly the story became clearer.

---

## Phase 3 — Alerting (February 2026)

Observability without alerting is just a pretty dashboard you have to remember to look at.

Added Alertmanager with Discord webhook notifications. LogQL Loki Ruler for log-based recording
rules — things like "alert if pfSense blocks spike more than 2x the 1-hour baseline." Interface
flap detection. SNMP unreachable alerts.

The Discord channel became the single notification surface. Routing rules kept noisy informational
alerts separate from critical ones that needed immediate attention.

**Lesson:** Get the alert thresholds wrong and you train yourself to ignore notifications.
Took a few iterations to find the right balance between signal and noise.

---

## Phase 4 — AI Threat Intelligence (February 2026)

This was the phase where Convergence stopped being a monitoring tool and became something more
interesting.

The `threat-intel` service watches pfSense firewall logs, takes the top blocked and suspicious
outbound IPs, and enriches each one with four threat intelligence APIs: AbuseIPDB, GreyNoise,
OTX AlienVault, and IPInfo. Composite threat scoring (0–100) with automatic risk classification.
GeoIP enrichment with a Grafana Geomap showing attack origins on a world map.

Then Claude Haiku enters the picture: the service sends the enriched threat data to the Claude
API and gets back an AI-generated security narrative. Not a generic summary — a pfSense-specific
executive brief using actual interface names, referencing pfBlockerNG paths, with actionable
remediation steps. The first time it correctly referenced `pfBlockerNG` alias syntax in a
blocking recommendation, it felt like a qualitative jump in usefulness.

**What worked:** The composite threat scoring turned out to be more useful than any individual
API score. Correlating "GreyNoise says this is a scanner" with "AbuseIPDB confidence 97" with
"this IP has hit us 50+ times in an hour" creates a much stronger signal than any one alone.

**What didn't:** Initial implementation hit API rate limits on GreyNoise during heavy event
periods. Added caching and rate limiting.

---

## Phase 5 — Automation (March 2026)

If the AI can identify a high-risk IP with 95+ confidence, why not let it block it?

The `automation-agent` service does exactly that — but carefully. Every decision is committed to
an immutable git audit trail (the GAIT — Git Audit and Integrity Trail) before any action is
attempted. A Discord bot provides `/approve`, `/reject`, `/approve-all`, `/reject-all`, and
`/pending` commands for human review. Auto-approval only kicks in above a configurable confidence
threshold. The default is conservative.

Repeat offender tracking in Redis: if an IP has been blocked 5+ times, or is generating 50+
events per hour, it gets escalated block durations and a permanent-block recommendation.

The pfSense integration was the hardest part. Three paths attempted: REST API, XML-RPC, SSH.
The XML-RPC path won out, though pfSense's tendency to prepend PHP echo output before the actual
XML-RPC response required a custom httpx transport to strip it.

**What worked:** The GAIT audit trail. Having a complete forensic record of every AI decision —
what data it saw, what prompt it received, what it decided, what happened — is genuinely
valuable. Not just for debugging but for building trust in the automation.

**Lesson:** Fail-closed by default. `DRY_RUN=true` until you're confident. The temptation to
flip it to false early is strong. Resist it.

---

## Phase 6 — Local LLM Option (March 2026)

Not everyone wants their firewall telemetry leaving their network to reach an Anthropic API
endpoint. Added Ollama as an alternative LLM backend for both `threat-intel` and
`automation-agent`. One env var to switch: `LLM_PROVIDER=anthropic|ollama`.

The interesting technical wrinkle: Qwen3-family models (the main local option) use a native
`/api/chat` endpoint that doesn't play well with the OpenAI-compat shim when you need to
control `think: false`. Switched the Ollama path to raw `httpx` calls to the native API.

The Ollama instance runs on the host machine (or a NAS, or a workstation) — it's not
containerised inside the Convergence stack. The container reaches it via `host.docker.internal`.

---

## March 24, 2026 — The NetClaw Attempt

With Phases 1–6 solid and running, the natural next question was: what if the platform could
do more than monitor and react? What if it could actually *operate* the network?

Enter NetClaw. A pre-built, Docker-packaged AI network engineer built on pyATS and the Claude
Agent SDK. The pitch: a CCIE-level AI agent that can run `show` commands, analyze configs,
propose and execute changes, all via a local OpenClaw gateway. Drop it into the stack, point it
at the devices, and have an always-available network expert on call.

**What was planned:** Add NetClaw as a service in `docker-compose.yml`, point it at the Cisco
switches and pfSense, wire it to VictoriaMetrics and Loki so it can see the same data the rest
of the stack sees. Ask it questions through the Discord bot. Escalate complex issues to it
automatically.

**What actually happened:**

The integration was started on a feature branch (`feature/netclaw-integration`). The
`docker-compose.yml` entry was added. Then: silence. The service wouldn't start.

Working through the issues on April 3, 2026:

1. **Wrong image name.** The docker-compose entry used `automateyournetwork/netclaw:latest` — the
   Docker Hub image. But a local `convergence_netclaw:latest` had already been built. Two
   different images; the compose file was pulling the wrong one (or trying to, if Docker Hub
   wasn't accessible).

2. **Missing config directory.** The compose file mounted `./config/netclaw:/app/config:ro` but
   `config/netclaw/` didn't exist on disk. Docker creates a directory for a missing bind-mount
   source, but it's empty — so NetClaw had no configuration to load.

3. **`openclaw.json` didn't exist.** The gateway needs a config file to know what mode to run in,
   what port to listen on, what models to use. None of that was created.

These are all fixable problems, and they were fixed. But the process of debugging them raised a
bigger question.

---

## April 3, 2026 — Rethinking the Approach

While fixing the NetClaw issues, a more fundamental question surfaced: is a single general-purpose
agent the right model for network operations?

NetClaw is powerful. But asking one agent to simultaneously:
- Watch NOC dashboards every 5 minutes
- Analyze SNMP data from Cisco switches
- Parse pfSense firewall logs
- Monitor Synology NAS health
- Handle escalations from all of the above
- Execute complex configuration changes

...produces an agent that's spread thin across all of it, deep in none of it.

Real NOCs don't work that way. They have L1 watch officers who maintain situational awareness
and escalate. L2/L3 specialists who own specific domains. Senior architects who handle the
complex stuff. That hierarchy exists because it works.

**The pivot:** Build a proper Network Operations Team (NET-OPS) using the Claude Agent SDK's
multi-agent capabilities:

- **NOC Watch Officer (L1):** Always-on, 5-minute poll cycles, situational awareness, escalation routing
- **Network Engineer (L2/L3):** Switches, interfaces, routing — owns the switching infrastructure
- **Security Engineer (L2/L3):** Threat intel, pfSense, firewall analysis — owns the security posture
- **NAS Engineer (L2/L3):** Synology health, SMART, RAID, backup status — owns storage
- **CCIE Architect (L4):** NetClaw. The escalation endpoint for anything requiring actual configuration changes.

NetClaw doesn't go away — it gets promoted. Rather than being the one agent trying to do
everything, it becomes the expert in the room that the team calls when something is genuinely
beyond their scope. That's exactly the right role for a CCIE-level agent with full pyATS access.

The new `net-ops-team` service will be a Python microservice using the Claude Agent SDK. Each
specialist is a proper Agent instance with curated tool access. A Supervisor orchestrates them,
composes hourly shift reports, and posts to Discord. Redis holds shared state between poll cycles
so the team builds institutional memory.

---

## What's Next

The project has grown from "metrics in Grafana" to a layered AI operations platform. The roadmap
for Phase 7:

1. Get NetClaw actually running (the fixes are in place, now verify it works)
2. Add Synology NAS SNMP monitoring (need the NAS IP address)
3. Build the `net-ops-team` service skeleton
4. Implement each specialist agent with their tools
5. Wire up Discord shift reports
6. Grafana dashboard for NAS health and team activity
7. Activate NetClaw as the CCIE escalation endpoint

The longer-term vision: a home network that runs itself, with humans reviewing summaries and
approving significant actions rather than reacting to individual alerts. Not autonomous — the
GAIT audit trail and Discord approvals are intentional friction. But considerably more capable
than anything running on a home network has a right to be.

---

*Last updated: 2026-04-03*
