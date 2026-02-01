"""Main FastAPI application for Convergence Agent Service."""

import uuid
from typing import Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.agents.network_agent import create_network_agent
from agent_service.models import ChatRequest, ChatResponse, HealthResponse
from agent_service import __version__


# Global agent instance
agent_instance = None
conversation_sessions: Dict[str, list] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global agent_instance

    # Startup: Create agent instance
    print("Starting Convergence Agent Service...")
    agent_instance = create_network_agent()
    print(f"Agent initialized with tools")

    yield

    # Shutdown: Cleanup
    print("Shutting down Convergence Agent Service...")
    agent_instance = None


# Create FastAPI app
app = FastAPI(
    title="Convergence Agent Service",
    description="AI-powered network automation agent API",
    version=__version__,
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to Nautobot URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    if agent_instance is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    return HealthResponse(
        status="healthy",
        version=__version__,
        agent_tools_loaded=15,  # Phase 1 + Phase 2 tools
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a query to the agent and get a response.

    This endpoint processes natural language queries and returns the agent's response.
    The agent can perform various network automation tasks including device onboarding,
    configuration management, and Nautobot operations.
    """
    if agent_instance is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        # Generate or use provided session ID
        session_id = request.session_id or str(uuid.uuid4())

        # Initialize session if new
        if session_id not in conversation_sessions:
            conversation_sessions[session_id] = []

        # Add user message to session
        conversation_sessions[session_id].append({
            "role": "user",
            "content": request.query,
        })

        # Prepare agent input
        from langchain_core.messages import HumanMessage

        # Add context if provided
        query_with_context = request.query
        if request.context:
            context_str = "\n".join([f"{k}: {v}" for k, v in request.context.items()])
            query_with_context = f"Context:\n{context_str}\n\nQuery: {request.query}"

        initial_state = {
            "messages": [HumanMessage(content=query_with_context)],
            "current_task": request.query,
            "iteration": 0,
        }

        # Run agent
        final_state = await agent_instance.ainvoke(initial_state)

        # Extract response
        last_message = final_state["messages"][-1]
        response_text = last_message.content if hasattr(last_message, "content") else str(last_message)

        # Extract tool calls if any
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

        # Add assistant message to session
        conversation_sessions[session_id].append({
            "role": "assistant",
            "content": response_text,
        })

        return ChatResponse(
            response=response_text,
            session_id=session_id,
            tool_calls=tool_calls if tool_calls else None,
            status="success",
        )

    except Exception as e:
        return ChatResponse(
            response="",
            session_id=request.session_id or "error",
            status="error",
            error=str(e),
        )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get conversation history for a session."""
    if session_id not in conversation_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "messages": conversation_sessions[session_id],
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a conversation session."""
    if session_id in conversation_sessions:
        del conversation_sessions[session_id]
        return {"status": "deleted", "session_id": session_id}

    raise HTTPException(status_code=404, detail="Session not found")


@app.websocket("/ws/chat")
async def websocket_chat(websocket):
    """WebSocket endpoint for real-time chat."""
    from agent_service.api.websocket import handle_websocket_chat

    await handle_websocket_chat(websocket, agent_instance)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agent_service.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )
