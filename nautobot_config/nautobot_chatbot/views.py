"""Views for Nautobot Chatbot plugin."""

import httpx
from django.conf import settings
from django.http import JsonResponse
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json


class ChatbotView(TemplateView):
    """Main chatbot interface view."""

    template_name = "nautobot_chatbot/chat_widget.html"

    def get_context_data(self, **kwargs):
        """Add context data for the template."""
        context = super().get_context_data(**kwargs)
        context["agent_service_url"] = getattr(
            settings,
            "PLUGINS_CONFIG",
            {},
        ).get("nautobot_chatbot", {}).get(
            "agent_service_url",
            "http://localhost:8080",
        )
        return context


@method_decorator(csrf_exempt, name="dispatch")
class ChatAPIView(TemplateView):
    """API endpoint for chatting with the agent."""

    def post(self, request, *args, **kwargs):
        """Handle chat POST requests."""
        try:
            # Parse request body
            data = json.loads(request.body)
            query = data.get("query")
            session_id = data.get("session_id")

            if not query:
                return JsonResponse(
                    {"error": "Query is required"},
                    status=400,
                )

            # Get agent service URL from settings
            agent_service_url = getattr(
                settings,
                "PLUGINS_CONFIG",
                {},
            ).get("nautobot_chatbot", {}).get(
                "agent_service_url",
                "http://agent-service:8080",
            )

            # Forward request to agent service
            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{agent_service_url}/api/chat",
                    json={
                        "query": query,
                        "session_id": session_id,
                        "context": {
                            "user": request.user.username if request.user else "anonymous",
                            "source": "nautobot",
                        },
                    },
                )
                response.raise_for_status()
                return JsonResponse(response.json())

        except httpx.HTTPError as e:
            return JsonResponse(
                {"error": f"Agent service error: {str(e)}"},
                status=502,
            )
        except Exception as e:
            return JsonResponse(
                {"error": f"Internal error: {str(e)}"},
                status=500,
            )
