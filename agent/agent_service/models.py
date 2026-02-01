"""Pydantic models for agent service API."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    query: str = Field(..., description="User query to send to the agent", min_length=1)
    session_id: Optional[str] = Field(None, description="Session ID for conversation tracking")
    context: Optional[dict] = Field(None, description="Additional context (device, site, etc.)")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    response: str = Field(..., description="Agent's response")
    session_id: str = Field(..., description="Session ID for this conversation")
    tool_calls: Optional[List[dict]] = Field(None, description="Tools called by agent")
    status: str = Field("success", description="Response status")
    error: Optional[str] = Field(None, description="Error message if any")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field("healthy", description="Service health status")
    version: str = Field(..., description="Service version")
    agent_tools_loaded: int = Field(..., description="Number of agent tools loaded")
