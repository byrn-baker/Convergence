"""
Nautobot configuration file for Convergence.

This file extends the default Nautobot configuration with app-specific settings.
"""

# Import base Nautobot configuration
from nautobot.core.settings import *  # noqa: F403, F401

# Enable installed plugins
PLUGINS = [
    "nautobot_ssot",  # Required dependency for device onboarding
    "nautobot_device_onboarding",
    "nautobot_golden_config",
    "nautobot_device_lifecycle_mgmt",
    "nautobot_chatbot",  # AI chat interface
]

# Plugin configuration
PLUGINS_CONFIG = {
    "nautobot_device_onboarding": {
        "default_device_role": "network-device",
        "default_device_status": "active",
        "default_ip_status": "active",
        "create_platform_if_missing": True,
        "create_manufacturer_if_missing": True,
        "create_device_type_if_missing": True,
        "create_device_role_if_missing": True,
        "skip_device_type_on_update": False,
        "skip_manufacturer_on_update": False,
        "default_management_interface": "GigabitEthernet0/0",
        "default_management_prefix_length": 24,
    },
    "nautobot_golden_config": {
        "default_deploy_status": "Not Approved",
        "per_feature_bar_width": 0.15,
        "per_feature_width": 13,
        "per_feature_height": 4,
        "enable_backup": True,
        "enable_compliance": True,
        "enable_intended": True,
        "enable_sotagg": True,
        "sot_agg_transposer": None,
    },
    "nautobot_device_lifecycle_mgmt": {
        "barchart_bar_width": 0.1,
        "barchart_width": 12,
        "barchart_height": 5,
    },
    "nautobot_chatbot": {
        "agent_service_url": "http://agent-service:8080",
    },
}
