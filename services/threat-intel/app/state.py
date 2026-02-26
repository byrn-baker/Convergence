"""Module-level state shared between scheduler and API handlers."""
from typing import Any

# Populated by the enrichment scheduler; read by /api/report
latest_report: dict[str, Any] = {}
