# Convergence

AI-Driven Network Observability and Automation

## Overview

Convergence is an intelligent network automation platform that combines:
- **Nautobot** as the source of truth for network inventory and state
- **AI Agents** powered by LangGraph for autonomous network operations
- **Observability Stack** (VictoriaMetrics + Grafana) for metrics and visualization
- **Vector** for telemetry pipeline and data transformation

## Architecture

### Core Components

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   Devices   │─────▶│    Vector    │─────▶│ VictoriaMetrics │
│ (Syslog/    │      │  (Telemetry  │      │   (Metrics)     │
│  SNMP)      │      │   Pipeline)  │      └────────┬────────┘
└─────────────┘      └──────────────┘               │
      │                                              │
      │ SSH/NETCONF                                  │
      ▼                                              ▼
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│  AI Agent   │◀────▶│   Nautobot   │      │    Grafana      │
│ (LangGraph) │      │   (Source    │      │ (Visualization) │
│             │      │  of Truth)   │      │                 │
└─────────────┘      └──────────────┘      └─────────────────┘
```

### Features

- **Autonomous Device Discovery**: AI agent discovers devices and populates Nautobot
- **Configuration Management**: Backup configs, detect drift, generate configurations
- **Observability**: Collect and visualize network metrics and logs
- **Natural Language Interface**: Query and control your network using plain English

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12 or 3.13
- OpenAI or Anthropic API key
- Network devices accessible via SSH (for agent operations)

### 1. Infrastructure Setup

Clone the repository and set up environment variables:

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
vim .env  # Add your API keys and credentials
```

Start the infrastructure stack:

```bash
# Start all services
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f
```

Services will be available at:
- **Nautobot**: http://localhost:8000 (admin/admin)
- **Grafana**: http://localhost:3000 (admin/admin)
- **VictoriaMetrics**: http://localhost:8428
- **Vector API**: http://localhost:8686

### 2. Agent Setup

Navigate to the agent directory and run setup:

```bash
cd agent

# Run setup script (creates venv and installs dependencies)
./setup.sh

# Or manually:
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### 3. Configure Agent

Edit the `.env` file in the project root with your credentials:

```env
# Required: Choose one LLM provider
OPENAI_API_KEY=sk-...
# OR
ANTHROPIC_API_KEY=sk-ant-...

# Nautobot (default values work with docker-compose)
NAUTOBOT_URL=http://localhost:8000
NAUTOBOT_API_TOKEN=0123456789abcdef0123456789abcdef01234567

# Network device credentials
NETWORK_USERNAME=admin
NETWORK_PASSWORD=your_password
NETWORK_ENABLE_PASSWORD=your_enable_password
```

## Usage

### CLI Commands

The agent provides a CLI interface for common operations:

```bash
# Activate the virtual environment
source venv/bin/activate

# View help
python -m agent.main --help

# Discover a device and populate Nautobot
python -m agent.main discover 192.168.1.1 --device-type cisco_ios

# Audit devices for config drift
python -m agent.main audit --site datacenter-1

# Free-form query
python -m agent.main query "What devices are offline?"
python -m agent.main query "Backup configs for all routers in site HQ"
python -m agent.main query "Show me interfaces with high error rates"

# View current configuration
python -m agent.main config
```

### Agent Capabilities

The AI agent has access to these tools:

**Nautobot Tools:**
- `get_device`: Retrieve device information by name
- `list_devices`: List devices (with optional site filter)
- `create_device`: Add new device to Nautobot
- `update_device`: Update device information
- `get_device_config_context`: Get device configuration context

**Device Tools:**
- `run_command`: Execute CLI commands on devices
- `get_device_facts`: Gather device information (version, serial, uptime)
- `get_interfaces`: Retrieve interface status
- `backup_config`: Backup running configuration

### Example Workflows

**Device Discovery:**
```bash
python -m agent.main query "Connect to router 10.0.1.1 (cisco_ios), \
  discover its details, and create it in Nautobot under site 'HQ'"
```

**Configuration Audit:**
```bash
python -m agent.main query "For all devices in Nautobot, \
  connect and backup their configs, then report any devices that are unreachable"
```

**Troubleshooting:**
```bash
python -m agent.main query "Check interface status on switch 10.0.2.5 \
  and tell me which interfaces are down"
```

## Development

### Project Structure

```
convergence/
├── docker-compose.yml       # Infrastructure services
├── .env.example            # Environment variables template
├── vector/
│   └── vector.toml         # Vector telemetry pipeline config
├── grafana/
│   └── provisioning/       # Grafana datasource configs
└── agent/
    ├── pyproject.toml      # Python dependencies
    ├── setup.sh            # Setup script
    └── agent/
        ├── main.py         # CLI entry point
        ├── config/
        │   └── settings.py # Configuration management
        ├── agents/
        │   └── network_agent.py  # LangGraph agent
        └── tools/
            ├── nautobot_client.py  # Nautobot API tools
            └── device_tools.py     # Device interaction tools
```

### Adding New Tools

To add new capabilities to the agent:

1. Create a new tool in [agent/tools/](agent/tools/)
2. Use the `@tool` decorator from LangChain
3. Add the tool to the tools list in [network_agent.py](agent/agent/agents/network_agent.py#L25-L34)

Example:
```python
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> dict:
    """Tool description for the LLM.

    Args:
        param: Parameter description

    Returns:
        Result dictionary
    """
    # Implementation
    return {"result": "success"}
```

### Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (coming soon)
pytest

# Code formatting
black agent/
ruff check agent/
```

## Observability

### Metrics Collection

Vector collects:
- Syslog messages (UDP port 514)
- SNMP traps (UDP port 162)
- Streaming telemetry (gRPC port 9000)

Configure your devices to send logs/traps to the Docker host IP.

### Grafana Dashboards

Access Grafana at http://localhost:3000 to:
- Visualize network metrics
- Create alerts
- Build custom dashboards

VictoriaMetrics is pre-configured as a datasource.

## Roadmap

- [ ] Phase 1: Foundation ✅
  - [x] Docker-compose stack
  - [x] Basic agent scaffold
  - [x] Nautobot integration
  - [x] Device connectivity

- [ ] Phase 2: Enhanced Discovery
  - [ ] Multi-vendor support (Arista, Juniper, etc.)
  - [ ] Bulk discovery workflows
  - [ ] CDP/LLDP neighbor discovery
  - [ ] Automated topology mapping

- [ ] Phase 3: Advanced Observability
  - [ ] Pre-built Grafana dashboards
  - [ ] Anomaly detection
  - [ ] Predictive analytics
  - [ ] Custom metric collectors

- [ ] Phase 4: Config Management
  - [ ] Config template generation
  - [ ] Drift detection and remediation
  - [ ] Change approval workflows
  - [ ] Rollback mechanisms
  - [ ] Compliance checking

- [ ] Phase 5: Autonomous Operations
  - [ ] Self-healing capabilities
  - [ ] Proactive issue detection
  - [ ] Capacity planning
  - [ ] Multi-agent orchestration

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

See [LICENSE](LICENSE) file for details.
