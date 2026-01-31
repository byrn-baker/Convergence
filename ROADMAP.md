# Convergence Project Roadmap

This roadmap outlines the development path for Convergence from foundation to autonomous network operations.

## Timeline Overview

```
Phase 1: Foundation (✅ Complete)
│
├─ Phase 2: Enhanced Discovery (3-4 weeks)
│  └─ Multi-vendor support, topology mapping
│
├─ Phase 3: Advanced Observability (4-5 weeks)
│  └─ Dashboards, metrics, anomaly detection
│
├─ Phase 4: Config Management (4-6 weeks)
│  └─ Templates, drift detection, compliance
│
└─ Phase 5: Autonomous Operations (6-8 weeks)
   └─ Self-healing, predictive analytics, multi-agent orchestration
```

---

## Phase 1: Foundation ✅

**Status**: Complete
**Duration**: Completed

### Completed Deliverables
- ✅ Docker-compose infrastructure stack
- ✅ Nautobot 3.0.5 with Python 3.12
- ✅ VictoriaMetrics for metrics storage
- ✅ Grafana for visualization
- ✅ Vector telemetry pipeline
- ✅ LangGraph-based AI agent scaffold
- ✅ Nautobot API integration tools
- ✅ Device SSH connectivity tools
- ✅ CLI interface with Typer
- ✅ Comprehensive documentation

---

## Phase 2: Enhanced Discovery (Revised - Using Nautobot Apps)

**Goal**: Leverage existing Nautobot apps for device discovery, with AI agent orchestration for intelligent automation.

**Duration**: 2-3 weeks (reduced from 3-4 weeks)
**Prerequisites**: Phase 1 complete

**Strategy**: Instead of building discovery from scratch, integrate battle-tested Nautobot apps (Device Onboarding, Network Importer) and add AI agent orchestration layer for intelligence and natural language interface.

### Key Nautobot Apps

1. **Nautobot Device Onboarding**: Automated device discovery and onboarding
2. **Nautobot Network Importer** (optional): Comprehensive network data import
3. **Nautobot Golden Config** (for Phase 4): Config management

### Objectives

1. Integrate Nautobot Device Onboarding app
2. Create AI agent tools to orchestrate discovery apps
3. Add natural language interface to discovery
4. Implement intelligent retry and error handling
5. Build topology visualization on top of discovered data

### Milestones

#### Milestone 2.1: Nautobot App Integration (Week 1)
**Tasks**:
- [ ] Install Nautobot Device Onboarding app
  - Add to docker-compose as Nautobot plugin
  - Configure app settings
  - Set up app database migrations
- [ ] Install Network Importer (optional)
  - Add as Nautobot plugin
  - Configure import adapters
- [ ] Configure device platforms and network drivers
  - Add supported platforms (Cisco IOS, NX-OS, Arista, Juniper)
  - Configure Netmiko/Napalm drivers
  - Test connectivity to sample devices
- [ ] Set up credential management in Nautobot
  - Create secrets for device access
  - Configure secrets groups
  - Assign credentials to device types/sites

**Deliverables**:
- Updated `docker-compose.yml` with Nautobot apps
- `nautobot/` directory with app configurations
- Nautobot platform and driver configuration
- Documentation for supported vendors

**Success Criteria**:
- Device Onboarding app accessible in Nautobot UI
- Can manually onboard a test device via app
- All configured platforms connect successfully

#### Milestone 2.2: AI Agent App Integration Tools (Week 1-2)
**Tasks**:
- [ ] Create Nautobot app API client
  - API wrapper for Device Onboarding
  - API wrapper for Network Importer
  - Error handling and retries
- [ ] Build AI agent tools for discovery
  - `onboard_device` tool: Trigger device onboarding via app
  - `bulk_onboard` tool: Onboard multiple devices
  - `get_onboarding_status` tool: Check discovery progress
  - `import_network_data` tool: Trigger network importer
- [ ] Add intelligent orchestration
  - Automatic platform detection
  - Credential fallback logic
  - Error analysis and retry strategies
  - Progress tracking and reporting
- [ ] Create natural language interface
  - Parse discovery requests
  - Convert to app API calls
  - Aggregate and summarize results

**Deliverables**:
- `agent/tools/nautobot_apps.py` module
- Agent tools for all major app functions
- Natural language discovery interface
- Progress tracking system

**Success Criteria**:
- Agent can trigger discovery via natural language
- Intelligent retry on failures (wrong credentials, timeout, etc.)
- Progress visible in real-time

#### Milestone 2.3: Topology Discovery & Visualization (Week 2)
**Tasks**:
- [ ] Enable neighbor discovery in Device Onboarding
  - Configure CDP/LLDP discovery
  - Enable cable/connection creation
- [ ] Create topology analysis tool
  - Query Nautobot for device relationships
  - Build NetworkX graph from Nautobot data
  - Topology metrics and analysis
- [ ] Implement visualization
  - Generate topology diagrams
  - Export to various formats
  - Interactive viewer integration
- [ ] Add AI agent topology tools
  - `analyze_topology` tool: Analyze network structure
  - `find_path` tool: Find paths between devices
  - `identify_spof` tool: Identify single points of failure

**Deliverables**:
- `agent/tools/topology_analysis.py` module
- Topology visualization scripts
- AI agent topology analysis tools

**Success Criteria**:
- Complete topology auto-discovered via app
- Visual topology diagrams generated
- Agent can answer topology questions

#### Milestone 2.4: Bulk Discovery Workflows (Week 2-3)
**Tasks**:
- [ ] Create discovery orchestration workflows
  - Site-based bulk discovery
  - Subnet scanning and discovery
  - Scheduled discovery jobs
- [ ] Implement discovery profiles
  - Profile per site/device type
  - Credential sets per profile
  - Custom onboarding parameters
- [ ] Add AI agent bulk operations
  - `discover_site` tool: Discover all devices in a site
  - `discover_subnet` tool: Scan and discover subnet
  - `schedule_discovery` tool: Schedule recurring discovery
- [ ] Build monitoring and reporting
  - Discovery dashboard in Grafana
  - Success/failure metrics
  - Historical discovery trends

**Deliverables**:
- Discovery profile system
- Bulk discovery orchestration
- Grafana dashboard for discovery metrics
- Automated reporting

**Success Criteria**:
- Can discover 100+ devices in bulk
- Discovery profiles simplify configuration
- Dashboard shows real-time progress

#### Milestone 2.5: Advanced Discovery Features (Week 3)
**Tasks**:
- [ ] Add configuration backup during discovery
  - Auto-backup configs on onboarding
  - Store in Git repository
  - Version tracking
- [ ] Implement discovery validation
  - Verify discovered data accuracy
  - Cross-reference with existing records
  - Flag inconsistencies
- [ ] Create discovery playbooks
  - Pre-discovery checks
  - Post-discovery validation
  - Automated remediation
- [ ] Add AI agent advanced tools
  - `validate_discovery` tool: Verify discovery results
  - `remediate_discovery_issues` tool: Fix common problems
  - `generate_discovery_report` tool: Comprehensive reports

**Deliverables**:
- Config backup integration
- Discovery validation framework
- Discovery playbook library
- Advanced agent tools

**Success Criteria**:
- Configs backed up during discovery
- Validation catches data errors
- Playbooks automate common tasks

### Phase 2 Success Metrics
- Nautobot apps integrated and operational
- Support for 3+ network vendors via apps
- Automatic topology discovery
- Bulk discovery of 100+ devices
- Natural language discovery interface
- 95%+ discovery success rate
- 50% reduction in Phase 2 development time

### Why This Approach is Better

**Advantages**:
- ✅ **Faster development**: 2-3 weeks vs 3-4 weeks
- ✅ **Battle-tested code**: Mature, community-supported apps
- ✅ **Less maintenance**: Apps maintained by Nautobot community
- ✅ **Multi-vendor support**: Apps already support many vendors
- ✅ **AI focus**: Spend time on AI orchestration, not device drivers
- ✅ **Natural language**: Unique value-add for AI agent
- ✅ **Proven reliability**: Apps used in production by many organizations

**AI Agent Value-Add**:
- 🤖 Natural language discovery interface
- 🤖 Intelligent error handling and retry logic
- 🤖 Contextual decision-making
- 🤖 Automated workflow orchestration
- 🤖 Discovery result analysis and reporting
- 🤖 Proactive issue detection

---

## Phase 3: Advanced Observability

**Goal**: Build comprehensive observability with pre-built dashboards, alerting, and anomaly detection.

**Duration**: 4-5 weeks
**Prerequisites**: Phase 1 complete, Phase 2 in progress

### Objectives

1. Create pre-built Grafana dashboards
2. Implement SNMP polling system
3. Build streaming telemetry collectors
4. Add anomaly detection
5. Implement intelligent alerting

### Milestones

#### Milestone 3.1: SNMP Polling System (Week 1)
**Tasks**:
- [ ] Create SNMP poller service
  - Implement in Python with asyncio
  - Support SNMPv2c and SNMPv3
  - Efficient bulk operations
- [ ] Build SNMP MIB parser
  - Parse standard MIBs (IF-MIB, HOST-RESOURCES, etc.)
  - Vendor-specific MIB support
  - OID-to-name translation
- [ ] Implement metric collection
  - Interface statistics (utilization, errors, discards)
  - CPU and memory metrics
  - Environmental metrics (temperature, power)
- [ ] Forward metrics to VictoriaMetrics
  - Prometheus exposition format
  - Metric labeling and tagging
  - Cardinality management

**Deliverables**:
- `services/snmp-poller/` directory with poller service
- Docker container for SNMP poller
- Updated docker-compose.yml
- Configuration for polling intervals and OIDs

**Success Criteria**:
- SNMP poller runs continuously
- Metrics are collected from all devices every 30-60 seconds
- Metrics are successfully stored in VictoriaMetrics

#### Milestone 3.2: Streaming Telemetry (Week 1-2)
**Tasks**:
- [ ] Implement gNMI collector
  - gNMI subscription support
  - Support for on-change and sample subscriptions
  - TLS/authentication handling
- [ ] Add model-driven telemetry support
  - YANG model parsing
  - Cisco MDT support
  - Juniper JTI support
- [ ] Enhance Vector pipeline
  - gRPC source configuration
  - Protocol buffer decoding
  - Metric normalization
- [ ] Create telemetry configuration generator
  - Auto-generate device telemetry configs
  - Deploy via agent

**Deliverables**:
- gNMI collector service
- Enhanced Vector configuration
- Telemetry config templates

**Success Criteria**:
- Streaming telemetry data flows to VictoriaMetrics
- Sub-second metric resolution for critical metrics
- Supports at least 2 streaming telemetry protocols

#### Milestone 3.3: Pre-built Dashboards (Week 2-3)
**Tasks**:
- [ ] Create network overview dashboard
  - Total device count and status
  - Network health score
  - Recent events/alerts
  - Top talkers and errors
- [ ] Create per-device dashboards
  - Interface statistics graphs
  - CPU and memory trends
  - Environmental metrics
  - Error rate graphs
- [ ] Create capacity planning dashboard
  - Interface utilization trends
  - Growth projections
  - Capacity alerts
- [ ] Create SLA monitoring dashboard
  - Uptime tracking
  - Latency monitoring
  - Packet loss metrics
- [ ] Add dashboard provisioning
  - Auto-provision dashboards on startup
  - Dashboard-as-code in Git

**Deliverables**:
- `grafana/dashboards/` directory with JSON definitions
- Dashboard screenshots in documentation
- Dashboard customization guide

**Success Criteria**:
- 5+ pre-built dashboards available
- Dashboards automatically provisioned on stack startup
- Dashboards provide actionable insights

#### Milestone 3.4: Anomaly Detection (Week 3-4)
**Tasks**:
- [ ] Implement baseline learning
  - Collect normal behavior metrics
  - Statistical baseline computation
  - Time-series pattern analysis
- [ ] Create anomaly detection algorithms
  - Standard deviation-based detection
  - Machine learning models (optional)
  - Seasonal trend analysis
- [ ] Build anomaly scoring system
  - Anomaly severity scoring
  - Context-aware anomaly evaluation
  - False positive reduction
- [ ] Add AI agent anomaly tool
  - Query anomalies via agent
  - Automatic anomaly investigation
  - Root cause analysis

**Deliverables**:
- `services/anomaly-detector/` service
- Anomaly detection configuration
- Integration with AI agent

**Success Criteria**:
- System learns normal behavior patterns
- Anomalies are detected with <10% false positive rate
- Agent can explain detected anomalies

#### Milestone 3.5: Intelligent Alerting (Week 4-5)
**Tasks**:
- [ ] Configure Grafana alerting
  - Alert rules for common issues
  - Multi-condition alerts
  - Alert grouping and deduplication
- [ ] Implement alert routing
  - Integration with PagerDuty, Slack, etc.
  - Priority-based routing
  - Escalation policies
- [ ] Add AI agent alert tool
  - Agent receives alerts
  - Automatic investigation
  - Suggested remediation
- [ ] Create alert playbooks
  - Standard response procedures
  - Agent-executable remediation

**Deliverables**:
- Grafana alert rule definitions
- Alert routing configuration
- Agent alert handling tools
- Alert playbook library

**Success Criteria**:
- Critical issues generate alerts within 1 minute
- Alerts are routed to appropriate teams
- Agent can automatically investigate and suggest fixes

### Phase 3 Success Metrics
- 5+ pre-built dashboards operational
- SNMP polling all devices every 60 seconds
- Streaming telemetry for critical devices
- Anomaly detection with <10% false positive rate
- Alert response time under 1 minute

---

## Phase 4: Config Management

**Goal**: Implement comprehensive configuration management with templates, drift detection, compliance checking, and safe rollback.

**Duration**: 4-6 weeks
**Prerequisites**: Phase 1 complete, Phase 2 recommended

### Objectives

1. Generate configurations from templates
2. Detect and remediate configuration drift
3. Implement compliance checking
4. Create change approval workflows
5. Build safe rollback mechanisms

### Milestones

#### Milestone 4.1: Config Template System (Week 1-2)
**Tasks**:
- [ ] Choose templating engine
  - Jinja2 integration
  - Template inheritance
  - Custom filters and tests
- [ ] Create template library
  - Base templates per vendor/platform
  - Feature-specific templates (VLANs, routing, ACLs)
  - Golden config templates
- [ ] Build template rendering engine
  - Variable substitution from Nautobot
  - Validation before deployment
  - Dry-run capability
- [ ] Add AI agent template generation
  - Natural language to template
  - Template customization via agent
  - Template library search

**Deliverables**:
- `agent/templates/` directory with config templates
- Template rendering module
- Template validation tools
- Agent tools for template operations

**Success Criteria**:
- Agent can generate configs from templates
- Templates support all major vendors
- Generated configs pass validation

#### Milestone 4.2: Configuration Deployment (Week 2-3)
**Tasks**:
- [ ] Implement config deployment methods
  - SSH/CLI deployment
  - NETCONF deployment
  - API-based deployment (RESTCONF, eAPI, etc.)
- [ ] Add pre-deployment checks
  - Syntax validation
  - Impact analysis
  - Rollback plan verification
- [ ] Create deployment strategies
  - Atomic commits
  - Partial deployments
  - Scheduled deployments
- [ ] Build deployment tracking
  - Change history in Nautobot
  - Deployment logs
  - Success/failure tracking

**Deliverables**:
- `agent/tools/config_deployment.py` module
- Deployment validation framework
- Change tracking integration

**Success Criteria**:
- Configs deployed successfully without manual intervention
- Failed deployments automatically roll back
- All changes are tracked in Nautobot

#### Milestone 4.3: Drift Detection (Week 3-4)
**Tasks**:
- [ ] Implement config backup scheduling
  - Automatic daily/hourly backups
  - Backup storage in Git
  - Backup retention policies
- [ ] Create config comparison engine
  - Line-by-line diff
  - Semantic diff (ignore comments, whitespace)
  - Vendor-specific parsing
- [ ] Build drift detection system
  - Compare running vs. intended config
  - Identify unauthorized changes
  - Calculate drift severity
- [ ] Add AI agent drift analysis
  - Explain drift in natural language
  - Suggest remediation
  - Auto-remediation for approved changes

**Deliverables**:
- Config backup service
- Git repository for config storage
- Drift detection engine
- Agent drift analysis tools

**Success Criteria**:
- All configs backed up daily
- Drift detected within 1 hour
- Agent can explain and remediate drift

#### Milestone 4.4: Compliance Checking (Week 4-5)
**Tasks**:
- [ ] Create compliance rule engine
  - Define compliance rules
  - Support for multiple standards (PCI-DSS, HIPAA, etc.)
  - Custom rule creation
- [ ] Implement compliance scanning
  - Scan configs against rules
  - Generate compliance reports
  - Track compliance over time
- [ ] Build remediation workflows
  - Auto-generate remediation configs
  - Compliance fix suggestions
  - Scheduled remediation
- [ ] Add compliance dashboards
  - Compliance score per device
  - Trending and historical data
  - Non-compliant device list

**Deliverables**:
- `agent/compliance/` module with rule engine
- Compliance rule library
- Compliance reports in Grafana
- Agent compliance tools

**Success Criteria**:
- Compliance rules cover 90%+ of common standards
- Compliance scanning completes in <10 minutes for 100 devices
- Non-compliant configs are identified and reported

#### Milestone 4.5: Change Management & Rollback (Week 5-6)
**Tasks**:
- [ ] Implement change request system
  - Create change tickets
  - Approval workflows
  - Change scheduling
- [ ] Build approval process
  - Multi-level approval
  - Integration with ticketing systems
  - Emergency change bypass
- [ ] Create rollback mechanisms
  - Checkpoint/restore support
  - Config version tracking
  - Automatic rollback on failure
- [ ] Add change validation
  - Pre-change validation
  - Post-change validation
  - Network state verification

**Deliverables**:
- Change management module
- Approval workflow system
- Rollback automation tools
- Validation framework

**Success Criteria**:
- All changes require approval (unless emergency)
- Failed changes automatically roll back
- Rollback success rate >95%

### Phase 4 Success Metrics
- Config templates for 3+ vendors
- 100% of devices backed up daily
- Drift detected and reported within 1 hour
- Compliance scanning covers major standards
- Safe rollback available for all changes

---

## Phase 5: Autonomous Operations

**Goal**: Enable truly autonomous network operations with self-healing, proactive issue detection, and multi-agent orchestration.

**Duration**: 6-8 weeks
**Prerequisites**: Phases 1-4 complete

### Objectives

1. Implement self-healing capabilities
2. Build proactive issue detection
3. Add predictive analytics
4. Create capacity planning automation
5. Implement multi-agent orchestration

### Milestones

#### Milestone 5.1: Self-Healing Framework (Week 1-2)
**Tasks**:
- [ ] Define self-healing policies
  - Issue → Remediation mapping
  - Safety constraints
  - Escalation criteria
- [ ] Implement automatic remediation
  - Common issue auto-fix (interface flapping, routing loops)
  - Service restart/reload automation
  - Configuration corrections
- [ ] Build safety mechanisms
  - Change impact analysis
  - Automatic rollback on failure
  - Human-in-the-loop for critical changes
- [ ] Create remediation playbooks
  - Playbook library for common issues
  - AI agent playbook execution
  - Playbook effectiveness tracking

**Deliverables**:
- `agent/self_healing/` module
- Remediation playbook library
- Safety constraint configuration
- Self-healing dashboard

**Success Criteria**:
- Common issues resolved without human intervention
- Self-healing success rate >90%
- No unintended consequences from auto-remediation

#### Milestone 5.2: Proactive Issue Detection (Week 2-3)
**Tasks**:
- [ ] Implement health scoring
  - Device health metrics
  - Network segment health
  - Overall network health
- [ ] Create issue prediction models
  - Predict device failures
  - Predict capacity exhaustion
  - Predict performance degradation
- [ ] Build early warning system
  - Alert before issues occur
  - Recommended preventive actions
  - Risk scoring
- [ ] Add AI agent proactive tool
  - Query predicted issues
  - Automatic investigation
  - Preventive action suggestions

**Deliverables**:
- Health scoring system
- Prediction models
- Early warning alerts
- Agent proactive monitoring tools

**Success Criteria**:
- Issues predicted 24-48 hours in advance
- Prediction accuracy >70%
- Preventive actions reduce incidents by 30%+

#### Milestone 5.3: Predictive Analytics (Week 3-4)
**Tasks**:
- [ ] Build time-series forecasting
  - Traffic growth forecasting
  - Utilization forecasting
  - Error rate trends
- [ ] Implement anomaly prediction
  - Predict future anomalies
  - Seasonal pattern recognition
  - Baseline evolution
- [ ] Create impact analysis
  - Predict change impact
  - Simulate network changes
  - Risk assessment
- [ ] Add predictive dashboards
  - Growth projections
  - Capacity exhaustion timelines
  - Risk heat maps

**Deliverables**:
- Time-series forecasting module
- Impact analysis tools
- Predictive dashboards in Grafana
- Agent predictive query tools

**Success Criteria**:
- Accurate forecasts for 30-90 day horizons
- Impact analysis predicts issues before deployment
- Capacity planning automated

#### Milestone 5.4: Capacity Planning Automation (Week 4-5)
**Tasks**:
- [ ] Implement resource tracking
  - Interface capacity tracking
  - Device resource utilization
  - License usage tracking
- [ ] Build growth analysis
  - Historical growth trends
  - Growth projections
  - Capacity exhaustion alerts
- [ ] Create capacity recommendations
  - Upgrade recommendations
  - Circuit additions
  - Device replacements
- [ ] Add capacity reports
  - Executive summary reports
  - Detailed capacity analysis
  - Budget planning data

**Deliverables**:
- Capacity tracking system
- Growth analysis tools
- Capacity planning reports
- Agent capacity planning tools

**Success Criteria**:
- Capacity exhaustion predicted 6+ months in advance
- Upgrade recommendations are accurate and actionable
- Reports reduce manual capacity planning effort by 80%+

#### Milestone 5.5: Multi-Agent Orchestration (Week 5-8)
**Tasks**:
- [ ] Design multi-agent architecture
  - Specialized agents (discovery, remediation, analysis, etc.)
  - Agent communication protocol
  - Task delegation system
- [ ] Implement agent coordination
  - Orchestrator agent
  - Task queue and scheduling
  - Agent state management
- [ ] Build collaborative workflows
  - Multi-step operations spanning agents
  - Parallel task execution
  - Result aggregation
- [ ] Create agent monitoring
  - Agent health monitoring
  - Performance metrics
  - Task success tracking
- [ ] Add advanced agent capabilities
  - Learning from past actions
  - Strategy optimization
  - Collaborative problem-solving

**Deliverables**:
- Multi-agent architecture design
- Agent orchestration system
- Collaborative workflow examples
- Agent monitoring dashboard

**Success Criteria**:
- 3+ specialized agents working together
- Complex workflows executed automatically
- Agent orchestration reduces task completion time by 50%+

### Phase 5 Success Metrics
- 90%+ self-healing success rate for common issues
- Issues predicted 24-48 hours in advance
- 30%+ reduction in incidents through proactive detection
- Capacity planning fully automated
- Multi-agent system handles complex operations autonomously

---

## Implementation Best Practices

### Development Workflow
1. **Feature branches**: Create feature branch for each milestone
2. **Code review**: All code reviewed before merge
3. **Testing**: Unit tests, integration tests, end-to-end tests
4. **Documentation**: Update docs with each feature
5. **Incremental rollout**: Deploy to test environment before production

### Quality Gates
- **Code coverage**: Maintain >80% test coverage
- **Performance**: No degradation with new features
- **Security**: Security review for authentication/credentials
- **Documentation**: All features documented
- **User testing**: Key features validated by users

### Risk Management
- **Rollback plan**: Every phase has rollback capability
- **Staged rollout**: New features deployed gradually
- **Monitoring**: Comprehensive monitoring for new features
- **Incident response**: Clear escalation paths
- **Backup strategies**: Data backups before major changes

---

## Success Criteria Summary

### Phase 2
- ✅ 3+ network vendors supported
- ✅ Automatic topology discovery
- ✅ 100+ devices discovered in bulk
- ✅ Secure credential management

### Phase 3
- ✅ 5+ Grafana dashboards
- ✅ SNMP polling operational
- ✅ Streaming telemetry for critical devices
- ✅ Anomaly detection with <10% false positives

### Phase 4
- ✅ Config templates for 3+ vendors
- ✅ Daily config backups for all devices
- ✅ Drift detection within 1 hour
- ✅ Compliance scanning operational

### Phase 5
- ✅ 90%+ self-healing success rate
- ✅ 24-48 hour issue prediction
- ✅ 30%+ incident reduction
- ✅ Multi-agent orchestration functional

---

## Next Steps

To begin Phase 2:

1. **Review and approve** this roadmap
2. **Create GitHub milestones** for Phase 2
3. **Set up development environment** for multi-vendor testing
4. **Acquire test devices** or simulators (vEOS, vMX, etc.)
5. **Begin Milestone 2.1** (Multi-Vendor Support)

For questions or suggestions, please open an issue or discussion in the repository.
