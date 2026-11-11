"""
Backend registry and automatic local discovery scanner.
"""

import asyncio
from typing import Dict, List, Optional, Union
import httpx

from xenrouter.backends.base import BaseBackend
from xenrouter.backends.ollama import OllamaBackend
from xenrouter.backends.openai_compatible import OpenAICompatibleBackend
from xenrouter.types import BackendConfig, BackendStatus, BackendType


PROBE_CANDIDATES = [
    {"name": "ollama", "type": BackendType.OLLAMA, "port": 11434, "path": "/api/version"},
    {"name": "lmstudio", "type": BackendType.LMSTUDIO, "port": 1234, "path": "/v1/models"},
    {"name": "llamacpp", "type": BackendType.LLAMACPP, "port": 8080, "path": "/v1/models"},
    {"name": "vllm", "type": BackendType.VLLM, "port": 8000, "path": "/v1/models"},
    {"name": "koboldcpp", "type": BackendType.KOBOLDCPP, "port": 5001, "path": "/v1/models"},
]


class BackendRegistry:
    """Manages active backend instances and periodic health evaluations."""

    def __init__(self):
        self._backends: Dict[str, BaseBackend] = {}

    def create_backend(self, config: BackendConfig) -> BaseBackend:
        """Instantiate appropriate adapter for config."""
        if config.type == BackendType.OLLAMA:
            return OllamaBackend(config)
        return OpenAICompatibleBackend(config)

    def register(self, config_or_backend: Union[BackendConfig, BaseBackend]) -> BaseBackend:
        """Register or update a backend."""
        if isinstance(config_or_backend, BaseBackend):
            self._backends[config_or_backend.name] = config_or_backend
            return config_or_backend
        backend = self.create_backend(config_or_backend)
        self._backends[config_or_backend.name] = backend
        return backend

    def get(self, name: str) -> Optional[BaseBackend]:
        """Fetch backend by name."""
        return self._backends.get(name)

    def all(self) -> List[BaseBackend]:
        """List all registered backends."""
        return list(self._backends.values())

    def online(self) -> List[BaseBackend]:
        """List all operational backends."""
        return [b for b in self._backends.values() if b.status == BackendStatus.ONLINE and b.enabled]

    async def check_backend(self, backend: BaseBackend, client: httpx.AsyncClient) -> None:
        """Perform health check and retrieve models for one backend."""
        is_up = await backend.health_check(client)
        if is_up:
            await backend.fetch_models(client)

    async def refresh_all(self, client: httpx.AsyncClient) -> None:
        """Health check all registered backends concurrently."""
        tasks = [self.check_backend(b, client) for b in self._backends.values() if b.enabled]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def probe_local_ports(client: httpx.AsyncClient, host: str = "127.0.0.1") -> List[dict]:
        """Scan standard local inference ports to discover active engines."""
        discovered = []

        async def test_port(candidate: dict):
            url = f"http://{host}:{candidate['port']}{candidate['path']}"
            try:
                resp = await client.get(url, timeout=1.5)
                if resp.status_code in [200, 401]:
                    discovered.append({
                        "name": candidate["name"],
                        "type": candidate["type"],
                        "base_url": f"http://{host}:{candidate['port']}",
                        "status": "ONLINE" if resp.status_code == 200 else "AUTH_REQUIRED",
                        "port": candidate["port"]
                    })
            except Exception:
                pass

        await asyncio.gather(*[test_port(c) for c in PROBE_CANDIDATES], return_exceptions=True)
        return discovered
