"""Configuration settings for Convergence Agent."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Configuration
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "convergence"

    # Nautobot Configuration
    nautobot_url: str = "http://localhost:8000"
    nautobot_api_token: str = "0123456789abcdef0123456789abcdef01234567"

    # Network Device Credentials
    network_username: str = "admin"
    network_password: str = ""
    network_enable_password: str = ""

    # Agent Configuration
    agent_model: str = "gpt-4"  # or "claude-3-5-sonnet-20241022"
    agent_temperature: float = 0.1
    agent_max_iterations: int = 10


# Global settings instance
settings = Settings()
