"""Shared in-process state for the automation agent."""
from typing import Any

# Rolling report of recent automation sessions (last 100 kept in memory)
latest_report: dict[str, Any] | None = None

# Pending human-approval sessions: session_id -> session payload
# Entries expire after 4 hours even if never actioned.
pending_approvals: dict[str, dict[str, Any]] = {}
