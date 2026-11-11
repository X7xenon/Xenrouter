"""
Integration tests for Xenrouter FastAPI server.
"""

import json
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
import httpx

from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.router import Router
from xenrouter.server.app import create_app
from xenrouter.server.state import AppState
from xenrouter.types import BackendConfig, BackendStatus, BackendType, ModelInfo


@pytest.fixture
def test_setup():
    cfg = XenrouterConfig(
        host="127.0.0.1",
        port=8989,
        auto_probe_local=False,
        health_check_interval=999.0
    )
    registry = BackendRegistry()
    state = AppState(cfg)
    router = Router(cfg, registry)

    backend_cfg = BackendConfig(
        name="local-llm",
        type=BackendType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:8000",
        api_keys=["key-1", "key-2"]
    )
    backend = registry.register(backend_cfg)
    backend.status = BackendStatus.ONLINE
    backend.models = [ModelInfo(id="mock-model", backend_name="local-llm", backend_type="openai_compatible")]

    app = create_app(cfg, state, registry, router)
    client = TestClient(app)
    return client, backend, state


def test_root_and_models(test_setup):
    client, backend, state = test_setup
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Xenrouter"

    models_resp = client.get("/v1/models")
    assert models_resp.status_code == 200
    data = models_resp.json()["data"]
    ids = [m["id"] for m in data]
    assert "mock-model" in ids
    assert "local-llm/mock-model" in ids


def test_health_and_backends(test_setup):
    client, backend, state = test_setup
    health_resp = client.get("/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"

    backends_resp = client.get("/v1/backends")
    assert backends_resp.status_code == 200
    backends = backends_resp.json()["backends"]
    assert len(backends) == 1
    assert backends[0]["name"] == "local-llm"
    assert len(backends[0]["keys_states"]) == 2


def test_chat_completions_mock(test_setup):
    client, backend, state = test_setup

    mock_response = httpx.Response(
        200,
        json={
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Hello from local inference!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 6}
        },
        request=httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False
        }

        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from local inference!"


def test_three_keys_exhaustion_before_cascade():
    """Verify that all 3 keys of the primary provider are exhausted before cascading to next backend."""
    cfg = XenrouterConfig(
        host="127.0.0.1",
        port=8989,
        auto_probe_local=False,
        health_check_interval=999.0
    )
    registry = BackendRegistry()
    state = AppState(cfg)
    router = Router(cfg, registry)

    # Primary backend with 3 keys (simulating APInex)
    b1_cfg = BackendConfig(
        name="apinex",
        type=BackendType.OPENAI_COMPATIBLE,
        base_url="https://api.apinex.bond/v1",
        priority=1,
        api_keys=["key-alpha", "key-beta", "key-gamma"]
    )
    b1 = registry.register(b1_cfg)
    b1.status = BackendStatus.ONLINE
    b1.models = [ModelInfo(id="free/deepseek-v4.1-flash", backend_name="apinex", backend_type="openai_compatible")]

    # Secondary fallback backend (simulating Google / SiliconFlow)
    b2_cfg = BackendConfig(
        name="google",
        type=BackendType.OPENAI_COMPATIBLE,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        priority=2,
        api_keys=["google-key"]
    )
    b2 = registry.register(b2_cfg)
    b2.status = BackendStatus.ONLINE
    b2.models = [ModelInfo(id="gemini-2.0-flash", backend_name="google", backend_type="openai_compatible")]

    cfg.fallbacks["free/deepseek-v4.1-flash"] = ["gemini-2.0-flash"]

    app = create_app(cfg, state, registry, router)
    client = TestClient(app)

    # Mock responses: 3 consecutive 429 errors on APInex keys, followed by 200 OK on Google
    resp_429 = httpx.Response(
        429,
        text="Rate limit exceeded",
        headers={"ratelimit-remaining": "0"},
        request=httpx.Request("POST", "https://api.apinex.bond/v1/chat/completions")
    )
    resp_200 = httpx.Response(
        200,
        json={
            "id": "chatcmpl-fallback",
            "choices": [{"message": {"role": "assistant", "content": "Hello from Google cascade!"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8}
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/chat/completions")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        # key 1 fails, key 2 fails, key 3 fails -> all 3 exhausted -> cascades to b2 which succeeds!
        mock_post.side_effect = [resp_429, resp_429, resp_429, resp_200]

        payload = {
            "model": "free/deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "Testing 3 keys"}],
            "stream": False
        }

        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from Google cascade!"

        # Assert all 3 keys of APInex were tried before falling back to Google (total 4 post calls)
        assert mock_post.call_count == 4

        metrics = state.get_metrics()
        assert metrics.total_requests == 1
        assert metrics.total_prompt_tokens == 15
        assert metrics.total_completion_tokens == 8

        usage_resp = client.get("/v1/usage")
        assert usage_resp.status_code == 200
        u_data = usage_resp.json()
        assert u_data["today"]["requests"] == 1
        assert u_data["today"]["total_tokens"] == 23
        assert u_data["this_month"]["total_tokens"] == 23
        assert u_data["providers_today"][0]["provider"] == "google"

