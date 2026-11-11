"""
Tests for Xenrouter routing engine.
"""

from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.router import Router
from xenrouter.types import AliasConfig, BackendConfig, BackendStatus, BackendType, ModelInfo


def test_prefix_routing():
    cfg = XenrouterConfig()
    registry = BackendRegistry()

    ollama_cfg = BackendConfig(
        name="ollama",
        type=BackendType.OLLAMA,
        base_url="http://127.0.0.1:11434"
    )
    backend = registry.register(ollama_cfg)
    backend.status = BackendStatus.ONLINE
    backend.models = [ModelInfo(id="qwen2.5:7b", backend_name="ollama", backend_type="ollama")]

    router = Router(cfg, registry)
    routes = router.resolve_routes("ollama/qwen2.5:7b")

    assert len(routes) == 1
    assert routes[0].backend.name == "ollama"
    assert routes[0].model_id == "qwen2.5:7b"


def test_alias_and_fallback_resolution():
    cfg = XenrouterConfig(
        aliases={
            "coding": AliasConfig(targets=["qwen2.5-coder:32b", "deepseek-coder:6.7b"]),
            "gpt-4o": AliasConfig(targets=["coding"])
        }
    )
    registry = BackendRegistry()

    lmstudio_cfg = BackendConfig(
        name="lmstudio",
        type=BackendType.LMSTUDIO,
        base_url="http://127.0.0.1:1234"
    )
    backend = registry.register(lmstudio_cfg)
    backend.status = BackendStatus.ONLINE
    # lmstudio has deepseek-coder:6.7b (the second target in the cascade)
    backend.models = [ModelInfo(id="deepseek-coder:6.7b", backend_name="lmstudio", backend_type="lmstudio")]

    router = Router(cfg, registry)
    routes = router.resolve_routes("gpt-4o")

    assert len(routes) == 1
    assert routes[0].backend.name == "lmstudio"
    assert routes[0].model_id == "deepseek-coder:6.7b"


def test_unified_models_catalog():
    cfg = XenrouterConfig(
        aliases={
            "coding": AliasConfig(targets=["qwen2.5-coder:14b"])
        }
    )
    registry = BackendRegistry()

    b_cfg = BackendConfig(
        name="ollama",
        type=BackendType.OLLAMA,
        base_url="http://127.0.0.1:11434"
    )
    backend = registry.register(b_cfg)
    backend.status = BackendStatus.ONLINE
    backend.models = [ModelInfo(id="llama3.2:3b", backend_name="ollama", backend_type="ollama")]

    router = Router(cfg, registry)
    catalog = router.get_unified_models_list()

    model_ids = [m["id"] for m in catalog]
    assert "auto" in model_ids
    assert catalog[0]["id"] == "auto"
    assert "llama3.2:3b" in model_ids
    assert "ollama/llama3.2:3b" in model_ids
    assert "coding" in model_ids


def test_auto_model_resolution():
    cfg = XenrouterConfig(
        default_model="qwen/qwen3.8-27b",
        aliases={
            "auto": AliasConfig(targets=["qwen/qwen3.8-27b", "coding"]),
            "coding": AliasConfig(targets=["qwen/qwen3.8-27b"])
        }
    )
    registry = BackendRegistry()
    b_cfg = BackendConfig(name="groq", base_url="https://api.groq.com/openai/v1")
    backend = registry.register(b_cfg)
    backend.status = BackendStatus.ONLINE
    backend.models = [ModelInfo(id="qwen/qwen3.8-27b", backend_name="groq", backend_type="openai_compatible")]

    router = Router(cfg, registry)
    routes = router.resolve_routes("auto")
    assert len(routes) >= 1
    assert routes[0].backend.name == "groq"
    assert routes[0].model_id == "qwen/qwen3.8-27b"
