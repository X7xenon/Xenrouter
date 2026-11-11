"""
Shared global runtime state, request tracking, and metrics collector.
"""

from collections import deque
from pathlib import Path
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Union
from xenrouter.config import XenrouterConfig
from xenrouter.types import RequestLog, ServerMetrics
from xenrouter.usage import UsageTracker


class AppState:
    """Thread-safe global state for metrics, live request queue, and config."""

    def __init__(self, config: XenrouterConfig, usage_db_path: Optional[Union[str, Path]] = None):
        self.config = config
        self.start_time = time.time()
        self._lock = threading.Lock()
        self.recent_logs: Deque[RequestLog] = deque(maxlen=config.max_history_logs)
        self.usage_tracker = UsageTracker(db_path=usage_db_path)

        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.active_requests = 0
        self.provider_tokens: Dict[str, Dict[str, int]] = {}
        self.model_tokens: Dict[str, Dict[str, int]] = {}

    def record_request_start(self) -> None:
        with self._lock:
            self.total_requests += 1
            self.active_requests += 1

    @staticmethod
    def _accumulate_bucket(
        buckets: Dict[str, Dict[str, int]],
        key: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        if not key:
            return
        entry = buckets.setdefault(key, {"prompt": 0, "completion": 0, "total": 0, "requests": 0})
        entry["prompt"] += prompt_tokens
        entry["completion"] += completion_tokens
        entry["total"] += prompt_tokens + completion_tokens
        entry["requests"] += 1

    def record_request_end(
        self,
        success: bool,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> None:
        with self._lock:
            self.active_requests = max(0, self.active_requests - 1)
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens

            self._accumulate_bucket(self.provider_tokens, provider, prompt_tokens, completion_tokens)
            self._accumulate_bucket(self.model_tokens, model, prompt_tokens, completion_tokens)

        try:
            self.usage_tracker.record(
                success=success,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                provider=provider,
                model=model,
            )
        except Exception:
            pass

    def get_usage_summary(self, days: int = 30, months: int = 12) -> Dict[str, Any]:
        """Return persistent daily and monthly usage summary enriched with session stats."""
        summary = self.usage_tracker.get_summary(days=days, months=months)
        metrics = self.get_metrics()
        summary["session"] = {
            "requests": metrics.total_requests,
            "successful": metrics.successful_requests,
            "failed": metrics.failed_requests,
            "prompt_tokens": metrics.total_prompt_tokens,
            "completion_tokens": metrics.total_completion_tokens,
            "total_tokens": metrics.total_tokens,
            "uptime_seconds": round(metrics.uptime_seconds, 1),
        }
        return summary

    def add_log(self, log: RequestLog) -> None:
        with self._lock:
            self.recent_logs.appendleft(log)

    def get_recent_logs(self, limit: int = 50) -> List[RequestLog]:
        with self._lock:
            return list(self.recent_logs)[:limit]

    def get_metrics(self) -> ServerMetrics:
        with self._lock:
            now = time.time()
            return ServerMetrics(
                total_requests=self.total_requests,
                successful_requests=self.successful_requests,
                failed_requests=self.failed_requests,
                total_prompt_tokens=self.total_prompt_tokens,
                total_completion_tokens=self.total_completion_tokens,
                total_tokens=self.total_prompt_tokens + self.total_completion_tokens,
                active_requests=self.active_requests,
                uptime_seconds=now - self.start_time,
                provider_tokens={p: dict(v) for p, v in self.provider_tokens.items()},
                model_tokens={m: dict(v) for m, v in self.model_tokens.items()}
            )
