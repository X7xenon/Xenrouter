"""
Standard OpenAI-compatible inference backend adapter.
Covers LM Studio, llama.cpp / llama-server, vLLM, KoboldCPP, and LocalAI.
"""

import time
from typing import List
import httpx

from xenrouter.backends.base import BaseBackend
from xenrouter.types import BackendStatus, ModelInfo


class OpenAICompatibleBackend(BaseBackend):
    """Adapter for any engine exposing standard /v1 OpenAI API contracts."""

    async def health_check(self, client: httpx.AsyncClient) -> bool:
        start_time = time.perf_counter()
        target_url = f"{self.base_url}/v1/models"
        
        # Some servers don't require /v1 prefix in base_url if already included
        if self.base_url.endswith("/v1"):
            target_url = f"{self.base_url}/models"

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
        target_url = f"{self.base_url}/v1/models"
        if self.base_url.endswith("/v1"):
            target_url = f"{self.base_url}/models"

        key = self.get_api_key()
        headers = self.build_headers(key)

        try:
            resp = await client.get(target_url, headers=headers, timeout=8.0)
            if resp.status_code != 200:
                return self.models

            data = resp.json()
            models_list: List[ModelInfo] = []
            raw_entries = data.get("data", [])

            for item in raw_entries:
                model_id = item.get("id") or item.get("name")
                if not model_id:
                    continue

                if self.models_filter and model_id not in self.models_filter:
                    continue

                models_list.append(
                    ModelInfo(
                        id=model_id,
                        backend_name=self.name,
                        backend_type=str(self.type.value),
                        owned_by=item.get("owned_by", f"provider-{self.name}"),
                        created=item.get("created", int(time.time()))
                    )
                )

            if models_list:
                self.models = models_list
            return self.models

        except Exception as exc:
            self.error_message = f"Model fetch error: {exc}"
            return self.models
