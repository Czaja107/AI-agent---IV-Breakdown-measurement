"""
CLI entry point for the IV-agent experiment manager.

Commands:
  run       — Execute a full measurement run using the specified config.
  simulate  — Alias for 'run' with instruments.simulate forced to True.
  summarize — Print a summary of an already-completed run from its output dir.

Examples:
  python -m iv_agent run --config configs/demo.yaml
  python -m iv_agent simulate --config configs/demo_small.yaml
  python -m iv_agent summarize --run outputs/demo_run/RUN_DEMO_001
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from .config.schema import AgentConfig

console = Console()


@click.group()
def cli() -> None:
    """IV-Agent: Autonomous capacitor reliability characterisation agent."""


@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True),
              help="Path to the YAML configuration file.")
def run(config: str) -> None:
    """Execute a full measurement run (real or simulated depending on config)."""
    _execute_run(config, force_simulate=False)


@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True),
              help="Path to the YAML configuration file.")
def simulate(config: str) -> None:
    """Execute a simulated run (overrides config to use simulation backend)."""
    _execute_run(config, force_simulate=True)


@cli.command()
@click.option("--run", "-r", "run_dir", required=True, type=click.Path(exists=True),
              help="Path to the run output directory (e.g. outputs/demo_run/RUN_001).")
def summarize(run_dir: str) -> None:
    """Print a summary of an already-completed run."""
    run_path = Path(run_dir)

    summary_path = run_path / "summary.json"
    if not summary_path.exists():
        console.print(f"[red]No summary.json found in {run_path}[/red]")
        sys.exit(1)

    data = json.loads(summary_path.read_text())
    console.print(Panel(
        f"[bold cyan]Run Summary[/bold cyan]\n\n"
        f"Chip: [yellow]{data.get('chip_id')}[/yellow]  "
        f"Run: [yellow]{data.get('run_id')}[/yellow]\n"
        f"Start: {data.get('start_time', '—')}  End: {data.get('end_time', '—')}\n\n"
        f"Devices: {data.get('n_devices_done')}/{data.get('n_devices_total')}  |  "
        f"Healthy: {data.get('n_healthy')}  |  Degrading: {data.get('n_degrading')}  |  "
        f"Failed: {data.get('n_failed')}  |  Shorted: {data.get('n_shorted')}  |  "
        f"Contact: {data.get('n_contact_issue')}\n\n"
        f"Alerts: {data.get('n_alerts')}  |  Notes: {data.get('notes_count', '—')}\n\n"
        + _format_hypotheses(data.get("hypotheses", {})),
        title="IV-Agent Run Summary",
        border_style="cyan",
    ))

    # Print alerts if any
    alerts = data.get("alerts", [])
    if alerts:
        console.print("\n[bold]Alerts:[/bold]")
        for a in alerts:
            sev = a.get("severity", "?")
            title = a.get("title", "")
            ts = a.get("timestamp", "")[:19]
            colour = "red" if sev >= 3 else "yellow"
            console.print(f"  [{colour}]SEV {sev}[/{colour}] [{ts}] {title}")

    # Print notes location
    notes_path = run_path / "notes.md"
    if notes_path.exists():
        console.print(f"\n[dim]Notes: {notes_path}[/dim]")


def _execute_run(config_path: str, force_simulate: bool = False) -> None:
    """Load config, optionally force simulation, and execute the run."""
    try:
        cfg = AgentConfig.from_yaml(config_path)
    except Exception as exc:
        console.print(f"[red]Failed to load config from {config_path}: {exc}[/red]")
        sys.exit(1)

    if force_simulate:
        cfg.instruments.simulate = True

    console.print(
        f"[dim]Config loaded: chip={cfg.run.chip_id}, "
        f"grid={cfg.grid.nx}×{cfg.grid.ny}, "
        f"simulate={cfg.instruments.simulate}[/dim]"
    )

    from .orchestration.agent import ExperimentAgent
    agent = ExperimentAgent(cfg)
    agent.run()


def _format_hypotheses(hypotheses: dict) -> str:
    if not hypotheses:
        return "No hypotheses data."
    active = {k: v for k, v in hypotheses.items() if v.get("support", 0) > 0.1}
    if not active:
        return "No active hypotheses."
    lines = ["[bold]Hypotheses:[/bold]"]
    for k, v in sorted(active.items(), key=lambda x: x[1].get("support", 0), reverse=True):
        bar = "█" * int(v.get("support", 0) * 10)
        lines.append(f"  {k:<35} {bar} {v.get('support', 0):.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    cli()
