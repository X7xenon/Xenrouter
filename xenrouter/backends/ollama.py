"""
Ollama backend adapter for Xenrouter.
Supports both native Ollama endpoints (/api/tags) and the OpenAI compatibility layer (/v1).
"""

import time
from typing import List
import httpx

from xenrouter.backends.base import BaseBackend
from xenrouter.types import BackendStatus, ModelInfo


class OllamaBackend(BaseBackend):
    """Adapter for Ollama local instances."""

    async def health_check(self, client: httpx.AsyncClient) -> bool:
        start_time = time.perf_counter()
        target_url = f"{self.base_url}/api/version"

        key = self.get_api_key()
        headers = self.build_headers(key)

        try:
            resp = await client.get(target_url, headers=headers, timeout=5.0)
            self.latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.last_checked = time.time()

            if resp.status_code == 200:
                self.status = BackendStatus.ONLINE
                self.error_message = None
                self.report_key_result(key=key, status_code=resp.status_code, is_error=False)
                return True
            else:
                self.status = BackendStatus.DEGRADED
                self.error_message = f"HTTP {resp.status_code}: {resp.text[:100]}"
                self.report_key_result(key=key, status_code=resp.status_code, is_error=True)
                return False

        except Exception as exc:
            self.status = BackendStatus.OFFLINE
            self.error_message = str(exc)
            self.latency_ms = 0.0
            self.last_checked = time.time()
            self.report_key_result(key=key, status_code=500, is_error=True)
            return False

    async def fetch_models(self, client: httpx.AsyncClient) -> List[ModelInfo]:
        target_url = f"{self.base_url}/api/tags"
        key = self.get_api_key()
        headers = self.build_headers(key)

        try:
            resp = await client.get(target_url, headers=headers, timeout=8.0)
            if resp.status_code != 200:
                # Fallback to /v1/models if /api/tags fails
                resp = await client.get(f"{self.base_url}/v1/models", headers=headers, timeout=8.0)
                if resp.status_code != 200:
                    return []

                data = resp.json()
                raw_entries = data.get("data", [])
                models_list = []
                for item in raw_entries:
                    mid = item.get("id")
                    if mid and (not self.models_filter or mid in self.models_filter):
                        models_list.append(ModelInfo(
                            id=mid,
                            backend_name=self.name,
                            backend_type="ollama",
                            owned_by="ollama"
                        ))
                self.models = models_list
                return models_list

            data = resp.json()
            models_list = []
            for item in data.get("models", []):
                model_name = item.get("name") or item.get("model")
                if not model_name:
                    continue

                if self.models_filter and model_name not in self.models_filter:
                    continue

                # Add canonical model name (e.g. qwen2.5-coder:14b)
                models_list.append(
                    ModelInfo(
                        id=model_name,
                        backend_name=self.name,
                        backend_type="ollama",
                        owned_by="ollama"
                    )
                )

                # Also add name without tag if tag is :latest (e.g. llama3 -> llama3:latest)
                if model_name.endswith(":latest"):
                    bare_name = model_name[:-7]
                    if not any(m.id == bare_name for m in models_list):
                        models_list.append(
                            ModelInfo(
                                id=bare_name,
                                backend_name=self.name,
                                backend_type="ollama",
                                owned_by="ollama"
                            )
                        )

            self.models = models_list
            return models_list

        except Exception as exc:
            self.error_message = f"Ollama model fetch failed: {exc}"
            return []
