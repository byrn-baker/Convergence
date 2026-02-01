"""WebSocket endpoint for streaming agent responses."""

import json
import uuid
from typing import Dict

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage


class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept and store a WebSocket connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        """Remove a WebSocket connection."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, client_id: str, message: dict):
        """Send a message to a specific client."""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            await websocket.send_json(message)


manager = ConnectionManager()


async def handle_websocket_chat(websocket: WebSocket, agent_instance):
    """
    Handle WebSocket chat connections.

    This allows real-time streaming of agent responses as they're generated.
    """
    client_id = str(uuid.uuid4())

    try:
        await manager.connect(websocket, client_id)

        # Send connection success message
        await manager.send_message(client_id, {
            "type": "connection",
            "status": "connected",
            "client_id": client_id,
        })

        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            query = message_data.get("query")
            session_id = message_data.get("session_id", client_id)

            if not query:
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "No query provided",
                })
                continue

            # Send processing status
            await manager.send_message(client_id, {
                "type": "status",
                "status": "processing",
                "query": query,
            })

            try:
                # Prepare agent input
                initial_state = {
                    "messages": [HumanMessage(content=query)],
                    "current_task": query,
                    "iteration": 0,
                }

                # Run agent (stream would require astream if available)
                final_state = await agent_instance.ainvoke(initial_state)

                # Extract response
                last_message = final_state["messages"][-1]
                response_text = last_message.content if hasattr(last_message, "content") else str(last_message)

                # Extract tool calls
                tool_calls = []
                for msg in final_state["messages"]:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        tool_calls.extend([
                            {
                                "tool": tc.get("name"),
                                "args": tc.get("args"),
                            }
                            for tc in msg.tool_calls
                        ])

                # Send response
                await manager.send_message(client_id, {
                    "type": "response",
                    "response": response_text,
                    "session_id": session_id,
                    "tool_calls": tool_calls,
                })

            except Exception as e:
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": str(e),
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(client_id)
