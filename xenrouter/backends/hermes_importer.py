"""
Comprehensive Hermes Agent provider auto-discovery and credential importer.
Extracts all configured inference providers, API keys, and models from
Hermes configuration (~/.hermes and AppData/Local/hermes config.yaml, .env, auth.json).
Outputs clean, canonical provider names without any 'hermes' prefix.
Synchronized to active state as of 2026-11-07.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from xenrouter.types import BackendConfig, BackendType, KeyRotationStrategy


def get_hermes_paths() -> List[Path]:
    """Retrieve potential Hermes configuration directories."""
    paths = [
        Path.home() / "AppData" / "Local" / "hermes",
        Path.home() / ".hermes",
        Path("X:/Hermes/Hermes"),
    ]
    return [p for p in paths if p.exists() and p.is_dir()]


def clean_provider_name(raw_name: str, base_url: str = "") -> str:
    """
    Generate clean, canonical provider name without any 'hermes' or 'hermes-' prefix.
    Examples:
        'Api.xkiro.com' / 'api_xkiro_com' -> 'xkiro'
        'Integrate.api.nvidia.com' / 'integrate_api_nvidia_com' -> 'nvidia'
        'Tokenharbor.ai' / 'tokenharbor_ai' -> 'tokenharbor'
        'Api.groq.com' / 'api_groq_com' -> 'groq'
        'Api.inceptionlabs.ai' / 'api_inceptionlabs_ai' -> 'inceptionlabs'
        'Api.hcnsec.cn' / 'api_hcnsec_cn' -> 'hcnsec'
        'Api.apinex.bond' / 'api_apinex_bond' -> 'apinex'
        'Inference.dahl.global' / 'inference_dahl_global' -> 'dahl'
        'Vyceai.com' / 'vyceai_com' -> 'vyceai'
        'Api.router9.com' / 'api_router9_com' -> 'router9'
        'Api.river.ai' / 'api_river_ai' -> 'river'
        'Zro.moonmath.ai' / 'zro_moonmath_ai' -> 'moonmath'
        'Api.free.ai' / 'api_free_ai' -> 'free-ai'
        'Top-tools-ai.com' / 'top_tools_ai_com' -> 'top-tools'
        'kaggle' -> 'kaggle'
        'Api.orcarouter.ai' / 'api_orcarouter_ai' -> 'orcarouter'
        'Api.iteracompute.com' / 'api_iteracompute_com' -> 'iteracompute'
        'api.navy' / 'api_navy' -> 'navy'
        'ollama.com' / 'ollama-cloud' -> 'ollama-cloud'
        'nous' -> 'nous'
    """
    s = raw_name.lower().strip()

    # Strip prefixes
    for pfx in ["hermes-custom-", "hermes_custom_", "hermes-", "hermes_", "custom:"]:
        if s.startswith(pfx):
            s = s[len(pfx):]

    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/")[0]

    # Normalize underscores and dashes for hostname matching
    dot_normalized = s.replace("_", ".").replace("-", ".")

    known_mappings = {
        "api.apinex.bond": "apinex",
        "api.hcnsec.cn": "hcnsec",
        "api.xkiro.com": "xkiro",
        "inference.dahl.global": "dahl",
        "integrate.api.nvidia.com": "nvidia",
        "tokenharbor.ai": "tokenharbor",
        "vyceai.com": "vyceai",
        "api.router9.com": "router9",
        "api.inceptionlabs.ai": "inceptionlabs",
        "api.groq.com": "groq",
        "api.river.ai": "river",
        "zro.moonmath.ai": "moonmath",
        "api.free.ai": "free-ai",
        "top.tools.ai.com": "top-tools",
        "top-tools-ai.com": "top-tools",
        "kaggle": "kaggle",
        "api.orcarouter.ai": "orcarouter",
        "api.iteracompute.com": "iteracompute",
        "api.navy": "navy",
        "api-navy": "navy",
        "navy": "navy",
        "ollama.com": "ollama-cloud",
        "ollama-cloud": "ollama-cloud",
        "ollama.cloud": "ollama-cloud",
        "nous": "nous",
        "seekai.cc": "seekai",
        "seekai": "seekai",
        "api.unorouter.com": "unorouter",
        "ahefi.com": "ahefi",
        "ahefi": "ahefi",
        "cleanapis.com": "cleanapis",
        "cleanapis": "cleanapis",
        "api.justwoker.icu": "justwoker",
        "api.apmix.ai": "apmix",
        "apmix.ai": "apmix",
        "apmix": "apmix",
        "radoxai.com": "radoxai",
        "codecraftapi.com": "codecraft",
        "codecraft": "codecraft",
        "vyceai.com": "vyceai",
        "vyceai": "vyceai",
        "vyce": "vyceai",
        "google": "gemini",
        "gemini": "gemini",
        "generativelanguage.googleapis.com": "gemini",
        "huggingface": "huggingface",
        "router.huggingface.co": "huggingface",
        "wusrouter.com": "wusrouter",
        "wusrouter": "wusrouter",
        "freemodel.in": "freemodel",
        "freemodel": "freemodel",
        "api.llm7.io": "llm7",
        "llm7.io": "llm7",
        "llm7": "llm7",
        "coarena.ai": "coarena",
        "api.coarena.ai": "coarena",
        "coarena": "coarena",
    }

    if dot_normalized in known_mappings:
        return known_mappings[dot_normalized]
    if s in known_mappings:
        return known_mappings[s]

    # Clean domain parts
    parts = dot_normalized.split(".")
    ignored = {"api", "inference", "integrate", "www", "zro", "dev", "app", "io", "ai", "com", "cn", "global", "bond", "org", "net", "cc", "icu"}
    filtered = [p for p in parts if p not in ignored]

    if filtered:
        return "-".join(filtered)
    return dot_normalized.replace(".", "-")


def parse_hermes_env(env_path: Path) -> Dict[str, str]:
    """Parse key-value pairs from Hermes .env file."""
    env_vars = {}
    if not env_path.exists():
        return env_vars

    try:
        content = env_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v:
                env_vars[k] = v
    except Exception:
        pass

    return env_vars


def get_hermes_active_model() -> Optional[str]:
    """Retrieve user's active default model from Hermes config.yaml."""
    hermes_dirs = get_hermes_paths()
    if not hermes_dirs:
        return None

    cfg_path = hermes_dirs[0] / "config.yaml"
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8", errors="ignore")) or {}
            model_section = data.get("model", {})
            if isinstance(model_section, dict):
                return model_section.get("default") or model_section.get("model")
            elif isinstance(model_section, str):
                return model_section
        except Exception:
            pass
    return None


def discover_hermes_backends() -> List[BackendConfig]:
    """
    Discover all configured Hermes providers from config.yaml, .env, and auth.json.
    Constructs unified BackendConfig objects with:
    - Clean actual provider names (NO 'hermes' prefix)
    - User-selected models loaded directly from Hermes custom_providers
    - Pooled API keys with automatic rotation and failover
    """
    backends: Dict[str, BackendConfig] = {}
    hermes_dirs = get_hermes_paths()

    if not hermes_dirs:
        return []

    primary_dir = hermes_dirs[0]
    config_file = primary_dir / "config.yaml"
    env_file = primary_dir / ".env"
    auth_file = primary_dir / "auth.json"

    env_vars = parse_hermes_env(env_file)

    DEAD_PROVIDERS = {
        "hcnsec", "dahl", "router9", "kaggle",
        "seekai", "justwoker", "unorouter", "radoxai"
    }

    # 1. Parse custom_providers directly from config.yaml
    if config_file.exists():
        try:
            cfg_data = yaml.safe_load(config_file.read_text(encoding="utf-8", errors="ignore")) or {}
            custom_list = cfg_data.get("custom_providers", [])

            for p in custom_list:
                raw_name = p.get("name", "")
                base_url = p.get("base_url", "")
                if not raw_name or not base_url:
                    continue

                provider_name = clean_provider_name(raw_name, base_url)
                if provider_name.lower() in ["xenrouter", "local-router", "self"] or "127.0.0.1:8989" in base_url or "localhost:8989" in base_url:
                    continue
                if provider_name.lower() in DEAD_PROVIDERS:
                    continue
                key_env = p.get("key_env")
                api_keys: List[str] = []

                if key_env and key_env in env_vars and env_vars[key_env]:
                    key_val = env_vars[key_env]
                    if not key_val.startswith("http"):
                        for subk in key_val.replace(";", ",").split(","):
                            subk_clean = subk.strip()
                            if subk_clean and subk_clean not in api_keys:
                                api_keys.append(subk_clean)

                # Check for numbered key variants (e.g. KEY_1, KEY_2, KEY_3)
                if key_env:
                    for k_name, k_val in env_vars.items():
                        if k_name.startswith(key_env + "_") and k_val and not k_val.startswith("http"):
                            for subk in k_val.replace(";", ",").split(","):
                                subk_clean = subk.strip()
                                if subk_clean and subk_clean not in api_keys:
                                    api_keys.append(subk_clean)

                # Extract user-configured models from Hermes
                raw_models = p.get("models", {})
                models_filter: List[str] = []
                if isinstance(raw_models, dict):
                    models_filter = list(raw_models.keys())
                elif isinstance(raw_models, list):
                    models_filter = list(raw_models)

                # Ensure default model is at index 0 if specified
                default_model = p.get("model")
                if default_model and default_model != "auto":
                    if default_model in models_filter:
                        models_filter.remove(default_model)
                    models_filter.insert(0, default_model)

                backends[provider_name] = BackendConfig(
                    name=provider_name,
                    type=BackendType.OPENAI_COMPATIBLE,
                    base_url=base_url.rstrip("/"),
                    api_keys=api_keys,
                    key_rotation_strategy=KeyRotationStrategy.ROUND_ROBIN,
                    key_cooldown_seconds=60.0,
                    priority=1 if provider_name in ["apinex", "google", "siliconflow", "nous", "nvidia", "xkiro", "tokenharbor", "groq", "inceptionlabs"] else 2,
                    timeout=90.0,
                    max_concurrency=4,
                    models_filter=models_filter if models_filter else None
                )
        except Exception:
            pass

    # 2. Parse providers from .env (for any providers not already in custom_providers)
    for k, v in env_vars.items():
        if not v or v.startswith("http"):
            continue

        if k.startswith("HERMES_CUSTOM_") and k.endswith("_API_KEY"):
            raw_slug = k[len("HERMES_CUSTOM_"):-len("_API_KEY")].lower()
            provider_name = clean_provider_name(raw_slug)
            if provider_name.lower() in DEAD_PROVIDERS:
                continue

            # Map known URLs
            if "top_tools" in raw_slug or "top-tools" in raw_slug:
                base_url = "https://top-tools-ai.com/api/v1"
            elif "groq" in raw_slug:
                base_url = "https://api.groq.com/openai/v1"
            elif "hcnsec" in raw_slug:
                base_url = "https://api.hcnsec.cn/v1"
            elif "dahl" in raw_slug:
                base_url = "https://inference.dahl.global/v1"
            elif "nvidia" in raw_slug:
                base_url = "https://integrate.api.nvidia.com/v1"
            elif "tokenharbor" in raw_slug:
                base_url = "https://tokenharbor.ai/v1"
            elif "xkiro" in raw_slug:
                base_url = "https://api.xkiro.com/v1"
            elif "apinex" in raw_slug:
                base_url = "https://api.apinex.bond/v1"
            elif "inceptionlabs" in raw_slug:
                base_url = "https://api.inceptionlabs.ai/v1"
            elif "vyceai" in raw_slug or "vyce" in raw_slug:
                base_url = "https://vyceai.com/v1"
            elif "apmix" in raw_slug:
                base_url = "https://api.apmix.ai/v1"
            elif "cleanapis" in raw_slug:
                base_url = "https://cleanapis.com/v1"
            elif "codecraft" in raw_slug:
                base_url = "https://codecraftapi.com/v1"
            elif "router9" in raw_slug:
                base_url = "https://api.router9.com/v1"
            elif "river" in raw_slug:
                base_url = "https://api.river.ai/v1"
            elif "moonmath" in raw_slug:
                base_url = "https://zro.moonmath.ai/v1"
            elif "orcarouter" in raw_slug:
                base_url = "https://api.orcarouter.ai/v1"
            elif "iteracompute" in raw_slug:
                base_url = "https://api.iteracompute.com/v1"
            else:
                host = raw_slug.replace("_", ".")
                base_url = f"https://{host}/v1"

            keys_list = [k.strip() for k in v.replace(";", ",").split(",") if k.strip() and not k.strip().startswith("http")]
            if provider_name in backends:
                for k_item in keys_list:
                    if k_item not in backends[provider_name].api_keys:
                        backends[provider_name].api_keys.append(k_item)
            else:
                backends[provider_name] = BackendConfig(
                    name=provider_name,
                    type=BackendType.OPENAI_COMPATIBLE,
                    base_url=base_url,
                    api_keys=keys_list,
                    key_rotation_strategy=KeyRotationStrategy.ROUND_ROBIN,
                    key_cooldown_seconds=60.0,
                    priority=1 if provider_name in ["apinex", "google", "siliconflow", "nous", "nvidia", "xkiro", "tokenharbor", "groq", "inceptionlabs", "gemini"] else 2,
                    timeout=90.0,
                    max_concurrency=4
                )

    # 3. Add first-party Hermes & environment-backed providers (Navy, Ollama Cloud, Gemini, Hugging Face, etc.)
    navy_key = env_vars.get("NAVY_API_KEY") or env_vars.get("HERMES_CUSTOM_API_NAVY_API_KEY") or os.environ.get("NAVY_API_KEY")
    if navy_key:
        name = "navy"
        if name in backends:
            if navy_key not in backends[name].api_keys:
                backends[name].api_keys.append(navy_key)
        else:
            backends[name] = BackendConfig(
                name=name,
                type=BackendType.OPENAI_COMPATIBLE,
                base_url="https://api.navy/v1",
                api_keys=[navy_key],
                priority=1,
                timeout=120.0,
                max_concurrency=6
            )

    ollama_cloud_key = env_vars.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY")
    if ollama_cloud_key:
        name = "ollama-cloud"
        if name in backends:
            if ollama_cloud_key not in backends[name].api_keys:
                backends[name].api_keys.append(ollama_cloud_key)
        else:
            backends[name] = BackendConfig(
                name=name,
                type=BackendType.OPENAI_COMPATIBLE,
                base_url="https://ollama.com/v1",
                api_keys=[ollama_cloud_key],
                priority=2,
                timeout=120.0,
                max_concurrency=4
            )

    # Gemini (Google AI Studio - 1.5B tokens/day free tier)
    gemini_key = env_vars.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        name = "gemini"
        if name in backends:
            if gemini_key not in backends[name].api_keys:
                backends[name].api_keys.append(gemini_key)
            backends[name].base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        else:
            backends[name] = BackendConfig(
                name=name,
                type=BackendType.OPENAI_COMPATIBLE,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_keys=[gemini_key],
                priority=1,
                timeout=90.0,
                max_concurrency=6
            )

    # Hugging Face Router (100+ open-source models)
    hf_token = (
        env_vars.get("HF_TOKEN")
        or env_vars.get("HUGGINGFACE_TOKEN")
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
    )
    if hf_token:
        name = "huggingface"
        if name in backends:
            if hf_token not in backends[name].api_keys:
                backends[name].api_keys.append(hf_token)
        else:
            backends[name] = BackendConfig(
                name=name,
                type=BackendType.OPENAI_COMPATIBLE,
                base_url="https://router.huggingface.co/v1",
                api_keys=[hf_token],
                priority=2,
                timeout=90.0,
                max_concurrency=4
            )

    # Handwritten providers keys check (Vyce.ai, Apmix.ai, Clean APIs, Code Craft)
    for h_name, env_keys, default_url in [
        ("apmix", ["HERMES_CUSTOM_API_APMIX_AI_API_KEY", "APMIX_API_KEY"], "https://api.apmix.ai/v1"),
        ("cleanapis", ["HERMES_CUSTOM_CLEANAPIS_COM_API_KEY", "CLEANAPIS_API_KEY"], "https://cleanapis.com/v1"),
        ("codecraft", ["HERMES_CUSTOM_CODECRAFTAPI_COM_API_KEY", "CODECRAFT_API_KEY"], "https://codecraftapi.com/v1"),
        ("vyceai", ["HERMES_CUSTOM_VYCEAI_COM_API_KEY", "VYCEAI_API_KEY", "VYCE_API_KEY"], "https://vyceai.com/v1"),
    ]:
        found_keys: List[str] = []
        for ek in env_keys:
            val = env_vars.get(ek) or os.environ.get(ek)
            if val and not val.startswith("http"):
                for subk in val.replace(";", ",").split(","):
                    subk_clean = subk.strip()
                    if subk_clean and subk_clean not in found_keys:
                        found_keys.append(subk_clean)
        if found_keys:
            if h_name in backends:
                for fk in found_keys:
                    if fk not in backends[h_name].api_keys:
                        backends[h_name].api_keys.append(fk)
            else:
                backends[h_name] = BackendConfig(
                    name=h_name,
                    type=BackendType.OPENAI_COMPATIBLE,
                    base_url=default_url,
                    api_keys=found_keys,
                    priority=2,
                    timeout=90.0,
                    max_concurrency=4
                )

    # 4. Parse auth.json credential pools (Nous OAuth, multi-keys)
    if auth_file.exists():
        try:
            auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
            pool = auth_data.get("credential_pool", {})

            for provider_key, creds in pool.items():
                if not creds:
                    continue
                provider_name = clean_provider_name(provider_key)
                if provider_name.lower() in ["xenrouter", "local-router", "self"]:
                    continue
                if provider_name.lower() in DEAD_PROVIDERS:
                    continue

                collected_keys = []
                base_url = None
                for c in creds:
                    if isinstance(c, str):
                        token = c.strip()
                    elif isinstance(c, dict):
                        token = c.get("access_token") or c.get("api_key")
                        if not token and "source" in c and str(c["source"]).startswith("env:"):
                            env_src = str(c["source"]).split("env:", 1)[1].strip()
                            token = env_vars.get(env_src) or os.environ.get(env_src)
                        if not base_url:
                            base_url = c.get("base_url") or c.get("inference_base_url")
                    else:
                        token = None
                    if token and token not in collected_keys:
                        collected_keys.append(token)

                if provider_name == "gemini" and base_url and not base_url.rstrip("/").endswith("/openai"):
                    base_url = f"{base_url.rstrip('/')}/openai"

                if base_url and ("127.0.0.1:8989" in base_url or "localhost:8989" in base_url):
                    continue

                if provider_name in backends:
                    for tk in collected_keys:
                        if tk not in backends[provider_name].api_keys:
                            backends[provider_name].api_keys.append(tk)
                    if base_url and backends[provider_name].base_url != base_url:
                        backends[provider_name].base_url = base_url.rstrip("/")
                elif base_url:
                    backends[provider_name] = BackendConfig(
                        name=provider_name,
                        type=BackendType.OPENAI_COMPATIBLE,
                        base_url=base_url.rstrip("/"),
                        api_keys=collected_keys,
                        key_rotation_strategy=KeyRotationStrategy.ROUND_ROBIN,
                        key_cooldown_seconds=60.0,
                        priority=1 if provider_name in ["nous", "gemini"] else 2,
                        timeout=120.0,
                        max_concurrency=4
                    )
        except Exception:
            pass

    return list(backends.values())
