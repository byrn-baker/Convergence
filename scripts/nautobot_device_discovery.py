#!/usr/bin/env python3
"""
Nautobot Device Discovery for OTEL Collector Configuration

Queries Nautobot GraphQL API to get device information and generates
OTEL Collector SNMP receiver configurations with proper labels.

Usage:
    python nautobot_device_discovery.py --generate-config
    python nautobot_device_discovery.py --list-devices
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, List
from pathlib import Path
import yaml

# Manually load .env file if it exists (overrides existing env vars)
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ[key] = value  # Override existing env vars

# Configuration from environment
NAUTOBOT_URL = os.getenv('NAUTOBOT_URL', 'http://nautobot:8000')
NAUTOBOT_TOKEN = os.getenv('NAUTOBOT_TOKEN', '')
NAUTOBOT_VERIFY_SSL = os.getenv('NAUTOBOT_VERIFY_SSL', 'true').lower() == 'true'
SNMP_COMMUNITY = os.getenv('SNMP_COMMUNITY', 'public')

# Disable SSL warnings in development when using self-signed certs
if not NAUTOBOT_VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    print("⚠️  SSL verification disabled (development mode)")


def get_nautobot_devices() -> List[Dict]:
    """
    Query Nautobot GraphQL API to get all network devices with management IPs.

    Returns:
        List of device dictionaries with name, IP, vendor, role, site
    """
    if not NAUTOBOT_TOKEN:
        print("ERROR: NAUTOBOT_TOKEN not set in environment")
        sys.exit(1)

    headers = {
        'Authorization': f'Token {NAUTOBOT_TOKEN}',
        'Content-Type': 'application/json',
    }

    # GraphQL query to get all device data in one request
    graphql_query = """
    query {
      devices {
        name
        primary_ip4 {
          host
        }
        device_type {
          model
          manufacturer {
            name
          }
        }
        role {
          name
        }
        location {
          name
        }
        status {
          name
        }
      }
    }
    """

    url = f"{NAUTOBOT_URL}/api/graphql/"

    try:
        response = requests.post(
            url,
            headers=headers,
            json={'query': graphql_query},
            timeout=30,
            verify=NAUTOBOT_VERIFY_SSL
        )
        response.raise_for_status()
        data = response.json()

        if 'errors' in data:
            print(f"ERROR: GraphQL query failed: {data['errors']}")
            sys.exit(1)

        devices = []
        for device in data.get('data', {}).get('devices', []):
            # Extract device information from GraphQL response
            primary_ip4 = device.get('primary_ip4')
            ip = primary_ip4.get('host', 'unavailable') if primary_ip4 else 'unavailable'

            device_type = device.get('device_type', {})
            model = device_type.get('model', 'unknown') if device_type else 'unknown'

            manufacturer = device_type.get('manufacturer', {}) if device_type else {}
            vendor = manufacturer.get('name', 'unknown') if manufacturer else 'unknown'

            role = device.get('role', {})
            role_name = role.get('name', 'unknown') if role else 'unknown'

            location = device.get('location', {})
            site = location.get('name', 'unknown') if location else 'unknown'

            status = device.get('status', {})
            status_name = status.get('name', 'unknown') if status else 'unknown'

            # Only include devices with primary IPs
            if ip and ip != 'unavailable':
                device_info = {
                    'name': device.get('name', 'unknown'),
                    'ip': ip,
                    'vendor': vendor,
                    'model': model,
                    'role': role_name,
                    'site': site,
                    'status': status_name,
                }
                devices.append(device_info)

        print(f"✅ Found {len(devices)} devices with primary IPs in Nautobot")
        return devices

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to query Nautobot GraphQL API: {e}")
        sys.exit(1)


def generate_otel_snmp_receiver(device: Dict) -> Dict:
    """
    Generate OTEL Collector SNMP receiver configuration for a device.
    
    Args:
        device: Device info dictionary from Nautobot
        
    Returns:
        OTEL receiver configuration dictionary
    """
    receiver_name = f"snmp/{device['name'].lower().replace(' ', '-')}"
    
    config = {
        receiver_name: {
            'collection_interval': '60s',
            'endpoint': f"udp://{device['ip']}:161",
            'version': 'v2c',
            'community': '${env:SNMP_COMMUNITY}',
            'attributes': {
                'interface.name': {
                    'oid': '1.3.6.1.2.1.2.2.1.2',
                    'indexed_value_prefix': ''
                },
                'interface.description': {
                    'oid': '1.3.6.1.2.1.31.1.1.1.18',
                    'indexed_value_prefix': ''
                }
            },
            'metrics': {
                'system.uptime': {
                    'unit': 's',
                    'gauge': {
                        'value_type': 'int'
                    },
                    'scalar_oids': [
                        {'oid': '1.3.6.1.2.1.1.3.0'}
                    ]
                },
                'interface.in.octets': {
                    'unit': 'By',
                    'sum': {
                        'aggregation': 'cumulative',
                        'monotonic': True,
                        'value_type': 'int'
                    },
                    'column_oids': [
                        {
                            'oid': '1.3.6.1.2.1.2.2.1.10',
                            'attributes': [
                                {'name': 'interface.name'}
                            ]
                        }
                    ]
                },
                'interface.out.octets': {
                    'unit': 'By',
                    'sum': {
                        'aggregation': 'cumulative',
                        'monotonic': True,
                        'value_type': 'int'
                    },
                    'column_oids': [
                        {
                            'oid': '1.3.6.1.2.1.2.2.1.16',
                            'attributes': [
                                {'name': 'interface.name'}
                            ]
                        }
                    ]
                },
                'interface.in.errors': {
                    'unit': '1',
                    'sum': {
                        'aggregation': 'cumulative',
                        'monotonic': True,
                        'value_type': 'int'
                    },
                    'column_oids': [
                        {
                            'oid': '1.3.6.1.2.1.2.2.1.14',
                            'attributes': [
                                {'name': 'interface.name'}
                            ]
                        }
                    ]
                }
            }
        }
    }
    
    return config


def generate_otel_attributes_processor(device: Dict) -> Dict:
    """
    Generate attributes processor config to add Nautobot metadata.
    
    Args:
        device: Device info dictionary from Nautobot
        
    Returns:
        Attributes processor configuration
    """
    processor_name = f"attributes/{device['name'].lower().replace(' ', '-')}"
    
    config = {
        processor_name: {
            'actions': [
                {'key': 'device.name', 'value': device['name'], 'action': 'insert'},
                {'key': 'device.ip', 'value': device['ip'], 'action': 'insert'},
                {'key': 'device.vendor', 'value': device['vendor'], 'action': 'insert'},
                {'key': 'device.model', 'value': device['model'], 'action': 'insert'},
                {'key': 'device.role', 'value': device['role'], 'action': 'insert'},
                {'key': 'device.site', 'value': device['site'], 'action': 'insert'},
            ]
        }
    }
    
    return config


def list_devices():
    """List all devices from Nautobot."""
    devices = get_nautobot_devices()
    
    print("\n📋 Devices in Nautobot:\n")
    for device in devices:
        print(f"  • {device['name']}")
        print(f"    IP: {device['ip']}")
        print(f"    Vendor: {device['vendor']} ({device['model']})")
        print(f"    Role: {device['role']}")
        print(f"    Site: {device['site']}")
        print(f"    Status: {device['status']}")
        print()


def generate_config_snippet():
    """Generate OTEL Collector config snippet from Nautobot devices."""
    devices = get_nautobot_devices()
    
    if not devices:
        print("⚠️  No devices found in Nautobot")
        return
    
    print("\n📝 Generated OTEL Collector Configuration:\n")
    print("=" * 80)
    print("# Add these receivers to your OTEL config:")
    print("=" * 80)
    
    receivers = {}
    processors = {}
    receiver_names = []
    processor_names = []
    
    for device in devices:
        # Only include active devices (case-insensitive)
        if device['status'].lower() != 'active':
            continue
            
        receiver_config = generate_otel_snmp_receiver(device)
        processor_config = generate_otel_attributes_processor(device)
        
        receivers.update(receiver_config)
        processors.update(processor_config)
        
        receiver_name = list(receiver_config.keys())[0]
        processor_name = list(processor_config.keys())[0]
        receiver_names.append(receiver_name)
        processor_names.append(processor_name)
    
    # Print YAML configuration
    print("\nreceivers:")
    print(yaml.dump(receivers, default_flow_style=False, indent=2))
    
    print("\nprocessors:")
    print(yaml.dump(processors, default_flow_style=False, indent=2))
    
    print("\nservice:")
    print("  pipelines:")
    print("    metrics:")
    print(f"      receivers: [otlp, prometheus, {', '.join(receiver_names)}]")
    print(f"      processors: [memory_limiter, {', '.join(processor_names)}, resource, batch]")
    print("      exporters: [prometheusremotewrite, debug]")
    
    print("\n" + "=" * 80)
    print(f"✅ Generated config for {len(receiver_names)} active devices")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Nautobot Device Discovery for OTEL Collector'
    )
    parser.add_argument(
        '--generate-config',
        action='store_true',
        help='Generate OTEL Collector config snippet'
    )
    parser.add_argument(
        '--list-devices',
        action='store_true',
        help='List all devices from Nautobot'
    )
    
    args = parser.parse_args()
    
    if args.list_devices:
        list_devices()
    elif args.generate_config:
        generate_config_snippet()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
