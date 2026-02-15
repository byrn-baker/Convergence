# Nautobot Device Enrichment

This guide explains how to use Nautobot as the source of truth for device metadata in Convergence.

## How It Works

1. **Nautobot** stores all device information (hostname, IP, vendor, site, role, etc.)
2. **Python script** queries Nautobot API and generates OTEL Collector configuration
3. **OTEL Collector** collects metrics with proper device labels automatically
4. **Grafana** displays metrics with accurate device names and metadata

## Setup

### 1. Configure Nautobot Access

Edit `.env` file and add your Nautobot details:

```bash
# Nautobot Configuration
NAUTOBOT_URL=http://nautobot:8000  # Your Nautobot URL
NAUTOBOT_TOKEN=your-api-token-here  # Get from Nautobot UI: Admin → API Tokens
```

**To create a Nautobot API token:**
1. Log into Nautobot
2. Go to **Admin → Users → API Tokens**
3. Click **Add** and create a new token
4. Copy the token to your `.env` file

### 2. Verify Nautobot Connection

List all devices from Nautobot:

```bash
cd /mnt/d/ubuntu-24-04-bbaker4/github-projects/Convergence
python scripts/nautobot_device_discovery.py --list-devices
```

**Expected output:**
```
✅ Found 5 devices in Nautobot

📋 Devices in Nautobot:

  • core-switch-1
    IP: 192.168.1.1
    Vendor: cisco (Catalyst 9300)
    Role: core-switch
    Site: datacenter-1
    Status: active

  • edge-switch-2
    IP: 192.168.3.2
    Vendor: cisco (Catalyst 2960)
    Role: access-switch
    Site: office-main
    Status: active
```

### 3. Generate OTEL Configuration

Generate OTEL Collector config from Nautobot:

```bash
python scripts/nautobot_device_discovery.py --generate-config > config/nautobot-devices.yaml
```

This creates SNMP receiver configs for **all active devices** in Nautobot with proper labels:
- `device.name` - Actual hostname from Nautobot
- `device.ip` - Management IP
- `device.vendor` - Manufacturer
- `device.model` - Device model
- `device.role` - Device role (core, access, etc.)
- `device.site` - Physical site location

### 4. Apply Configuration

**Option A: Manual (one-time setup)**
```bash
# Review the generated config
python scripts/nautobot_device_discovery.py --generate-config

# Copy the receivers and processors sections to config/otel-collector/config.yaml
# Update the service.pipelines section with the new receiver/processor names

# Restart OTEL Collector
docker-compose restart otel-collector
```

**Option B: Automated (recommended)**
```bash
# TODO: Add script to automatically update OTEL config and reload
./scripts/sync_nautobot_devices.sh
```

## Device Requirements in Nautobot

For devices to be discovered, they must have:

1. **Primary IPv4 address** configured
2. **Status: Active** (staging/offline devices are skipped)
3. **Device type** assigned (for vendor/model info)
4. **Site** assigned
5. **Device role** assigned

## Benefits

✅ **Single Source of Truth** - Update device name in Nautobot, metrics are automatically updated  
✅ **Rich Metadata** - Site, role, model info on every metric  
✅ **Auto-Discovery** - New devices in Nautobot = automatic monitoring  
✅ **No Manual Config** - No need to manually update OTEL config for each device  
✅ **Accurate Hostnames** - Real device names, not made-up labels  

## Metrics with Nautobot Enrichment

Before:
```
interface_in_octets_bytes_total{
  device_ip="192.168.3.2",
  device_vendor="cisco",
  interface_name="GigabitEthernet1/0/1"
}
```

After:
```
interface_in_octets_bytes_total{
  device_name="edge-switch-2",
  device_ip="192.168.3.2",
  device_vendor="cisco",
  device_model="Catalyst 2960",
  device_role="access-switch",
  device_site="office-main",
  interface_name="GigabitEthernet1/0/1"
}
```

## Grafana Queries with Enrichment

Now you can filter by real attributes:

```promql
# All interfaces at a specific site
interface_in_octets_bytes_total{device_site="datacenter-1"}

# All core switches
interface_in_octets_bytes_total{device_role="core-switch"}

# Traffic for a specific device by name
rate(interface_in_octets_bytes_total{device_name="edge-switch-2"}[5m]) * 8
```

## Automation

### Periodic Sync (Optional)

Run device discovery on a schedule to auto-discover new devices:

```bash
# Add to crontab
0 * * * * cd /path/to/Convergence && python scripts/nautobot_device_discovery.py --generate-config > config/nautobot-devices.yaml && docker-compose restart otel-collector
```

This checks Nautobot every hour for new devices and updates monitoring automatically.

## Troubleshooting

### "ERROR: NAUTOBOT_TOKEN not set"
- Make sure `.env` file has `NAUTOBOT_TOKEN=...`
- Load env vars: `source .env` or `export $(cat .env | xargs)`

### "ERROR: Failed to query Nautobot API"
- Check `NAUTOBOT_URL` is correct and Nautobot is accessible
- Verify API token is valid (check in Nautobot UI)
- Check network connectivity: `curl -H "Authorization: Token YOUR_TOKEN" http://nautobot:8000/api/dcim/devices/`

### "Found 0 devices"
- Check devices in Nautobot have:
  - Status = Active
  - Primary IP configured
  - Device type assigned

## Next Steps

1. Set up your Nautobot URL and token in `.env`
2. Run `--list-devices` to verify connection
3. Run `--generate-config` to see generated config
4. Apply config and restart OTEL Collector
5. Check Grafana - devices now have real names!
