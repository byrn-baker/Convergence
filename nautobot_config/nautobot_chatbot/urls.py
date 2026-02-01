"""URL patterns for Nautobot Chatbot plugin."""

from django.urls import path
from nautobot_chatbot.views import ChatbotView, ChatAPIView


app_name = "nautobot_chatbot"

urlpatterns = [
    path("", ChatbotView.as_view(), name="chatbot"),
    path("api/chat/", ChatAPIView.as_view(), name="chat_api"),
]
