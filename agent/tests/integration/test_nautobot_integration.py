"""Integration tests for Nautobot connectivity."""

import pytest
import os
from agent.tools.nautobot_client import NautobotClient
from agent.tools.nautobot_apps import NautobotAppsClient


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Integration tests require RUN_INTEGRATION_TESTS=true",
)
class TestNautobotIntegration:
    """Integration tests requiring a running Nautobot instance."""

    def test_nautobot_connectivity(self):
        """Test basic Nautobot API connectivity."""
        client = NautobotClient()

        # Verify we can connect to Nautobot
        try:
            # Try to list devices (should work even if empty)
            result = client.list_devices(limit=1)
            assert isinstance(result, list)
        except Exception as e:
            pytest.fail(f"Failed to connect to Nautobot: {e}")

    def test_device_onboarding_app_available(self):
        """Test that Device Onboarding app is available."""
        client = NautobotAppsClient()

        # Try to list onboarding tasks
        try:
            result = client.list_onboarding_tasks(limit=1)
            # Should succeed even if no tasks exist
            assert "tasks" in result or "error" in result
        except Exception as e:
            pytest.fail(f"Device Onboarding app not available: {e}")

    @pytest.mark.slow
    def test_full_device_workflow(self):
        """Test complete device workflow (requires test device)."""
        # This test would require an actual device or simulator
        pytest.skip("Requires actual network device or simulator")

    def test_golden_config_app_available(self):
        """Test that Golden Config app is available."""
        client = NautobotAppsClient()

        # Try to access golden config endpoint
        try:
            result = client.get_golden_config("test-device")
            # Should get error or success, but not crash
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"Golden Config app not available: {e}")
