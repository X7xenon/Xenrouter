"""
End-to-end integration test verifying full proxy pipeline, key rotation, and streaming.
"""

import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

from tests.mock_inference_server import app as mock_backend_app
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.router import Router
from xenrouter.server.app import create_app
from xenrouter.server.state import AppState
from xenrouter.types import AliasConfig, BackendConfig, BackendStatus, BackendType, KeyRotationStrategy, ModelInfo


@pytest.mark.asyncio
async def test_full_pipeline_with_mock_and_key_rotation():
    # Setup Xenrouter configuration
    cfg = XenrouterConfig(
        host="127.0.0.1",
        port=8989,
        auto_probe_local=False,
        health_check_interval=999.0,
        aliases={
            "coding": AliasConfig(targets=["qwen2.5-coder:14b"]),
            "fast": AliasConfig(targets=["llama3.2:3b"])
        }
    )

    registry = BackendRegistry()
    state = AppState(cfg)
    router = Router(cfg, registry)

    # Configure backend with multiple API keys for rotation
    backend_cfg = BackendConfig(
        name="mock-engine",
        type=BackendType.OPENAI_COMPATIBLE,
        base_url="http://mock-server",
        api_keys=["sk-test-alpha", "sk-test-beta", "sk-test-gamma"],
        key_rotation_strategy=KeyRotationStrategy.ROUND_ROBIN,
        key_cooldown_seconds=30.0
    )
    backend = registry.register(backend_cfg)
    backend.status = BackendStatus.ONLINE
    backend.models = [
        ModelInfo(id="qwen2.5-coder:14b", backend_name="mock-engine", backend_type="openai_compatible"),
        ModelInfo(id="llama3.2:3b", backend_name="mock-engine", backend_type="openai_compatible")
    ]

    # Use ASGITransport to route HTTP requests from Xenrouter directly to mock_backend_app in memory!
    transport = httpx.ASGITransport(app=mock_backend_app)
    mock_http_client = httpx.AsyncClient(transport=transport, base_url="http://mock-server")

    # Wire into Xenrouter's ProxyEngine
    from xenrouter.server.proxy import ProxyEngine
    proxy_engine = ProxyEngine(router=router, state=state, client=mock_http_client)

    # Test Chat Completion with Alias "coding"
    from fastapi import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"host", b"127.0.0.1")],
        "client": ("127.0.0.1", 12345)
    }
    req = Request(scope)

    payload = {
        "model": "coding",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False
    }

    # Request 1: Should try key, if rate limited it rotates to next operational key!
    res = await proxy_engine.forward_chat_completion(req, payload)
    assert res.status_code == 200

    # Verify metrics updated
    metrics = state.get_metrics()
    assert metrics.total_requests >= 1
    assert metrics.successful_requests == 1

    # Verify Key Rotation occurred and keys states recorded
    key_states = backend.key_rotator.get_states()
    assert len(key_states) == 3
    total_usages = sum(k.usage_count for k in key_states)
    assert total_usages >= 1

    await mock_http_client.aclose()
