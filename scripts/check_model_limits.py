"""
Comprehensive Model Limits & Quota Audit for Xenrouter.
Audits all installed/discovered models across all providers, detailing:
- Tier (FREE, FREE-TIER, LOCAL, COMMUNITY, STANDARD)
- RPM (Requests Per Minute) Limit
- RPD (Requests Per Day) Limit
- TPM (Tokens Per Minute) Limit
- Context Window (Tokens)
- Cost / Token Fee
- Live Quota / Cooldown Status
"""

import json
from pathlib import Path
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from xenrouter.backends.hermes_importer import discover_hermes_backends
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import load_config
from xenrouter.limits import get_all_model_limits

console = Console()


def audit_all_limits():
    cfg = load_config()
    registry = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            registry.register(hb)
    for b in cfg.backends:
        registry.register(b)

    profiles = get_all_model_limits(registry)

    # Separate by tier
    free_models = [p for p in profiles if p.tier in ("FREE", "COMMUNITY")]
    freetier_models = [p for p in profiles if p.tier in ("FREE-TIER", "DEVELOPER-TIER", "DEVELOPER-CREDITS")]
    local_models = [p for p in profiles if p.tier == "LOCAL"]
    standard_models = [p for p in profiles if p.tier == "STANDARD"]

    console.print(f"[bold cyan]XENROUTER MODEL LIMITS & TIER AUDIT ({len(profiles)} Total Models)[/bold cyan]")
    console.print(f"Free: [bold green]{len(free_models)}[/bold green] | Free-Tier: [bold yellow]{len(freetier_models)}[/bold yellow] | Local (Uncapped): [bold cyan]{len(local_models)}[/bold cyan] | Standard: [bold white]{len(standard_models)}[/bold white]\n")

    # Table of Free & Free-Tier models
    table = Table(
        title="FREE & FREE-TIER INFERENCE MODELS AND RATE LIMITS",
        box=box.ROUNDED,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan"
    )
    table.add_column("Provider", style="bold white", width=14)
    table.add_column("Model ID", style="bright_white", width=34)
    table.add_column("Tier", justify="center", width=14)
    table.add_column("RPM", justify="right", width=8)
    table.add_column("RPD", justify="right", width=9)
    table.add_column("Context", justify="right", width=9)
    table.add_column("Live Quota", style="magenta", width=16)

    featured = (free_models + freetier_models)[:35]
    for p in featured:
        tier_style = "bold green" if p.tier == "FREE" else "bold yellow"
        rpm_str = str(p.rpm_limit) if p.rpm_limit else "Uncapped"
        rpd_str = str(p.rpd_limit) if p.rpd_limit else "Uncapped"
        ctx_str = f"{p.context_window // 1024}k"

        table.add_row(
            p.provider,
            p.model_id[:33],
            Text(p.tier, style=tier_style),
            rpm_str,
            rpd_str,
            ctx_str,
            p.live_quota_remaining or "Uncapped"
        )

    console.print(table)

    # Save complete JSON
    out_file = Path("model_limits_report.json")
    out_file.write_text(json.dumps([p.model_dump() for p in profiles], indent=2), encoding="utf-8")
    console.print(f"\n[green]Comprehensive limit audit report saved to: [cyan]{out_file}[/cyan][/green]")


if __name__ == "__main__":
    audit_all_limits()
