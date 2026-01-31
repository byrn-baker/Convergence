# Phase 2 Implementation Guide: Enhanced Discovery with Nautobot Apps

This guide explains how to implement Phase 2 of Convergence using existing Nautobot apps for accelerated development.

## Overview

Instead of building device discovery from scratch, Phase 2 leverages mature Nautobot apps:
- **Nautobot Device Onboarding**: Automated device discovery and onboarding
- **Nautobot Golden Config**: Configuration management and compliance
- **Nautobot Device Lifecycle**: Hardware lifecycle tracking

The AI agent provides:
- Natural language interface
- Intelligent orchestration
- Error handling and retry logic
- Workflow automation

## Prerequisites

- Phase 1 complete
- Docker and Docker Compose running
- Basic understanding of Nautobot
- Network devices accessible via SSH

## Setup Instructions

### Step 1: Start the Stack with Nautobot Apps

The docker-compose.yml has been updated to include Nautobot apps. Start or restart the stack:

```bash
# If stack is already running, restart Nautobot to install apps
docker-compose restart nautobot

# Or start from scratch
docker-compose down
docker-compose up -d

# Watch Nautobot logs to see app installation
docker-compose logs -f nautobot
```

The apps will be automatically installed from `nautobot_config/local_requirements.txt`.

### Step 2: Access Nautobot and Configure Apps

1. **Access Nautobot UI**: http://localhost:8000 (admin/admin)

2. **Verify Apps are Installed**:
   - Navigate to **Plugins** in the top menu
   - You should see:
     - Device Onboarding
     - Golden Config
     - Device Lifecycle Management

3. **Configure Device Onboarding**:
   - Go to **Plugins → Device Onboarding → Settings**
   - Add supported platforms:
     - Cisco IOS: `cisco_ios`
     - Cisco NX-OS: `cisco_nxos`
     - Arista EOS: `arista_eos`
     - Juniper JunOS: `juniper_junos`

4. **Set up Secrets for Device Credentials**:
   - Navigate to **Secrets → Secrets**
   - Create secrets for:
     - Device username
     - Device password
     - Enable password (if needed)
   - Create a **Secrets Group** that includes these secrets
   - Assign the secrets group to device platforms or sites

5. **Configure Sites** (if not already done):
   - Go to **Organization → Sites**
   - Create your sites (HQ, Branch-Office-1, etc.)

## Using the AI Agent for Discovery

### Example 1: Onboard a Single Device

```bash
cd agent
source venv/bin/activate

python -m agent.main query "Onboard device 192.168.1.1, platform cisco_ios, site HQ"
```

The agent will:
1. Call the Nautobot Device Onboarding API
2. Monitor the onboarding task
3. Report success or failure
4. Provide device details

### Example 2: Bulk Onboarding

```bash
python -m agent.main query "
Onboard these devices:
- 192.168.1.1 (cisco_ios, site HQ)
- 192.168.1.2 (cisco_ios, site HQ)
- 10.0.1.1 (arista_eos, site Branch-Office-1)
"
```

### Example 3: Check Onboarding Status

```bash
python -m agent.main query "What's the status of recent device onboardings?"
```

### Example 4: Site-Based Discovery

```bash
python -m agent.main query "Discover all devices in subnet 192.168.1.0/24 and add them to site HQ"
```

## Manual Testing via Nautobot UI

Before using the AI agent, test the Device Onboarding app manually:

1. **Navigate to Plugins → Device Onboarding**
2. **Click "Add Device"**
3. **Fill in details**:
   - IP Address: Device IP
   - Platform: Select from dropdown (cisco_ios, etc.)
   - Site: Optional
   - Role: Optional
4. **Click Submit**
5. **Monitor Progress**: The task will show status (Pending → Running → Completed/Failed)
6. **Check Device**: Navigate to **DCIM → Devices** to see the onboarded device

## Troubleshooting

### App Installation Issues

If apps don't install:

```bash
# Exec into Nautobot container
docker exec -it convergence-nautobot bash

# Manually install apps
pip install -r /opt/nautobot/local_requirements.txt

# Run migrations
nautobot-server migrate

# Restart
exit
docker-compose restart nautobot
```

### Connection Issues

If device onboarding fails with connection errors:

1. **Check network connectivity**:
   ```bash
   docker exec -it convergence-nautobot ping 192.168.1.1
   ```

2. **Verify credentials**:
   - Go to Secrets in Nautobot UI
   - Test credentials manually via SSH

3. **Check platform**:
   - Ensure correct platform is selected
   - cisco_ios vs cisco_nxos matters

### API Permission Issues

If API calls fail with 403:

1. **Check API token**:
   - Go to **Admin → Users → admin → Tokens**
   - Verify token matches `.env` file
   - Regenerate if needed

2. **Check user permissions**:
   - Admin user should have all permissions
   - For non-admin users, add plugin permissions

## Development: Adding Agent Tools

The AI agent has several tools for interacting with Nautobot apps. See [nautobot_apps.py](agent/agent/tools/nautobot_apps.py).

### Available Tools

| Tool | Description |
|------|-------------|
| `onboard_device` | Onboard a single device |
| `get_onboarding_status` | Check onboarding task status |
| `bulk_onboard_devices` | Onboard multiple devices |
| `list_onboarding_tasks` | List all onboarding tasks |
| `get_golden_config` | Get golden config for a device |
| `compare_config` | Compare running vs golden config |

### Adding New Tools

To add new app integration tools:

1. **Add method to `NautobotAppsClient` class** in `nautobot_apps.py`
2. **Decorate with `@tool`**
3. **Add docstring** (LLM uses this to understand the tool)
4. **Update network agent** to include the tool

Example:

```python
@tool
def my_new_tool(self, param: str) -> dict[str, Any]:
    """Description for the LLM.

    Args:
        param: Parameter description

    Returns:
        Result dictionary
    """
    endpoint = f"{self.url}/api/plugins/my-app/endpoint/"
    # Implementation...
    return {"success": True}
```

## Next Steps

After setting up Phase 2:

1. **Test Manual Onboarding**: Onboard 1-2 devices manually via UI
2. **Test Agent Onboarding**: Use agent to onboard devices via natural language
3. **Bulk Discovery**: Onboard 10+ devices to test scalability
4. **Topology Discovery**: Enable CDP/LLDP in Device Onboarding settings
5. **Move to Phase 3**: Once discovery is working, proceed to observability

## Advanced Configuration

### Custom Onboarding Workflows

Create custom workflows in `agent/agents/`:

```python
async def site_discovery_workflow(site: str, subnet: str):
    """Discover all devices in a site's subnet."""
    # 1. Scan subnet for live hosts
    # 2. Attempt onboarding for each host
    # 3. Monitor progress
    # 4. Generate report
    pass
```

### Scheduled Discovery

Use cron to schedule recurring discovery:

```bash
# Add to crontab
0 2 * * * cd /path/to/convergence/agent && source venv/bin/activate && python -m agent.main query "Re-discover all devices to update info"
```

### Integration with External Systems

Integrate with external inventory systems:

```python
# Import devices from CSV
python -m agent.main query "Import devices from /path/to/devices.csv and onboard them"

# Sync with external CMDB
python -m agent.main query "Sync device inventory with our CMDB API at https://cmdb.example.com"
```

## Resources

- [Nautobot Device Onboarding Docs](https://docs.nautobot.com/projects/device-onboarding/en/latest/)
- [Nautobot Golden Config Docs](https://docs.nautobot.com/projects/golden-config/en/latest/)
- [Nautobot API Docs](http://localhost:8000/api/docs/) (after stack is running)
- [Convergence Examples](EXAMPLES.md)

## Support

For issues:
1. Check Nautobot logs: `docker-compose logs nautobot`
2. Check app logs in Nautobot UI: **Jobs → Job Results**
3. Open an issue in the Convergence repository
