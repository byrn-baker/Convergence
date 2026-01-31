"""Main entry point for Convergence Agent CLI."""

import asyncio
from typing import Optional
import typer
from rich.console import Console
from rich.markdown import Markdown

from agent.agents.network_agent import create_network_agent, run_agent
from agent.config import settings

app = typer.Typer(help="Convergence AI Agent for Network Automation")
console = Console()


@app.command()
def discover(
    target: str = typer.Argument(..., help="Target device IP or hostname"),
    device_type: str = typer.Option("cisco_ios", help="Device type (cisco_ios, cisco_nxos, etc.)"),
) -> None:
    """Discover a network device and populate Nautobot."""
    console.print(f"[bold blue]Discovering device:[/bold blue] {target}")

    task = f"""
    Connect to network device {target} (type: {device_type}) and:
    1. Gather device facts (hostname, serial, version, uptime)
    2. Get interface information
    3. Create or update the device in Nautobot with discovered information

    Provide a summary of what was discovered and saved.
    """

    asyncio.run(_run_agent_task(task))


@app.command()
def audit(
    site: Optional[str] = typer.Option(None, help="Site to audit (all if not specified)"),
) -> None:
    """Audit network devices for compliance and configuration drift."""
    console.print(f"[bold blue]Auditing devices[/bold blue]")

    task = f"""
    Audit network devices{f' in site {site}' if site else ''}:
    1. List all devices from Nautobot
    2. Connect to each device and backup the running configuration
    3. Compare running config with any config context in Nautobot
    4. Report any configuration drift or compliance issues

    Provide a summary of findings.
    """

    asyncio.run(_run_agent_task(task))


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask about the network"),
) -> None:
    """Query the agent about network state or perform tasks."""
    console.print(f"[bold blue]Processing query:[/bold blue] {question}")
    asyncio.run(_run_agent_task(question))


@app.command()
def config() -> None:
    """Display current agent configuration."""
    console.print("[bold]Convergence Agent Configuration[/bold]\n")
    console.print(f"Nautobot URL: {settings.nautobot_url}")
    console.print(f"Agent Model: {settings.agent_model}")
    console.print(f"Temperature: {settings.agent_temperature}")
    console.print(f"Max Iterations: {settings.agent_max_iterations}")
    console.print(f"LangChain Tracing: {settings.langchain_tracing_v2}")


async def _run_agent_task(task: str) -> None:
    """Run an agent task and display results.

    Args:
        task: Task description for the agent
    """
    try:
        agent = create_network_agent()
        console.print("[dim]Agent is processing...[/dim]\n")

        final_state = await run_agent(task, agent)

        # Display results
        messages = final_state.get("messages", [])
        if messages:
            last_message = messages[-1]
            console.print("[bold green]Agent Response:[/bold green]\n")

            if hasattr(last_message, "content"):
                # Render as markdown for better formatting
                md = Markdown(last_message.content)
                console.print(md)

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
