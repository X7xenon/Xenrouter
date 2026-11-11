"""
Configuration management for Xenrouter.
Supports YAML, JSON, environment variables, and auto-probing defaults.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from xenrouter.types import AliasConfig, BackendConfig, BackendType, LoadBalanceStrategy


class XenrouterConfig(BaseModel):
    host: str = Field(default="127.0.0.1", description="Server listen host")
    port: int = Field(default=8989, description="Server listen port")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="Allowed CORS origins")
    auto_probe_local: bool = Field(default=True, description="Automatically probe standard local ports on launch")
    import_hermes_providers: bool = Field(default=True, description="Automatically import Hermes agent providers")
    health_check_interval: float = Field(default=15.0, description="Health check poll interval in seconds")
    default_model: Optional[str] = Field(default=None, description="Default model when requested model is omitted or unknown")
    backends: List[BackendConfig] = Field(default_factory=list, description="List of configured local inference backends")
    aliases: Dict[str, AliasConfig] = Field(default_factory=dict, description="Virtual model aliases")
    fallbacks: Dict[str, List[str]] = Field(default_factory=dict, description="Model-specific fallback chains")
    max_history_logs: int = Field(default=200, description="In-memory request log buffer size")

    def add_or_update_backend(self, backend: BackendConfig) -> None:
        """Add or update an inference backend in the configuration."""
        for idx, b in enumerate(self.backends):
            if b.name.lower() == backend.name.lower():
                self.backends[idx] = backend
                return
        self.backends.append(backend)

    def remove_backend(self, name: str) -> bool:
        """Remove a backend by name."""
        orig_len = len(self.backends)
        self.backends = [b for b in self.backends if b.name.lower() != name.lower()]
        return len(self.backends) < orig_len

    def toggle_backend(self, name: str, enabled: bool) -> bool:
        """Enable or disable a backend."""
        for b in self.backends:
            if b.name.lower() == name.lower():
                b.enabled = enabled
                return True
        return False

    def set_default_model(self, model_name: str) -> None:
        """Set the active default model."""
        self.default_model = model_name

    def save(self, path: str = "xenrouter.yaml") -> None:
        """Save this configuration to YAML."""
        save_config(self, path)


def get_default_config() -> XenrouterConfig:
    """Returns a production-ready default configuration synchronized with active 2026-11-07 models."""
    default_backends = [
        BackendConfig(
            name="ollama",
            type=BackendType.OLLAMA,
            base_url="http://127.0.0.1:11434",
            enabled=True,
            priority=1,
            timeout=180.0,
            max_concurrency=4
        ),
        BackendConfig(
            name="lmstudio",
            type=BackendType.LMSTUDIO,
            base_url="http://127.0.0.1:1234",
            enabled=True,
            priority=2,
            timeout=180.0,
            max_concurrency=2
        ),
        BackendConfig(
            name="llamacpp",
            type=BackendType.LLAMACPP,
            base_url="http://127.0.0.1:8080",
            enabled=True,
            priority=3,
            timeout=180.0,
            max_concurrency=2
        ),
        BackendConfig(
            name="vllm",
            type=BackendType.VLLM,
            base_url="http://127.0.0.1:8000",
            enabled=True,
            priority=4,
            timeout=180.0,
            max_concurrency=8
        ),
    ]

    coarena_keys = [
        k.strip()
        for k in (os.environ.get("COARENA_API_KEY", ""), os.environ.get("COARENA_API_KEY_2", ""))
        if k.strip()
    ]
    if coarena_keys:
        default_backends.append(
            BackendConfig(
                name="coarena",
                type=BackendType.OPENAI_COMPATIBLE,
                base_url="https://coarena.ai/api/v1",
                api_key=coarena_keys[0],
                api_keys=coarena_keys,
                enabled=True,
                priority=1,
                timeout=60.0,
                max_concurrency=8,
            )
        )

    default_aliases = {
        "auto": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "coding",
                "fast",
                "general"
            ],
            description="APInex free/deepseek-v4.1-flash first, cascading by tokens and RPM >= 15"
        ),
        "coding": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "qwen3.8-omni-flash:free",
                "wusrouter/qwen3.8-flash:free",
                "coarena/gemini-3-8-flash",
                "coarena/deepseek-v4-1-flash-1017",
                "coarena/claude-sonnet-5-5",
                "coarena/qwen3-8-2-4t-a95b",
                "qwen/qwen3.8-27b",
                "deepseek-v4.1-flash",
                "deepseek-v4.1-flash:free",
                "deepseek-ai/DeepSeek-V4.1-Flash",
                "mercury-3",
                "zro/deepseek-v4.1-flash",
                "gemini-3.8-flash",
                "free/glm-5.3-flash",
                "openai/gpt-oss-120b",
                "llama-3.3-70b-versatile",
                "hermes-3-llama-3.1-70b",
                "llama-3.3-70b-instruct:free",
                "Qwen/Qwen3-8B"
            ],
            description="Daily limit providers first (APInex -> xKiro -> WusRouter -> Coarena -> IteraCompute), cascading to grants & permanent free"
        ),
        "fast": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "mercury-2.5",
                "coarena/gemini-3-8-flash",
                "free/gemini-3.8-flash",
                "gemini-3.8-flash",
                "wusrouter/qwen3.8-flash:free",
                "coarena/glm-5-3-flash",
                "free/glm-5.3-flash",
                "Qwen/Qwen3-8B",
                "qwen7b"
            ],
            description="Ultra-fast low-latency autocomplete cascade"
        ),
        "reasoning": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "mercury-decide",
                "coarena/claude-opus-5-5",
                "coarena/deepseek-v4-1-flash-1017",
                "claude-opus-5-5",
                "DeepSeek-R1-Distill-Qwen-7B",
                "mercury-3",
                "coarena/gemini-3-8-flash",
                "free/gemini-3.8-flash",
                "gemini-3.8-flash",
                "qwen/qwen3.8-max:free"
            ],
            description="Deep reasoning and chain of thought cascade"
        ),
        "general": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "coarena/gemini-3-8-flash",
                "coarena/gpt-6-astra",
                "coarena/claude-sonnet-5-5",
                "free/gemini-3.8-flash",
                "gemini-3.8-flash",
                "gpt-6-astra",
                "openai/gpt-oss-120b",
                "wusrouter/qwen3.8-flash:free",
                "qwen/qwen3.8-27b",
                "hermes-3-llama-3.1-70b"
            ],
            description="General conversational and instruction models"
        ),
        "gpt-4o": AliasConfig(
            targets=["coding", "general"],
            description="Compatibility alias for agents hardcoded to gpt-4o"
        ),
        "gpt-4": AliasConfig(
            targets=["coding", "general"],
            description="Compatibility alias for agents hardcoded to gpt-4"
        ),
        "claude-3-5-sonnet": AliasConfig(
            targets=["coarena/claude-sonnet-5-5", "coding", "reasoning"],
            description="Compatibility alias for agents requesting Claude 3.5 Sonnet"
        ),
        "deepseek-v4.1-flash": AliasConfig(
            targets=[
                "free/deepseek-v4.1-flash",
                "coarena/deepseek-v4-1-flash-1017",
                "deepseek-v4.1-flash:free",
                "deepseek-ai/DeepSeek-V4.1-Flash",
                "zro/deepseek-v4.1-flash"
            ],
            description="Priority cascade for DeepSeek V4.1 Flash across Apinex, Coarena, Tokenharbor, River AI, and Moonmath"
        )
    }

    return XenrouterConfig(
        host="127.0.0.1",
        port=8989,
        auto_probe_local=True,
        backends=default_backends,
        aliases=default_aliases,
        default_model="deepseek-v4.1-flash"
    )


def find_config_file(explicit_path: Optional[Any] = None) -> Optional[Path]:
    """Search for configuration file in current directory or user home."""
    if explicit_path and isinstance(explicit_path, (str, Path)):
        p = Path(explicit_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Specified configuration file not found: {explicit_path}")

    candidates = [
        Path("xenrouter.yaml"),
        Path("xenrouter.yml"),
        Path("xenrouter.json"),
        Path.home() / ".xenrouter" / "xenrouter.yaml",
        Path.home() / ".config" / "xenrouter" / "xenrouter.yaml",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def load_config(path: Optional[str] = None) -> XenrouterConfig:
    """Load configuration from file or return standard defaults."""
    cfg_file = find_config_file(path)
    if not cfg_file:
        return get_default_config()

    try:
        content = cfg_file.read_text(encoding="utf-8")
        if cfg_file.suffix.lower() in [".yaml", ".yml"]:
            data = yaml.safe_load(content) or {}
        else:
            import json
            data = json.loads(content) or {}

        return XenrouterConfig(**data)
    except Exception as exc:
        raise ValueError(f"Failed to parse configuration file {cfg_file}: {exc}") from exc


def save_config(config: XenrouterConfig, path: str = "xenrouter.yaml") -> None:
    """Save configuration object to YAML file."""
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    dict_repr = config.model_dump(mode="json")
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(dict_repr, f, default_flow_style=False, sort_keys=False)
