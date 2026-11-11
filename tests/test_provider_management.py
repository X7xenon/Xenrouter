"""
Tests for provider management, canonical naming, dynamic model fetching, and config updates.
"""

import pytest
from xenrouter.backends.hermes_importer import clean_provider_name, discover_hermes_backends
from xenrouter.config import XenrouterConfig, get_default_config
from xenrouter.types import BackendConfig, BackendType


def test_clean_provider_name():
    """Verify that all node IDs have clean actual provider names with zero hermes prefix."""
    cases = [
        ("Api.apinex.bond", "apinex"),
        ("Api.hcnsec.cn", "hcnsec"),
        ("Api.xkiro.com", "xkiro"),
        ("Inference.dahl.global", "dahl"),
        ("Integrate.api.nvidia.com", "nvidia"),
        ("Tokenharbor.ai", "tokenharbor"),
        ("Vyceai.com", "vyceai"),
        ("Api.router9.com", "router9"),
        ("Api.inceptionlabs.ai", "inceptionlabs"),
        ("Api.groq.com", "groq"),
        ("Api.river.ai", "river"),
        ("Zro.moonmath.ai", "moonmath"),
        ("Api.free.ai", "free-ai"),
        ("Top-tools-ai.com", "top-tools"),
        ("kaggle", "kaggle"),
        ("Api.orcarouter.ai", "orcarouter"),
        ("Api.iteracompute.com", "iteracompute"),
        ("api.navy", "navy"),
        ("api-navy", "navy"),
        ("ollama.com", "ollama-cloud"),
        ("hermes-ollama-cloud", "ollama-cloud"),
        ("hermes-api-xkiro-com", "xkiro"),
        ("custom:api.xkiro.com", "xkiro"),
        ("api_groq_com", "groq"),
        ("integrate_api_nvidia_com", "nvidia"),
    ]

    for raw, expected in cases:
        cleaned = clean_provider_name(raw)
        assert cleaned == expected, f"Failed for {raw}: got {cleaned}, expected {expected}"
        assert not cleaned.startswith("hermes"), f"Provider name {cleaned} still contains 'hermes' prefix!"


def test_config_backend_management():
    """Verify adding, updating, disabling, and removing backends in XenrouterConfig."""
    cfg = get_default_config()
    initial_count = len(cfg.backends)

    # 1. Add new custom provider
    custom_b = BackendConfig(
        name="custom-vllm",
        type=BackendType.OPENAI_COMPATIBLE,
        base_url="http://192.168.1.100:8000/v1",
        api_keys=["sk-secret-123"],
        models_filter=["meta-llama/Llama-3-70B-Instruct"]
    )
    cfg.add_or_update_backend(custom_b)
    assert len(cfg.backends) == initial_count + 1
    assert cfg.backends[-1].name == "custom-vllm"

    # 2. Toggle backend
    assert cfg.toggle_backend("custom-vllm", False) is True
    assert next(b for b in cfg.backends if b.name == "custom-vllm").enabled is False

    assert cfg.toggle_backend("custom-vllm", True) is True
    assert next(b for b in cfg.backends if b.name == "custom-vllm").enabled is True

    # 3. Set default model
    cfg.set_default_model("meta-llama/Llama-3-70B-Instruct")
    assert cfg.default_model == "meta-llama/Llama-3-70B-Instruct"

    # 4. Remove backend
    assert cfg.remove_backend("custom-vllm") is True
    assert len(cfg.backends) == initial_count
    assert not any(b.name == "custom-vllm" for b in cfg.backends)


def test_hermes_discovery_has_no_hermes_prefix():
    """Verify all discovered Hermes backends have clean real names."""
    backends = discover_hermes_backends()
    for b in backends:
        assert not b.name.startswith("hermes-"), f"Discovered backend '{b.name}' has 'hermes-' prefix!"
        assert not b.name.startswith("hermes_"), f"Discovered backend '{b.name}' has 'hermes_' prefix!"
