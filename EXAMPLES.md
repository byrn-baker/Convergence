# Convergence Agent Examples

This document provides practical examples of using the Convergence AI agent for network automation tasks.

## Discovery Examples

### Basic Device Discovery

Discover a single device and add it to Nautobot:

```bash
python -m agent.main discover 192.168.1.1 --device-type cisco_ios
```

### Custom Discovery Query

Use natural language for more complex discovery:

```bash
python -m agent.main query "Connect to 10.0.1.1 (cisco_ios), get all device info including serial number, interfaces, and add it to Nautobot under site 'Headquarters'"
```

### Bulk Discovery

Discover multiple devices:

```bash
python -m agent.main query "Discover devices at 10.0.1.1, 10.0.1.2, and 10.0.1.3 (all cisco_ios), then add them to Nautobot"
```

## Inventory Management

### List Devices

Query Nautobot for device inventory:

```bash
python -m agent.main query "Show me all devices in Nautobot"
python -m agent.main query "List all devices in site 'Datacenter-1'"
python -m agent.main query "Which devices are marked as offline?"
```

### Update Device Information

```bash
python -m agent.main query "Update device 'router-1' in Nautobot with serial number ABC123XYZ"
```

## Configuration Management

### Backup Configurations

```bash
# Backup single device
python -m agent.main query "Backup the running config from router 10.0.1.1"

# Backup all devices in a site
python -m agent.main query "Backup configs for all devices in site 'Branch-Office'"

# Backup all devices
python -m agent.main audit
```

### Configuration Audits

```bash
# Audit specific site
python -m agent.main audit --site datacenter-1

# Custom audit query
python -m agent.main query "Connect to all devices, backup their configs, and report which ones have 'logging buffered' disabled"
```

### Configuration Drift Detection

```bash
python -m agent.main query "For devices in site 'HQ', compare running config with the config context in Nautobot and report any differences"
```

## Troubleshooting

### Interface Status

```bash
python -m agent.main query "Check interface status on switch 10.0.2.5 and tell me which interfaces are down"

python -m agent.main query "Show me all interfaces on router-1 that have errors"
```

### Device Health Checks

```bash
python -m agent.main query "Check if device 10.0.1.1 is reachable and get its uptime"

python -m agent.main query "For all devices in Nautobot, try to connect and report which ones are unreachable"
```

### Command Execution

```bash
python -m agent.main query "Run 'show ip route summary' on router 10.0.1.1 and summarize the output"

python -m agent.main query "Execute 'show version' on all devices in site 'Branch-1' and tell me which ones need IOS updates"
```

## Reporting

### Compliance Reports

```bash
python -m agent.main query "Check all devices and report which ones don't have 'service password-encryption' enabled"

python -m agent.main query "Audit SSH configuration on all devices and report which ones allow version 1"
```

### Inventory Reports

```bash
python -m agent.main query "Generate a report of all device serial numbers in Nautobot"

python -m agent.main query "List all devices grouped by site and their status"

python -m agent.main query "Show me devices that don't have a primary IP address set in Nautobot"
```

### Capacity Planning

```bash
python -m agent.main query "For all switches, show me how many interfaces are used vs available"
```

## Multi-Step Workflows

### Complete Device Onboarding

```bash
python -m agent.main query "
1. Connect to new device 10.0.5.10 (cisco_ios)
2. Gather all device information
3. Create the device in Nautobot under site 'Remote-Office'
4. Backup its configuration
5. Check for any non-standard configurations
6. Provide a summary report
"
```

### Site Audit Workflow

```bash
python -m agent.main query "
For site 'Datacenter-1':
1. List all devices from Nautobot
2. Connect to each device
3. Backup configurations
4. Check for devices with high interface error rates
5. Report any unreachable devices
6. Summarize findings
"
```

### Proactive Monitoring

```bash
python -m agent.main query "
Check all devices and:
1. Report any with uptime less than 1 hour (potential reboot)
2. Show devices with CPU utilization over 80%
3. List interfaces with high error counts
4. Identify any devices not responding
"
```

## Advanced Queries

### Natural Language Analysis

```bash
python -m agent.main query "What's the most common IOS version in my network?"

python -m agent.main query "Which site has the most devices?"

python -m agent.main query "Are there any devices with duplicate serial numbers?"
```

### Contextual Queries

The agent maintains context within a task, so you can ask follow-up questions:

```bash
python -m agent.main query "
First, list all devices in site 'HQ'.
Then, for devices that are marked as 'active', connect and check if they're actually reachable.
Finally, update Nautobot to mark unreachable devices as 'offline'.
"
```

## Integration Examples

### Using with CI/CD

You can integrate the agent into automation workflows:

```bash
#!/bin/bash
# Pre-change validation script

echo "Validating network state before change..."
python -m agent.main query "Backup configs for all devices in production" > pre-change-backup.log

# Make changes...

echo "Validating network state after change..."
python -m agent.main query "Compare current configs with backups and report differences" > post-change-diff.log
```

### Scheduled Audits

Use cron for scheduled checks:

```bash
# Add to crontab for daily 2 AM audit
0 2 * * * cd /path/to/convergence/agent && source venv/bin/activate && python -m agent.main audit --site datacenter-1 >> /var/log/convergence-audit.log 2>&1
```

## Tips for Effective Queries

1. **Be Specific**: Include device type, IP addresses, and site names
2. **Use Natural Language**: The agent understands conversational requests
3. **Break Down Complex Tasks**: For multi-step operations, list steps clearly
4. **Provide Context**: Mention relevant details like sites, device roles, or specific configurations you're looking for
5. **Ask for Summaries**: End complex queries with "provide a summary" or "report findings"

## Error Handling

The agent will report errors clearly:

```bash
python -m agent.main query "Connect to 192.168.1.99"
# If unreachable, agent will report: "Failed to connect to 192.168.1.99: Connection timeout"
```

You can ask the agent to handle errors gracefully:

```bash
python -m agent.main query "Try to connect to devices in site 'Branch', and for any unreachable devices, just note them in the report and continue"
```

## Configuration

Check current agent configuration:

```bash
python -m agent.main config
```

This shows:
- Nautobot URL and connection status
- LLM model being used
- Agent parameters (temperature, max iterations)
- LangChain tracing status

## Getting Help

```bash
# View available commands
python -m agent.main --help

# Get help on specific command
python -m agent.main discover --help
python -m agent.main audit --help
```

## Next Steps

- Explore [Vector configuration](vector/vector.toml) for telemetry collection
- Set up [Grafana dashboards](http://localhost:3000) for visualization
- Customize agent behavior in [settings.py](agent/agent/config/settings.py)
- Add custom tools in [agent/tools/](agent/agent/tools/)
