# Convergence Quickstart Guide

Get up and running with Convergence in minutes!

## Prerequisites

- **Docker** 20.10+ and **Docker Compose** 2.0+
- **Python** 3.12+ (for CLI toolkit)
- **Poetry** 1.8+ (for Python dependency management)
- Network devices with SNMP/syslog enabled
- At least 4GB RAM and 20GB disk space

## Quick Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/convergence.git
cd convergence
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your network credentials
vim .env
```

**Required settings in `.env`:**

```env
# Network credentials
NETWORK_USERNAME=admin
NETWORK_PASSWORD=your_password
SNMP_COMMUNITY=public

# Grafana admin password
GRAFANA_ADMIN_PASSWORD=admin

# VictoriaMetrics retention
VM_RETENTION_PERIOD=90d
```

### 3. Install Python CLI (Optional)

```bash
# Install Poetry if you don't have it
curl -sSL https://install.python-poetry.org | python3 -

# Install Convergence CLI
poetry install

# Verify installation
poetry run convergence version
```

### 4. Start the Platform

```bash
# Using Make (recommended)
make up

# Or using Docker Compose directly
docker-compose up -d
```

### 5. Verify Health

```bash
# Check all services
make health

# Or manually
curl http://localhost:3000/api/health     # Grafana
curl http://localhost:8428/health         # VictoriaMetrics
curl http://localhost:13133/              # OTEL Collector
```

## Access Points

Once the platform is running, access the following:

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Grafana | http://localhost:3000 | admin / admin |
| VictoriaMetrics | http://localhost:8428 | N/A |
| OTEL Collector Metrics | http://localhost:8888/metrics | N/A |
| OTEL Health Check | http://localhost:13133/ | N/A |

## Configure Your Network Devices

### Step 1: Add Device Configurations

Edit the device configuration files to add your network devices:

**For Cisco devices:**
```bash
vim config/otel-collector/receivers/cisco-devices.yaml
```

**For Juniper devices:**
```bash
vim config/otel-collector/receivers/juniper-devices.yaml
```

**For Arista devices:**
```bash
vim config/otel-collector/receivers/arista-devices.yaml
```

### Step 2: Configure Devices to Send Telemetry

#### Cisco IOS/IOS-XE

**SNMP Configuration:**
```cisco
! SNMPv2c
snmp-server community public RO

! Or SNMPv3 (recommended)
snmp-server group snmpv3group v3 priv
snmp-server user snmpv3user snmpv3group v3 auth sha <password> priv aes 128 <priv-password>
```

**Syslog Configuration:**
```cisco
logging host <CONVERGENCE_IP> transport udp port 514
logging trap informational
```

**Model-Driven Telemetry (MDT):**
```cisco
telemetry ietf subscription 100
 encoding encode-kvgpb
 filter xpath /interfaces/interface
 stream yang-push
 update-policy periodic 30
 receiver ip address <CONVERGENCE_IP> 6030 protocol grpc-tcp
```

#### Juniper JunOS

**SNMP Configuration:**
```junos
set snmp community public authorization read-only
set snmp trap-group convergence targets <CONVERGENCE_IP>
```

**Syslog Configuration:**
```junos
set system syslog host <CONVERGENCE_IP> any info
set system syslog host <CONVERGENCE_IP> facility-override local0
```

**JTI Streaming:**
```junos
set system services extension-service request-response grpc clear-text port 50051
set services analytics streaming-server convergence remote-address <CONVERGENCE_IP>
set services analytics streaming-server convergence remote-port 50051
set services analytics export-profile convergence local-address <DEVICE_IP>
set services analytics export-profile convergence reporting-rate 30
set services analytics sensor interfaces
set services analytics sensor interfaces export-name interfaces
set services analytics sensor interfaces resource /interfaces/
```

#### Arista EOS

**SNMP Configuration:**
```eos
snmp-server community public ro
```

**Syslog Configuration:**
```eos
logging host <CONVERGENCE_IP> 514 protocol udp
logging format timestamp traditional
```

**gNMI Streaming:**
```eos
management api gnmi
   transport grpc default
      vrf MGMT
   provider eos-native
```

### Step 3: Restart OTEL Collector

After configuring your devices:

```bash
# Restart the collector to pick up new config
make restart

# Or
docker-compose restart otel-collector
```

## Verify Data Collection

### Check OTEL Collector Logs

```bash
# View collector logs
make logs-otel

# Look for successful connections
docker-compose logs otel-collector | grep -i "started"
```

### Query VictoriaMetrics

```bash
# Check available metrics
curl -s "http://localhost:8428/api/v1/label/__name__/values" | jq

# Query specific metric
curl -s "http://localhost:8428/api/v1/query?query=up" | jq
```

### View in Grafana

1. Open Grafana: http://localhost:3000
2. Login with `admin` / `admin`
3. Navigate to **Dashboards**
4. Open **Convergence - Network Overview**

## Using the CLI

### Initialize Platform

```bash
poetry run convergence init
```

### Validate Configurations

```bash
poetry run convergence validate

# Validate specific component
poetry run convergence validate --component otel-collector
```

### Check Health

```bash
poetry run convergence health
```

### Discover Devices

```bash
# Discover specific host
poetry run convergence discover --host 192.168.1.1 --vendor cisco

# Scan subnet (future feature)
poetry run convergence discover --subnet 192.168.1.0/24
```

### View Configuration

```bash
poetry run convergence config
```

## Useful Make Commands

```bash
make up              # Start all services
make down            # Stop all services
make restart         # Restart all services
make logs            # View all logs
make logs-otel       # View OTEL Collector logs
make health          # Check service health
make validate        # Validate configurations
make clean           # Remove all data (DESTRUCTIVE!)
make test            # Run tests
make lint            # Run linting
make format          # Format code
```

## Troubleshooting

### Services Won't Start

```bash
# Check Docker logs
docker-compose logs

# Check for port conflicts
sudo lsof -i :3000  # Grafana
sudo lsof -i :8428  # VictoriaMetrics
sudo lsof -i :514   # Syslog
```

### No Metrics in Grafana

1. Check OTEL Collector is receiving data:
   ```bash
   docker-compose logs otel-collector | grep -i "receiver"
   ```

2. Check VictoriaMetrics is receiving writes:
   ```bash
   curl -s "http://localhost:8428/api/v1/label/__name__/values"
   ```

3. Verify device connectivity:
   ```bash
   # SNMP test
   snmpwalk -v2c -c public <DEVICE_IP> system

   # Syslog test
   logger -n localhost -P 514 "Test message"
   ```

### OTEL Collector Errors

```bash
# Check configuration syntax
poetry run convergence validate --component otel-collector

# Test OTEL config
docker-compose exec otel-collector /otelcol --config=/etc/otelcol/config.yaml --dry-run
```

### Permission Issues

```bash
# Fix data directory permissions
sudo chown -R $USER:$USER data/

# Fix Docker socket permissions (Linux)
sudo usermod -aG docker $USER
newgrp docker
```

## Next Steps

1. **Configure More Devices**: Add all your network devices to the configuration files
2. **Explore Dashboards**: Check out vendor-specific dashboards in Grafana
3. **Set Up Alerting**: Configure Grafana alerts for critical metrics
4. **Customize**: Modify dashboards and create custom visualizations
5. **Scale**: Review performance tuning for production deployments

## Getting Help

- **Documentation**: [docs/](../README.md)
- **Issues**: GitHub Issues
- **Examples**: [config/](../../config/) and [dashboards/](../../dashboards/)

## What's Next?

- [Architecture Overview](../architecture/README.md)
- [Vendor Configuration Guides](../vendor-configs/README.md)
- [Dashboard Customization](../dashboards/README.md)
- [Production Deployment](../production/README.md)
