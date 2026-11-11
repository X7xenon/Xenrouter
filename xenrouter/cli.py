"""
Command line interface for Xenrouter.
Unified local inference router, dynamic model fetcher, and custom provider manager.
All displays use 100% Windows terminal CP1252-safe characters (zero emojis, zero double-slashes).
"""

import asyncio
import os
from pathlib import Path
import sys

# Ensure UTF-8 execution and console code page
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import threading
import time
from typing import Any, List, Optional
import httpx
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
import typer
import uvicorn
import yaml

from xenrouter import __version__
from xenrouter.backends.hermes_importer import clean_provider_name, discover_hermes_backends, get_hermes_active_model
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig, get_default_config, load_config, save_config
from xenrouter.limits import ModelLimitProfile, classify_model_tier, get_all_model_limits
from xenrouter.router import Router
from xenrouter.server.app import create_app
from xenrouter.server.state import AppState
from xenrouter.tui.components import render_routes_view, render_usage_view, render_welcome_banner
from xenrouter.tui.dashboard import TUIDashboard, TUIView
from xenrouter.types import AliasConfig, BackendConfig, BackendType, KeyRotationStrategy, ServerMetrics
from xenrouter.usage import UsageTracker

app = typer.Typer(
    name="xenrouter",
    help="Xenrouter - Ultra-lightweight Unified Local Inference Router and TUI.",
    add_completion=False
)
provider_app = typer.Typer(
    name="provider",
    help="Manage custom and local inference providers.",
    add_completion=False
)
app.add_typer(provider_app, name="provider")

route_app = typer.Typer(
    name="route",
    help="Inspect, visualize, and modify live inference routing cascades and graphs.",
    add_completion=False
)
app.add_typer(route_app, name="route")

console = Console()


def save_key_to_env(key_name: str, key_value: str, env_path: str = ".env") -> None:
    """Save an API key variable to .env file safely."""
    p = Path(env_path)
    lines: List[str] = []
    if p.exists():
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key_name}="):
            lines[i] = f"{key_name}={key_value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key_name}={key_value}")

    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def query_provider_models(base_url: str, api_key: Optional[str] = None, backend_type: str = "openai_compatible") -> List[str]:
    """Fetch live models directly from inference provider endpoint."""
    url = base_url.rstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=12.0, verify=False) as client:
        if backend_type == "ollama":
            r = await client.get(f"{url}/api/tags")
            if r.status_code == 200:
                data = r.json()
                return [m.get("name") for m in data.get("models", []) if m.get("name")]
            raise RuntimeError(f"Ollama tags error HTTP {r.status_code}")

        models_url = f"{url}/models" if url.endswith("/v1") else f"{url}/v1/models"
        r = await client.get(models_url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            models: List[str] = []
            for item in data.get("data", []):
                mid = item.get("id") or item.get("name")
                if mid:
                    models.append(mid)
            return models
        elif r.status_code == 401:
            raise RuntimeError("Authentication failed (HTTP 401). Verify your API key.")
        elif r.status_code == 429:
            raise RuntimeError("Rate limit exceeded (HTTP 429) on provider.")
        else:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(None, "--host", "-h", help="Host to listen on"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to listen on"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to xenrouter.yaml"),
    headless: bool = typer.Option(False, "--headless", help="Run in headless daemon mode without TUI"),
):
    """Xenrouter - Ultra-lightweight Unified Local Inference Router and TUI."""
    if ctx.invoked_subcommand is None:
        real_host = host if isinstance(host, str) else None
        real_port = port if isinstance(port, int) else None
        real_cfg = config_file if isinstance(config_file, (str, Path)) else None
        real_headless = bool(headless) if isinstance(headless, bool) else False
        start(host=real_host, port=real_port, config_file=real_cfg, headless=real_headless)


def _poll_keyboard_char(timeout_sec: float = 0.25) -> Optional[str]:
    """Non-blocking keyboard character polling for interactive terminal."""
    try:
        import msvcrt
        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    if ch2 == b"H":
                        return "up"
                    elif ch2 == b"P":
                        return "down"
                    elif ch2 == b"K":
                        return "left"
                    elif ch2 == b"M":
                        return "right"
                    return None
                if ch == b"\x1b":
                    return "esc"
                try:
                    return ch.decode("utf-8", errors="ignore").lower()
                except Exception:
                    return None
            time.sleep(0.02)
        return None
    except ImportError:
        try:
            import select
            rlist, _, _ = select.select([sys.stdin], [], [], timeout_sec)
            if rlist:
                ch = sys.stdin.read(1)
                return ch.lower()
        except Exception:
            time.sleep(timeout_sec)
        return None


def _dispatch_test_request(port: int) -> None:
    """Fire an asynchronous completion test request to the active local router."""
    try:
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 15
        }
        httpx.post(url, json=payload, timeout=8.0)
    except Exception:
        pass


@app.command()
def stop(
    port: int = typer.Option(8989, "--port", "-p", help="Port of running Xenrouter instance")
):
    """Stop the running Xenrouter daemon process."""
    if sys.platform == "win32":
        import subprocess
        try:
            ps_cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=5)
            console.print(f"[bold green]Xenrouter on port {port} stopped successfully.[/bold green]")
            return
        except Exception as e:
            console.print(f"[red]Error stopping Xenrouter: {e}[/red]")
            return
    console.print("[yellow]Use kill or stop-process to terminate the process on this OS.[/yellow]")


_VIEW_TOGGLE_MAP = {
    "w": (TUIView.WELCOME, "WELCOME VIEW | Press [d] or [w] to return to Dashboard"),
    "r": (TUIView.ROUTES, "ROUTING GRAPH | Press [d] or [r] to return to Dashboard"),
    "m": (TUIView.MODELS, "MODELS VIEW | [n] Next | [b] Back | [f] Fetch | [d] Dashboard"),
    "p": (TUIView.PROVIDERS, "PROVIDERS DIRECTORY | [n] Next | [b] Back | [d] Dashboard"),
    "l": (TUIView.LIMITS, "LIMITS & QUOTAS MATRIX | [n] Next | [b] Back | [d] Dashboard"),
    "u": (TUIView.USAGE, "DAILY & MONTHLY USAGE | [n] Models & History | [b] Overview | [d] Dashboard"),
}


def _handle_tui_keypress(
    ch: str,
    dashboard: TUIDashboard,
    cfg: XenrouterConfig,
    registry: BackendRegistry,
    live: Any,
    server: Any = None,
) -> bool:
    """Process one TUI keypress; return True when the user requests exit."""
    if ch == "q":
        if server is not None:
            server.should_exit = True
        return True

    if ch in _VIEW_TOGGLE_MAP:
        target_view, enter_msg = _VIEW_TOGGLE_MAP[ch]
        if dashboard.current_view == target_view:
            dashboard.switch_view(TUIView.DASHBOARD)
            dashboard.set_notification("Returned to Main Dashboard.")
        else:
            dashboard.switch_view(target_view)
            dashboard.set_notification(enter_msg)
            if target_view == TUIView.USAGE and dashboard.is_remote:
                dashboard.sync_from_remote(f"http://{cfg.host}:{cfg.port}")
    elif ch in ("d", "esc"):
        dashboard.switch_view(TUIView.DASHBOARD)
        dashboard.set_notification("Main Dashboard active.")
    elif ch in ("n", "right", "down", "j"):
        dashboard.next_page()
    elif ch in ("b", "left", "up", "k"):
        dashboard.prev_page()
    elif ch == "t":
        dashboard.set_notification("Testing active inference route with auto cascade...")
        threading.Thread(target=_dispatch_test_request, args=(cfg.port,), daemon=True).start()
    elif ch == "f" and server is not None:
        live.stop()
        try:
            console.print("\n[bold cyan]XENROUTER DYNAMIC MODEL FETCHER[/bold cyan]")
            fetch_models_cmd(target=None, api_key=None, save=True)
            if cfg.import_hermes_providers:
                for hb in discover_hermes_backends():
                    registry.register(hb)
        except Exception as ex:
            console.print(f"[red]Fetch failed: {ex}[/red]")
            time.sleep(1.0)
        live.start()
        dashboard.set_notification("Model inventory refreshed.")

    return False


def _run_tui_loop(
    dashboard: TUIDashboard,
    cfg: XenrouterConfig,
    registry: BackendRegistry,
    server: Any = None,
    server_thread: Optional[threading.Thread] = None,
) -> None:
    """Run unified interactive TUI event loop with 1s remote sync and key handling."""
    with dashboard.run_live() as live:
        last_sync = time.time()
        while server_thread is None or server_thread.is_alive():
            now = time.time()
            if now - last_sync >= 1.0:
                dashboard.sync_from_remote(f"http://{cfg.host}:{cfg.port}")
                live.update(dashboard.generate_layout())
                last_sync = now

            ch = _poll_keyboard_char(0.15)
            if ch:
                should_quit = _handle_tui_keypress(ch, dashboard, cfg, registry, live, server=server)
                if should_quit:
                    break
                live.update(dashboard.generate_layout())


@app.command()
def start(
    host: Optional[str] = typer.Option(None, "--host", "-h", help="Host to listen on"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to listen on"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to xenrouter.yaml"),
    headless: bool = typer.Option(False, "--headless", help="Run in headless daemon mode without TUI"),
):
    """Start the unified local inference router and aesthetic TUI."""
    real_cfg_file = config_file if isinstance(config_file, (str, Path)) else None
    cfg = load_config(real_cfg_file)
    if host and isinstance(host, str):
        cfg.host = host
    if port and isinstance(port, int):
        cfg.port = port
    is_headless = bool(headless) if isinstance(headless, bool) else False

    # Check if port is already occupied
    import socket
    port_in_use = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex((cfg.host, cfg.port)) == 0:
            port_in_use = True

    if port_in_use:
        is_xen = False
        try:
            with httpx.Client(timeout=1.0) as cl:
                r = cl.get(f"http://{cfg.host}:{cfg.port}/")
                if r.status_code == 200 and r.json().get("name") == "Xenrouter":
                    is_xen = True
        except Exception:
            pass

        if is_xen:
            if is_headless:
                console.print(render_welcome_banner())
                console.print(f"[bold yellow]Xenrouter daemon is ALREADY running and healthy on http://{cfg.host}:{cfg.port}/v1[/bold yellow]")
                console.print("[dim]Use 'xenrouter' to open the interactive dashboard, or 'xenrouter stop' to terminate it.[/dim]\n")
                return
            else:
                registry = BackendRegistry()
                state = AppState(cfg)
                dashboard = TUIDashboard(cfg, state, registry, is_remote=True)
                dashboard.sync_from_remote(f"http://{cfg.host}:{cfg.port}")
                try:
                    _run_tui_loop(dashboard, cfg, registry)
                except (KeyboardInterrupt, SystemExit):
                    pass
                return
        else:
            console.print(f"[bold red]Port {cfg.port} is already in use by another application. Please free port {cfg.port} or run with --port <new_port>.[/bold red]")
            return

    registry = BackendRegistry()
    for b_cfg in cfg.backends:
        registry.register(b_cfg)
    if cfg.import_hermes_providers:
        try:
            for h_cfg in discover_hermes_backends():
                if not registry.get(h_cfg.name):
                    registry.register(h_cfg)
        except Exception:
            pass

    state = AppState(cfg)
    router = Router(cfg, registry)
    fastapi_app = create_app(cfg, state, registry, router)

    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=cfg.host,
        port=cfg.port,
        log_level="error" if not is_headless else "info",
        access_log=is_headless
    )
    server = uvicorn.Server(uvicorn_config)

    if is_headless:
        console.print(render_welcome_banner())
        console.print(f"[bold cyan]Starting Xenrouter v{__version__} (headless mode)...[/bold cyan]")
        console.print(f"Endpoint: [bold green]http://{cfg.host}:{cfg.port}/v1[/bold green]")
        console.print(f"Active Model: [bold yellow]{cfg.default_model or 'coding'}[/bold yellow]")
        console.print("Press Ctrl+C to stop.\n")
        server.run()
    else:
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        dashboard = TUIDashboard(cfg, state, registry)
        time.sleep(0.8)

        try:
            _run_tui_loop(dashboard, cfg, registry, server=server, server_thread=server_thread)
        except (KeyboardInterrupt, SystemExit):
            server.should_exit = True
            console.print("\n[bold yellow]Xenrouter shutdown complete.[/bold yellow]")


@app.command()
def probe(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Target host to probe")
):
    """Scan local network and ports for active inference engines."""
    console.print(f"[bold cyan]Scanning local inference engines on {host}...[/bold cyan]")

    async def run_probe():
        async with httpx.AsyncClient() as client:
            return await BackendRegistry.probe_local_ports(client, host)

    results = asyncio.run(run_probe())
    if not results:
        console.print("[yellow]No local inference engines detected on standard ports (11434, 1234, 8080, 8000).[/yellow]")
        return

    table = Table(title="LOCAL INFERENCE ENGINES", box=box.ROUNDED, border_style="cyan")
    table.add_column("Engine", style="bold white")
    table.add_column("Type", style="dim white")
    table.add_column("Endpoint", style="cyan")
    table.add_column("Port", justify="right")
    table.add_column("Status", style="bold green")

    for item in results:
        table.add_row(item["name"], item["type"].value, item["base_url"], str(item["port"]), f"[{item['status']}]")

    console.print(table)


@app.command()
def status(
    endpoint: str = typer.Option("http://127.0.0.1:8989", "--url", "-u", help="Xenrouter base URL")
):
    """Query live status of running Xenrouter instance."""
    base = endpoint.rstrip("/")
    try:
        resp = httpx.get(f"{base}/v1/health", timeout=3.0)
        backends_resp = httpx.get(f"{base}/v1/backends", timeout=3.0)
        metrics_resp = httpx.get(f"{base}/v1/metrics", timeout=3.0)
    except Exception as exc:
        console.print(f"[bold red]Cannot connect to Xenrouter at {base}: {exc}[/bold red]")
        sys.exit(1)

    health_data = resp.json()
    metrics_data = metrics_resp.json() if metrics_resp.status_code == 200 else {}
    tot_tok = metrics_data.get("total_tokens", 0)
    prompt_tok = metrics_data.get("total_prompt_tokens", 0)
    comp_tok = metrics_data.get("total_completion_tokens", 0)

    console.print(f"[bold cyan]Xenrouter Status:[/bold cyan] [bold green]{health_data.get('status').upper()}[/bold green]")
    console.print(
        f"Uptime: {health_data.get('uptime_seconds')}s | "
        f"Active Requests: {health_data.get('active_requests')} | "
        f"Total Tokens: [bold green]{tot_tok:,}[/bold green] (Prompt: {prompt_tok:,}, Completion: {comp_tok:,})"
    )

    backends = backends_resp.json().get("backends", [])
    table = Table(title="REGISTERED INFERENCE PROVIDERS", box=box.ROUNDED, border_style="dim cyan")
    table.add_column("Provider", style="bold white")
    table.add_column("Base URL", style="cyan")
    table.add_column("Status", style="bold green")
    table.add_column("Ping", justify="right")
    table.add_column("Models", justify="right")
    table.add_column("Key Pool", style="yellow")
    table.add_column("Quota", style="magenta")

    for b in backends:
        quota_val = b.get("ratelimit_remaining")
        quota_str = f"{quota_val} left" if quota_val is not None else (b.get("quota_remaining_str") or "Uncapped")
        table.add_row(
            b["name"],
            b["base_url"],
            f"[{b['status']}]",
            f"{b['latency_ms']:.0f}ms" if b["latency_ms"] > 0 else "-",
            str(b["models_count"]),
            f"{len(b['keys_states'])} key(s)",
            quota_str
        )
    console.print(table)


@app.command(name="metrics")
def show_metrics(
    endpoint: str = typer.Option("http://127.0.0.1:8989", "--url", "-u", help="Xenrouter base URL"),
    json_out: bool = typer.Option(False, "--json", help="Output metrics as raw JSON")
):
    """View real-time token usage breakdown, request volume, and throughput stats."""
    base = endpoint.rstrip("/")
    try:
        resp = httpx.get(f"{base}/v1/metrics", timeout=3.0)
        data = resp.json()
    except Exception as exc:
        console.print(f"[bold red]Cannot connect to Xenrouter at {base}: {exc}[/bold red]")
        sys.exit(1)

    if json_out:
        import json
        console.print(json.dumps(data, indent=2))
        return

    console.print("[bold cyan]XENROUTER TOKEN USAGE & INFERENCE METRICS[/bold cyan]")
    total_tokens = data.get("total_tokens", 0)
    prompt_tokens = data.get("total_prompt_tokens", 0)
    comp_tokens = data.get("total_completion_tokens", 0)
    total_reqs = data.get("total_requests", 0)
    succ_reqs = data.get("successful_requests", 0)
    fail_reqs = data.get("failed_requests", 0)
    uptime = data.get("uptime_seconds", 0.0)

    console.print(
        f"Total Tokens: [bold green]{total_tokens:,}[/bold green] | "
        f"Prompt Tokens: [bold cyan]{prompt_tokens:,}[/bold cyan] | "
        f"Completion Tokens: [bold yellow]{comp_tokens:,}[/bold yellow]\n"
        f"Total Requests: [bold white]{total_reqs}[/bold white] (Success: [green]{succ_reqs}[/green], Failed: [red]{fail_reqs}[/red]) | "
        f"Uptime: [dim]{uptime:.0f}s[/dim]\n"
    )

    prov_tokens = data.get("provider_tokens", {})
    if prov_tokens:
        p_table = Table(title="TOKEN USAGE BY PROVIDER", box=box.ROUNDED, border_style="cyan")
        p_table.add_column("Provider", style="bold white", width=16)
        p_table.add_column("Requests", justify="right", width=10)
        p_table.add_column("Prompt Tokens", justify="right", width=16)
        p_table.add_column("Completion Tokens", justify="right", width=18)
        p_table.add_column("Total Tokens", justify="right", width=16, style="bold green")

        for prov, info in sorted(prov_tokens.items(), key=lambda x: x[1].get("total", 0), reverse=True):
            p_table.add_row(
                prov,
                str(info.get("requests", 0)),
                f"{info.get('prompt', 0):,}",
                f"{info.get('completion', 0):,}",
                f"{info.get('total', 0):,}"
            )
        console.print(p_table)

    model_tokens = data.get("model_tokens", {})
    if model_tokens:
        m_table = Table(title="TOKEN USAGE BY MODEL", box=box.ROUNDED, border_style="magenta")
        m_table.add_column("Model Identifier", style="bold white", ratio=4)
        m_table.add_column("Requests", justify="right", width=10)
        m_table.add_column("Prompt Tokens", justify="right", width=16)
        m_table.add_column("Completion Tokens", justify="right", width=18)
        m_table.add_column("Total Tokens", justify="right", width=16, style="bold green")

        for m_name, info in sorted(model_tokens.items(), key=lambda x: x[1].get("total", 0), reverse=True):
            m_table.add_row(
                m_name,
                str(info.get("requests", 0)),
                f"{info.get('prompt', 0):,}",
                f"{info.get('completion', 0):,}",
                f"{info.get('total', 0):,}"
            )
        console.print(m_table)


@app.command(name="usage")
def show_usage(
    endpoint: str = typer.Option("http://127.0.0.1:8989", "--url", "-u", help="Xenrouter base URL"),
    days: int = typer.Option(30, "--days", "-d", help="Number of recent daily buckets to display"),
    months: int = typer.Option(12, "--months", "-m", help="Number of monthly buckets to display"),
    json_out: bool = typer.Option(False, "--json", help="Output usage stats as raw JSON"),
):
    """Display persistent daily and monthly token/request usage analytics."""
    base = endpoint.rstrip("/")
    data = None
    try:
        resp = httpx.get(f"{base}/v1/usage?days={days}&months={months}", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
    except Exception:
        pass

    if data is None:
        tracker = UsageTracker()
        try:
            data = tracker.get_summary(days=days, months=months)
        finally:
            tracker.close()

    if json_out:
        import json
        console.print(json.dumps(data, indent=2))
        return

    metrics = ServerMetrics(
        total_requests=int(data.get("session", {}).get("requests", 0)),
        successful_requests=int(data.get("session", {}).get("successful", 0)),
        failed_requests=int(data.get("session", {}).get("failed", 0)),
        total_prompt_tokens=int(data.get("session", {}).get("prompt_tokens", 0)),
        total_completion_tokens=int(data.get("session", {}).get("completion_tokens", 0)),
        total_tokens=int(data.get("session", {}).get("total_tokens", 0)),
        uptime_seconds=float(data.get("session", {}).get("uptime_seconds", 0.0)),
    )
    console.print(render_usage_view(data, metrics, page=0))


@app.command(name="models")
def list_models(
    endpoint: str = typer.Option("http://127.0.0.1:8989", "--url", "-u", help="Xenrouter base URL")
):
    """List all models available across active providers and virtual cascades."""
    base = endpoint.rstrip("/")
    try:
        resp = httpx.get(f"{base}/v1/models", timeout=4.0)
        data = resp.json().get("data", [])
    except Exception:
        # Fall back to local config inspection if server is not running
        cfg = load_config()
        reg = BackendRegistry()
        if cfg.import_hermes_providers:
            for hb in discover_hermes_backends():
                reg.register(hb)
        for b in cfg.backends:
            reg.register(b)
        router = Router(cfg, reg)
        data = router.get_unified_models_list()

    table = Table(title="UNIFIED MODELS & ALIASES", box=box.ROUNDED, border_style="cyan")
    table.add_column("Model Identifier", style="bold white")
    table.add_column("Provider / Source", style="dim cyan")
    table.add_column("Type", style="yellow")

    for item in data:
        owned_by = item.get("owned_by", "")
        backend = item.get("backend", "-")
        if item.get("id") == "auto" or owned_by == "xenrouter-auto":
            kind = "Hermes Auto Selector"
        elif owned_by == "xenrouter-alias":
            kind = "Virtual Cascade"
        else:
            kind = "Inference Model"
        table.add_row(item["id"], backend if backend != "-" else owned_by, kind)

    console.print(table)


@app.command(name="limits")
def show_limits(
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="Filter by tier: free, free-tier, community, local, standard"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Filter by provider name"),
    json_out: bool = typer.Option(False, "--json", help="Output limits as raw JSON"),
):
    """Display comprehensive rate limits, RPM, RPD, context ceilings, and quota matrix across all installed models."""
    cfg = load_config()
    reg = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            reg.register(hb)
    for b in cfg.backends:
        reg.register(b)

    profiles = get_all_model_limits(reg)

    if provider:
        p_filt = provider.lower()
        profiles = [p for p in profiles if p_filt in p.provider.lower()]

    if tier:
        t_filt = tier.lower()
        profiles = [p for p in profiles if t_filt in p.tier.lower()]

    if json_out:
        import json
        console.print(json.dumps([p.dict() for p in profiles], indent=2))
        return

    free_count = sum(1 for p in profiles if p.tier == "FREE")
    freetier_count = sum(1 for p in profiles if "TIER" in p.tier or p.tier == "COMMUNITY")
    local_count = sum(1 for p in profiles if p.tier == "LOCAL")
    std_count = sum(1 for p in profiles if p.tier == "STANDARD")

    console.print(f"[bold cyan]XENROUTER MODEL LIMITS & TIER INVENTORY ({len(profiles)} Total Models)[/bold cyan]")
    console.print(
        f"Free: [bold green]{free_count}[/bold green] | "
        f"Free-Tier: [bold yellow]{freetier_count}[/bold yellow] | "
        f"Local (Uncapped): [bold cyan]{local_count}[/bold cyan] | "
        f"Standard: [bold white]{std_count}[/bold white]\n"
    )

    table = Table(
        title="MODEL RATE LIMITS, CONTEXT CEILINGS, AND QUOTAS",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="dim cyan"
    )
    table.add_column("Provider", style="bold white", width=12)
    table.add_column("Model Identifier", style="bright_white", width=32)
    table.add_column("Tier", justify="center", width=12)
    table.add_column("RPM", justify="right", width=6)
    table.add_column("RPD", justify="right", width=6)
    table.add_column("Context", justify="right", width=8)
    table.add_column("Live Quota", style="magenta", width=14)

    tier_rank = {"FREE": 0, "FREE-TIER": 1, "COMMUNITY": 2, "DEVELOPER-TIER": 3, "LOCAL": 4, "DEVELOPER-CREDITS": 5, "STANDARD": 6}
    sorted_profiles = sorted(profiles, key=lambda p: (tier_rank.get(p.tier, 99), p.provider, p.model_id))

    for p in sorted_profiles[:60]:
        tier_style = "bold green" if p.tier == "FREE" else ("bold cyan" if "TIER" in p.tier or p.tier == "COMMUNITY" else "yellow")
        if p.tier == "LOCAL":
            tier_style = "bold blue"

        rpm_str = str(p.rpm_limit) if p.rpm_limit else "uncap"
        rpd_str = str(p.rpd_limit) if p.rpd_limit else "-"
        ctx_str = f"{p.context_window // 1024}k"

        table.add_row(
            p.provider,
            p.model_id[:31],
            Text(p.tier, style=tier_style),
            rpm_str,
            rpd_str,
            ctx_str,
            p.live_quota_remaining or "Uncapped"
        )

    console.print(table)
    if len(sorted_profiles) > 60:
        console.print(f"[dim]... and {len(sorted_profiles) - 60} more models. Use '--tier' or '--provider' to filter.[/dim]")


@app.command(name="model")
def select_model(
    model_name: Optional[str] = typer.Argument(None, help="Name of model to set as active default")
):
    """View or set the active default model."""
    cfg = load_config()

    if model_name:
        cfg.default_model = model_name
        cfg.save()
        console.print(f"[bold green]Default model set to: '{model_name}'[/bold green]")
        return

    # Interactive model picker
    console.print(f"Current active model: [bold yellow]{cfg.default_model or 'coding'}[/bold yellow]\n")

    reg = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            reg.register(hb)
    for b in cfg.backends:
        reg.register(b)

    all_models: List[str] = []
    for alias in cfg.aliases.keys():
        all_models.append(f"alias:{alias}")
    for b in reg.all():
        for m in b.models:
            if m.id not in all_models:
                all_models.append(m.id)

    if not all_models:
        console.print("[yellow]No models found.[/yellow]")
        return

    console.print(f"[bold cyan]Available Models ({len(all_models)} total):[/bold cyan]")
    for idx, m in enumerate(all_models[:30], 1):
        is_cur = " [active]" if m == cfg.default_model or m == f"alias:{cfg.default_model}" else ""
        console.print(f"  [{idx:2d}] {m}{is_cur}")
    if len(all_models) > 30:
        console.print(f"  ... and {len(all_models) - 30} more.")

    choice = typer.prompt("\nEnter model number or exact model name to set as active (or press Enter to cancel)", default="")
    if not choice:
        return

    selected = ""
    if choice.isdigit() and 1 <= int(choice) <= min(len(all_models), 30):
        selected = all_models[int(choice) - 1].replace("alias:", "")
    else:
        selected = choice.replace("alias:", "").strip()

    if selected:
        cfg.default_model = selected
        cfg.save()
        console.print(f"[bold green]Active default model updated to: '{selected}'[/bold green]")


@app.command(name="fetch")
def fetch_models_cmd(
    target: Optional[str] = typer.Argument(None, help="Provider name (e.g. nvidia, groq, xkiro) or base URL"),
    api_key: Optional[str] = typer.Option(None, "--key", "-k", help="API Key for the provider"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save selected models to config")
):
    """
    Fetch live models directly from an inference provider endpoint via API,
    interactively select models, and save them into xenrouter.yaml and .env.
    """
    cfg = load_config()

    # Discover known providers
    hermes_backends = discover_hermes_backends() if cfg.import_hermes_providers else []
    known_backends = {b.name: b for b in cfg.backends}
    for hb in hermes_backends:
        if hb.name not in known_backends:
            known_backends[hb.name] = hb

    base_url = ""
    key = api_key
    provider_name = ""
    b_type = "openai_compatible"

    if not target:
        console.print("[bold cyan]SELECT INFERENCE PROVIDER TO FETCH MODELS FROM:[/bold cyan]")
        providers_list = sorted(known_backends.keys())
        for idx, p_name in enumerate(providers_list[:25], 1):
            b_obj = known_backends[p_name]
            m_cnt = len(b_obj.models_filter) if b_obj.models_filter else 0
            console.print(f"  [{idx:2d}] {p_name:<16} ({b_obj.base_url}) - {m_cnt} configured models")
        console.print("  [ 0] Enter custom endpoint URL")

        p_choice = typer.prompt("Select provider number", default="1")
        if p_choice == "0":
            target = typer.prompt("Enter base URL (e.g. https://api.together.xyz/v1)")
        elif p_choice.isdigit() and 1 <= int(p_choice) <= len(providers_list):
            target = providers_list[int(p_choice) - 1]
        else:
            target = p_choice

    if target in known_backends:
        provider_name = target
        b_obj = known_backends[target]
        base_url = b_obj.base_url
        if not key and b_obj.api_keys:
            key = b_obj.api_keys[0]
        b_type = b_obj.type.value
    else:
        base_url = target
        provider_name = clean_provider_name(target)
        if not key:
            key = typer.prompt("Enter API Key (leave empty if local/none)", default="", hide_input=True)

    console.print(f"\n[cyan]Querying inference endpoint: {base_url}...[/cyan]")

    try:
        live_models = asyncio.run(query_provider_models(base_url, api_key=key if key else None, backend_type=b_type))
    except Exception as exc:
        console.print(f"[bold red]Failed to fetch models from {base_url}: {exc}[/bold red]")
        sys.exit(1)

    if not live_models:
        console.print("[yellow]Provider returned zero models.[/yellow]")
        return

    console.print(f"\n[bold green]Fetched {len(live_models)} models from '{provider_name}':[/bold green]")
    for idx, m in enumerate(live_models[:40], 1):
        console.print(f"  [{idx:2d}] {m}")
    if len(live_models) > 40:
        console.print(f"  ... and {len(live_models) - 40} more models available.")

    console.print("\n[dim]Selection options: 'all', specific numbers (e.g. '1, 3, 5-8'), filter by keyword (e.g. '/qwen'), or 'q' to quit[/dim]")
    selection = typer.prompt("Select models to keep", default="all")

    if selection.lower() == "q":
        return

    selected_models: List[str] = []
    if selection.lower() == "all":
        selected_models = live_models
    elif selection.startswith("/"):
        keyword = selection[1:].strip().lower()
        selected_models = [m for m in live_models if keyword in m.lower()]
        console.print(f"Filtered {len(selected_models)} models matching '{keyword}'.")
    else:
        parts = [p.strip() for p in selection.split(",")]
        for p in parts:
            if "-" in p:
                try:
                    s_str, e_str = p.split("-", 1)
                    s_idx, e_idx = int(s_str), int(e_str)
                    for i in range(s_idx, min(e_idx + 1, len(live_models) + 1)):
                        selected_models.append(live_models[i - 1])
                except ValueError:
                    pass
            elif p.isdigit():
                idx = int(p)
                if 1 <= idx <= len(live_models):
                    selected_models.append(live_models[idx - 1])
            else:
                if p in live_models:
                    selected_models.append(p)

    if not selected_models:
        console.print("[yellow]No models selected.[/yellow]")
        return

    console.print(f"[bold green]Selected {len(selected_models)} models for provider '{provider_name}'.[/bold green]")

    if save:
        # Save to xenrouter.yaml
        found = False
        for b in cfg.backends:
            if b.name.lower() == provider_name.lower():
                b.models_filter = selected_models
                if key and key not in b.api_keys:
                    b.api_keys.append(key)
                found = True
                break

        if not found:
            new_b = BackendConfig(
                name=provider_name,
                type=BackendType(b_type) if b_type in [t.value for t in BackendType] else BackendType.OPENAI_COMPATIBLE,
                base_url=base_url,
                api_keys=[key] if key else [],
                models_filter=selected_models,
                enabled=True,
                priority=1
            )
            cfg.backends.append(new_b)

        # Prompt for active default model
        set_default = typer.prompt("Would you like to set one of these as your active default model? [Number or Enter to skip]", default="")
        if set_default.isdigit():
            idx = int(set_default)
            if 1 <= idx <= len(selected_models):
                cfg.default_model = selected_models[idx - 1]
                console.print(f"Default model set to: [bold yellow]{cfg.default_model}[/bold yellow]")

        # Prompt for alias cascade
        add_alias = typer.prompt("Add these models to a routing alias? [coding / fast / reasoning / general / Enter to skip]", default="")
        if add_alias and add_alias in cfg.aliases:
            for sm in selected_models:
                if sm not in cfg.aliases[add_alias].targets:
                    cfg.aliases[add_alias].targets.insert(0, sm)
            console.print(f"Updated alias '{add_alias}' with newly fetched models.")

        cfg.save()
        if key:
            env_key_name = f"XENROUTER_{provider_name.upper().replace('-', '_')}_API_KEY"
            save_key_to_env(env_key_name, key)
            console.print(f"Key saved to .env as [cyan]{env_key_name}[/cyan]")

        console.print(f"[bold green]Changes saved successfully to xenrouter.yaml[/bold green]")


@provider_app.command(name="add")
def provider_add(
    name: Optional[str] = typer.Argument(None, help="Unique provider name (e.g. together, deepinfra, local-vllm)"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Inference endpoint base URL"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="API key for authentication"),
    backend_type: str = typer.Option("openai_compatible", "--type", "-t", help="Backend engine type"),
    priority: int = typer.Option(1, "--priority", "-p", help="Priority order rank (1 is highest)")
):
    """Add a new custom inference provider with connection test and model selection."""
    if not name:
        name = typer.prompt("Provider name (e.g. together, deepinfra, local-vllm)")
    if not url:
        url = typer.prompt("Base URL endpoint (e.g. https://api.together.xyz/v1, http://127.0.0.1:8000)")
    if key is None:
        key = typer.prompt("API Key (leave blank if local / none)", default="", hide_input=False)

    provider_name = clean_provider_name(name)
    console.print(f"[cyan]Verifying connection to {url}...[/cyan]")

    # Probe endpoint
    start_t = time.perf_counter()
    models_found: List[str] = []
    try:
        models_found = asyncio.run(query_provider_models(url, api_key=key if key else None, backend_type=backend_type))
        dur_ms = (time.perf_counter() - start_t) * 1000.0
        console.print(f"[bold green][+] Connected successfully in {dur_ms:.0f}ms! Found {len(models_found)} live models.[/bold green]")
    except Exception as exc:
        console.print(f"[yellow][!] Could not fetch models: {exc}. Proceeding with manual config.[/yellow]")

    # Build backend
    new_backend = BackendConfig(
        name=provider_name,
        type=BackendType(backend_type) if backend_type in [t.value for t in BackendType] else BackendType.OPENAI_COMPATIBLE,
        base_url=url.rstrip("/"),
        api_keys=[key] if key else [],
        enabled=True,
        priority=priority,
        models_filter=models_found if models_found else None
    )

    cfg = load_config()
    cfg.add_or_update_backend(new_backend)
    cfg.save()

    if key:
        env_var_name = f"XENROUTER_{provider_name.upper().replace('-', '_')}_API_KEY"
        save_key_to_env(env_var_name, key)
        console.print(f"API key stored as [cyan]{env_var_name}[/cyan] in .env")

    console.print(f"[bold green]Provider '{provider_name}' successfully added to xenrouter.yaml[/bold green]")


@provider_app.command(name="list")
def provider_list():
    """List all configured inference providers, endpoints, and models."""
    cfg = load_config()
    registry = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            registry.register(hb)
    for b in cfg.backends:
        registry.register(b)

    table = Table(title="CONFIGURED INFERENCE PROVIDERS", box=box.ROUNDED, border_style="cyan")
    table.add_column("Provider", style="bold white")
    table.add_column("Type", style="dim white")
    table.add_column("Base URL", style="cyan")
    table.add_column("Priority", justify="right")
    table.add_column("Key Pool", style="yellow")
    table.add_column("Configured Models", justify="right")
    table.add_column("State", style="bold green")

    for b in registry.all():
        k_count = len(b.config.api_keys)
        m_count = len(b.models)
        state_str = "[active]" if b.enabled else "[disabled]"
        table.add_row(
            b.name,
            b.type.value,
            b.base_url,
            str(b.priority),
            f"{k_count} key(s)" if k_count else "no key",
            str(m_count),
            state_str
        )

    console.print(table)


@provider_app.command(name="select")
def provider_select(
    provider_name: Optional[str] = typer.Argument(None, help="Provider name to select (e.g. xkiro, wusrouter, iteracompute, apinex)"),
    alias: str = typer.Option("coding", "--alias", "-a", help="Routing alias cascade to update (default: coding)"),
    position: Optional[int] = typer.Option(None, "--pos", "-p", help="Position in cascade: 1 for Primary, 2 for Step 2, etc. (default: 1)"),
    as_default: bool = typer.Option(False, "--default", "-d", help="Also set as global default model")
):
    """Manually select an inference provider and update routing cascades."""
    from xenrouter.limits import resolve_provider_best_model, resolve_model_provider_info

    cfg = load_config()
    registry = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            registry.register(hb)
    for b in cfg.backends:
        registry.register(b)

    all_b = registry.all()

    # Fast non-interactive path when provider_name is specified
    if provider_name:
        p_norm = provider_name.lower().strip()
        matched_backend = None
        for b in all_b:
            if b.name.lower() == p_norm or p_norm in b.name.lower():
                matched_backend = b
                break

        model_to_use = resolve_provider_best_model(p_norm)
        if not model_to_use and matched_backend and matched_backend.models:
            model_to_use = matched_backend.models[0].id

        if not model_to_use:
            console.print(f"[bold red]Unknown provider '{provider_name}'. Run 'xenrouter provider list' to view active providers.[/bold red]")
            raise typer.Exit(1)

        alias_lower = alias.lower().strip()
        if alias_lower not in cfg.aliases:
            cfg.aliases[alias_lower] = AliasConfig(targets=[], description=f"Custom cascade for {alias_lower}")

        targets = cfg.aliases[alias_lower].targets
        if model_to_use in targets:
            targets.remove(model_to_use)

        target_pos = (position - 1) if (position is not None and position >= 1) else 0
        if target_pos >= len(targets):
            targets.append(model_to_use)
        else:
            targets.insert(target_pos, model_to_use)

        if as_default or target_pos == 0:
            cfg.default_model = model_to_use

        cfg.save()
        p_info = resolve_model_provider_info(model_to_use, registry)
        console.print(f"[bold green]Successfully set [cyan]{p_info['provider']}[/cyan] ({model_to_use}) at Step {target_pos + 1} of cascade '{alias_lower}'![/bold green]")
        console.print(f"Saved to [dim]xenrouter.yaml[/dim]. Current '{alias_lower}' cascade sequence:")
        for idx, t in enumerate(targets, 1):
            t_info = resolve_model_provider_info(t, registry)
            console.print(f"  Step {idx}: [bold yellow][{t_info['provider']}][/bold yellow] -> [cyan]{t}[/cyan]")
        return

    # Interactive wizard
    if not all_b:
        console.print("[yellow]No providers found.[/yellow]")
        return

    console.print("[bold cyan]MANUAL INFERENCE PROVIDER SELECTOR & CASCADE MANAGER[/bold cyan]\n")
    for idx, b in enumerate(all_b, 1):
        state_tag = "[bold green]ONLINE[/bold green]" if b.enabled else "[dim]OFFLINE[/dim]"
        best_m = resolve_provider_best_model(b.name) or (b.models[0].id if b.models else "No models")
        console.print(f"  [{idx:2d}] [bold white]{b.name:<16}[/bold white] {state_tag} | Primary: [cyan]{best_m}[/cyan]")

    choice = typer.prompt("\nEnter provider number to select", default="1")
    if not choice.isdigit() or not (1 <= int(choice) <= len(all_b)):
        console.print("[red]Invalid selection.[/red]")
        return

    selected_b = all_b[int(choice) - 1]
    best_model = resolve_provider_best_model(selected_b.name) or (selected_b.models[0].id if selected_b.models else None)

    console.print(f"\n[bold white]Selected Provider: [cyan]{selected_b.name}[/cyan][/bold white]")
    console.print(f"Endpoint: {selected_b.base_url}")
    console.print(f"Primary Free Model: {best_model}")
    console.print(f"Configured Models Count: {len(selected_b.models)}")

    console.print("\nWhere do you want to place this provider?")
    console.print("  [1] Make Step 1 (Primary) for 'coding' cascade")
    console.print("  [2] Make Step 2 for 'coding' cascade")
    console.print("  [3] Make Step 1 (Primary) for 'auto' cascade")
    console.print("  [4] Make Step 1 (Primary) for 'fast' cascade")
    console.print("  [5] Custom position in an alias cascade")
    console.print("  [6] Toggle enable / disable")
    console.print("  [0] Cancel")

    action = typer.prompt("Select action", default="1")
    if action == "1" and best_model:
        targets = cfg.aliases["coding"].targets
        if best_model in targets:
            targets.remove(best_model)
        targets.insert(0, best_model)
        cfg.save()
        console.print(f"[bold green]Set {selected_b.name} as Step 1 of 'coding' cascade![/bold green]")
    elif action == "2" and best_model:
        targets = cfg.aliases["coding"].targets
        if best_model in targets:
            targets.remove(best_model)
        targets.insert(1 if len(targets) >= 1 else 0, best_model)
        cfg.save()
        console.print(f"[bold green]Set {selected_b.name} as Step 2 of 'coding' cascade![/bold green]")
    elif action == "3" and best_model:
        targets = cfg.aliases["auto"].targets
        if best_model in targets:
            targets.remove(best_model)
        targets.insert(0, best_model)
        cfg.default_model = best_model
        cfg.save()
        console.print(f"[bold green]Set {selected_b.name} as Primary for 'auto' cascade![/bold green]")
    elif action == "4" and best_model:
        targets = cfg.aliases["fast"].targets
        if best_model in targets:
            targets.remove(best_model)
        targets.insert(0, best_model)
        cfg.save()
        console.print(f"[bold green]Set {selected_b.name} as Step 1 of 'fast' cascade![/bold green]")
    elif action == "5" and best_model:
        target_alias = typer.prompt("Enter cascade name (e.g. coding, fast, reasoning, general)", default="coding").strip().lower()
        pos_str = typer.prompt("Enter step position number (1 for Primary)", default="1").strip()
        pos = int(pos_str) if pos_str.isdigit() else 1
        if target_alias in cfg.aliases:
            targets = cfg.aliases[target_alias].targets
            if best_model in targets:
                targets.remove(best_model)
            insert_idx = max(0, min(pos - 1, len(targets)))
            targets.insert(insert_idx, best_model)
            cfg.save()
            console.print(f"[bold green]Set {selected_b.name} at Step {insert_idx + 1} of '{target_alias}' cascade![/bold green]")
    elif action == "6":
        new_state = not selected_b.enabled
        cfg.toggle_backend(selected_b.name, new_state)
        cfg.save()
        console.print(f"Provider '{selected_b.name}' is now {'enabled' if new_state else 'disabled'}.")


@provider_app.command(name="reorder")
def provider_reorder_cmd(
    alias: str = typer.Argument(..., help="Alias cascade name (e.g. coding, fast, reasoning, general)"),
    providers: List[str] = typer.Argument(..., help="Ordered list of provider names (e.g. apinex xkiro wusrouter iteracompute)")
):
    """Reorder a cascade by specifying provider names in your desired priority order."""
    from xenrouter.limits import resolve_provider_best_model, resolve_model_provider_info

    cfg = load_config()
    alias_lower = alias.lower().strip()
    if alias_lower not in cfg.aliases:
        console.print(f"[bold red]Alias '{alias_lower}' not found. Available aliases: {list(cfg.aliases.keys())}[/bold red]")
        raise typer.Exit(1)

    new_targets = []
    for p in providers:
        m = resolve_provider_best_model(p)
        if m:
            if m not in new_targets:
                new_targets.append(m)
        else:
            console.print(f"[yellow]Warning: Provider '{p}' not recognized or has no configured best model. Skipping.[/yellow]")

    if not new_targets:
        console.print("[bold red]No valid providers resolved. Cascade unchanged.[/bold red]")
        raise typer.Exit(1)

    # Preserve any unmentioned models at the end of the cascade
    for existing in cfg.aliases[alias_lower].targets:
        if existing not in new_targets:
            new_targets.append(existing)

    cfg.aliases[alias_lower].targets = new_targets
    cfg.save()

    console.print(f"[bold green]Successfully reordered cascade '{alias_lower}' by provider sequence![/bold green]")
    console.print(f"Saved to [dim]xenrouter.yaml[/dim]. Current sequence:")
    for idx, t in enumerate(new_targets, 1):
        t_info = resolve_model_provider_info(t)
        console.print(f"  Step {idx:2d}: [bold yellow][{t_info['provider']}][/bold yellow] -> [cyan]{t}[/cyan]")


@provider_app.command(name="enable")
def provider_enable(name: str = typer.Argument(..., help="Provider name to enable")):
    """Enable an inference provider."""
    cfg = load_config()
    if cfg.toggle_backend(name, True):
        cfg.save()
        console.print(f"[bold green]Provider '{name}' enabled.[/bold green]")
    else:
        # Check Hermes providers
        console.print(f"Adding provider override in xenrouter.yaml...")
        new_b = BackendConfig(name=name, base_url="", enabled=True)
        cfg.backends.append(new_b)
        cfg.save()
        console.print(f"[bold green]Provider '{name}' enabled.[/bold green]")


@provider_app.command(name="disable")
def provider_disable(name: str = typer.Argument(..., help="Provider name to disable")):
    """Disable an inference provider."""
    cfg = load_config()
    cfg.toggle_backend(name, False)
    cfg.save()
    console.print(f"[bold yellow]Provider '{name}' disabled.[/bold yellow]")


@provider_app.command(name="remove")
def provider_remove(name: str = typer.Argument(..., help="Provider name to remove")):
    """Remove a custom inference provider from configuration."""
    cfg = load_config()
    if cfg.remove_backend(name):
        cfg.save()
        console.print(f"[bold green]Provider '{name}' removed from xenrouter.yaml[/bold green]")
    else:
        console.print(f"[yellow]Provider '{name}' not found in custom backends list.[/yellow]")


@app.command()
def init(
    output: str = typer.Option("xenrouter.yaml", "--output", "-o", help="Target config file path")
):
    """Generate a starter xenrouter.yaml configuration file."""
    cfg = get_default_config()
    save_config(cfg, output)
    console.print(f"[bold green]Configuration generated successfully at '{output}'[/bold green]")


@app.command()
def test(
    model: str = typer.Option("coding", "--model", "-m", help="Model or alias to test"),
    prompt: str = typer.Option("Hi", "--prompt", help="Prompt text"),
    endpoint: str = typer.Option("http://127.0.0.1:8989", "--url", "-u", help="Xenrouter base URL"),
    all_providers: bool = typer.Option(False, "--all", "-a", help="Run advanced test saying 'Hi' to all configured inference providers")
):
    """Send a test chat completion to verify routing and measure response speed."""
    if all_providers:
        from scripts.advanced_provider_test import run_advanced_testing
        asyncio.run(run_advanced_testing(prompt=prompt))
        return

    base = endpoint.rstrip("/")
    url = f"{base}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    console.print(f"[cyan]Dispatching test request for model '[bold]{model}[/bold]'...[/cyan]")
    start = time.perf_counter()

    try:
        resp = httpx.post(url, json=payload, timeout=60.0)
        dur = (time.perf_counter() - start) * 1000.0
        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            safe_reply = reply.encode("ascii", errors="replace").decode("ascii")
            console.print(f"\n[bold green]Success (HTTP 200) in {dur:.1f}ms:[/bold green]")
            console.print(f"[white]{safe_reply}[/white]\n")
            console.print(f"Tokens: Prompt {usage.get('prompt_tokens', 0)} | Completion {usage.get('completion_tokens', 0)}")
        else:
            console.print(f"[bold red]Request failed with HTTP {resp.status_code}:[/bold red] {resp.text}")
    except Exception as exc:
        console.print(f"[bold red]Failed to communicate with Xenrouter: {exc}[/bold red]")


@app.command(name="hermes")
def hermes_status():
    """Inspect and test imported Hermes Agent providers."""
    backends = discover_hermes_backends()

    if not backends:
        console.print("[yellow]No Hermes providers found in ~/.hermes or AppData/Local/hermes.[/yellow]")
        return

    console.print(f"[bold cyan]Discovered {len(backends)} Hermes providers (actual provider names):[/bold cyan]")
    table = Table(title="HERMES PROVIDERS AUDIT", box=box.ROUNDED, border_style="cyan")
    table.add_column("Provider", style="bold white")
    table.add_column("Base URL", style="cyan")
    table.add_column("Key Pool", style="yellow")
    table.add_column("Strategy", style="dim white")
    table.add_column("Models", justify="right")
    table.add_column("Quota / Rate Limit", style="magenta")

    for b in backends:
        key_display = f"{len(b.api_keys)} key(s)"
        m_count = str(len(b.models_filter)) if b.models_filter else "-"
        table.add_row(b.name, b.base_url, key_display, b.key_rotation_strategy.value, m_count, "Uncapped")

    console.print(table)


@app.command(name="banner")
def banner(
    compact: bool = typer.Option(False, "--compact", "-c", help="Render without subtext"),
):
    """Display the aesthetic Xenrouter Big Boss welcome banner."""
    console.print(render_welcome_banner(include_subtext=not compact))


@app.command(name="welcome")
def welcome(
    compact: bool = typer.Option(False, "--compact", "-c", help="Render without subtext"),
):
    """Display the aesthetic Xenrouter Big Boss welcome banner."""
    console.print(render_welcome_banner(include_subtext=not compact))


def view_routing_graph():
    """Render and display the hierarchical inference routing graph."""
    cfg = load_config()
    reg = BackendRegistry()
    if cfg.import_hermes_providers:
        for hb in discover_hermes_backends():
            reg.register(hb)
    for b in cfg.backends:
        reg.register(b)
    console.print(render_routes_view(cfg, reg))


@route_app.callback(invoke_without_command=True)
def route_default(ctx: typer.Context):
    """View the visual inference routing graph."""
    if ctx.invoked_subcommand is None:
        view_routing_graph()


@route_app.command(name="graph")
def graph_cmd():
    """Display the hierarchical inference routing graph tree."""
    view_routing_graph()


@route_app.command(name="view")
def view_cmd():
    """Display the hierarchical inference routing graph tree."""
    view_routing_graph()


@route_app.command(name="providers")
def providers_cascade_cmd():
    """Display the provider-centric execution cascade and failover graph."""
    from rich.tree import Tree
    from rich.panel import Panel
    from rich import box

    tree = Tree("[bold bright_cyan]INFERENCE PROVIDER EXECUTION GRAPH[/bold bright_cyan]")
    steps = [
        (1, "APInex", "https://api.apinex.bond/v1", "free/deepseek-v4.1-flash", "2 active keys", "Try Key 1 -> On 429/401 -> Rotate Key 2 (Exhaust all before cascade)", "10M weighted tok/day | 15 RPM | 65k ctx", "Both keys exhausted"),
        (2, "Google AI Studio", "https://generativelanguage.googleapis.com", "gemini-2.0-flash", "1 key", "High-volume frontier cascade", "1.5 Billion tok/day | 30 RPM | 4M TPM | 1M ctx", "Daily limit or HTTP 429"),
        (3, "SiliconFlow", "https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", "1 key", "Zero-cost sub-14B uncapped execution", "Permanently Free / Uncapped | 1,000 RPM | 50k TPM", "Provider latency or degraded"),
        (4, "Nous Research", "https://inference.nousresearch.com/v1", "hermes-3-llama-3.1-70b", "1 key", "High-capacity reasoning cascade", "144M tok/day | 50 RPM | 500k TPM | 128k ctx", "Monthly pool exhaustion or 429"),
        (5, "River AI", "https://api.river.ai/v1", "deepseek-ai/DeepSeek-V4.1-Flash", "1 key", "High-context 1M token gateway", "$25 credit (~208M tokens) | 60 RPM | 1M ctx", "Credit depletion"),
        (6, "Inception Labs", "https://api.inceptionlabs.ai/v1", "mercury-3", "1 key", "Low-latency diffusion architecture", "100M grant + 15M/day | 60-120 RPM | 64k ctx", "Concurrency ceiling or 429"),
        (7, "IteraCompute", "https://api.iteracompute.com/v1", "qwen/qwen3.8-27b", "1 key", "High-parameter 27B model failover", "30M tok/month | 30 RPM | 160k TPM | 65k ctx", "Monthly quota limit"),
        (8, "Groq Cloud", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant", "1 key", "Ultra-high-speed LPU inference (500+ tok/s)", "~1M tok/day | 30 RPM | 30k TPM | 128k ctx", "TPM/RPM ceiling"),
        (9, "OpenRouter", "https://openrouter.ai/api/v1", "llama-3.3-70b-instruct:free", "1 key", "Free-tier aggregator fallback", "~2M-4M tok/day | 20 RPM | 50 req/day free", "Daily quota exhausted"),
        (10, "Mistral AI", "https://api.mistral.ai/v1", "codestral-latest", "1 key", "Final high-context code safety net", "Free Experiment tier | 60 RPM (1 RPS) | 256k ctx", "Terminal fallback")
    ]

    cur = tree
    for num, name, url, model, keys, policy, quota, trigger in steps:
        node_text = (
            f"[bold yellow][STEP {num}] {name}[/bold yellow] [dim]({url})[/dim]\n"
            f"  [dim]Primary Target:[/dim] [bold cyan]{model}[/bold cyan]   [dim]Key Pool:[/dim] [white]{keys}[/white]\n"
            f"  [dim]Rotation Policy:[/dim] [green]{policy}[/green]\n"
            f"  [dim]Token Capacity:[/dim] [magenta]{quota}[/magenta]\n"
            f"  [dim]Failover Trigger:[/dim] [red]{trigger}[/red]"
        )
        cur = cur.add(node_text)

    p = Panel(tree, title="[bold cyan]INFERENCE PROVIDER EXECUTION ORDER[/bold cyan]", box=box.ROUNDED, border_style="bright_blue")
    console.print(p)


@route_app.command(name="set")
def set_cascade_cmd(
    alias: str = typer.Argument(..., help="Alias name (e.g. coding, fast, reasoning, general, auto)"),
    targets: List[str] = typer.Argument(..., help="Ordered model target IDs in cascade sequence")
):
    """Set the full cascade targets list for an alias."""
    cfg = load_config()
    alias_lower = alias.lower().strip()
    if alias_lower not in cfg.aliases:
        cfg.aliases[alias_lower] = AliasConfig(targets=targets, description=f"Custom cascade for {alias_lower}")
    else:
        cfg.aliases[alias_lower].targets = targets

    cfg.save()
    console.print(f"[bold green]Updated cascade for alias '{alias_lower}':[/bold green]")
    for i, t in enumerate(targets, 1):
        console.print(f"  Step {i}: [cyan]{t}[/cyan]")


@route_app.command(name="add")
def add_cascade_cmd(
    alias: str = typer.Argument(..., help="Alias name"),
    model: str = typer.Argument(..., help="Model ID to append or insert into cascade"),
    position: Optional[int] = typer.Option(None, "--pos", "-p", help="1-indexed position to insert model at (default: append)")
):
    """Add a model to an existing alias cascade."""
    cfg = load_config()
    alias_lower = alias.lower().strip()
    if alias_lower not in cfg.aliases:
        console.print(f"[red]Alias '{alias_lower}' not found. Available aliases: {list(cfg.aliases.keys())}[/red]")
        raise typer.Exit(1)

    cur_targets = cfg.aliases[alias_lower].targets
    if model in cur_targets:
        console.print(f"[yellow]Model '{model}' is already in cascade '{alias_lower}'.[/yellow]")
        return

    if position is not None and 1 <= position <= len(cur_targets) + 1:
        cur_targets.insert(position - 1, model)
    else:
        cur_targets.append(model)

    cfg.save()
    console.print(f"[bold green]Added '{model}' to cascade '{alias_lower}'. Current sequence:[/bold green]")
    for i, t in enumerate(cur_targets, 1):
        console.print(f"  Step {i}: [cyan]{t}[/cyan]")


@route_app.command(name="remove")
def remove_cascade_cmd(
    alias: str = typer.Argument(..., help="Alias name"),
    model: str = typer.Argument(..., help="Model ID to remove from cascade")
):
    """Remove a model from an alias cascade."""
    cfg = load_config()
    alias_lower = alias.lower().strip()
    if alias_lower not in cfg.aliases:
        console.print(f"[red]Alias '{alias_lower}' not found.[/red]")
        raise typer.Exit(1)

    cur_targets = cfg.aliases[alias_lower].targets
    if model not in cur_targets:
        console.print(f"[yellow]Model '{model}' not found in cascade '{alias_lower}'.[/yellow]")
        return

    cur_targets.remove(model)
    cfg.save()
    console.print(f"[bold green]Removed '{model}' from cascade '{alias_lower}'. Remaining sequence:[/bold green]")
    for i, t in enumerate(cur_targets, 1):
        console.print(f"  Step {i}: [cyan]{t}[/cyan]")


@route_app.command(name="primary")
def primary_cmd(
    model: str = typer.Argument(..., help="Model ID to set as primary default")
):
    """Set the primary default model and place at the front of 'auto' cascade."""
    cfg = load_config()
    cfg.default_model = model
    if "auto" in cfg.aliases:
        targets = cfg.aliases["auto"].targets
        if model in targets:
            targets.remove(model)
        targets.insert(0, model)
    cfg.save()
    console.print(f"[bold green]Primary default model set to '{model}' and placed at top of auto cascade.[/bold green]")


@route_app.command(name="edit")
def edit_cascade_interactive():
    """Interactive terminal wizard to inspect, reorder, and modify routing cascades."""
    cfg = load_config()
    aliases = list(cfg.aliases.keys())
    console.print("[bold cyan]XENROUTER INTERACTIVE CASCADE MANAGER[/bold cyan]\n")
    for idx, a in enumerate(aliases, 1):
        console.print(f"  [{idx}] [bold yellow]{a}[/bold yellow] -> {len(cfg.aliases[a].targets)} target(s)")

    choice = typer.prompt("\nSelect alias number to edit (or 'q' to quit)", default="1")
    if choice.lower() in ["q", "quit", "exit"]:
        return

    try:
        alias_idx = int(choice) - 1
        selected_alias = aliases[alias_idx]
    except Exception:
        console.print("[red]Invalid selection.[/red]")
        return

    alias_cfg = cfg.aliases[selected_alias]
    console.print(f"\n[bold green]Editing cascade for: {selected_alias}[/bold green]")
    for i, t in enumerate(alias_cfg.targets, 1):
        console.print(f"  [{i}] {t}")

    console.print("\nActions: [a] Add model | [r] Remove model | [q] Cancel")
    act = typer.prompt("Select action", default="q")
    if act.lower() == "a":
        new_m = typer.prompt("Enter model ID to add")
        if new_m and new_m not in alias_cfg.targets:
            alias_cfg.targets.append(new_m)
            cfg.save()
            console.print(f"[bold green]Added '{new_m}' to {selected_alias}. Saved to xenrouter.yaml[/bold green]")
    elif act.lower() == "r":
        rm_idx = int(typer.prompt("Enter step number to remove")) - 1
        if 0 <= rm_idx < len(alias_cfg.targets):
            removed = alias_cfg.targets.pop(rm_idx)
            cfg.save()
            console.print(f"[bold green]Removed '{removed}' from {selected_alias}. Saved to xenrouter.yaml[/bold green]")


@route_app.command(name="provider")
def route_provider_shortcut(
    alias: str = typer.Argument(..., help="Alias cascade (e.g. coding, fast, auto)"),
    provider: str = typer.Argument(..., help="Provider name (e.g. xkiro, wusrouter, iteracompute, apinex)"),
    position: int = typer.Option(1, "--pos", "-p", help="1-indexed position in cascade (default: 1)")
):
    """Place a provider directly into a cascade sequence."""
    provider_select(provider_name=provider, alias=alias, position=position)


def main():
    app()


if __name__ == "__main__":
    main()
