from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    netclaw_proxy_url: str = Field(default="http://netclaw:18790", alias="NETCLAW_PROXY_URL")
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    discord_channel_id: int = Field(default=0, alias="NETOPS_CHANNEL_ID")
    poll_interval_minutes: int = Field(default=10, alias="POLL_INTERVAL_MINUTES")
    report_interval_minutes: int = Field(default=60, alias="REPORT_INTERVAL_MINUTES")
    dedup_minutes: int = Field(default=30, alias="DEDUP_MINUTES")

    model_config = {"populate_by_name": True, "extra": "ignore"}


settings = Settings()
