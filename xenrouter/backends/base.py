"""
Base class definition for all local inference engine backends.
"""

import abc
import asyncio
import time
from typing import List, Optional
import httpx

from xenrouter.types import BackendConfig, BackendStatus, ModelInfo
from xenrouter.key_rotator import KeyRotator


class BaseBackend(abc.ABC):
    """Abstract interface for local inference backends."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self.name = config.name
        self.type = config.type
        self.base_url = config.base_url.rstrip("/")
        self.enabled = config.enabled
        self.priority = config.priority
        self.timeout = config.timeout
        self.max_concurrency = config.max_concurrency
        self.weight = config.weight
        self.models_filter = set(config.models_filter) if config.models_filter else None

        # Assemble keys pool
        keys = list(config.api_keys)
        if config.api_key and config.api_key not in keys:
            keys.insert(0, config.api_key)

        self.key_rotator = KeyRotator(
            backend_name=self.name,
            keys=keys,
            strategy=config.key_rotation_strategy,
            cooldown_seconds=config.key_cooldown_seconds
        )

        self.status = BackendStatus.UNKNOWN
        self.latency_ms = 0.0
        self.active_concurrency = 0
        self.models: List[ModelInfo] = []
        if config.models_filter:
            self.models = [
                ModelInfo(
                    id=m,
                    backend_name=self.name,
                    backend_type=str(self.type.value),
                    owned_by=self.name,
                    created=int(time.time())
                )
                for m in config.models_filter
            ]
        self.last_checked: float = 0.0
        self.error_message: Optional[str] = None
        self.ratelimit_remaining: Optional[int] = None
        self.ratelimit_limit: Optional[int] = None
        self.ratelimit_reset_seconds: Optional[float] = None
        self.quota_remaining_str: Optional[str] = None
        self._lock = asyncio.Lock()

    def update_quota_from_headers(self, headers: dict) -> None:
        """Parse rate limit and quota information from HTTP response headers."""
        for k, v in headers.items():
            k_low = k.lower()
            if k_low in ["x-ratelimit-remaining-requests", "x-ratelimit-remaining", "ratelimit-remaining"]:
                try:
                    self.ratelimit_remaining = int(v)
                except ValueError:
                    self.quota_remaining_str = v
            elif k_low in ["x-ratelimit-limit-requests", "x-ratelimit-limit", "ratelimit-limit"]:
                try:
                    self.ratelimit_limit = int(v)
                except ValueError:
                    pass
            elif k_low in ["x-ratelimit-reset-requests", "x-ratelimit-reset", "retry-after"]:
                try:
                    self.ratelimit_reset_seconds = float(v)
                except ValueError:
                    pass

    def get_api_key(self) -> Optional[str]:
        """Obtain the next operational API key from the rotator."""
        return self.key_rotator.get_next_key()

    def report_key_result(self, key: Optional[str], status_code: int, is_error: bool = False) -> None:
        """Report execution outcome to the rotator."""
        self.key_rotator.report_result(key=key, status_code=status_code, is_error=is_error)

    def is_available(self) -> bool:
        """Check if backend is enabled, online, and under concurrency ceiling."""
        if not self.enabled:
            return False
        if self.status != BackendStatus.ONLINE:
            return False
        if self.active_concurrency >= self.max_concurrency:
            return False
        return True

    def acquire_slot(self) -> bool:
        """Attempt to claim a concurrency slot."""
        if self.active_concurrency >= self.max_concurrency:
            return False
        self.active_concurrency += 1
        return True

    def release_slot(self) -> None:
        """Release an active concurrency slot."""
        self.active_concurrency = max(0, self.active_concurrency - 1)

    @abc.abstractmethod
    async def health_check(self, client: httpx.AsyncClient) -> bool:
        """Ping backend, record latency, and update status."""
        pass

    @abc.abstractmethod
    async def fetch_models(self, client: httpx.AsyncClient) -> List[ModelInfo]:
        """Query backend to retrieve list of active models."""
        pass

    def build_headers(self, key: Optional[str] = None) -> dict:
        """Generate HTTP headers including auth if key present."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Xenrouter/0.1.0",
            "Accept-Encoding": "identity"
        }
        active_key = key or self.get_api_key()
        if active_key:
            headers["Authorization"] = f"Bearer {active_key}"
        return headers
