"""Network automation agent using LangGraph."""

from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

from agent.config import settings
from agent.tools.nautobot_client import NautobotClient
from agent.tools.device_tools import DeviceTools


class AgentState(TypedDict):
    """State for the network agent."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    current_task: str
    iteration: int


def create_network_agent() -> StateGraph:
    """Create a LangGraph agent for network automation.

    Returns:
        Compiled StateGraph agent
    """
    # Initialize tools
    nautobot = NautobotClient()
    device_tools = DeviceTools()

    # Create tool list
    tools = [
        nautobot.get_device,
        nautobot.list_devices,
        nautobot.create_device,
        nautobot.update_device,
        nautobot.get_device_config_context,
        device_tools.run_command,
        device_tools.get_device_facts,
        device_tools.get_interfaces,
        device_tools.backup_config,
    ]

    # Initialize LLM based on configuration
    if "gpt" in settings.agent_model.lower():
        llm = ChatOpenAI(
            model=settings.agent_model,
            temperature=settings.agent_temperature,
            api_key=settings.openai_api_key,
        )
    else:
        llm = ChatAnthropic(
            model=settings.agent_model,
            temperature=settings.agent_temperature,
            api_key=settings.anthropic_api_key,
        )

    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)

    # Create tool node
    tool_node = ToolNode(tools)

    def should_continue(state: AgentState) -> str:
        """Determine if agent should continue or end.

        Args:
            state: Current agent state

        Returns:
            Next node name ("tools" or "end")
        """
        messages = state["messages"]
        last_message = messages[-1]

        # Check iteration limit
        if state.get("iteration", 0) >= settings.agent_max_iterations:
            return "end"

        # If LLM makes a tool call, route to tools node
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"

        # Otherwise, end
        return "end"

    def call_model(state: AgentState) -> dict:
        """Call the LLM with current state.

        Args:
            state: Current agent state

        Returns:
            Updated state with LLM response
        """
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)

        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
        }

    # Create the graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    # Set entry point
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # Add edge from tools back to agent
    workflow.add_edge("tools", "agent")

    # Compile the graph
    return workflow.compile()


async def run_agent(task: str, agent: StateGraph) -> dict:
    """Run the agent with a given task.

    Args:
        task: Task description for the agent
        agent: Compiled agent graph

    Returns:
        Final state after agent execution
    """
    initial_state = {
        "messages": [HumanMessage(content=task)],
        "current_task": task,
        "iteration": 0,
    }

    final_state = await agent.ainvoke(initial_state)
    return final_state
