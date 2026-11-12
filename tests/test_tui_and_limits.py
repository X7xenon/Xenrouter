"""
Tests for Xenrouter TUI multi-view catalog, keyboard polling, and limits CLI.
"""

import pytest
from xenrouter.backends.openai_compatible import OpenAICompatibleBackend
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import load_config
from xenrouter.limits import classify_model_tier, get_all_model_limits
from xenrouter.server.state import AppState
from xenrouter.tui.components import (
    render_aliases_panel,
    render_backends_table,
    render_footer,
    render_header,
    render_limits_view,
    render_models_view,
    render_providers_full_view,
)
from xenrouter.tui.dashboard import TUIDashboard, TUIView
from xenrouter.types import BackendConfig, BackendType, ServerMetrics


def test_classify_model_tier():
    # Test known free
    t_groq = classify_model_tier("openai/gpt-oss-120b", "groq")
    assert t_groq["tier"] == "FREE-TIER"
    assert t_groq["rpm"] == 30

    # Test :free pattern
    t_free = classify_model_tier("qwen/qwen3.8-max:free", "xkiro")
    assert t_free["tier"] == "FREE"
    assert t_free["cost"] == "$0.00"

    # Test local
    t_local = classify_model_tier("llama3.2:3b", "ollama")
    assert t_local["tier"] == "LOCAL"
    assert t_local["rpm"] is None


def test_tui_view_switching():
    cfg = load_config()
    state = AppState(cfg)
    reg = BackendRegistry()
    dash = TUIDashboard(cfg, state, reg)

    assert dash.current_view == TUIView.DASHBOARD
    layout_dash = dash.generate_layout()
    assert layout_dash is not None

    # Switch to MODELS view
    dash.switch_view(TUIView.MODELS)
    assert dash.current_view == TUIView.MODELS
    layout_models = dash.generate_layout()
    assert layout_models is not None

    # Test pagination in MODELS view
    dash.next_page()
    assert dash.models_page == 1
    dash.prev_page()
    assert dash.models_page == 0

    # Switch to LIMITS view
    dash.switch_view(TUIView.LIMITS)
    assert dash.current_view == TUIView.LIMITS
    layout_limits = dash.generate_layout()
    assert layout_limits is not None

    # Switch to PROVIDERS view
    dash.switch_view(TUIView.PROVIDERS)
    assert dash.current_view == TUIView.PROVIDERS
    layout_providers = dash.generate_layout()
    assert layout_providers is not None

    # Set notification
    dash.set_notification("Test notification banner")
    assert dash.notification == "Test notification banner"


def test_render_components_safety():
    cfg = load_config()
    metrics = ServerMetrics(
        uptime_seconds=3600.0,
        total_requests=42,
        successful_requests=41,
        failed_requests=1,
        total_prompt_tokens=1000,
        total_completion_tokens=2500,
        average_latency_ms=350.0
    )

    reg = BackendRegistry()
    b_test = OpenAICompatibleBackend(
        BackendConfig(
            name="test-provider",
            type=BackendType.OPENAI_COMPATIBLE,
            base_url="https://test.ai/v1",
            api_keys=["sk-test"],
            models_filter=["model-alpha", "free/model-beta:free"]
        )
    )
    reg.register(b_test)

    # Header
    h = render_header(cfg, metrics, 1, 1)
    assert h is not None

    # Footers
    f_dash = render_footer("dashboard")
    f_models = render_footer("models")
    f_limits = render_footer("limits")
    f_prov = render_footer("providers")
    assert "[m] Models View" in f_dash.plain
    assert "[d/Esc] Dashboard" in f_models.plain
    assert "[d/Esc] Dashboard" in f_limits.plain
    assert "[d/Esc] Dashboard" in f_prov.plain

    # Views
    v_models = render_models_view(cfg, reg, page=0)
    assert v_models is not None
    v_limits = render_limits_view(reg, page=0)
    assert v_limits is not None
    v_prov = render_providers_full_view(reg, page=0)
    assert v_prov is not None


def test_token_usage_tracking_breakdown():
    cfg = load_config()
    state = AppState(cfg)

    state.record_request_start()
    state.record_request_end(
        success=True,
        prompt_tokens=150,
        completion_tokens=50,
        provider="groq",
        model="openai/gpt-oss-120b"
    )

    state.record_request_start()
    state.record_request_end(
        success=True,
        prompt_tokens=200,
        completion_tokens=100,
        provider="groq",
        model="qwen/qwen3.8-27b"
    )

    state.record_request_start()
    state.record_request_end(
        success=True,
        prompt_tokens=80,
        completion_tokens=40,
        provider="xkiro",
        model="qwen/qwen3.8-max:free"
    )

    metrics = state.get_metrics()
    assert metrics.total_requests == 3
    assert metrics.successful_requests == 3
    assert metrics.total_prompt_tokens == 430
    assert metrics.total_completion_tokens == 190
    assert metrics.total_tokens == 620

    # Provider breakdown verification
    assert "groq" in metrics.provider_tokens
    assert metrics.provider_tokens["groq"]["prompt"] == 350
    assert metrics.provider_tokens["groq"]["completion"] == 150
    assert metrics.provider_tokens["groq"]["total"] == 500
    assert metrics.provider_tokens["groq"]["requests"] == 2

    assert "xkiro" in metrics.provider_tokens
    assert metrics.provider_tokens["xkiro"]["total"] == 120

    # Model breakdown verification
    assert "openai/gpt-oss-120b" in metrics.model_tokens
    assert metrics.model_tokens["openai/gpt-oss-120b"]["total"] == 200
    assert metrics.model_tokens["qwen/qwen3.8-27b"]["total"] == 300


def test_welcome_banner_and_aesthetic_components():
    from xenrouter.tui.components import (
        render_dots,
        render_pixel_x,
        render_welcome_banner,
        render_welcome_panel,
    )

    dots = render_dots()
    assert "●" in dots.plain

    x_lines = render_pixel_x()
    assert len(x_lines) == 8
    assert all("██" in line.plain for line in x_lines)

    banner = render_welcome_banner()
    assert banner is not None

    panel = render_welcome_panel()
    assert panel is not None

    # Test TUIDashboard switching to WELCOME view
    cfg = load_config()
    state = AppState(cfg)
    reg = BackendRegistry()
    dash = TUIDashboard(cfg, state, reg)

    dash.switch_view(TUIView.WELCOME)
    assert dash.current_view == TUIView.WELCOME
    layout_welcome = dash.generate_layout()
    assert layout_welcome is not None


def test_usage_tracker_daily_and_monthly_persistence(tmp_path):
    from xenrouter.usage import UsageTracker

    db_file = tmp_path / "usage.db"
    tracker = UsageTracker(db_path=db_file)
    try:
        tracker.record(success=True, prompt_tokens=100, completion_tokens=50, provider="apinex", model="free/deepseek-v4.1-flash", usage_date="2026-10-15")
        tracker.record(success=True, prompt_tokens=300, completion_tokens=100, provider="coarena", model="claude-sonnet-5-5", usage_date="2026-11-10")
        tracker.record(success=True, prompt_tokens=400, completion_tokens=200, provider="coarena", model="claude-sonnet-5-5", usage_date="2026-11-11")
        tracker.record(success=False, prompt_tokens=0, completion_tokens=0, provider="xkiro", model="qwen3.8-omni-flash:free", usage_date="2026-11-11")
    finally:
        tracker.close()

    # Reopen to verify SQLite persistence
    reopened = UsageTracker(db_path=db_file)
    try:
        summary = reopened.get_summary(days=14, months=12, ref_date="2026-11-11")
        assert summary["today"]["date"] == "2026-11-11"
        assert summary["today"]["requests"] == 2
        assert summary["today"]["successful"] == 1
        assert summary["today"]["failed"] == 1
        assert summary["today"]["total_tokens"] == 600

        assert summary["this_month"]["month"] == "2026-11"
        assert summary["this_month"]["requests"] == 3
        assert summary["this_month"]["total_tokens"] == 1000

        assert summary["all_time"]["requests"] == 4
        assert summary["all_time"]["total_tokens"] == 1150

        assert [d["date"] for d in summary["daily"]] == ["2026-11-11", "2026-11-10", "2026-10-15"]
        assert [m["month"] for m in summary["monthly"]] == ["2026-11", "2026-10"]
        assert summary["providers_month"][0]["provider"] == "coarena"
        assert summary["providers_month"][0]["total_tokens"] == 1000
    finally:
        reopened.close()


def test_usage_tui_view_and_hotkey_footer(tmp_path):
    import io
    from rich.console import Console
    from xenrouter.tui.components import render_usage_view

    cfg = load_config()
    state = AppState(cfg, usage_db_path=tmp_path / "tui_usage.db")
    try:
        state.record_request_start()
        state.record_request_end(success=True, prompt_tokens=250, completion_tokens=150, provider="coarena", model="claude-sonnet-5-5")

        reg = BackendRegistry()
        dash = TUIDashboard(cfg, state, reg)

        f_dash = render_footer("dashboard")
        f_usage = render_footer("usage")
        assert "[u] Usage" in f_dash.plain
        assert "[d/Esc] Dashboard" in f_usage.plain

        dash.switch_view(TUIView.USAGE)
        assert dash.current_view == TUIView.USAGE
        assert dash.generate_layout() is not None

        dash.next_page()
        assert dash.usage_page == 1
        assert dash.generate_layout() is not None
        dash.prev_page()
        assert dash.usage_page == 0

        out = io.StringIO()
        c = Console(file=out, width=140)
        c.print(render_usage_view(dash.get_usage_data(), state.get_metrics(), page=0))
        rendered = out.getvalue()
        assert "DAILY & MONTHLY USAGE ANALYTICS" in rendered
        assert "coarena" in rendered
    finally:
        state.usage_tracker.close()


def test_reload_and_refresh_tui_and_keypresses():
    from xenrouter.cli import _handle_tui_keypress
    from unittest.mock import MagicMock

    cfg = load_config()
    state = AppState(cfg)
    reg = BackendRegistry()
    dash = TUIDashboard(cfg, state, reg)

    # Footer verification
    f_dash = render_footer("dashboard")
    assert "[r] Reload" in f_dash.plain
    assert "[g] Routes Graph" in f_dash.plain

    f_routes = render_footer("routes")
    assert "[r] Reload" in f_routes.plain

    # Test 'g' toggles Routes view and back
    mock_live = MagicMock()
    quit_req = _handle_tui_keypress("g", dash, cfg, reg, mock_live)
    assert not quit_req
    assert dash.current_view == TUIView.ROUTES

    quit_req = _handle_tui_keypress("g", dash, cfg, reg, mock_live)
    assert not quit_req
    assert dash.current_view == TUIView.DASHBOARD

    # Test 'r' triggers reload notification
    quit_req = _handle_tui_keypress("r", dash, cfg, reg, mock_live)
    assert not quit_req
    assert "RELOADING" in dash.notification

    # Test 'f5' triggers reload notification
    quit_req = _handle_tui_keypress("f5", dash, cfg, reg, mock_live)
    assert not quit_req
    assert "RELOADING" in dash.notification



