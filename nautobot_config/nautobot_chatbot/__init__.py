"""Nautobot Chatbot Plugin - AI-powered chat interface for network automation."""

__version__ = "0.1.0"

from nautobot.apps import NautobotAppConfig


class ChatbotConfig(NautobotAppConfig):
    """Nautobot app configuration for the chatbot plugin."""

    name = "nautobot_chatbot"
    verbose_name = "AI Chatbot"
    version = __version__
    author = "Convergence Team"
    description = "AI-powered chat interface for network automation"
    base_url = "chatbot"
    required_settings = []
    default_settings = {
        "agent_service_url": "http://agent-service:8080",
    }


config = ChatbotConfig
