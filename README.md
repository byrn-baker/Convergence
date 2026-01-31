# Convergence

[![CI/CD](https://github.com/byrn-baker/Convergence/actions/workflows/ci.yml/badge.svg)](https://github.com/byrn-baker/Convergence/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

AI-Driven Network Observability and Automation

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Development](#development)
- [Testing](#testing)
- [Observability](#observability)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

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

### Key Features

#### 🤖 AI-Powered Automation
- **Natural Language Interface**: Control your network using plain English commands
- **Autonomous Agent**: LangGraph-powered agent that plans and executes complex workflows
- **Tool Orchestration**: AI agent intelligently selects and chains tools to accomplish tasks
- **Multi-LLM Support**: Works with OpenAI (GPT-4) and Anthropic (Claude) models

#### 🔍 Network Discovery & Management
- **Autonomous Device Discovery**: AI agent discovers devices and populates Nautobot
- **Multi-Vendor Support**: Cisco IOS, IOS-XE, NX-OS, and more (Netmiko-based)
- **Configuration Management**: Backup, restore, compare, and track configuration changes
- **Nautobot Integration**: Full CRUD operations for devices, sites, and inventory

#### 📊 Observability & Monitoring
- **Telemetry Pipeline**: Vector-based collection of syslog, SNMP traps, and streaming telemetry
- **Time-Series Storage**: VictoriaMetrics for efficient metrics storage and querying
- **Visualization**: Grafana dashboards for real-time network insights
- **Centralized Logging**: Aggregate and analyze logs from all network devices

#### 🧪 Production-Ready Development
- **Comprehensive Testing**: 36+ unit tests with 88.6% coverage
- **CI/CD Pipeline**: Automated testing, linting, and security scans
- **Type Safety**: Full mypy type checking
- **Code Quality**: Black formatting and Ruff linting

## Quick Start

### One-Command Quickstart

For the fastest setup experience:

```bash
git clone https://github.com/byrn-baker/Convergence.git
cd Convergence
cp .env.example .env
# Edit .env with your API keys
./quickstart.sh
```

This will start all services and set up the agent environment automatically.

### Prerequisites

- Docker and Docker Compose
- Python 3.12 or 3.13
- OpenAI or Anthropic API key
- Network devices accessible via SSH (for agent operations)

### Manual Setup

#### 1. Infrastructure Setup

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

#### 2. Agent Setup

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

#### 3. Configure Agent

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

Convergence has comprehensive test coverage with unit and integration tests.

```bash
# Install dev dependencies
cd agent
pip install -e ".[dev]"

# Run all tests
pytest

# Run specific test suites
pytest tests/unit/          # Unit tests only
pytest tests/integration/   # Integration tests (requires Docker services)

# Run with coverage
pytest --cov=agent --cov-report=html --cov-report=term

# Run tests using the test runner script
./run_tests.sh              # Run all tests
./run_tests.sh unit         # Unit tests only
./run_tests.sh lint         # Linting only
./run_tests.sh security     # Security scans

# Code formatting and linting
black agent/
ruff check agent/
mypy agent/
```

**Test Coverage:**
- 36 unit tests covering all core modules
- Integration tests for Nautobot connectivity
- 88.6% coverage on core modules
- Automated CI/CD with GitHub Actions

See [TESTING.md](TESTING.md) for detailed testing documentation.

## Documentation

Comprehensive documentation is available:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture, component diagrams, data flows, and deployment patterns
- **[TESTING.md](TESTING.md)** - Testing strategy, test execution, CI/CD pipeline details
- **[ROADMAP.md](ROADMAP.md)** - Project roadmap with 4-phase implementation plan
- **[PHASE2_GUIDE.md](PHASE2_GUIDE.md)** - Guide for integrating Nautobot apps (Device Onboarding, Golden Config)
- **[EXAMPLES.md](EXAMPLES.md)** - Usage examples and common workflows

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

### Phase 1: Foundation ✅ (Completed)
- [x] Docker-compose infrastructure stack
- [x] AI agent scaffold with LangGraph
- [x] Nautobot integration and API client
- [x] Device connectivity tools (SSH/Netmiko)
- [x] Comprehensive testing infrastructure
- [x] CI/CD pipeline with GitHub Actions
- [x] Complete documentation

### Phase 2: Enhanced Discovery (In Progress)
- [ ] Integrate Nautobot Device Onboarding app
- [ ] Integrate Golden Config app for config management
- [ ] Multi-vendor support (Arista, Juniper, Palo Alto)
- [ ] Bulk discovery workflows
- [ ] CDP/LLDP neighbor discovery
- [ ] Automated topology mapping

### Phase 3: Advanced Observability
- [ ] Pre-built Grafana dashboards
- [ ] Anomaly detection with AI
- [ ] Predictive analytics
- [ ] Custom metric collectors
- [ ] Alert correlation and intelligent routing

### Phase 4: Config Management
- [ ] AI-driven config template generation
- [ ] Drift detection and remediation
- [ ] Change approval workflows with validation
- [ ] Automated rollback mechanisms
- [ ] Compliance checking against policies

### Phase 5: Autonomous Operations
- [ ] Self-healing capabilities
- [ ] Proactive issue detection
- [ ] Capacity planning and optimization
- [ ] Multi-agent orchestration
- [ ] Natural language incident response

See [ROADMAP.md](ROADMAP.md) for detailed timeline and implementation details.

## Technology Stack

### AI & Orchestration
- **LangGraph** 0.2+ - Agent workflow orchestration
- **LangChain** 0.3+ - LLM abstraction and tool integration
- **OpenAI GPT-4** / **Anthropic Claude** - Large language models

### Network Automation
- **Nautobot** 3.0.5 - Network source of truth (DCIM, IPAM)
- **Netmiko** 4.3+ - Multi-vendor SSH connectivity
- **Nornir** 3.4+ - Network automation framework
- **Pynautobot** 2.0+ - Nautobot Python API client

### Observability Stack
- **Vector** - High-performance telemetry pipeline
- **VictoriaMetrics** - Time-series metrics database
- **Grafana** - Metrics visualization and alerting
- **PostgreSQL** - Relational database for Nautobot
- **Redis** - Caching and task queue

### Development Tools
- **Python** 3.12+ - Primary programming language
- **Pydantic** 2.0+ - Settings management and validation
- **Typer** - CLI framework
- **Rich** - Terminal formatting and output

### Testing & Quality
- **pytest** 8.0+ - Testing framework
- **pytest-cov** - Code coverage reporting
- **Black** - Code formatting
- **Ruff** - Fast Python linter
- **mypy** - Static type checking
- **Bandit** - Security vulnerability scanning

### Infrastructure
- **Docker** & **Docker Compose** - Container orchestration
- **GitHub Actions** - CI/CD automation

## Contributing

Contributions are welcome! Here's how you can help:

### Reporting Issues
- Use GitHub Issues to report bugs or request features
- Include reproduction steps, error messages, and environment details
- Check existing issues before creating a new one

### Pull Requests
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with clear commit messages
4. Add tests for new functionality
5. Ensure all tests pass (`./agent/run_tests.sh`)
6. Run linting and formatting (`black agent/ && ruff check agent/`)
7. Submit a pull request with a clear description

### Development Setup
```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/Convergence.git
cd Convergence

# Create virtual environment
cd agent
python3 -m venv venv
source venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run full test suite
./run_tests.sh
```

### Code Standards
- Follow PEP 8 style guidelines (enforced by Black and Ruff)
- Add type hints to all functions (checked by mypy)
- Write docstrings for public APIs
- Maintain test coverage above 80%
- Update documentation for new features

## License

See [LICENSE](LICENSE) file for details.

---

**Built with ❤️ for Network Engineers and AI enthusiasts**
