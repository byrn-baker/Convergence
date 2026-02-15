"""
Convergence CLI - Main entry point for the command-line interface
"""

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from pathlib import Path
import sys

from loguru import logger

# Create Typer app
app = typer.Typer(
    name="convergence",
    help="Convergence - A Unified Network Observability Platform",
    add_completion=True,
    rich_markup_mode="rich",
)

console = Console()


@app.command()
def init():
    """
    Initialize Convergence platform

    Sets up initial configuration files and validates the environment.
    """
    console.print("[bold blue]Initializing Convergence platform...[/bold blue]")

    # Check if .env exists
    env_file = Path(".env")
    if not env_file.exists():
        console.print("[yellow]⚠ .env file not found. Copying from .env.example...[/yellow]")
        env_example = Path(".env.example")
        if env_example.exists():
            import shutil

            shutil.copy(env_example, env_file)
            console.print("[green]✓ Created .env file[/green]")
        else:
            console.print("[red]✗ .env.example not found[/red]")
            raise typer.Exit(code=1)

    # Check if docker-compose.yml exists
    docker_compose = Path("docker-compose.yml")
    if not docker_compose.exists():
        console.print("[red]✗ docker-compose.yml not found[/red]")
        raise typer.Exit(code=1)

    console.print("[green]✓ Convergence platform initialized successfully![/green]")
    console.print("\nNext steps:")
    console.print("  1. Edit .env with your network credentials")
    console.print("  2. Run 'make up' to start the platform")
    console.print("  3. Run 'convergence health' to verify services")


@app.command()
def validate(
    component: str = typer.Option(
        None, "--component", "-c", help="Specific component to validate"
    )
):
    """
    Validate Convergence configurations

    Checks OTEL Collector, Grafana, and VictoriaMetrics configurations for errors.
    """
    import yaml
    from rich.syntax import Syntax

    console.print("[bold blue]Validating configurations...[/bold blue]\n")

    components = ["otel-collector", "grafana", "victoriametrics"] if not component else [component]

    all_valid = True

    for comp in components:
        console.print(f"[cyan]Checking {comp}...[/cyan]")

        if comp == "otel-collector":
            config_file = Path("config/otel-collector/config.yaml")
            if not config_file.exists():
                console.print(f"  [red]✗ Config file not found: {config_file}[/red]")
                all_valid = False
                continue

            try:
                with open(config_file) as f:
                    config = yaml.safe_load(f)

                # Validate required sections
                required = ["receivers", "processors", "exporters", "service"]
                for section in required:
                    if section not in config:
                        console.print(f"  [red]✗ Missing required section: {section}[/red]")
                        all_valid = False
                    else:
                        console.print(f"  [green]✓ {section} configured[/green]")

            except yaml.YAMLError as e:
                console.print(f"  [red]✗ Invalid YAML: {e}[/red]")
                all_valid = False

        elif comp == "grafana":
            datasource = Path("config/grafana/provisioning/datasources/victoriametrics.yaml")
            if datasource.exists():
                console.print("  [green]✓ Datasource provisioning configured[/green]")
            else:
                console.print("  [yellow]⚠ Datasource provisioning not found[/yellow]")

        elif comp == "victoriametrics":
            prometheus_config = Path("config/victoriametrics/prometheus.yml")
            if prometheus_config.exists():
                console.print("  [green]✓ Prometheus config found[/green]")
            else:
                console.print("  [yellow]⚠ Prometheus config not found[/yellow]")

        console.print()

    if all_valid:
        console.print("[bold green]✓ All configurations are valid![/bold green]")
    else:
        console.print("[bold red]✗ Some configurations have errors[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def health():
    """
    Check health of Convergence services

    Verifies that all Docker services are running and accessible.
    """
    import subprocess
    import httpx

    console.print("[bold blue]Checking Convergence platform health...[/bold blue]\n")

    # Check Docker services
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            console.print("[green]✓ Docker Compose is accessible[/green]")
        else:
            console.print("[red]✗ Docker Compose is not accessible[/red]")
            raise typer.Exit(code=1)
    except FileNotFoundError:
        console.print("[red]✗ Docker Compose is not installed[/red]")
        raise typer.Exit(code=1)

    # Check service endpoints
    endpoints = {
        "Grafana": "http://localhost:3000/api/health",
        "VictoriaMetrics": "http://localhost:8428/health",
        "OTEL Collector": "http://localhost:13133/",
    }

    table = Table(title="Service Health")
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Endpoint", style="white")

    for service, url in endpoints.items():
        try:
            response = httpx.get(url, timeout=5)
            if response.status_code == 200:
                table.add_row(service, "[green]✓ Healthy[/green]", url)
            else:
                table.add_row(service, f"[yellow]⚠ Status {response.status_code}[/yellow]", url)
        except Exception as e:
            table.add_row(service, "[red]✗ Unreachable[/red]", url)

    console.print(table)


@app.command()
def discover(
    subnet: str = typer.Option(None, "--subnet", help="Network subnet to scan (e.g., 192.168.1.0/24)"),
    host: str = typer.Option(None, "--host", help="Single host to discover"),
    vendor: str = typer.Option(None, "--vendor", help="Expected vendor (cisco, juniper, arista)"),
):
    """
    Discover network devices

    Scans the specified subnet or host to discover network devices.
    """
    if not subnet and not host:
        console.print("[red]Error: Must specify either --subnet or --host[/red]")
        raise typer.Exit(code=1)

    console.print("[bold blue]Starting device discovery...[/bold blue]\n")

    if subnet:
        console.print(f"[cyan]Scanning subnet: {subnet}[/cyan]")
        # TODO: Implement subnet scanning
        console.print("[yellow]⚠ Subnet scanning not yet implemented[/yellow]")

    if host:
        console.print(f"[cyan]Discovering host: {host}[/cyan]")
        if vendor:
            console.print(f"[cyan]Expected vendor: {vendor}[/cyan]")
        # TODO: Implement single host discovery
        console.print("[yellow]⚠ Host discovery not yet implemented[/yellow]")


@app.command()
def dashboard():
    """
    Dashboard management commands

    Generate, validate, and deploy Grafana dashboards.
    """
    console.print("[bold blue]Dashboard management[/bold blue]")
    console.print("\nAvailable dashboards:")
    console.print("  - Unified: network-overview, interface-health, capacity-planning")
    console.print("  - Cisco: cisco-ios, cisco-nxos, cisco-xr")
    console.print("  - Juniper: juniper-mx, juniper-qfx, juniper-ex")
    console.print("  - Arista: arista-eos, arista-vxlan, arista-evpn")


@app.command()
def config():
    """
    Show current Convergence configuration

    Displays the current configuration settings.
    """
    from rich.tree import Tree

    tree = Tree("[bold]Convergence Configuration[/bold]")

    # Check .env
    env_file = Path(".env")
    if env_file.exists():
        env_branch = tree.add("[green]✓ Environment (.env)[/green]")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "PASSWORD" in line or "TOKEN" in line:
                        key = line.split("=")[0]
                        env_branch.add(f"{key}=***")
                    else:
                        env_branch.add(line)
    else:
        tree.add("[red]✗ Environment (.env) not found[/red]")

    # Check config files
    config_branch = tree.add("[cyan]Configuration Files[/cyan]")
    config_files = [
        "config/otel-collector/config.yaml",
        "config/victoriametrics/prometheus.yml",
        "config/grafana/provisioning/datasources/victoriametrics.yaml",
    ]

    for config_file in config_files:
        path = Path(config_file)
        if path.exists():
            config_branch.add(f"[green]✓ {config_file}[/green]")
        else:
            config_branch.add(f"[red]✗ {config_file}[/red]")

    console.print(tree)


@app.command()
def version():
    """
    Show Convergence version
    """
    from convergence import __version__

    console.print(f"[bold]Convergence[/bold] version [cyan]{__version__}[/cyan]")


if __name__ == "__main__":
    app()
