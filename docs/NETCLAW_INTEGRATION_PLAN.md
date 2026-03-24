# NetClaw Integration Plan for Convergence

**Date:** March 24, 2026
**Objective:** Integrate NetClaw AI network engineering agent to enhance Convergence's network configuration management and troubleshooting capabilities while maintaining Nautobot as the source of truth.

---

## Executive Summary

Convergence currently provides excellent network observability and automated threat response, but lacks advanced network troubleshooting, configuration management, and device health monitoring capabilities. NetClaw brings CCIE-level network engineering expertise with 97 skills and 43 MCP integrations specifically designed for network automation.

**Key Benefits:**
- Advanced troubleshooting workflows for connectivity issues, routing problems, and performance degradation
- ITSM-gated configuration changes with ServiceNow integration
- Device health monitoring across the entire fleet
- Topology discovery and reconciliation against Nautobot
- Security auditing and compliance checking
- Packet capture analysis and deep network debugging

---

## Current Convergence Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Network Infrastructure                   │
│  Internet/WAN · pfSense · Cisco Switches · Nautobot (SoT)   │
├─────────────────────────────────────────────────────────────┤
│                 Collection & Storage Layer                  │
│  OTEL Collector · VictoriaMetrics · Loki · Redis · Grafana  │
├─────────────────────────────────────────────────────────────┤
│                    AI Services Layer                        │
│  threat-intel · automation-agent · GAIT Audit Trail        │
├─────────────────────────────────────────────────────────────┤
│                 External Integrations                       │
│  AbuseIPDB · GreyNoise · OTX · IPInfo · Claude/Ollama       │
└─────────────────────────────────────────────────────────────┘
```

**Current Capabilities:**
- ✅ Network observability (SNMP, syslog, metrics)
- ✅ Threat intelligence enrichment
- ✅ Automated pfSense firewall blocking
- ✅ Nautobot device discovery
- ✅ Grafana dashboards and alerting

**Gaps Addressed by NetClaw:**
- ❌ Advanced network troubleshooting
- ❌ Configuration change management
- ❌ Device health monitoring beyond basic metrics
- ❌ Topology reconciliation and drift detection
- ❌ Security posture auditing
- ❌ Packet-level analysis

---

## NetClaw Architecture Integration

### Phase 1: Core NetClaw Deployment (Week 1-2)

#### 1.1 NetClaw Installation
```bash
# Add to docker-compose.yml
netclaw:
  image: automateyournetwork/netclaw:latest
  container_name: convergence-netclaw
  ports:
    - "18789:18789"    # OpenClaw Gateway
    - "3001:3000"     # NetClaw Visual HUD
  volumes:
    - netclaw-workspace:/app/workspace
    - ./config/netclaw:/app/config:ro
  environment:
    - OPENCLAW_MODE=gateway
    - NETCLAW_LAB_MODE=false
    - NAUTOBOT_URL=${NAUTOBOT_URL}
    - NAUTOBOT_TOKEN=${NAUTOBOT_TOKEN}
    - VICTORIAMETRICS_URL=http://victoriametrics:8428
    - GRAFANA_URL=http://grafana:3000
    - LOKI_URL=http://loki:3100
    - PFSENSE_HOST=${PFSENSE_HOST}
    - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
  networks:
    - convergence
  depends_on:
    - nautobot  # If running in Docker
```

#### 1.2 Configuration Files
Create `/config/netclaw/` directory with:
- `openclaw.json` - Gateway configuration
- `netclaw.env` - Environment variables
- `testbed.yaml` - Device inventory (generated from Nautobot)

#### 1.3 Nautobot Integration Setup
```yaml
# netclaw.env
NAUTOBOT_URL=http://nautobot:8000
NAUTOBOT_TOKEN=${NAUTOBOT_TOKEN}
NAUTOBOT_VERIFY_SSL=false

# Device discovery from Nautobot
NETCLAW_DEVICE_DISCOVERY=nautobot
NETCLAW_SITE_FILTER=home-lab
```

### Phase 2: MCP Server Configuration (Week 2-3)

#### 2.1 Core MCP Servers to Enable
Based on Convergence's existing stack:

| MCP Server | Purpose | Integration Point |
|------------|---------|-------------------|
| **nautobot-mcp** | IPAM source of truth | Replace NetBox references |
| **grafana-mcp** | Dashboard management | Enhance existing Grafana integration |
| **prometheus-mcp** | Direct metrics queries | Complement VictoriaMetrics |
| **loki-mcp** | Log analysis | Deep log correlation |
| **pyats-mcp** | Device automation | Advanced device interactions |
| **pfsense-mcp** | Firewall management | Enhance pfSense integration |
| **packet-buddy** | PCAP analysis | Network troubleshooting |
| **gait-mcp** | Audit trails | Integration with GAIT |

#### 2.2 NetClaw Skills to Activate
Priority skills for home network management:

**Device Management:**
- `pyats-health-check` - Fleet-wide device monitoring
- `pyats-routing` - OSPF/BGP analysis and troubleshooting
- `pyats-security` - Security posture auditing
- `pyats-topology` - CDP/LLDP discovery and mapping

**Troubleshooting:**
- `pyats-troubleshoot` - OSI-layer methodology
- `packet-analysis` - Deep packet inspection
- `gtrace-path-analysis` - Network path tracing

**Configuration Management:**
- `pyats-config-mgmt` - ITSM-gated changes
- `servicenow-change-workflow` - Change management
- `nautobot-sot` - Source of truth reconciliation

### Phase 3: Enhanced Observability Integration (Week 3-4)

#### 3.1 Grafana Dashboard Integration
NetClaw can create and modify Grafana dashboards:
- Add NetClaw health monitoring panels
- Create topology visualization dashboards
- Add configuration change tracking panels

#### 3.2 Alert Enhancement
Integrate NetClaw alerts with existing Alertmanager:
- Device health alerts from NetClaw
- Configuration drift notifications
- Security posture alerts

#### 3.3 GAIT Audit Trail Integration
Merge NetClaw's GAIT trails with Convergence's existing audit system:
- Unified audit repository
- Cross-reference automation decisions
- Compliance reporting

### Phase 4: Advanced Automation Workflows (Week 4-5)

#### 4.1 Automated Troubleshooting
Create NetClaw skills that trigger on alerts:
```
Alert → NetClaw Analysis → Automated Resolution → GAIT Audit
```

#### 4.2 Configuration Drift Detection
```
Nautobot (SoT) ↔ NetClaw Reconciliation → Drift Alerts → Change Requests
```

#### 4.3 Threat Response Enhancement
Integrate NetClaw's security analysis with existing threat intel:
```
Threat Detected → NetClaw Security Audit → Enhanced Blocking Rules → pfSense Update
```

### Phase 5: User Interface Integration (Week 5-6)

#### 5.1 Discord Bot Enhancement
Extend existing Discord bot with NetClaw commands:
- `/netclaw status` - Network health overview
- `/netclaw troubleshoot <device>` - Device analysis
- `/netclaw config <change>` - Configuration proposals
- `/netclaw topology` - Network map generation

#### 5.2 Grafana Panel Integration
Add NetClaw control panels to existing dashboards:
- Device health status widgets
- Configuration change history
- Active troubleshooting sessions

---

## Technical Implementation Details

### Docker Compose Integration
```yaml
# Add to existing docker-compose.yml
netclaw:
  build:
    context: ./services/netclaw
    dockerfile: Dockerfile
  environment:
    - NAUTOBOT_URL=${NAUTOBOT_URL}
    - VICTORIAMETRICS_URL=http://victoriametrics:8428
    - GRAFANA_URL=http://grafana:3000
    - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
  volumes:
    - netclaw-workspace:/app/workspace
    - ./config/netclaw:/app/config:ro
  networks:
    - convergence
```

### Configuration Management
Create `/config/netclaw/` with:
- `openclaw.json` - Gateway settings
- `netclaw.env` - Environment variables
- `devices.yaml` - Device inventory from Nautobot
- `skills/` - Custom Convergence-specific skills

### Network Integration
- NetClaw runs on the same `convergence` network
- Access to all existing services (VictoriaMetrics, Grafana, Loki, Redis)
- SSH access to network devices through existing credentials

---

## Skills Development Plan

### Custom Convergence Skills
Develop NetClaw skills specific to Convergence workflows:

#### convergence-device-discovery
```yaml
name: convergence-device-discovery
description: "Sync NetClaw device inventory with Nautobot"
triggers:
  - cron: "0 */4 * * *"  # Every 4 hours
  - manual: true
actions:
  - nautobot-sot: get_devices
  - pyats: update_testbed
  - gait: audit_changes
```

#### convergence-threat-response
```yaml
name: convergence-threat-response
description: "Enhanced threat response with NetClaw analysis"
triggers:
  - webhook: threat-intel-service
actions:
  - packet-analysis: capture_traffic
  - pyats-security: audit_firewall
  - pfsense-mcp: update_rules
```

#### convergence-config-drift
```yaml
name: convergence-config-drift
description: "Detect and report configuration drift"
triggers:
  - cron: "0 * * * *"  # Hourly
actions:
  - nautobot-sot: get_intent
  - pyats: collect_actual
  - servicenow: create_incident
```

---

## Migration Strategy

### Gradual Rollout
1. **Week 1:** NetClaw deployment and basic Nautobot integration
2. **Week 2:** Enable core MCP servers and basic skills
3. **Week 3:** Integrate with existing monitoring stack
4. **Week 4:** Add automated workflows and alerting
5. **Week 5:** User interface enhancements
6. **Week 6:** Production deployment and training

### Fallback Plan
- NetClaw failures don't impact existing Convergence functionality
- All NetClaw actions are logged and auditable
- Manual override capabilities maintained

### Testing Strategy
- Start with read-only operations (monitoring, analysis)
- Gradual introduction of automated actions
- Parallel operation with existing automation
- Comprehensive audit trail validation

---

## Success Metrics

### Operational Metrics
- **MTTR Reduction:** 50% faster troubleshooting resolution
- **Configuration Accuracy:** 90% reduction in manual config errors
- **Alert Noise Reduction:** 60% fewer false positive alerts
- **Audit Compliance:** 100% automated audit trail coverage

### User Experience Metrics
- **Time to Resolution:** Average troubleshooting time < 15 minutes
- **Automation Coverage:** 80% of network issues auto-resolved
- **User Satisfaction:** NetClaw assistance requested for 70% of incidents

---

## Risk Assessment

### Technical Risks
- **MCP Server Compatibility:** Ensure all 43 MCP servers work with existing stack
- **Performance Impact:** Monitor resource usage of NetClaw services
- **Network Security:** Secure NetClaw access to network devices

### Operational Risks
- **Learning Curve:** Training required for advanced NetClaw features
- **Alert Fatigue:** Potential increase in notifications during initial deployment
- **Integration Complexity:** Managing multiple automation systems

### Mitigation Strategies
- **Phased Deployment:** Gradual feature rollout with rollback capabilities
- **Comprehensive Testing:** Extensive testing in staging environment
- **Documentation:** Detailed runbooks and troubleshooting guides
- **Support Plan:** Access to NetClaw community and maintainers

---

## Resource Requirements

### Infrastructure
- **CPU:** +2 vCPUs for NetClaw services
- **Memory:** +4GB RAM
- **Storage:** +20GB for NetClaw workspace and audit trails
- **Network:** Additional ports (18789 for gateway, 3001 for UI)

### Personnel
- **DevOps Engineer:** 2 weeks for integration
- **Network Engineer:** 1 week for device configuration
- **Training:** 1 day for operations team

### Timeline
- **Planning & Design:** 1 week
- **Implementation:** 4 weeks
- **Testing & Validation:** 2 weeks
- **Deployment & Training:** 1 week
- **Total:** 8 weeks

---

## Conclusion

Integrating NetClaw will transform Convergence from a monitoring platform into a comprehensive network operations center with AI-assisted troubleshooting, automated configuration management, and advanced security capabilities. The strong Nautobot integration ensures consistency with existing workflows while NetClaw's extensive skill set provides the advanced network engineering capabilities needed for complex home network management.

The phased approach minimizes risk while maximizing the benefits of AI-assisted network operations.