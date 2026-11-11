"""
Model rate limits, quotas, and free/free-tier classification engine for Xenrouter.
Provides comprehensive tracking of RPM, RPD, TPM, context window ceilings,
and live quota headers across all local and remote inference providers.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ModelLimitProfile(BaseModel):
    model_id: str
    provider: str
    tier: str  # FREE, FREE-TIER, LOCAL, COMMUNITY, or DEDICATED
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    context_window: int = 32768
    cost_per_m_tokens: str = "Free"
    live_quota_remaining: Optional[str] = None
    notes: str = ""


KNOWN_TIER_PROFILES: Dict[str, Dict[str, Any]] = {
    # APInex Free Tier (Top Priority Route)
    "apinex/free/deepseek-v4.1-flash": {
        "tier": "FREE",
        "rpm": 15,
        "rpd": 500,
        "tpm": 15000,
        "ctx": 65536,
        "cost": "$0.00 (10M Pool)",
        "notes": "Top Priority Route, 3-key pool failover"
    },
    "apinex/deepseek-v4.1-flash": {
        "tier": "FREE",
        "rpm": 15,
        "rpd": 500,
        "tpm": 15000,
        "ctx": 65536,
        "cost": "$0.00 (10M Pool)",
        "notes": "Top Priority Route, 3-key pool failover"
    },
    # Coarena Free Model API
    "coarena/gemini-3-8-flash": {
        "tier": "FREE",
        "rpm": 60,
        "rpd": 5000,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena premier multi-modal fast model"
    },
    "coarena/deepseek-v4-1-flash-1017": {
        "tier": "FREE",
        "rpm": 60,
        "rpd": 5000,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena DeepSeek V4.1 Flash 1017"
    },
    "coarena/claude-sonnet-5-5": {
        "tier": "FREE",
        "rpm": 60,
        "rpd": 5000,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena Claude Sonnet 5.5 frontier model"
    },
    "coarena/claude-opus-5-5": {
        "tier": "FREE",
        "rpm": 30,
        "rpd": 2000,
        "tpm": 50000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena Claude Opus 5.5 deep reasoning"
    },
    "coarena/qwen3-8-2-4t-a95b": {
        "tier": "FREE",
        "rpm": 60,
        "rpd": 5000,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena Qwen3.8-2.4T-A95B massive coding model"
    },
    "coarena/gpt-6-astra": {
        "tier": "FREE",
        "rpm": 60,
        "rpd": 5000,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "$0.00 (Coarena Free)",
        "notes": "Coarena GPT-6 Astra instruction model"
    },
    # Groq free developer tier
    "groq/openai/gpt-oss-120b": {
        "tier": "FREE-TIER",
        "rpm": 30,
        "rpd": 14400,
        "tpm": 6000,
        "ctx": 131072,
        "cost": "$0.00 (Dev Tier)",
        "notes": "Fastest LPU inference (<600ms)"
    },
    "groq/qwen/qwen3.8-27b": {
        "tier": "FREE-TIER",
        "rpm": 30,
        "rpd": 14400,
        "tpm": 6000,
        "ctx": 131072,
        "cost": "$0.00 (Dev Tier)",
        "notes": "High-throughput coding model"
    },
    "groq/whisper-large-v3-turbo": {
        "tier": "FREE-TIER",
        "rpm": 20,
        "rpd": 2000,
        "ctx": 32768,
        "cost": "$0.00",
        "notes": "Audio transcription"
    },
    # InceptionLabs developer tier
    "inceptionlabs/mercury-2.5": {
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "Free Tier",
        "notes": "Low latency reasoning"
    },
    "inceptionlabs/mercury-3": {
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "Free Tier",
        "notes": "Frontier agentic model"
    },
    "inceptionlabs/mercury-decide": {
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "tpm": 100000,
        "ctx": 128000,
        "cost": "Free Tier",
        "notes": "Decision & tool planning"
    },
    # River AI community tier
    "river/deepseek-ai/DeepSeek-V4.1-Flash": {
        "tier": "FREE-TIER",
        "rpm": 20,
        "rpd": 1000,
        "ctx": 65536,
        "cost": "$0.00",
        "notes": "High concurrency flash model"
    },
    # Moonmath tier
    "moonmath/zro/deepseek-v4.1-flash": {
        "tier": "FREE-TIER",
        "rpm": 15,
        "rpd": 500,
        "ctx": 65536,
        "cost": "$0.00",
        "notes": "Uncapped greeting"
    },
    # Free-AI tier
    "free-ai/qwen7b": {
        "tier": "FREE",
        "rpm": 20,
        "rpd": 1000,
        "ctx": 32768,
        "cost": "$0.00",
        "notes": "Zero token fee"
    },
    # Top-Tools tier
    "top-tools/Top-Tools-Ai": {
        "tier": "COMMUNITY",
        "rpm": 10,
        "rpd": 300,
        "ctx": 32768,
        "cost": "$0.00",
        "notes": "Tool-use optimized"
    },
    # Nvidia NIM Developer credits
    "nvidia/meta/llama-3.1-8b-instruct": {
        "tier": "DEVELOPER-CREDITS",
        "rpm": 40,
        "ctx": 131072,
        "cost": "1000 trial credits",
        "notes": "Nvidia NIM hardware acceleration"
    },
    "nvidia/nvidia/llama-3.1-nemotron-70b-instruct": {
        "tier": "DEVELOPER-CREDITS",
        "rpm": 40,
        "ctx": 131072,
        "cost": "1000 trial credits",
        "notes": "Frontier 70B instruct"
    },
}


def classify_model_tier(model_id: str, provider_name: str) -> Dict[str, Any]:
    """Classify model into tier, RPM, RPD, context, and cost."""
    key = f"{provider_name.lower()}/{model_id.lower()}"
    if key in KNOWN_TIER_PROFILES:
        return KNOWN_TIER_PROFILES[key]

    m_low = model_id.lower()
    p_low = provider_name.lower()

    # Local engines: completely unlimited
    if p_low in ("ollama", "lmstudio", "llamacpp", "vllm", "koboldcpp", "local"):
        return {
            "tier": "LOCAL",
            "rpm": None,
            "rpd": None,
            "tpm": None,
            "ctx": 131072,
            "cost": "$0.00 (Local Hardware)",
            "notes": "Completely uncapped & private on LAN"
        }

    # Free model indicators in ID
    if ":free" in m_low or "free/" in m_low or "-free" in m_low or "/free" in m_low:
        return {
            "tier": "FREE",
            "rpm": 15,
            "rpd": 200,
            "tpm": 15000,
            "ctx": 65536 if "deepseek" in m_low or "gemini" in m_low else 32768,
            "cost": "$0.00",
            "notes": "Free tier endpoint"
        }

    # Flash / Lite models
    if "flash" in m_low or "lite" in m_low or "turbo" in m_low:
        return {
            "tier": "FREE-TIER",
            "rpm": 30,
            "rpd": 1000,
            "tpm": 30000,
            "ctx": 131072 if "gemini" in m_low else 65536,
            "cost": "Free / Low Cost",
            "notes": "High speed, low latency"
        }

    # Default cloud model
    return {
        "tier": "STANDARD",
        "rpm": 20,
        "rpd": 500,
        "tpm": 20000,
        "ctx": 65536,
        "cost": "Pooled Key Quota",
        "notes": "Key rotated pool"
    }


def get_all_model_limits(registry: Any) -> List[ModelLimitProfile]:
    """Extract and compile rate limit profiles for all models in Xenrouter."""
    profiles: List[ModelLimitProfile] = []
    seen = set()

    for b in registry.all():
        quota_str = "Uncapped"
        if b.ratelimit_remaining is not None:
            quota_str = f"{b.ratelimit_remaining} req left"
        elif b.quota_remaining_str:
            quota_str = b.quota_remaining_str[:18]

        for m in b.models:
            comp_key = (b.name, m.id)
            if comp_key in seen:
                continue
            seen.add(comp_key)

            info = classify_model_tier(m.id, b.name)
            profiles.append(
                ModelLimitProfile(
                    model_id=m.id,
                    provider=b.name,
                    tier=info["tier"],
                    rpm_limit=info.get("rpm"),
                    rpd_limit=info.get("rpd"),
                    tpm_limit=info.get("tpm"),
                    context_window=info.get("ctx", 32768),
                    cost_per_m_tokens=info.get("cost", "$0.00"),
                    live_quota_remaining=quota_str,
                    notes=info.get("notes", "")
                )
            )

    return profiles


# Master Provider-to-Best-Model registry for zero-cost, high-token inference cascades
MODEL_PROVIDER_MAP: Dict[str, Dict[str, Any]] = {
    "free/deepseek-v4.1-flash": {
        "provider": "APInex",
        "provider_slug": "apinex",
        "tier": "DAILY",
        "rpm": 15,
        "ctx": 65536,
        "daily_tokens": "20M tokens (Daily)",
        "notes": "2 API keys, daily login reset, top priority route"
    },
    "apinex/free/deepseek-v4.1-flash": {
        "provider": "APInex",
        "provider_slug": "apinex",
        "tier": "DAILY",
        "rpm": 15,
        "ctx": 65536,
        "daily_tokens": "20M tokens (Daily)",
        "notes": "2 API keys, daily login reset, top priority route"
    },
    "qwen3.8-omni-flash:free": {
        "provider": "xKiro",
        "provider_slug": "xkiro",
        "tier": "DAILY-POOL",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "500K (+ Additional 30M)",
        "notes": "xKiro 500K base + 30M additional token pool"
    },
    "xkiro/qwen3.8-omni-flash:free": {
        "provider": "xKiro",
        "provider_slug": "xkiro",
        "tier": "DAILY-POOL",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "500K (+ Additional 30M)",
        "notes": "xKiro 500K base + 30M additional token pool"
    },
    "navy/gpt-6-astra": {
        "provider": "Navy.ai",
        "provider_slug": "navy",
        "tier": "DAILY",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "150K tokens Daily",
        "notes": "Frontier GPT-6 Astra & Claude 5.5 daily pool"
    },
    "gpt-6-astra": {
        "provider": "Navy.ai",
        "provider_slug": "navy",
        "tier": "DAILY",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "150K tokens Daily",
        "notes": "Frontier GPT-6 Astra daily pool"
    },
    "llm7/deepseek-v4-flash:0731": {
        "provider": "LLM7 (io)",
        "provider_slug": "llm7",
        "tier": "DAILY",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "100K tokens Daily",
        "notes": "Verified alive daily token pool (100K tokens)"
    },
    "llm7/Inkling-Small": {
        "provider": "LLM7 (io)",
        "provider_slug": "llm7",
        "tier": "DAILY",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "100K tokens Daily",
        "notes": "Verified alive daily token pool (100K tokens)"
    },
    "wusrouter/qwen3.8-flash:free": {
        "provider": "WusRouter",
        "provider_slug": "wusrouter",
        "tier": "COMMUNITY-POOL",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "10M tokens",
        "notes": "Verified alive community pool (10M tokens)"
    },
    "vyceai/deepseek-v4-flash": {
        "provider": "Vyce.ai",
        "provider_slug": "vyceai",
        "tier": "DAILY-REWARD",
        "rpm": 20,
        "ctx": 65536,
        "daily_tokens": "$50 Daily Reward",
        "notes": "Multiple API keys with daily check-in rewards"
    },
    "apmix/hy4": {
        "provider": "Apmix.ai",
        "provider_slug": "apmix",
        "tier": "FREE-GRANT",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "4M tokens (1 time)",
        "notes": "Set multiple API keys, Hy4 (Free)"
    },
    "cleanapis/deepseek-v4-flash": {
        "provider": "Clean APIs",
        "provider_slug": "cleanapis",
        "tier": "MONTHLY",
        "rpm": 60,
        "ctx": 65536,
        "daily_tokens": "500K tokens ($500K) Monthly",
        "notes": "Set Multiple API keys, 60 RPM"
    },
    "codecraft/deepseek-v4-flash": {
        "provider": "Code Craft API",
        "provider_slug": "codecraft",
        "tier": "MONTHLY",
        "rpm": 60,
        "ctx": 65536,
        "daily_tokens": "500K Monthly",
        "notes": "Set Multiple API keys, 60 RPM"
    },
    "deepseek-v4.1-flash": {
        "provider": "FreeModel",
        "provider_slug": "freemodel",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~15M/day pool",
        "notes": "Verified alive DeepSeek V4.1 Flash on FreeModel"
    },
    "freemodel/deepseek-v4.1-flash": {
        "provider": "FreeModel",
        "provider_slug": "freemodel",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~15M/day pool",
        "notes": "Verified alive DeepSeek V4.1 Flash on FreeModel"
    },
    "cohere/north-mini-code": {
        "provider": "xKiro",
        "provider_slug": "xkiro",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "500K (+ Additional 30M)",
        "notes": "Verified alive code intelligence model on xKiro"
    },
    "xkiro/cohere/north-mini-code": {
        "provider": "xKiro",
        "provider_slug": "xkiro",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "500K (+ Additional 30M)",
        "notes": "Verified alive code intelligence model on xKiro"
    },
    "gemini-3.8-flash": {
        "provider": "Google AI Studio",
        "provider_slug": "google",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 1048576,
        "daily_tokens": "1.5 Billion/day",
        "notes": "Flagship 3.8 Flash free tier model (1M context)"
    },
    "google/gemini-3.8-flash": {
        "provider": "Google AI Studio",
        "provider_slug": "google",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 1048576,
        "daily_tokens": "1.5 Billion/day",
        "notes": "Flagship 3.8 Flash free tier model (1M context)"
    },
    "wusrouter/qwen3.8-flash:free": {
        "provider": "WusRouter",
        "provider_slug": "wusrouter",
        "tier": "FREE",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "~10M/day pool",
        "notes": "Verified alive high-speed community gateway"
    },
    "claude-opus-5-5": {
        "provider": "FreeModel",
        "provider_slug": "freemodel",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~15M/day pool",
        "notes": "Frontier Claude reasoning & coding model"
    },
    "gpt-6-astra": {
        "provider": "FreeModel",
        "provider_slug": "freemodel",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~15M/day pool",
        "notes": "Frontier general intelligence endpoint"
    },
    "deepseek-v4.1-flash:free": {
        "provider": "TokenHarbor",
        "provider_slug": "tokenharbor",
        "tier": "FREE",
        "rpm": 15,
        "ctx": 65536,
        "daily_tokens": "~5M/day pool",
        "notes": "Verified alive community token pool"
    },
    "anthropic/claude-opus-4-6": {
        "provider": "LLM7",
        "provider_slug": "llm7",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~5M/day pool",
        "notes": "Multi-model experimentation relay"
    },
    "zro/deepseek-v4.1-flash": {
        "provider": "Moonmath",
        "provider_slug": "moonmath",
        "tier": "FREE",
        "rpm": 15,
        "ctx": 65536,
        "daily_tokens": "~2M/day pool",
        "notes": "Verified alive zero-cost inference"
    },
    "qwen7b": {
        "provider": "Free-AI",
        "provider_slug": "freeai",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 32768,
        "daily_tokens": "Uncapped Free",
        "notes": "Verified alive low-latency community model"
    },
    "Top-Tools-Ai": {
        "provider": "Top-Tools",
        "provider_slug": "toptools",
        "tier": "COMMUNITY",
        "rpm": 10,
        "ctx": 32768,
        "daily_tokens": "~1M/day pool",
        "notes": "Tool-use optimized community gateway"
    },
    "Qwen/Qwen3-8B": {
        "provider": "SiliconFlow",
        "provider_slug": "siliconflow",
        "tier": "FREE",
        "rpm": 1000,
        "ctx": 32768,
        "daily_tokens": "Uncapped Free",
        "notes": "Permanently free sub-14B model"
    },
    "hermes-3-llama-3.1-70b": {
        "provider": "Nous Research",
        "provider_slug": "nous",
        "tier": "COMMUNITY",
        "rpm": 50,
        "ctx": 128000,
        "daily_tokens": "144M/day",
        "notes": "High-capacity reasoning cascade"
    },
    "deepseek-ai/DeepSeek-V4.1-Flash": {
        "provider": "River AI",
        "provider_slug": "river",
        "tier": "DEVELOPER-CREDITS",
        "rpm": 60,
        "ctx": 1048576,
        "daily_tokens": "$25 grant (~208M tokens)",
        "notes": "High-context 1M token gateway"
    },
    "mercury-3": {
        "provider": "Inception Labs",
        "provider_slug": "inceptionlabs",
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "ctx": 65536,
        "daily_tokens": "100M grant + 15M/day",
        "notes": "Low-latency diffusion architecture"
    },
    "mercury-2.5": {
        "provider": "Inception Labs",
        "provider_slug": "inceptionlabs",
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "ctx": 65536,
        "daily_tokens": "100M grant + 15M/day",
        "notes": "Low-latency diffusion autocomplete"
    },
    "mercury-decide": {
        "provider": "Inception Labs",
        "provider_slug": "inceptionlabs",
        "tier": "DEVELOPER-TIER",
        "rpm": 60,
        "ctx": 65536,
        "daily_tokens": "100M grant + 15M/day",
        "notes": "Decision & planning reasoning model"
    },
    "qwen/qwen3.8-27b": {
        "provider": "IteraCompute",
        "provider_slug": "iteracompute",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 65536,
        "daily_tokens": "30M/month (~1M/day)",
        "notes": "High-parameter 27B model failover"
    },
    "llama-3.3-70b-versatile": {
        "provider": "Groq Cloud",
        "provider_slug": "groq",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "~500k-1M/day",
        "notes": "Ultra-fast LPU inference"
    },
    "llama-3.1-8b-instant": {
        "provider": "Groq Cloud",
        "provider_slug": "groq",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "~1M/day",
        "notes": "Ultra-fast LPU inference (500+ tok/s)"
    },
    "openai/gpt-oss-120b": {
        "provider": "Groq Cloud",
        "provider_slug": "groq",
        "tier": "FREE-TIER",
        "rpm": 30,
        "ctx": 131072,
        "daily_tokens": "~1M/day",
        "notes": "High-throughput general model"
    },
    "llama-3.3-70b-instruct:free": {
        "provider": "OpenRouter",
        "provider_slug": "openrouter",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~2M-4M/day",
        "notes": "Free-tier aggregator fallback"
    },
    "qwen/qwen3.8-max:free": {
        "provider": "OpenRouter",
        "provider_slug": "openrouter",
        "tier": "FREE",
        "rpm": 20,
        "ctx": 131072,
        "daily_tokens": "~2M-4M/day",
        "notes": "Free-tier aggregator fallback"
    },
    "free/glm-5.3-flash": {
        "provider": "Z.ai (Zhipu)",
        "provider_slug": "zai",
        "tier": "FREE",
        "rpm": 30,
        "ctx": 200000,
        "daily_tokens": "~50M/day (1000 calls)",
        "notes": "GLM flagship flash model"
    },
    "DeepSeek-R1-Distill-Qwen-7B": {
        "provider": "SiliconFlow",
        "provider_slug": "siliconflow",
        "tier": "FREE",
        "rpm": 1000,
        "ctx": 65536,
        "daily_tokens": "Uncapped Free",
        "notes": "Reasoning distilled model"
    }
}


def resolve_model_provider_info(model_id: str, registry: Optional[Any] = None) -> Dict[str, Any]:
    """Resolve full provider display name, status, and rate limit profile for any model ID."""
    if model_id in MODEL_PROVIDER_MAP:
        info = dict(MODEL_PROVIDER_MAP[model_id])
    else:
        bare = model_id.split("/")[-1].lower()
        matched_info = None
        for k, v in MODEL_PROVIDER_MAP.items():
            if k.split("/")[-1].lower() == bare:
                matched_info = dict(v)
                break
        if matched_info:
            info = matched_info
        else:
            if "/" in model_id:
                prefix = model_id.split("/")[0]
                info = {
                    "provider": prefix.capitalize(),
                    "provider_slug": prefix.lower(),
                    "tier": "COMMUNITY",
                    "rpm": 20,
                    "ctx": 32768,
                    "daily_tokens": "Standard",
                    "notes": "Community endpoint"
                }
            else:
                info = {
                    "provider": "Local / Node",
                    "provider_slug": "local",
                    "tier": "LOCAL",
                    "rpm": None,
                    "ctx": 32768,
                    "daily_tokens": "Uncapped",
                    "notes": "Local node"
                }

    status = "standby"
    key_count = 0
    if registry:
        for b in registry.all():
            if b.name.lower() == info["provider_slug"].lower() or any(m.id.lower() == model_id.lower() for m in b.models):
                status = b.status.value.lower()
                key_count = len(b.key_rotator.get_states()) if hasattr(b, "key_rotator") else 0
                break

    info["status"] = status
    info["key_count"] = key_count
    return info


# Deterministic mapping from provider slug / canonical name to its highest-yield free tier model
PROVIDER_BEST_MODEL_MAP: Dict[str, str] = {
    "apinex": "free/deepseek-v4.1-flash",
    "xkiro": "qwen3.8-omni-flash:free",
    "wusrouter": "wusrouter/qwen3.8-flash:free",
    "iteracompute": "qwen/qwen3.8-27b",
    "freemodel": "deepseek-v4.1-flash",
    "tokenharbor": "deepseek-v4.1-flash:free",
    "river": "deepseek-ai/DeepSeek-V4.1-Flash",
    "inceptionlabs": "mercury-3",
    "moonmath": "zro/deepseek-v4.1-flash",
    "google": "gemini-3.8-flash",
    "gemini": "gemini-3.8-flash",
    "zai": "free/glm-5.3-flash",
    "groq": "openai/gpt-oss-120b",
    "nous": "hermes-3-llama-3.1-70b",
    "siliconflow": "Qwen/Qwen3-8B",
    "freeai": "qwen7b",
    "free-ai": "qwen7b",
    "toptools": "Top-Tools-Ai",
    "top-tools": "Top-Tools-Ai",
    "openrouter": "llama-3.3-70b-instruct:free",
    "navy": "gpt-6-astra",
    "llm7": "deepseek-v4-flash:0731",
    "vyceai": "deepseek-v4-flash",
    "apmix": "hy4",
    "cleanapis": "deepseek-v4-flash",
    "codecraft": "deepseek-v4-flash",
    "nvidia": "meta/llama-3.1-8b-instruct",
    "huggingface": "deepseek-ai/DeepSeek-V4.1-Flash",
    "coarena": "claude-sonnet-5-5",
}


def resolve_provider_best_model(provider_name: str) -> Optional[str]:
    """Resolve the premier free-tier model for any provider name or slug."""
    p_norm = provider_name.lower().strip()
    if p_norm in PROVIDER_BEST_MODEL_MAP:
        return PROVIDER_BEST_MODEL_MAP[p_norm]
    for k, v in PROVIDER_BEST_MODEL_MAP.items():
        if k in p_norm or p_norm in k:
            return v
    return None
