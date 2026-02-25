"""Prometheus metrics for the automation agent."""
from prometheus_client import Counter, Gauge, Histogram

# Total actions attempted, labelled by final status:
#   dry_run   - logged only, DRY_RUN=true
#   pending   - sent to Discord, awaiting human approval
#   success   - live action applied and verified
#   fail      - execution or verification error
#   skipped   - no_action (Claude decided safe / FP / below threshold)
automation_actions_total = Counter(
    "automation_actions_total",
    "Total automation action decisions",
    ["status"],
)

# Wall-clock time for an entire automation session (fetch → propose → execute → verify)
automation_session_duration_seconds = Histogram(
    "automation_session_duration_seconds",
    "Duration of a full automation session",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

# How many sessions are currently waiting for human approval
automation_pending_approvals = Gauge(
    "automation_pending_approvals",
    "Sessions currently awaiting human approval via Discord / API",
)

# Unix timestamp of the last successful poll cycle
automation_last_poll_timestamp = Gauge(
    "automation_last_poll_timestamp_seconds",
    "Unix timestamp of the last threat-intel poll cycle",
)

# How many IPs qualified for action consideration in total (cumulative)
automation_qualifying_ips_total = Counter(
    "automation_qualifying_ips_total",
    "Cumulative IPs that met the action threshold and passed FP filter",
)

# Actions skipped because max_actions_per_hour was reached
automation_rate_limited_total = Counter(
    "automation_rate_limited_total",
    "Actions skipped due to hourly rate limit",
)

# Audit trail git commits recorded
automation_audit_commits_total = Counter(
    "automation_audit_commits_total",
    "Total GAIT audit trail git commits written",
)
