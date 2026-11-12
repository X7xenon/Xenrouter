"""
Ultra-aesthetic, minimalist developer TUI components for Xenrouter.
Designed with razor-clean typography, subtle borders, high information density,
and 100% Windows terminal compatibility (zero UnicodeEncodeError risk, zero emojis, zero double-slashes).
"""

from typing import Any, Dict, List, Optional
import sys
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from xenrouter.backends.base import BaseBackend
from xenrouter.config import XenrouterConfig
from xenrouter.limits import ModelLimitProfile, classify_model_tier, get_all_model_limits, resolve_model_provider_info
from xenrouter.types import RequestLog, ServerMetrics

# Pixel art palette: 8 rows x 10 blocks (each block = 2 chars '██')
PIXEL_X_PALETTE: List[Dict[int, str]] = [
    # row 0 (top: orange / coral)
    {0: "#f97316", 1: "#fb923c", 8: "#fb7185", 9: "#f43f5e"},
    # row 1 (amber / rose)
    {1: "#fbbf24", 2: "#f59e0b", 7: "#f43f5e", 8: "#e11d48"},
    # row 2 (lime-yellow / purple)
    {2: "#a3e635", 3: "#84cc16", 6: "#c084fc", 7: "#a855f7"},
    # row 3 (green / purple-violet center cross)
    {3: "#22c55e", 4: "#10b981", 5: "#9333ea", 6: "#7c3aed"},
    # row 4 (teal / indigo center cross)
    {3: "#14b8a6", 4: "#06b6d4", 5: "#6366f1", 6: "#4f46e5"},
    # row 5 (cyan / blue)
    {2: "#06b6d4", 3: "#0ea5e9", 6: "#3b82f6", 7: "#2563eb"},
    # row 6 (sky blue / royal blue)
    {1: "#0ea5e9", 2: "#38bdf8", 7: "#2563eb", 8: "#1d4ed8"},
    # row 7 (bottom: bright cyan / deep blue)
    {0: "#38bdf8", 1: "#60a5fa", 8: "#1d4ed8", 9: "#1e40af"},
]

# Compact 6-row pixel art palette for responsive hero headers
PIXEL_X_PALETTE_6: List[Dict[int, str]] = [
    {0: "#f97316", 1: "#fb923c", 6: "#fb7185", 7: "#f43f5e"},
    {1: "#fbbf24", 2: "#f59e0b", 5: "#c084fc", 6: "#a855f7"},
    {2: "#a3e635", 3: "#22c55e", 4: "#9333ea", 5: "#7c3aed"},
    {2: "#14b8a6", 3: "#06b6d4", 4: "#6366f1", 5: "#4f46e5"},
    {1: "#0ea5e9", 2: "#38bdf8", 5: "#3b82f6", 6: "#2563eb"},
    {0: "#38bdf8", 1: "#60a5fa", 6: "#1d4ed8", 7: "#1e40af"},
]


def _can_encode(text: str) -> bool:
    try:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        text.encode(enc)
        return True
    except Exception:
        return False


def render_dots(indent: str = "  ") -> Text:
    """Render terminal window control dots (red, amber, green)."""
    dots = Text(indent)
    dot_char = "●" if _can_encode("●") else "o"
    dots.append(f"{dot_char}  ", style="#ff5f56")
    dots.append(f"{dot_char}  ", style="#ffbd2e")
    dots.append(dot_char, style="#27c93f")
    return dots


def render_pixel_x(indent: str = "  ") -> List[Text]:
    """Render the chunky, colorful rainbow-gradient pixel art 'X'."""
    lines: List[Text] = []
    block_char = "██" if _can_encode("██") else "##"
    for row in PIXEL_X_PALETTE:
        line = Text(indent)
        for col in range(10):
            if col in row:
                line.append(block_char, style=row[col])
            else:
                line.append("  ")
        lines.append(line)
    return lines


def render_welcome_banner(
    indent: str = "  ",
    include_subtext: bool = True,
    custom_subtext: Optional[str] = None
) -> Group:
    """
    Render ultra-aesthetic welcome banner for Big Boss.
    Features macOS-style terminal dots, chunky rainbow-gradient pixel art 'X',
    and 'Welcome to Xenrouter Big Boss!'.
    """
    elements = [
        Text(""),
        render_dots(indent),
        Text(""),
        *render_pixel_x(indent),
        Text(""),
    ]

    title = Text(indent)
    title.append("Welcome to ", style="bold white")
    title.append("Xenrouter ", style="bold #38bdf8")
    title.append("Big Boss!", style="bold #fbbf24")
    elements.append(title)

    if include_subtext:
        sub = Text(indent)
        sub_msg = custom_subtext or "Unified Local Inference Router & Token Cascade Engine"
        sub.append(sub_msg, style="dim")
        elements.append(sub)

    elements.append(Text(""))
    return Group(*elements)


def render_welcome_panel() -> Panel:
    """Render the welcome banner encapsulated in a themed panel for TUI views."""
    return Panel(
        render_welcome_banner(indent="    "),
        title="[bold bright_cyan]WELCOME[/bold bright_cyan]",
        box=box.ROUNDED,
        border_style="dim cyan",
        padding=(1, 2)
    )


def format_duration(seconds: float) -> str:
    """Format seconds into concise terminal uptime."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def format_number(val: int) -> str:
    """Format large numbers with readable metric suffixes."""
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    elif val >= 1_000:
        return f"{val / 1_000:.1f}k"
    return str(val)


def render_header(
    config: XenrouterConfig,
    metrics: ServerMetrics,
    online_count: int,
    total_count: int,
    compact: bool = False
) -> Panel:
    """Render aesthetic command bar with chunky rainbow pixel-art 'X' and Big Boss greeting."""
    total_reqs = metrics.total_requests
    succ_rate = (metrics.successful_requests / total_reqs * 100.0) if total_reqs > 0 else 100.0

    if compact:
        grid = Table.grid(expand=True)
        grid.add_column(ratio=6, justify="left")
        grid.add_column(ratio=6, justify="right")

        left = Text()
        left.append("● ", style="#ff5f56")
        left.append("● ", style="#ffbd2e")
        left.append("●  ", style="#27c93f")
        left.append("xenrouter ", style="bold bright_cyan")
        left.append("v0.1.0  ", style="dim white")
        left.append(f"http://{config.host}:{config.port}/v1  ", style="cyan")
        left.append("active: ", style="dim")
        left.append(f"{config.default_model or 'coding'}  ", style="bold yellow")
        left.append("status: ", style="dim")
        left.append("nominal", style="bold green" if online_count > 0 else "bold yellow")

        right = Text()
        right.append(f"{online_count}/{total_count} nodes online  ", style="bold green")
        right.append(f"req: {total_reqs}  ", style="white")
        right.append(f"rel: {succ_rate:.0f}%  ", style="green" if succ_rate >= 95 else "red")
        right.append(f"tokens: {format_number(metrics.total_completion_tokens)}  ", style="cyan")
        right.append(f"up: {format_duration(metrics.uptime_seconds)}", style="dim")

        grid.add_row(left, right)
        return Panel(
            grid,
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1)
        )

    # Full Hero Header with chunky pixel-art 'X' and Big Boss greeting
    grid = Table.grid(expand=True)
    grid.add_column(width=20)
    grid.add_column(ratio=1)

    dots = Text("  ")
    dots.append("●  ", style="#ff5f56")
    dots.append("●  ", style="#ffbd2e")
    dots.append("●", style="#27c93f")

    x_lines = []
    for r in PIXEL_X_PALETTE_6:
        l = Text("  ")
        for col in range(8):
            if col in r:
                l.append("██", style=r[col])
            else:
                l.append("  ")
        x_lines.append(l)

    info = [
        Text.from_markup(f"[bold white]Welcome to[/bold white] [bold #38bdf8]Xenrouter[/bold #38bdf8] [bold #fbbf24]Big Boss![/bold #fbbf24]  [dim white]v0.1.0[/dim white]"),
        Text.from_markup("[dim cyan]Unified Local Inference Router & Dynamic Token Cascade Engine[/dim cyan]"),
        Text.from_markup(f"[dim]endpoint:[/dim] [bold cyan]http://{config.host}:{config.port}/v1[/bold cyan]   [dim]active:[/dim] [bold yellow]{config.default_model or 'coding'}[/bold yellow]"),
        Text.from_markup(f"[dim]status:[/dim] [bold green]{online_count}/{total_count} nodes online ({'nominal' if online_count > 0 else 'offline'})[/bold green]   [dim]reqs:[/dim] [white]{total_reqs}[/white]   [dim]rel:[/dim] [{'green' if succ_rate >= 95 else 'red'}]{succ_rate:.0f}%[/]"),
        Text.from_markup(f"[dim]tokens:[/dim] [bold cyan]{format_number(metrics.total_completion_tokens)} completion[/bold cyan]   [dim]uptime:[/dim] [dim white]{format_duration(metrics.uptime_seconds)}[/dim white]"),
        Text(""),
    ]

    grid.add_row(dots, Text(""))
    for xl, inf in zip(x_lines, info):
        grid.add_row(xl, inf)

    return Panel(grid, box=box.ROUNDED, border_style="bright_blue", padding=(0, 1))


def render_backends_table(backends: List[BaseBackend]) -> Table:
    """Render high-density, clean provider nodes table with actual provider names."""
    table = Table(
        title="[bold white]INFERENCE PROVIDERS[/bold white]",
        box=box.ROUNDED,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        title_justify="left",
        pad_edge=False
    )

    table.add_column("Provider", style="bold white", width=16)
    table.add_column("Status", justify="left", width=12)
    table.add_column("Ping", justify="right", width=9)
    table.add_column("Primary Model", style="yellow", width=28)
    table.add_column("Models", justify="right", width=8)
    table.add_column("Key Pool", style="dim white", width=12)
    table.add_column("Quota / Rate Limit", style="magenta", width=16)

    # Sort backends: ONLINE first, then by latency
    sorted_backends = sorted(
        backends,
        key=lambda b: (0 if b.status.value == "ONLINE" else 1, b.latency_ms if b.latency_ms > 0 else 99999)
    )

    displayed = [b for b in sorted_backends if b.enabled][:10]

    for b in displayed:
        status_val = b.status.value
        if status_val == "ONLINE":
            status_text = Text("* online", style="bold green")
        elif status_val == "DEGRADED":
            status_text = Text("! degraded", style="bold yellow")
        elif status_val == "UNKNOWN":
            status_text = Text("o standby", style="dim yellow")
        else:
            status_text = Text("x offline", style="dim red")

        # Latency coloring
        if b.latency_ms <= 0:
            ping_text = Text("-", style="dim")
        elif b.latency_ms < 500:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="green")
        elif b.latency_ms < 2000:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="yellow")
        else:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="red")

        # Primary model display
        primary_model = "-"
        if b.models:
            primary_model = b.models[0].id
            if len(primary_model) > 27:
                primary_model = primary_model[:24] + "..."

        # Key pool
        keys_states = b.key_rotator.get_states()
        if not keys_states:
            keys_text = Text("local / none", style="dim")
        else:
            active_k = sum(1 for k in keys_states if k.is_active)
            keys_text = Text(f"{active_k}/{len(keys_states)} active", style="dim cyan")

        # Quota info
        if b.ratelimit_remaining is not None:
            quota_text = Text(f"{b.ratelimit_remaining} req left", style="bold magenta")
        elif b.quota_remaining_str:
            quota_text = Text(b.quota_remaining_str[:15], style="magenta")
        else:
            quota_text = Text("Uncapped", style="dim")

        table.add_row(
            b.name,
            status_text,
            ping_text,
            primary_model,
            str(len(b.models)),
            keys_text,
            quota_text
        )

    if not displayed:
        table.add_row("-", Text("no providers", style="dim"), "-", "-", "-", "-", "-")

    return table


def render_aliases_panel(config: XenrouterConfig, backends: List[BaseBackend]) -> Panel:
    """Render smart cascades and routing map in clean aesthetic lines."""
    text = Text()

    online_models = set()
    for b in backends:
        for m in b.models:
            online_models.add(m.id.lower())

    for alias, alias_cfg in config.aliases.items():
        if alias in ["gpt-4o", "gpt-4", "claude-3-5-sonnet"]:
            continue  # Keep panel concise, show core cascades
        text.append(f"  {alias:<12}", style="bold cyan")
        text.append(" -> ", style="dim")

        targets_str = []
        for t in alias_cfg.targets[:4]:
            is_live = t.lower() in online_models or t in config.aliases
            color = "green" if is_live else "dim"
            targets_str.append(f"[{color}]{t}[/{color}]")

        text.append_text(Text.from_markup(" | ".join(targets_str)))
        if len(alias_cfg.targets) > 4:
            text.append(f" (+{len(alias_cfg.targets) - 4})", style="dim")
        text.append("\n")

    return Panel(
        text,
        title="[bold white]ROUTING CASCADES[/bold white]",
        box=box.ROUNDED,
        border_style="dim white",
        title_align="left",
        padding=(0, 1)
    )


def render_logs_panel(logs: List[RequestLog]) -> Panel:
    """Render live inference inspector showing real-time requests."""
    table = Table.grid(expand=True)
    table.add_column(width=9, style="dim")
    table.add_column(width=6, style="cyan")
    table.add_column(width=16, style="yellow")
    table.add_column(ratio=6, style="white")
    table.add_column(width=9, justify="right", style="green")
    table.add_column(width=9, justify="right", style="cyan")
    table.add_column(width=8, justify="right")

    if not logs:
        empty_text = Text()
        empty_text.append("Ready for inference.\n", style="dim white")
        empty_text.append("Dispatch requests to ", style="dim")
        empty_text.append("http://127.0.0.1:8989/v1/chat/completions", style="bold cyan")
        empty_text.append(" using model 'coding' or '<provider>/<model>'.", style="dim")
        return Panel(
            empty_text,
            title="[bold white]LIVE INFERENCE INSPECTOR[/bold white]",
            box=box.ROUNDED,
            border_style="dim cyan",
            title_align="left",
            padding=(0, 1)
        )

    for item in logs[-6:]:
        import datetime
        time_str = datetime.datetime.fromtimestamp(item.timestamp).strftime("%H:%M:%S")

        status_style = "bold green" if item.status_code == 200 else "bold red"
        status_text = Text(str(item.status_code), style=status_style)

        table.add_row(
            time_str,
            "POST",
            f"[{item.backend_used}]",
            item.resolved_model[:36],
            f"{item.duration_ms:.0f}ms",
            f"{item.tokens_completion} tok",
            status_text
        )

    return Panel(
        table,
        title="[bold white]LIVE INFERENCE INSPECTOR[/bold white]",
        box=box.ROUNDED,
        border_style="dim cyan",
        title_align="left",
        padding=(0, 1)
    )


def render_models_view(
    config: XenrouterConfig,
    registry: Any,
    page: int = 0,
    page_size: int = 15
) -> Panel:
    """Render comprehensive models catalog with tier tags, context, and provider mapping."""
    all_models: List[Dict[str, Any]] = []

    # Virtual cascades first
    for alias, alias_cfg in config.aliases.items():
        all_models.append({
            "id": alias,
            "provider": "xenrouter-alias",
            "tier": "VIRTUAL-CASCADE",
            "ctx": "Dynamic",
            "rpm": "Dynamic",
            "active": alias == config.default_model
        })

    # Provider models
    for b in registry.all():
        for m in b.models:
            tier_info = classify_model_tier(m.id, b.name)
            ctx_val = tier_info.get("ctx", 32768)
            rpm_val = tier_info.get("rpm", "-")
            all_models.append({
                "id": m.id,
                "provider": b.name,
                "tier": tier_info["tier"],
                "ctx": f"{ctx_val // 1024}k" if isinstance(ctx_val, int) else str(ctx_val),
                "rpm": f"{rpm_val} RPM" if rpm_val != "-" else "Uncapped",
                "active": m.id == config.default_model
            })

    total_models = len(all_models)
    total_pages = max(1, (total_models + page_size - 1) // page_size)
    cur_page = max(0, min(page, total_pages - 1))

    start_idx = cur_page * page_size
    page_items = all_models[start_idx : start_idx + page_size]

    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        pad_edge=False
    )
    table.add_column("#", justify="right", width=5, style="dim")
    table.add_column("Model Identifier", style="bold white", ratio=4)
    table.add_column("Provider", style="cyan", width=16)
    table.add_column("Tier", justify="center", width=16)
    table.add_column("Context", justify="right", width=10)
    table.add_column("Rate Limit", justify="right", width=14)
    table.add_column("Active", justify="center", width=10)

    for idx, item in enumerate(page_items, start_idx + 1):
        tier_style = "bold green" if "FREE" in item["tier"] else ("cyan" if "TIER" in item["tier"] else "yellow")
        if item["tier"] == "LOCAL":
            tier_style = "bold blue"
        elif item["tier"] == "VIRTUAL-CASCADE":
            tier_style = "bold magenta"

        active_text = Text("[ACTIVE]", style="bold bright_green") if item["active"] else Text("-", style="dim")
        table.add_row(
            str(idx),
            item["id"],
            item["provider"],
            Text(item["tier"], style=tier_style),
            str(item["ctx"]),
            str(item["rpm"]),
            active_text
        )

    title = f"[bold white]MODELS CATALOG & TIER INVENTORY[/bold white] [dim](Page {cur_page + 1}/{total_pages} | {total_models} Total Models)[/dim]"
    return Panel(
        table,
        title=title,
        box=box.ROUNDED,
        border_style="bright_blue",
        title_align="left",
        padding=(0, 1)
    )


def render_limits_view(
    registry: Any,
    page: int = 0,
    page_size: int = 15
) -> Panel:
    """Render full model limits, quotas, and free/free-tier classification matrix."""
    profiles: List[ModelLimitProfile] = get_all_model_limits(registry)

    tier_rank = {"FREE": 0, "FREE-TIER": 1, "COMMUNITY": 2, "DEVELOPER-TIER": 3, "LOCAL": 4, "DEVELOPER-CREDITS": 5, "STANDARD": 6}
    sorted_profiles = sorted(profiles, key=lambda p: (tier_rank.get(p.tier, 99), p.provider, p.model_id))

    free_count = sum(1 for p in profiles if p.tier == "FREE")
    freetier_count = sum(1 for p in profiles if "TIER" in p.tier or p.tier == "COMMUNITY")
    local_count = sum(1 for p in profiles if p.tier == "LOCAL")
    total_count = len(profiles)

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    cur_page = max(0, min(page, total_pages - 1))
    start_idx = cur_page * page_size
    page_items = sorted_profiles[start_idx : start_idx + page_size]

    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        pad_edge=False
    )
    table.add_column("#", justify="right", width=5, style="dim")
    table.add_column("Model Identifier", style="bold white", ratio=4)
    table.add_column("Provider", style="cyan", width=14)
    table.add_column("Tier", justify="center", width=16)
    table.add_column("RPM", justify="right", width=8)
    table.add_column("RPD", justify="right", width=8)
    table.add_column("Context", justify="right", width=10)
    table.add_column("Live Quota", justify="right", width=16)
    table.add_column("Notes", style="dim", ratio=3)

    for idx, p in enumerate(page_items, start_idx + 1):
        tier_style = "bold green" if p.tier == "FREE" else ("bold cyan" if "TIER" in p.tier or p.tier == "COMMUNITY" else "yellow")
        if p.tier == "LOCAL":
            tier_style = "bold blue"

        rpm_str = str(p.rpm_limit) if p.rpm_limit else "uncapped"
        rpd_str = str(p.rpd_limit) if p.rpd_limit else "-"
        ctx_str = f"{p.context_window // 1024}k"

        table.add_row(
            str(idx),
            p.model_id,
            p.provider,
            Text(p.tier, style=tier_style),
            rpm_str,
            rpd_str,
            ctx_str,
            p.live_quota_remaining or "Uncapped",
            p.notes[:32] if p.notes else "-"
        )

    title = (
        f"[bold white]MODEL LIMITS & QUOTAS[/bold white] "
        f"[dim](Page {cur_page + 1}/{total_pages} | {free_count} Free | {freetier_count} Free-Tier | {local_count} Local | {total_count} Total)[/dim]"
    )
    return Panel(
        table,
        title=title,
        box=box.ROUNDED,
        border_style="bright_magenta",
        title_align="left",
        padding=(0, 1)
    )


def render_providers_full_view(
    registry: Any,
    page: int = 0,
    page_size: int = 14
) -> Panel:
    """Render full directory of all configured inference providers."""
    backends = registry.all()
    sorted_backends = sorted(
        backends,
        key=lambda b: (0 if b.status.value == "ONLINE" else 1, b.latency_ms if b.latency_ms > 0 else 99999)
    )

    total_providers = len(sorted_backends)
    total_pages = max(1, (total_providers + page_size - 1) // page_size)
    cur_page = max(0, min(page, total_pages - 1))
    start_idx = cur_page * page_size
    page_items = sorted_backends[start_idx : start_idx + page_size]

    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        pad_edge=False
    )
    table.add_column("Provider", style="bold white", width=16)
    table.add_column("Status", justify="left", width=12)
    table.add_column("Latency", justify="right", width=9)
    table.add_column("Base URL", style="dim cyan", ratio=4)
    table.add_column("Models", justify="right", width=8)
    table.add_column("Key Pool", style="dim white", width=14)
    table.add_column("Quota / Rate Limit", style="magenta", width=18)

    for b in page_items:
        status_val = b.status.value
        if status_val == "ONLINE":
            status_text = Text("* online", style="bold green")
        elif status_val == "DEGRADED":
            status_text = Text("! degraded", style="bold yellow")
        elif status_val == "UNKNOWN":
            status_text = Text("o standby", style="dim yellow")
        else:
            status_text = Text("x offline", style="dim red")

        if b.latency_ms <= 0:
            ping_text = Text("-", style="dim")
        elif b.latency_ms < 500:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="green")
        elif b.latency_ms < 2000:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="yellow")
        else:
            ping_text = Text(f"{b.latency_ms:.0f}ms", style="red")

        keys_states = b.key_rotator.get_states()
        if not keys_states:
            keys_text = Text("local / none", style="dim")
        else:
            active_k = sum(1 for k in keys_states if k.is_active)
            keys_text = Text(f"{active_k}/{len(keys_states)} active", style="dim cyan")

        if b.ratelimit_remaining is not None:
            quota_text = Text(f"{b.ratelimit_remaining} req left", style="bold magenta")
        elif b.quota_remaining_str:
            quota_text = Text(b.quota_remaining_str[:16], style="magenta")
        else:
            quota_text = Text("Uncapped", style="dim")

        table.add_row(
            b.name,
            status_text,
            ping_text,
            b.base_url[:42],
            str(len(b.models)),
            keys_text,
            quota_text
        )

    title = f"[bold white]INFERENCE PROVIDERS DIRECTORY[/bold white] [dim](Page {cur_page + 1}/{total_pages} | {total_providers} Total Providers)[/dim]"
    return Panel(
        table,
        title=title,
        box=box.ROUNDED,
        border_style="bright_blue",
        title_align="left",
        padding=(0, 1)
    )


def render_routes_view(config: XenrouterConfig, registry: Any) -> Panel:
    """Render comprehensive hierarchical routing graph showing aliases, failovers, and provider links."""
    root = Tree("[bold bright_cyan]Xenrouter Routing Graph[/bold bright_cyan] (Dynamic Token & Failover Cascade)")

    for alias_name, alias_cfg in config.aliases.items():
        if alias_name in ["gpt-4o", "gpt-4", "claude-3-5-sonnet"]:
            continue
        desc = alias_cfg.description or "Cascade"
        alias_branch = root.add(f"[bold yellow]{alias_name}[/bold yellow] [dim]({desc})[/dim]")

        for idx, target in enumerate(alias_cfg.targets, 1):
            if target in config.aliases:
                alias_branch.add(
                    f"[dim]Step {idx}:[/dim] [bold white]\\[VIRTUAL CASCADE][/bold white] -> "
                    f"[bold cyan]{target}[/bold cyan] [dim](Expands to {target} alias targets)[/dim]"
                )
                continue

            info = resolve_model_provider_info(target, registry)
            provider_title = info["provider"]
            status = info["status"]
            status_style = "bold green" if status == "online" else "yellow"
            key_count = info["key_count"]
            key_str = f"{key_count} key(s)" if key_count > 0 else "active"
            rpm = info.get("rpm")
            rpm_str = f"{rpm} RPM" if rpm else "uncapped"
            ctx = info.get("ctx", 32768)
            ctx_str = f"{ctx // 1024}k ctx" if ctx else ""
            daily = info.get("daily_tokens", "Standard")

            step_label = f"Step {idx}:" if idx > 1 else "Primary:"
            alias_branch.add(
                f"[dim]{step_label}[/dim] [bold white]\\[{provider_title}][/bold white] -> "
                f"[bold cyan]{target}[/bold cyan]  "
                f"[{status_style}]\\[{status} | {key_str}][/{status_style}]  "
                f"[magenta]{rpm_str}[/magenta] [dim]{ctx_str} | {daily}[/dim]"
            )

    return Panel(
        root,
        title="[bold white]INFERENCE ROUTING GRAPH & CASCADE HIERARCHY[/bold white]",
        box=box.ROUNDED,
        border_style="bright_blue",
        title_align="left",
        padding=(0, 1)
    )


def _build_usage_kpi_card(
    title: str,
    subtitle: str,
    requests: int,
    successful: int,
    failed: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    border_style: str,
    accent_style: str,
) -> Panel:
    """Build a compact KPI summary card for the usage view header strip."""
    body = Text()
    body.append(f"{title} ", style=f"bold {accent_style}")
    body.append(f"({subtitle})\n", style="dim white")
    body.append("Reqs: ", style="dim")
    body.append(f"{requests:,}", style="bold white")
    body.append(f"  ok:{successful:,}  err:{failed:,}\n", style="dim green" if failed == 0 else "yellow")
    body.append("Tokens: ", style="dim")
    body.append(f"{format_number(total_tokens)}", style=f"bold {accent_style}")
    body.append(f"  in:{format_number(prompt_tokens)}  out:{format_number(completion_tokens)}", style="dim cyan")
    return Panel(body, box=box.ROUNDED, border_style=border_style, padding=(0, 1))


def _build_period_usage_table(
    title: str,
    period_col_title: str,
    period_key: str,
    rows: List[Dict[str, Any]],
    highlight_value: str,
    highlight_label: str,
    border_style: str,
    empty_message: str,
) -> Panel:
    """Render either a daily or monthly usage table inside a bordered panel."""
    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        pad_edge=False,
    )
    table.add_column(period_col_title, style="bold white", no_wrap=True)
    table.add_column("Reqs", justify="right", no_wrap=True)
    table.add_column("OK/Err", justify="right", no_wrap=True)
    table.add_column("In", justify="right", no_wrap=True)
    table.add_column("Out", justify="right", no_wrap=True)
    table.add_column("Total", justify="right", style="bold green", no_wrap=True)

    if not rows:
        table.add_row("-", "0", "0/0", "0", "0", "0")
        table.caption = f"[dim]{empty_message}[/dim]"
    else:
        for item in rows:
            val = str(item.get(period_key, "-"))
            is_cur = val == highlight_value
            label = f"{val} *" if is_cur else val
            row_style = "bold bright_cyan" if is_cur else ""
            ok_cnt = int(item.get("successful", 0))
            err_cnt = int(item.get("failed", 0))
            table.add_row(
                Text(label, style=row_style or "white"),
                f"{int(item.get('requests', 0)):,}",
                Text(f"{ok_cnt}/{err_cnt}", style="green" if err_cnt == 0 else "yellow"),
                format_number(int(item.get("prompt_tokens", 0))),
                format_number(int(item.get("completion_tokens", 0))),
                format_number(int(item.get("total_tokens", 0))),
            )
        if highlight_value:
            table.caption = f"[dim]* {highlight_label}[/dim]"

    return Panel(
        table,
        title=f"[bold white]{title}[/bold white]",
        box=box.ROUNDED,
        border_style=border_style,
        title_align="left",
        padding=(0, 1),
    )


def _merge_today_month_breakdown(
    today_rows: List[Dict[str, Any]],
    month_rows: List[Dict[str, Any]],
    key_name: str,
) -> List[Dict[str, Any]]:
    """Merge today's and this month's usage rows keyed by provider or model name."""
    merged: Dict[str, Dict[str, Any]] = {}
    for row in month_rows:
        name = str(row.get(key_name, "unknown"))
        merged[name] = {
            key_name: name,
            "today_requests": 0,
            "today_tokens": 0,
            "month_requests": int(row.get("requests", 0)),
            "month_tokens": int(row.get("total_tokens", 0)),
            "month_prompt": int(row.get("prompt_tokens", 0)),
            "month_completion": int(row.get("completion_tokens", 0)),
        }
    for row in today_rows:
        name = str(row.get(key_name, "unknown"))
        entry = merged.setdefault(
            name,
            {
                key_name: name,
                "today_requests": 0,
                "today_tokens": 0,
                "month_requests": 0,
                "month_tokens": 0,
                "month_prompt": 0,
                "month_completion": 0,
            },
        )
        entry["today_requests"] = int(row.get("requests", 0))
        entry["today_tokens"] = int(row.get("total_tokens", 0))

    return sorted(
        merged.values(),
        key=lambda x: (x["month_tokens"], x["month_requests"], x["today_tokens"]),
        reverse=True,
    )


def _build_breakdown_table(
    title: str,
    col_title: str,
    key_name: str,
    today_rows: List[Dict[str, Any]],
    month_rows: List[Dict[str, Any]],
    month_total_tokens: int,
    max_rows: int = 8,
    border_style: str = "cyan",
) -> Panel:
    """Render combined Today vs This Month breakdown table with share indicator."""
    combined = _merge_today_month_breakdown(today_rows, month_rows, key_name)[:max_rows]
    bar_fill = "#"
    bar_empty = "-"

    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan",
        pad_edge=False,
    )
    table.add_column(col_title, style="bold white", ratio=3)
    table.add_column("Today Req", justify="right", no_wrap=True)
    table.add_column("Today Tok", justify="right", style="cyan", no_wrap=True)
    table.add_column("Month Req", justify="right", no_wrap=True)
    table.add_column("Month Tok", justify="right", style="bold green", no_wrap=True)
    table.add_column("Share", justify="left", style="yellow", no_wrap=True)

    if not combined:
        table.add_row("-", "0", "0", "0", "0", "[dim]No usage yet[/dim]")
    else:
        denom = max(1, month_total_tokens)
        for item in combined:
            m_toks = item["month_tokens"]
            pct = (m_toks / denom * 100.0) if month_total_tokens > 0 else 0.0
            filled = min(10, int(round(pct / 10.0)))
            bar = bar_fill * filled + bar_empty * (10 - filled)
            table.add_row(
                str(item[key_name])[:36],
                f"{item['today_requests']:,}",
                format_number(item["today_tokens"]),
                f"{item['month_requests']:,}",
                format_number(m_toks),
                f"[{bar}] {pct:4.1f}%",
            )

    return Panel(
        table,
        title=f"[bold white]{title}[/bold white]",
        box=box.ROUNDED,
        border_style=border_style,
        title_align="left",
        padding=(0, 1),
    )


def render_usage_view(
    usage_data: Dict[str, Any],
    metrics: ServerMetrics,
    page: int = 0,
) -> Panel:
    """Render comprehensive Daily and Monthly usage analytics view."""
    today = usage_data.get("today", {})
    this_month = usage_data.get("this_month", {})
    all_time = usage_data.get("all_time", {})
    session = usage_data.get("session", {})
    daily_rows = usage_data.get("daily", [])
    monthly_rows = usage_data.get("monthly", [])
    providers_today = usage_data.get("providers_today", [])
    providers_month = usage_data.get("providers_month", [])
    models_today = usage_data.get("models_today", [])
    models_month = usage_data.get("models_month", [])

    today_date = str(today.get("date", "Today"))
    cur_month = str(this_month.get("month", "Current Month"))

    session_reqs = int(session.get("requests", metrics.total_requests))
    session_up = float(session.get("uptime_seconds", metrics.uptime_seconds))

    kpi_grid = Table.grid(expand=True)
    kpi_grid.add_column(ratio=1)
    kpi_grid.add_column(ratio=1)
    kpi_grid.add_column(ratio=1)
    kpi_grid.add_row(
        _build_usage_kpi_card(
            title="DAILY USAGE",
            subtitle=today_date,
            requests=int(today.get("requests", 0)),
            successful=int(today.get("successful", 0)),
            failed=int(today.get("failed", 0)),
            prompt_tokens=int(today.get("prompt_tokens", 0)),
            completion_tokens=int(today.get("completion_tokens", 0)),
            total_tokens=int(today.get("total_tokens", 0)),
            border_style="cyan",
            accent_style="bright_cyan",
        ),
        _build_usage_kpi_card(
            title="MONTHLY USAGE",
            subtitle=cur_month,
            requests=int(this_month.get("requests", 0)),
            successful=int(this_month.get("successful", 0)),
            failed=int(this_month.get("failed", 0)),
            prompt_tokens=int(this_month.get("prompt_tokens", 0)),
            completion_tokens=int(this_month.get("completion_tokens", 0)),
            total_tokens=int(this_month.get("total_tokens", 0)),
            border_style="yellow",
            accent_style="bright_yellow",
        ),
        _build_usage_kpi_card(
            title="ALL-TIME TOTAL",
            subtitle=f"Live: {session_reqs:,} req, up {format_duration(session_up)}",
            requests=int(all_time.get("requests", 0)),
            successful=int(all_time.get("successful", 0)),
            failed=int(all_time.get("failed", 0)),
            prompt_tokens=int(all_time.get("prompt_tokens", 0)),
            completion_tokens=int(all_time.get("completion_tokens", 0)),
            total_tokens=int(all_time.get("total_tokens", 0)),
            border_style="green",
            accent_style="bright_green",
        ),
    )

    total_pages = 2
    cur_page = max(0, min(page, total_pages - 1))

    if cur_page == 0:
        period_grid = Table.grid(expand=True)
        period_grid.add_column(ratio=1)
        period_grid.add_column(ratio=1)
        period_grid.add_row(
            _build_period_usage_table(
                title="DAILY USAGE HISTORY (Recent 8 Days)",
                period_col_title="Date",
                period_key="date",
                rows=daily_rows[:8],
                highlight_value=today_date,
                highlight_label="Today",
                border_style="dim cyan",
                empty_message="No daily records yet",
            ),
            _build_period_usage_table(
                title="MONTHLY USAGE HISTORY (By Month)",
                period_col_title="Month",
                period_key="month",
                rows=monthly_rows[:8],
                highlight_value=cur_month,
                highlight_label="Current Month",
                border_style="dim yellow",
                empty_message="No monthly records yet",
            ),
        )

        bottom_panel = _build_breakdown_table(
            title="PROVIDER USAGE BREAKDOWN (Today vs This Month)",
            col_title="Provider",
            key_name="provider",
            today_rows=providers_today,
            month_rows=providers_month,
            month_total_tokens=int(this_month.get("total_tokens", 0)),
            max_rows=7,
            border_style="dim green",
        )
        content = Group(kpi_grid, period_grid, bottom_panel)
    else:
        models_panel = _build_breakdown_table(
            title="TOP MODELS USAGE (Today vs This Month)",
            col_title="Model Identifier",
            key_name="model",
            today_rows=models_today,
            month_rows=models_month,
            month_total_tokens=int(this_month.get("total_tokens", 0)),
            max_rows=10,
            border_style="dim magenta",
        )
        extended_daily = _build_period_usage_table(
            title="EXTENDED DAILY LOG (Up to 30 Days)",
            period_col_title="Date",
            period_key="date",
            rows=daily_rows[:12],
            highlight_value=today_date,
            highlight_label="Today",
            border_style="dim cyan",
            empty_message="No daily records yet",
        )
        content = Group(kpi_grid, models_panel, extended_daily)

    title = (
        f"[bold white]DAILY & MONTHLY USAGE ANALYTICS[/bold white] "
        f"[dim](Page {cur_page + 1}/{total_pages} | Today: {today_date} | Month: {cur_month})[/dim]"
    )
    return Panel(
        content,
        title=title,
        box=box.ROUNDED,
        border_style="bright_cyan",
        title_align="left",
        padding=(0, 1),
    )


def render_footer(current_view: str = "dashboard", notification: str = "") -> Text:
    """Render hotkey helper bar tailored to the active view."""
    footer = Text()

    if notification:
        footer.append(f" {notification} ", style="bold yellow")
        return footer

    footer.append(" [q] Quit  ", style="bold white")

    if current_view == "dashboard":
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[g] Routes Graph  ", style="bold yellow")
        footer.append("[m] Models View  ", style="bold cyan")
        footer.append("[p] Providers Directory  ", style="cyan")
        footer.append("[l] Limits & Quotas  ", style="magenta")
        footer.append("[u] Usage  ", style="bold green")
        footer.append("[w] Welcome  ", style="white")
        footer.append("[f] Fetch Models  ", style="dim yellow")
        footer.append("[t] Quick Test", style="green")
    elif current_view == "routes":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[m] Models  ", style="cyan")
        footer.append("[p] Providers  ", style="cyan")
        footer.append("[l] Limits  ", style="magenta")
        footer.append("[u] Usage", style="bold green")
    elif current_view == "welcome":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[m] Models  ", style="cyan")
        footer.append("[p] Providers  ", style="cyan")
        footer.append("[l] Limits  ", style="magenta")
        footer.append("[u] Usage", style="bold green")
    elif current_view == "models":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[n] Next Page  ", style="white")
        footer.append("[b] Prev Page  ", style="white")
        footer.append("[f] Fetch from Provider  ", style="bold yellow")
        footer.append("[l] View Limits  ", style="magenta")
        footer.append("[u] Usage", style="bold green")
    elif current_view == "providers":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[m] View Models  ", style="cyan")
        footer.append("[u] Usage  ", style="bold green")
        footer.append("[n] Next Page  ", style="white")
        footer.append("[b] Prev Page  ", style="white")
        footer.append("[t] Test Active Model", style="green")
    elif current_view == "limits":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[m] View Models  ", style="cyan")
        footer.append("[p] View Providers  ", style="cyan")
        footer.append("[u] Usage  ", style="bold green")
        footer.append("[n] Next Page  ", style="white")
        footer.append("[b] Prev Page", style="white")
    elif current_view == "usage":
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[n] Models & History  ", style="white")
        footer.append("[b] Overview  ", style="white")
        footer.append("[p] Providers  ", style="cyan")
        footer.append("[l] Limits  ", style="magenta")
        footer.append("[t] Quick Test", style="green")
    else:
        footer.append("[d/Esc] Dashboard  ", style="bold cyan")
        footer.append("[r] Reload  ", style="bold green")
        footer.append("[m] Models  ", style="cyan")
        footer.append("[p] Providers  ", style="cyan")
        footer.append("[u] Usage", style="bold green")

    return footer


# Alias for backwards compatibility
render_requests_table = render_logs_panel
