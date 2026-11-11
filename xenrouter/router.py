"""
Intelligent routing engine for local inference.
Handles prefix routing, virtual aliases, load balancing, and failover cascades.
"""

from typing import Dict, List, Optional, Tuple
from xenrouter.backends.base import BaseBackend
from xenrouter.backends.registry import BackendRegistry
from xenrouter.config import XenrouterConfig
from xenrouter.types import AliasConfig, LoadBalanceStrategy, ModelInfo


class RouteTarget:
    """Represents a resolved backend and model target."""

    def __init__(self, backend: BaseBackend, model_id: str, is_fallback: bool = False):
        self.backend = backend
        self.model_id = model_id
        self.is_fallback = is_fallback

    def __repr__(self) -> str:
        return f"<RouteTarget backend={self.backend.name} model={self.model_id} fallback={self.is_fallback}>"


class Router:
    """Core routing engine that resolves requested model names to operational backends."""

    def __init__(self, config: XenrouterConfig, registry: BackendRegistry):
        self.config = config
        self.registry = registry
        self._round_robin_indices: Dict[str, int] = {}

    def _resolve_alias(self, alias_name: str, depth: int = 0) -> List[str]:
        """Recursively resolve virtual alias to a flat list of candidate model names."""
        if depth > 5:
            return []
        if alias_name not in self.config.aliases:
            return [alias_name]

        alias_cfg = self.config.aliases[alias_name]
        candidates = []
        for target in alias_cfg.targets:
            if target in self.config.aliases:
                candidates.extend(self._resolve_alias(target, depth + 1))
            else:
                candidates.append(target)
        return candidates

    def _select_backend_for_model(self, model_id: str) -> Optional[BaseBackend]:
        """Find operational backends hosting this model and apply load balancing."""
        matching_backends: List[BaseBackend] = []
        target_norm = model_id.lower().strip()
        target_bare = target_norm.split("/")[-1]

        # 1. Check online backends first
        online_candidates = self.registry.online()
        # Fall back to all enabled backends if none marked ONLINE yet
        pool = online_candidates if online_candidates else [b for b in self.registry.all() if b.enabled]

        # Exact match check
        for backend in pool:
            for m in backend.models:
                m_norm = m.id.lower().strip()
                if m_norm == target_norm:
                    matching_backends.append(backend)
                    break

        # Fuzzy / bare name match (e.g. deepseek-v4.1-flash matching deepseek-ai/deepseek-v4.1-flash)
        if not matching_backends:
            for backend in pool:
                for m in backend.models:
                    m_bare = m.id.lower().strip().split("/")[-1]
                    if m_bare == target_bare:
                        matching_backends.append(backend)
                        break

        if not matching_backends:
            return None

        # Filter to backends that have available concurrency slots
        available = [b for b in matching_backends if b.is_available()]
        candidates = available if available else matching_backends

        # Sort by priority first (lower number = higher priority), then active concurrency
        candidates.sort(key=lambda b: (b.priority, b.active_concurrency))

        return candidates[0]

    def resolve_routes(self, requested_model: Optional[str]) -> List[RouteTarget]:
        """
        Build an ordered cascade of RouteTargets for a requested model.
        Supports explicit provider routing (e.g. 'nvidia/moonshotai/kimi-k3'),
        virtual aliases, Hermes 'auto' model routing, and direct model matching.
        """
        routes: List[RouteTarget] = []

        # Handle 'auto', None, or empty model requests
        if not requested_model:
            requested_model = "auto" if "auto" in self.config.aliases else (self.config.default_model or "coding")
        elif requested_model.lower() == "auto":
            requested_model = "auto" if "auto" in self.config.aliases else (self.config.default_model or "coding")

        # 1. Explicit provider routing: "<provider_name>/<model_id>"
        # e.g. "nvidia/moonshotai/kimi-k3" or "ollama/qwen2.5:7b"
        if "/" in requested_model and requested_model not in self.config.aliases:
            prefix, bare_model = requested_model.split("/", 1)
            target_backend = self.registry.get(prefix.lower())
            if target_backend and target_backend.enabled:
                routes.append(RouteTarget(backend=target_backend, model_id=bare_model, is_fallback=False))
                return routes

        # Direct provider selection: e.g. "xkiro", "wusrouter", "iteracompute", "apinex"
        provider_backend = self.registry.get(requested_model.lower().strip())
        if provider_backend and provider_backend.enabled and requested_model not in self.config.aliases:
            from xenrouter.limits import resolve_provider_best_model
            best_m = resolve_provider_best_model(provider_backend.name)
            chosen_m = None
            if best_m:
                for bm in provider_backend.models:
                    if bm.id.lower() == best_m.lower() or bm.id.split('/')[-1].lower() == best_m.split('/')[-1].lower():
                        chosen_m = bm.id
                        break
            if not chosen_m and provider_backend.models:
                chosen_m = provider_backend.models[0].id
            elif not chosen_m and best_m:
                chosen_m = best_m
            if chosen_m:
                routes.append(RouteTarget(backend=provider_backend, model_id=chosen_m, is_fallback=False))
                return routes

        # 2. Virtual alias expansion
        candidate_models = self._resolve_alias(requested_model)
        for cand in candidate_models:
            chosen_backend = None
            clean_model_id = cand

            # A. Check for explicit provider prefix: e.g. "iteracompute/qwen/qwen3.8-27b", "wusrouter/qwen3.8-flash:free"
            for b in self.registry.all():
                if b.enabled and cand.lower().startswith(f"{b.name.lower()}/"):
                    chosen_backend = b
                    clean_model_id = cand[len(b.name) + 1:]
                    break

            # B. Check if candidate is directly a provider name: e.g. "xkiro", "iteracompute"
            if not chosen_backend:
                p_backend = self.registry.get(cand.lower().strip())
                if p_backend and p_backend.enabled:
                    chosen_backend = p_backend
                    from xenrouter.limits import resolve_provider_best_model
                    best_m = resolve_provider_best_model(p_backend.name)
                    clean_model_id = best_m or (p_backend.models[0].id if p_backend.models else cand)

            # C. Look up backend hosting this model
            if not chosen_backend:
                chosen_backend = self._select_backend_for_model(cand)
                clean_model_id = cand

            if chosen_backend:
                if not any(r.backend.name == chosen_backend.name and r.model_id == clean_model_id for r in routes):
                    routes.append(RouteTarget(backend=chosen_backend, model_id=clean_model_id, is_fallback=False))

        # 3. Direct model match (if not already handled)
        if not routes:
            backend = self._select_backend_for_model(requested_model)
            if backend:
                routes.append(RouteTarget(backend=backend, model_id=requested_model, is_fallback=False))

        # 4. Custom fallback chains
        if requested_model in self.config.fallbacks:
            for fallback_name in self.config.fallbacks[requested_model]:
                f_backend = self._select_backend_for_model(fallback_name)
                if f_backend:
                    routes.append(RouteTarget(backend=f_backend, model_id=fallback_name, is_fallback=True))

        # 5. Default model fallback
        if not routes and self.config.default_model and self.config.default_model != requested_model:
            default_candidates = self._resolve_alias(self.config.default_model)
            for d_model in default_candidates:
                d_backend = self._select_backend_for_model(d_model)
                if d_backend:
                    routes.append(RouteTarget(backend=d_backend, model_id=d_model, is_fallback=True))

        # 6. Safety fallback: Any online model on any online backend
        if not routes:
            for b in self.registry.online():
                if b.models:
                    routes.append(RouteTarget(backend=b, model_id=b.models[0].id, is_fallback=True))
                    break

        return routes

    def get_unified_models_list(self) -> List[dict]:
        """Aggregate all available models from active backends plus configured aliases."""
        unified: List[dict] = []
        seen_ids = set()

        # Always place 'auto' as the premier model listed for Hermes Agent and OpenAI clients
        auto_target = self.config.default_model or "coding"
        unified.append({
            "id": "auto",
            "object": "model",
            "created": 1700000000,
            "owned_by": "xenrouter-auto",
            "permission": [],
            "root": auto_target,
            "parent": None,
            "description": "Hermes Agent automatic model router (auto-selects frontier online model)"
        })
        seen_ids.add("auto")

        # Add models from operational backends (or all enabled backends if initializing)
        pool = self.registry.online()
        if not pool:
            pool = [b for b in self.registry.all() if b.enabled]

        for backend in pool:
            for m in backend.models:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    unified.append({
                        "id": m.id,
                        "object": "model",
                        "created": m.created,
                        "owned_by": m.owned_by,
                        "permission": [],
                        "root": m.id,
                        "parent": None,
                        "backend": backend.name
                    })

                # Also provide namespaced variant: "backend_name/model_name"
                prefixed_id = f"{backend.name}/{m.id}"
                if prefixed_id not in seen_ids:
                    seen_ids.add(prefixed_id)
                    unified.append({
                        "id": prefixed_id,
                        "object": "model",
                        "created": m.created,
                        "owned_by": backend.name,
                        "permission": [],
                        "root": m.id,
                        "parent": None,
                        "backend": backend.name
                    })

        # Add virtual aliases
        for alias_name, alias_cfg in self.config.aliases.items():
            if alias_name not in seen_ids:
                seen_ids.add(alias_name)
                unified.append({
                    "id": alias_name,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "xenrouter-alias",
                    "permission": [],
                    "root": alias_cfg.targets[0] if alias_cfg.targets else alias_name,
                    "description": alias_cfg.description or f"Virtual alias routing to {alias_cfg.targets}"
                })

        return unified
