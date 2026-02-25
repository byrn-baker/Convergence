"""Automation agent configuration via environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic (Claude Haiku for action proposals)
    anthropic_api_key: str = ""

    # Infrastructure — uses redis DB 1 to isolate from threat-intel (DB 0)
    redis_url: str = "redis://redis:6379/1"
    victoriametrics_url: str = "http://victoriametrics:8428"
    loki_url: str = "http://loki:3100"
    threat_intel_url: str = "http://threat-intel:8000"

    # pfSense — XML-RPC (primary)
    pfsense_host: str = ""          # e.g. "192.168.1.1"
    pfsense_xmlrpc_user: str = "admin"
    pfsense_xmlrpc_pass: str = ""
    pfsense_verify_ssl: bool = False

    # pfSense — SSH (fallback)
    pfsense_ssh_host: str = ""      # defaults to pfsense_host if blank
    pfsense_ssh_user: str = "admin"
    pfsense_ssh_key_path: str = "/app/secrets/pfsense_id_ed25519"

    # Discord
    discord_webhook_url: str = ""

    # ---- Safety controls ----
    # Master kill-switch. true = log everything, execute nothing.
    dry_run: bool = True

    # composite_score threshold to even consider a block action
    auto_action_threshold: int = 80

    # composite_score at which Discord approval is skipped and action fires automatically.
    # Set higher than auto_action_threshold. Set to 101 to always require approval.
    auto_approve_threshold: int = 95

    # Hard cap: never take more than N live actions in a rolling 60-minute window
    max_actions_per_hour: int = 5

    # How long a temp block TTL should be (hours)
    block_ttl_hours: int = 24

    # ---- Scheduler ----
    # How often to poll threat-intel for new high-risk IPs (seconds)
    poll_interval_seconds: int = 600   # 10 minutes

    # ---- GAIT audit trail ----
    audit_repo_path: str = "/app/audit-repo"
    audit_git_user_name: str = "Convergence AutoAgent"
    audit_git_user_email: str = "autoagent@convergence.local"


settings = Settings()
