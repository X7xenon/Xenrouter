"""
Live interactive terminal dashboard for Xenrouter.
Composes cyber-terminal layout with live refresh, node status pills, multi-view catalog, and wiretap stream.
"""

from enum import Enum
import time
from typing import Any, Dict, Optional
import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from xenrouter.backends.hermes_importer import discover_hermes_backends
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.server.state import AppState
from xenrouter.types import BackendConfig, BackendStatus, BackendType, ModelInfo, RequestLog
from xenrouter.tui.components import (
    render_aliases_panel,
    render_backends_table,
    render_footer,
    render_header,
    render_limits_view,
    render_models_view,
    render_providers_full_view,
    render_requests_table,
    render_routes_view,
    render_usage_view,
    render_welcome_panel,
)


class TUIView(str, Enum):
    DASHBOARD = "dashboard"
    ROUTES = "routes"
    MODELS = "models"
    PROVIDERS = "providers"
    LIMITS = "limits"
    USAGE = "usage"
    WELCOME = "welcome"


class TUIDashboard:
    """Manages full terminal layout, live data binding, multi-view switching, and flicker-free rendering."""

    def __init__(self, config: XenrouterConfig, state: AppState, registry: BackendRegistry, is_remote: bool = False):
        self.config = config
        self.state = state
        self.registry = registry
        self.is_remote = is_remote
        self.console = Console()
        self.current_view = TUIView.DASHBOARD
        self.models_page = 0
        self.limits_page = 0
        self.providers_page = 0
        self.usage_page = 0
        self.remote_usage: Optional[Dict[str, Any]] = None
        self.notification = ""
        self.notification_expiry = 0.0

        # Pre-populate registry if empty so TUI immediately has all configured nodes
        if not self.registry.all():
            for b_cfg in self.config.backends:
                self.registry.register(b_cfg)
            if self.config.import_hermes_providers:
                try:
                    for h_cfg in discover_hermes_backends():
                        if not self.registry.get(h_cfg.name):
                            self.registry.register(h_cfg)
                except Exception:
                    pass

        # Perform initial sync from live running daemon if reachable
        self.sync_from_remote(f"http://{self.config.host}:{self.config.port}")

    def sync_from_remote(self, base_url: str = "http://127.0.0.1:8989") -> None:
        """Fetch live backend statuses, latencies, metrics, and request logs from running Xenrouter instance."""
        try:
            with httpx.Client(timeout=1.2) as client:
                r_b = client.get(f"{base_url}/v1/backends")
                if r_b.status_code == 200:
                    data = r_b.json().get("backends", [])
                    for item in data:
                        b_name = item.get("name")
                        existing = self.registry.get(b_name)
                        if not existing:
                            b_type = BackendType.OLLAMA if item.get("type") == "ollama" else BackendType.OPENAI_COMPATIBLE
                            new_cfg = BackendConfig(
                                name=b_name,
                                type=b_type,
                                base_url=item.get("base_url", ""),
                                enabled=item.get("enabled", True),
                                priority=1 if b_name in ["apinex", "google", "siliconflow", "nous", "nvidia", "xkiro", "tokenharbor", "groq", "inceptionlabs", "gemini"] else 2
                            )
                            existing = self.registry.register(new_cfg)

                        status_str = str(item.get("status", "offline")).lower()
                        if status_str == "online":
                            existing.status = BackendStatus.ONLINE
                        elif status_str == "degraded":
                            existing.status = BackendStatus.DEGRADED
                        else:
                            existing.status = BackendStatus.OFFLINE

                        existing.latency_ms = item.get("latency_ms", 0.0)
                        raw_models = item.get("models", [])
                        existing.models = [ModelInfo(id=m_id, backend_name=b_name, backend_type=item.get("type", "openai_compatible")) for m_id in raw_models]
                        if item.get("ratelimit_remaining") is not None:
                            existing.ratelimit_remaining = item.get("ratelimit_remaining")

                r_m = client.get(f"{base_url}/v1/metrics")
                if r_m.status_code == 200:
                    m_data = r_m.json()
                    self.state.total_requests = m_data.get("total_requests", 0)
                    self.state.successful_requests = m_data.get("successful_requests", 0)
                    self.state.failed_requests = m_data.get("failed_requests", 0)
                    self.state.total_prompt_tokens = m_data.get("total_prompt_tokens", 0)
                    self.state.total_completion_tokens = m_data.get("total_completion_tokens", 0)
                    self.state.active_requests = m_data.get("active_requests", 0)
                    uptime_sec = m_data.get("uptime_seconds", 0)
                    self.state.start_time = time.time() - uptime_sec

                r_l = client.get(f"{base_url}/v1/logs?limit=15")
                if r_l.status_code == 200:
                    l_data = r_l.json().get("logs", [])
                    new_logs = []
                    for ld in l_data:
                        try:
                            new_logs.append(RequestLog(**ld))
                        except Exception:
                            pass
                    if new_logs:
                        self.state.recent_logs.clear()
                        for nl in reversed(new_logs):
                            self.state.recent_logs.appendleft(nl)

                r_u = client.get(f"{base_url}/v1/usage?days=30&months=12")
                if r_u.status_code == 200:
                    self.remote_usage = r_u.json()
        except Exception:
            pass

    def reload_and_refresh(self, base_url: str = "http://127.0.0.1:8989") -> Dict[str, Any]:
        """Trigger full reload & refresh on daemon or local registry."""
        result = {"status": "ok", "online": 0, "total": 0, "models": 0}
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.post(f"{base_url}/v1/reload")
                if r.status_code == 200:
                    data = r.json()
                    result["online"] = data.get("online_backends_count", 0)
                    result["total"] = data.get("total_backends_count", 0)
                    result["models"] = data.get("models_count", 0)
        except Exception:
            pass

        self.sync_from_remote(base_url)
        if result["total"] == 0:
            result["online"] = len(self.registry.online())
            result["total"] = len(self.registry.all())
        return result

    def get_usage_data(self) -> Dict[str, Any]:
        """Return live usage summary from remote daemon (when attached) or local tracker."""
        if self.is_remote and self.remote_usage is not None:
            return self.remote_usage
        return self.state.get_usage_summary(days=30, months=12)

    def set_notification(self, msg: str, duration: float = 3.5):
        """Display an ephemeral notification banner in the TUI footer."""
        self.notification = msg
        self.notification_expiry = time.time() + duration

    def switch_view(self, view: TUIView):
        """Switch active view cleanly."""
        self.current_view = view

    def next_page(self):
        """Page forward in the active view."""
        if self.current_view == TUIView.MODELS:
            self.models_page += 1
        elif self.current_view == TUIView.LIMITS:
            self.limits_page += 1
        elif self.current_view == TUIView.PROVIDERS:
            self.providers_page += 1
        elif self.current_view == TUIView.USAGE:
            self.usage_page = min(1, self.usage_page + 1)

    def prev_page(self):
        """Page backward in the active view."""
        if self.current_view == TUIView.MODELS:
            self.models_page = max(0, self.models_page - 1)
        elif self.current_view == TUIView.LIMITS:
            self.limits_page = max(0, self.limits_page - 1)
        elif self.current_view == TUIView.PROVIDERS:
            self.providers_page = max(0, self.providers_page - 1)
        elif self.current_view == TUIView.USAGE:
            self.usage_page = max(0, self.usage_page - 1)

    def _populate_subview(
        self,
        layout: Layout,
        body_renderable: Any,
        metrics: Any,
        online_count: int,
        total_count: int,
        notif: str,
    ) -> None:
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=1),
        )
        layout["header"].update(render_header(self.config, metrics, online_count, total_count, compact=True))
        layout["body"].update(body_renderable)
        layout["footer"].update(render_footer(self.current_view.value, notif))

    def generate_layout(self) -> Layout:
        """Compose the responsive composite Rich layout based on active view."""
        layout = Layout()
        metrics = self.state.get_metrics()
        backends = self.registry.all()
        online_count = len(self.registry.online())
        total_count = len(backends)

        notif = self.notification if time.time() < self.notification_expiry else ""

        if self.current_view == TUIView.DASHBOARD:
            layout.split_column(
                Layout(name="header", size=9),
                Layout(name="middle", size=13),
                Layout(name="requests", ratio=1),
                Layout(name="footer", size=1)
            )

            layout["middle"].split_row(
                Layout(name="backends", ratio=6),
                Layout(name="aliases", ratio=4)
            )

            logs = self.state.get_recent_logs(12)
            layout["header"].update(render_header(self.config, metrics, online_count, total_count, compact=False))
            layout["backends"].update(render_backends_table(backends))
            layout["aliases"].update(render_aliases_panel(self.config, backends))
            layout["requests"].update(render_requests_table(logs))
            layout["footer"].update(render_footer(self.current_view.value, notif))
            return layout

        subview_bodies = {
            TUIView.ROUTES: lambda: render_routes_view(self.config, self.registry),
            TUIView.MODELS: lambda: render_models_view(self.config, self.registry, self.models_page),
            TUIView.PROVIDERS: lambda: render_providers_full_view(self.registry, self.providers_page),
            TUIView.LIMITS: lambda: render_limits_view(self.registry, self.limits_page),
            TUIView.USAGE: lambda: render_usage_view(self.get_usage_data(), metrics, self.usage_page),
            TUIView.WELCOME: render_welcome_panel,
        }
        builder = subview_bodies.get(self.current_view)
        if builder:
            self._populate_subview(layout, builder(), metrics, online_count, total_count, notif)

        return layout

    def run_live(self) -> Live:
        """Create and return a configured Live context manager."""
        return Live(
            self.generate_layout(),
            console=self.console,
            refresh_per_second=4,
            screen=True
        )
