"""Automation agent configuration via environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic (Claude Haiku for action proposals)
    anthropic_api_key: str = ""

    # LLM provider: "anthropic" (default) or "ollama"
    llm_provider: str = "anthropic"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Infrastructure — uses redis DB 1 to isolate from threat-intel (DB 0)
    redis_url: str = "redis://redis:6379/1"
    victoriametrics_url: str = "http://victoriametrics:8428"
    loki_url: str = "http://loki:3100"
    threat_intel_url: str = "http://threat-intel:8000"

    # pfSense — connection (shared by all paths)
    pfsense_host: str = ""          # e.g. "192.168.1.1"
    pfsense_verify_ssl: bool = False  # false = accept self-signed certs

    # pfSense — Path A: REST API v2 (pfSense Plus 25.11, optional)
    # System > API > Keys — generate a key, assign to admin user.
    # Also requires a firewall alias + block rule (see docs).
    pfsense_api_key: str = ""
    pfsense_firewall_alias: str = "AutoAgent_Block_v4"

    # pfSense — Path B: XML-RPC exec_php (no API key needed, just web UI credentials)
    # Two sub-modes controlled by pfsense_xmlrpc_target:
    #   "alias"      — adds IP to a plain Firewall Alias via PHP config API (recommended)
    #                  Requires: Firewall > Aliases — create Host alias "AutoAgent_Block_v4"
    #                            Firewall > Rules  — block rule with Source = AutoAgent_Block_v4
    #   "pfblockerng" — appends to a pfBlockerNG IPv4 Custom List file and syncs
    #                  Requires: pfBlockerNG > IP > IPv4 Custom Lists — list "pfBlockerNG_AutoAgent_v4"
    pfsense_xmlrpc_user: str = "admin"
    pfsense_xmlrpc_pass: str = ""
    pfsense_xmlrpc_target: str = "alias"   # "alias" or "pfblockerng"

    # pfSense — Path C: SSH emergency fallback
    pfsense_ssh_host: str = ""      # defaults to pfsense_host if blank
    pfsense_ssh_user: str = "admin"
    pfsense_ssh_key_path: str = ""  # path to private key inside container; empty = SSH disabled

    # Discord — webhook (one-way, always used for outcome notifications)
    discord_webhook_url: str = ""

    # Discord — bot (two-way: /approve, /reject, /pending slash commands)
    # Create at https://discord.com/developers/applications → Bot → Reset Token
    # OAuth2 scopes needed: bot + applications.commands
    # Bot permissions needed: Send Messages, Use Slash Commands
    discord_bot_token: str = ""
    # Your server (guild) ID — enables instant slash command sync instead of ~1h global delay
    # Right-click server icon → Copy Server ID (enable Developer Mode first)
    discord_guild_id: int = 0

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

    # Number of lifetime blocks before an IP is flagged as a repeat offender
    # and Claude is instructed to recommend permanent block list addition
    repeat_offender_threshold: int = 5

    # Hourly event count above which an IP is flagged as high-volume/aggressive
    # (independent of block history — triggers permanent block recommendation)
    high_volume_threshold: int = 50

    # ---- Scheduler ----
    # How often to poll threat-intel for new high-risk IPs (seconds)
    poll_interval_seconds: int = 600   # 10 minutes
    # Set to false to disable independent polling — automation-agent becomes
    # execute-only, receiving block requests via /api/automation/submit from NetClaw
    poll_enabled: bool = True

    # ---- GAIT audit trail ----
    audit_repo_path: str = "/app/audit-repo"
    audit_git_user_name: str = "Convergence AutoAgent"
    audit_git_user_email: str = "autoagent@convergence.local"


settings = Settings()
