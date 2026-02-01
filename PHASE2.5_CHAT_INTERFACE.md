# Phase 2.5: Chat Interface Integration

## Overview

Phase 2.5 adds a beautiful, interactive chat interface directly into Nautobot's UI, making the AI agent accessible to all network engineers without requiring CLI access.

## What's New

### 1. Agent Web Service (FastAPI)
A production-ready REST API and WebSocket service that wraps the AI agent:

- **REST API**: `/api/chat` endpoint for synchronous queries
- **WebSocket**: `/ws/chat` for real-time streaming responses
- **Session Management**: Conversation history tracking
- **Health Checks**: `/health` endpoint for monitoring

**Location**: `agent/agent_service/`

### 2. Nautobot Chat Plugin
A custom Nautobot app that integrates the chat interface:

- **Navigation Menu**: "AI Assistant" tab in Nautobot's main menu
- **Chat Interface**: Modern, responsive chat UI
- **Quick Actions**: Pre-defined queries for common tasks
- **Session Persistence**: Maintains conversation context

**Location**: `nautobot_config/nautobot_chatbot/`

### 3. Docker Service
The agent service runs as a Docker container alongside Nautobot:

- **Port**: 8080 (accessible internally to Nautobot)
- **Environment**: Shares same configuration as CLI agent
- **Dependencies**: Waits for Nautobot to be healthy before starting

## Architecture

```
┌────────────────────────────────────────────────────┐
│           User's Browser                            │
│  ┌──────────────────────────────────────────────┐  │
│  │     Nautobot Web UI (Django)                 │  │
│  │  ┌────────────────────────────────────────┐  │  │
│  │  │  AI Chat Interface (JavaScript)        │  │  │
│  │  │  - Message display                     │  │  │
│  │  │  - Input form                          │  │  │
│  │  │  - Quick actions                       │  │  │
│  │  └─────────────┬──────────────────────────┘  │  │
│  └────────────────┼─────────────────────────────┘  │
└───────────────────┼────────────────────────────────┘
                    │ HTTP POST
                    ▼
       ┌────────────────────────────┐
       │  Nautobot Chat Plugin      │
       │  (Django View)             │
       │  - Receive query           │
       │  - Forward to agent        │
       │  - Return response         │
       └────────────┬───────────────┘
                    │ HTTP/WebSocket
                    ▼
       ┌────────────────────────────┐
       │  Agent Service (FastAPI)   │
       │  - REST API endpoints      │
       │  - WebSocket handler       │
       │  - Session management      │
       └────────────┬───────────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
    ┌─────────┐           ┌─────────┐
    │Nautobot │           │   LLM   │
    │   API   │           │(Claude) │
    └─────────┘           └─────────┘
```

## Usage

### Accessing the Chat Interface

1. **Navigate to Nautobot**: http://localhost:8000
2. **Login**: admin/admin (or your configured credentials)
3. **Click "AI Assistant"** tab in the main navigation
4. **Start chatting!**

### Example Queries

**Device Management:**
- "List all devices in Nautobot"
- "Show me devices at site HQ"
- "Get details for device router-01"

**Device Onboarding:**
- "Onboard device 192.168.1.1 with platform cisco_ios"
- "Show me the status of recent device onboarding tasks"
- "Onboard these devices: [list of IPs]"

**Configuration Management:**
- "Get the golden config for router-01"
- "Compare running config with golden config for router-01"
- "Check config compliance for all devices at site HQ"

**General Queries:**
- "What tools do you have available?"
- "How can you help me with network automation?"

### Quick Actions

The interface includes quick action buttons for common tasks:
- **List Devices**: Shows all devices in Nautobot
- **Onboarding Status**: Check recent onboarding tasks
- **Show Capabilities**: Displays available tools

## Technical Details

### Agent Service API

#### REST Endpoint
```http
POST /api/chat
Content-Type: application/json

{
  "query": "List all devices",
  "session_id": "optional-session-id",
  "context": {
    "user": "admin",
    "source": "nautobot"
  }
}
```

**Response:**
```json
{
  "response": "Here are all the devices...",
  "session_id": "session_abc123",
  "tool_calls": [
    {"tool": "list_devices", "args": {"limit": 50}}
  ],
  "status": "success"
}
```

#### WebSocket Endpoint
```javascript
const ws = new WebSocket('ws://agent-service:8080/ws/chat');

ws.send(JSON.stringify({
  query: "List all devices",
  session_id: "session_abc123"
}));

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.response);
};
```

### Session Management

The chat interface maintains conversation history using session IDs stored in `sessionStorage`. Each browser tab gets its own session, allowing multiple concurrent conversations.

### Error Handling

The system gracefully handles various error conditions:
- **Agent Service Down**: Shows friendly error message
- **Network Timeout**: Displays timeout message
- **Invalid Queries**: Agent responds with helpful guidance
- **API Errors**: Logs errors and notifies user

## Configuration

### Environment Variables

The agent service uses these environment variables (inherited from `.env`):

```env
# LLM Configuration
ANTHROPIC_API_KEY=your-key-here
AGENT_MODEL=claude-3-haiku-20240307
AGENT_TEMPERATURE=0.1
AGENT_MAX_ITERATIONS=10

# Nautobot Connection
NAUTOBOT_URL=http://nautobot:8080
NAUTOBOT_API_TOKEN=your-token-here

# Network Device Credentials
NETWORK_USERNAME=admin
NETWORK_PASSWORD=your-password
NETWORK_ENABLE_PASSWORD=your-enable-password
```

### Plugin Configuration

In `nautobot_config.py`:

```python
PLUGINS = [
    # ... other plugins
    "nautobot_chatbot",
]

PLUGINS_CONFIG = {
    "nautobot_chatbot": {
        "agent_service_url": "http://agent-service:8080",
    },
}
```

## Deployment

### Starting the Services

```bash
# Rebuild Nautobot with chatbot plugin
docker-compose up -d --build nautobot

# Build and start agent service
docker-compose up -d --build agent-service

# Check service health
docker-compose ps
curl http://localhost:8080/health
```

### Verifying the Integration

1. **Check Agent Service**:
   ```bash
   curl http://localhost:8080/health
   ```
   Should return: `{"status":"healthy","version":"0.1.0","agent_tools_loaded":15}`

2. **Check Nautobot Plugin**:
   - Login to Nautobot
   - Look for "AI Assistant" tab in navigation
   - If missing, check Nautobot logs: `docker-compose logs nautobot`

3. **Test Chat**:
   - Click "AI Assistant" → "AI Chat"
   - Type: "What tools do you have?"
   - You should see a response listing all 15 tools

## Troubleshooting

### "Agent not initialized" Error

**Cause**: Agent service failed to start
**Solution**:
```bash
docker-compose logs agent-service
# Look for startup errors
# Common issues: missing API key, wrong model name
```

### "Agent service error" in Chat UI

**Cause**: Agent service is unreachable from Nautobot
**Solution**:
```bash
# Check if agent service is running
docker-compose ps agent-service

# Test connectivity from Nautobot container
docker-compose exec nautobot curl http://agent-service:8080/health
```

### Chat UI Not Appearing

**Cause**: Plugin not installed or not enabled
**Solution**:
```bash
# Check if plugin is in PLUGINS list
docker-compose exec nautobot python -c "from django.conf import settings; print(settings.PLUGINS)"

# Collect static files
docker-compose exec nautobot nautobot-server collectstatic --noinput

# Restart Nautobot
docker-compose restart nautobot
```

### WebSocket Connection Fails

**Cause**: Firewall or proxy blocking WebSocket connections
**Solution**: The REST API fallback will be used automatically

## Development

### Adding New Features

To extend the chat interface:

1. **Add API Endpoints**: Modify `agent_service/main.py`
2. **Update UI**: Edit templates in `nautobot_chatbot/templates/`
3. **Add Styles**: Update `nautobot_chatbot/static/nautobot_chatbot/css/chat.css`
4. **Enhance JavaScript**: Modify `nautobot_chatbot/static/nautobot_chatbot/js/chat.js`

### Running Agent Service Locally

For development without Docker:

```bash
cd agent
source venv/bin/activate
pip install -e ".[dev]"

# Run the service
python -m agent_service.main
# Or with uvicorn for auto-reload
uvicorn agent_service.main:app --reload --port 8080
```

Then update Nautobot plugin config to point to `http://host.docker.internal:8080`

## Security Considerations

### Authentication

Currently, the chat interface inherits Nautobot's authentication:
- Users must be logged into Nautobot to access the chat
- The agent receives the username in the context

### Authorization

Future enhancements could include:
- Role-based access control for tools
- Audit logging of all agent actions
- Rate limiting per user

### Network Isolation

- Agent service is only accessible within the Docker network
- No external exposure of agent API
- All communication happens over internal Docker network

## Performance

### Response Times

- **Simple Queries**: 1-3 seconds
- **Tool Invocations**: 3-10 seconds
- **Complex Multi-Tool Queries**: 10-30 seconds

### Scaling

For high-traffic deployments:
- Run multiple agent service replicas
- Use a load balancer (nginx, HAProxy)
- Implement Redis for session storage
- Add response caching for common queries

## Future Enhancements

### Planned Features

- [ ] Streaming responses (character-by-character)
- [ ] File attachments (upload device configs)
- [ ] Voice input support
- [ ] Mobile-optimized UI
- [ ] Chat history persistence in database
- [ ] Multi-user collaboration
- [ ] Scheduled tasks via chat
- [ ] Integration with Slack/Teams

### Plugin Improvements

- [ ] Context-aware suggestions based on current page
- [ ] Quick device selection from Nautobot UI
- [ ] Embedded charts and visualizations
- [ ] Export conversation history
- [ ] Bookmark useful queries

## Documentation Links

- **Agent Service API**: http://localhost:8080/docs (when running)
- **Nautobot Apps**: https://docs.nautobot.com/projects/core/en/stable/development/apps/
- **FastAPI**: https://fastapi.tiangolo.com/
- **LangGraph**: https://langchain-ai.github.io/langgraph/

---

**Phase 2.5 Status**: ✅ Implemented and Ready for Testing
**Services**: Agent Service + Nautobot Chat Plugin
**Access**: http://localhost:8000 → AI Assistant tab
