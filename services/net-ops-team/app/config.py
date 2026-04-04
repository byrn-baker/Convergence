from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-sonnet-4-6", alias="NET_OPS_MODEL")
    victoriametrics_url: str = Field(default="http://victoriametrics:8428", alias="VICTORIAMETRICS_URL")
    loki_url: str = Field(default="http://loki:3100", alias="LOKI_URL")
    redis_url: str = Field(default="redis://redis:6379/2", alias="REDIS_URL")
    threat_intel_url: str = Field(default="http://threat-intel:8000", alias="THREAT_INTEL_URL")
    automation_agent_url: str = Field(default="http://automation-agent:8002", alias="AUTOMATION_AGENT_URL")
    netclaw_url: str = Field(default="http://netclaw:18789", alias="NETCLAW_URL")
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    discord_guild_id: int = Field(default=0, alias="DISCORD_GUILD_ID")
    netops_channel_id: int = Field(default=0, alias="NETOPS_CHANNEL_ID")
    nautobot_url: str = Field(default="https://192.168.3.253", alias="NAUTOBOT_URL")
    nautobot_token: str = Field(default="", alias="NAUTOBOT_TOKEN")
    nautobot_verify_ssl: bool = Field(default=False, alias="NAUTOBOT_VERIFY_SSL")
    pfsense_host: str = Field(default="", alias="PFSENSE_HOST")
    pfsense_verify_ssl: bool = Field(default=False, alias="PFSENSE_VERIFY_SSL")
    pfsense_xmlrpc_user: str = Field(default="admin", alias="PFSENSE_XMLRPC_USER")
    pfsense_xmlrpc_pass: str = Field(default="", alias="PFSENSE_XMLRPC_PASS")
    switch_ssh_user: str = Field(default="", alias="SWITCH_SSH_USER")
    switch_ssh_pass: str = Field(default="", alias="SWITCH_SSH_PASS")
    switch_ssh_enable_pass: str = Field(default="", alias="SWITCH_SSH_ENABLE_PASS")
    poll_interval_seconds: int = Field(default=300, alias="POLL_INTERVAL_SECONDS")
    shift_report_interval_seconds: int = Field(default=3600, alias="SHIFT_REPORT_INTERVAL_SECONDS")

    model_config = {"populate_by_name": True, "extra": "ignore"}


settings = Settings()
