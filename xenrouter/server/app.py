"""
FastAPI application definition and route bindings for Xenrouter.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.router import Router
from xenrouter.server.proxy import ProxyEngine
from xenrouter.server.state import AppState


def create_app(
    config: XenrouterConfig,
    state: AppState,
    registry: BackendRegistry,
    router: Router
) -> FastAPI:
    """Build and configure the FastAPI application."""

    client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0))
    proxy_engine = ProxyEngine(router=router, state=state, client=client)
    health_task: Optional[asyncio.Task] = None

    async def background_health_checker():
        """Periodic loop refreshing backend statuses and available models."""
        while True:
            try:
                await registry.refresh_all(client)
            except Exception:
                pass
            await asyncio.sleep(config.health_check_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal health_task
        # Pre-populate registry if not already registered
        for b_cfg in config.backends:
            if not registry.get(b_cfg.name):
                registry.register(b_cfg)

        # Import Hermes providers if enabled
        if config.import_hermes_providers:
            try:
                from xenrouter.backends.hermes_importer import discover_hermes_backends
                hermes_backends = discover_hermes_backends()
                for h_cfg in hermes_backends:
                    if not registry.get(h_cfg.name):
                        registry.register(h_cfg)
            except Exception:
                pass

        # Initial probe if auto_probe enabled
        if config.auto_probe_local:
            discovered = await BackendRegistry.probe_local_ports(client)
            for item in discovered:
                existing = registry.get(item["name"])
                if not existing:
                    from xenrouter.types import BackendConfig, BackendType
                    new_cfg = BackendConfig(
                        name=item["name"],
                        type=item["type"],
                        base_url=item["base_url"],
                        enabled=True
                    )
                    registry.register(new_cfg)

        # Launch periodic health check task in background immediately
        health_task = asyncio.create_task(background_health_checker())

        yield

        # Teardown
        if health_task:
            health_task.cancel()
        await client.aclose()

    app = FastAPI(
        title="Xenrouter",
        description="Ultra-lightweight unified local inference router",
        version="0.1.0",
        lifespan=lifespan
    )

    # CORS support
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        metrics = state.get_metrics()
        return {
            "name": "Xenrouter",
            "version": "0.1.0",
            "status": "ONLINE",
            "uptime_seconds": round(metrics.uptime_seconds, 1),
            "total_requests": metrics.total_requests,
            "endpoints": {
                "models": "/v1/models",
                "chat_completions": "/v1/chat/completions",
                "embeddings": "/v1/embeddings",
                "health": "/v1/health",
                "metrics": "/v1/metrics",
                "backends": "/v1/backends",
                "usage": "/v1/usage",
                "reload": "/v1/reload",
                "refresh": "/v1/refresh"
            }
        }

    @app.get("/v1/models")
    @app.get("/api/v1/models")
    async def list_models():
        """List unified model catalog across all local backends and virtual aliases."""
        models = router.get_unified_models_list()
        return {
            "object": "list",
            "data": models
        }

    @app.get("/api/tags")
    async def ollama_tags_probe():
        """Compatibility endpoint for agent probes expecting Ollama."""
        return {"models": []}

    @app.get("/v1/props")
    @app.get("/props")
    @app.get("/version")
    async def agent_props_probe():
        """Compatibility endpoint for agent probes expecting LM Studio or LocalAI."""
        return {"version": "0.1.0", "status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        """Unified OpenAI chat completions endpoint."""
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        return await proxy_engine.forward_chat_completion(request, payload)

    @app.post("/v1/completions")
    async def text_completions(request: Request):
        """Legacy text completions adapter forwarding as chat completions."""
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        # Normalize completion prompt to chat messages
        if "prompt" in payload and "messages" not in payload:
            prompt_text = payload["prompt"]
            if isinstance(prompt_text, list):
                prompt_text = "\n".join(prompt_text)
            payload["messages"] = [{"role": "user", "content": prompt_text}]

        return await proxy_engine.forward_chat_completion(request, payload)

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        """Unified OpenAI embeddings endpoint."""
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        return await proxy_engine.forward_embeddings(request, payload)

    @app.get("/v1/health")
    async def health():
        online_backends = registry.online()
        metrics = state.get_metrics()
        return {
            "status": "healthy" if online_backends else "degraded",
            "online_backends_count": len(online_backends),
            "total_backends_count": len(registry.all()),
            "active_requests": metrics.active_requests,
            "uptime_seconds": round(metrics.uptime_seconds, 1)
        }

    @app.get("/v1/metrics")
    async def get_metrics():
        return state.get_metrics().model_dump()

    @app.get("/v1/backends")
    async def get_backends():
        data = []
        for b in registry.all():
            keys_info = [
                {
                    "masked_key": k.masked_key,
                    "usage_count": k.usage_count,
                    "failure_count": k.failure_count,
                    "is_active": k.is_active
                }
                for k in b.key_rotator.get_states()
            ]

            data.append({
                "name": b.name,
                "type": b.type.value,
                "base_url": b.base_url,
                "enabled": b.enabled,
                "status": b.status.value,
                "latency_ms": round(b.latency_ms, 1),
                "active_concurrency": b.active_concurrency,
                "max_concurrency": b.max_concurrency,
                "models_count": len(b.models),
                "models": [m.id for m in b.models],
                "keys_count": b.key_rotator.total_keys,
                "keys_states": keys_info,
                "ratelimit_remaining": b.ratelimit_remaining,
                "ratelimit_limit": b.ratelimit_limit,
                "ratelimit_reset_seconds": b.ratelimit_reset_seconds,
                "quota_remaining_str": b.quota_remaining_str,
                "error": b.error_message
            })
        return {"backends": data}

    @app.get("/v1/logs")
    async def get_logs(limit: int = 50):
        return {"logs": [log.model_dump() for log in state.get_recent_logs(limit)]}

    @app.get("/v1/usage")
    async def get_usage(days: int = 30, months: int = 12):
        """Return persistent daily and monthly token/request usage analytics."""
        return state.get_usage_summary(days=days, months=months)

    @app.post("/v1/reload")
    @app.post("/v1/refresh")
    @app.get("/v1/reload")
    @app.get("/v1/refresh")
    async def reload_endpoints(sync: bool = False):
        """Reload configuration, re-discover Hermes backends, probe ports, and refresh all health checks."""
        # 1. Reload config from disk
        try:
            from xenrouter.config import load_config
            new_cfg = load_config()
            config.default_model = new_cfg.default_model
            config.aliases = new_cfg.aliases
            config.fallbacks = new_cfg.fallbacks
            for b_cfg in new_cfg.backends:
                existing = registry.get(b_cfg.name)
                if existing:
                    existing.config = b_cfg
                    existing.base_url = b_cfg.base_url
                    existing.enabled = b_cfg.enabled
                    if b_cfg.api_keys:
                        existing.key_rotator.set_keys(b_cfg.api_keys)
                else:
                    registry.register(b_cfg)
        except Exception:
            pass

        # 2. Re-discover Hermes backends
        if config.import_hermes_providers:
            try:
                from xenrouter.backends.hermes_importer import discover_hermes_backends
                hermes_backends = discover_hermes_backends()
                for h_cfg in hermes_backends:
                    existing = registry.get(h_cfg.name)
                    if existing:
                        existing.config = h_cfg
                        existing.base_url = h_cfg.base_url
                        existing.enabled = h_cfg.enabled
                        if h_cfg.api_keys:
                            existing.key_rotator.set_keys(h_cfg.api_keys)
                    else:
                        registry.register(h_cfg)
            except Exception:
                pass

        async def _run_background_reload():
            try:
                if config.auto_probe_local:
                    discovered = await BackendRegistry.probe_local_ports(client)
                    for item in discovered:
                        if not registry.get(item["name"]):
                            from xenrouter.types import BackendConfig, BackendType
                            new_cfg = BackendConfig(
                                name=item["name"],
                                type=item["type"],
                                base_url=item["base_url"],
                                enabled=True
                            )
                            registry.register(new_cfg)
                await registry.refresh_all(client)
            except Exception:
                pass

        if sync:
            await _run_background_reload()
        else:
            asyncio.create_task(_run_background_reload())

        online_count = len(registry.online())
        total_count = len(registry.all())
        models_count = len(router.get_unified_models_list())

        return {
            "status": "ok",
            "message": "Xenrouter configuration reloaded; provider health refresh in progress.",
            "online_backends_count": online_count,
            "total_backends_count": total_count,
            "models_count": models_count,
            "uptime_seconds": round(state.get_metrics().uptime_seconds, 1)
        }

    return app
