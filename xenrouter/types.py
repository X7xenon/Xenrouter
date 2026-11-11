"""
Data types and schemas for Xenrouter.
Includes local inference backends, routing strategies, API key rotation, and metrics.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BackendType(str, Enum):
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    LLAMACPP = "llamacpp"
    VLLM = "vllm"
    KOBOLDCPP = "koboldcpp"
    OPENAI_COMPATIBLE = "openai_compatible"


class BackendStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class KeyRotationStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    FAILOVER = "failover"


class LoadBalanceStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    PRIORITY = "priority"


class BackendConfig(BaseModel):
    name: str = Field(..., description="Unique backend identifier")
    type: BackendType = Field(default=BackendType.OPENAI_COMPATIBLE, description="Engine type")
    base_url: str = Field(..., description="Root HTTP endpoint for the backend (e.g. http://127.0.0.1:11434)")
    api_key: Optional[str] = Field(default=None, description="Single API key (deprecated in favor of api_keys)")
    api_keys: List[str] = Field(default_factory=list, description="Pool of API keys for automatic rotation")
    key_rotation_strategy: KeyRotationStrategy = Field(
        default=KeyRotationStrategy.ROUND_ROBIN,
        description="Key rotation strategy: round_robin, random, or failover"
    )
    key_cooldown_seconds: float = Field(
        default=60.0,
        description="Cooldown duration when an API key receives rate limit or auth error"
    )
    enabled: bool = Field(default=True, description="Whether this backend is active")
    priority: int = Field(default=1, description="Priority rank (1 is highest)")
    timeout: float = Field(default=120.0, description="Request timeout in seconds")
    max_concurrency: int = Field(default=4, description="Max concurrent requests allowed to this backend")
    weight: int = Field(default=1, description="Weight for load balancing algorithms")
    models_filter: Optional[List[str]] = Field(default=None, description="Allowed models list; if None, exposes all")


class AliasConfig(BaseModel):
    targets: List[str] = Field(..., description="Target model identifiers in cascade priority order")
    description: Optional[str] = Field(default=None, description="Explanation of virtual alias intent")
    strategy: LoadBalanceStrategy = Field(default=LoadBalanceStrategy.PRIORITY, description="Routing strategy")


class ModelInfo(BaseModel):
    id: str
    backend_name: str
    backend_type: str
    owned_by: str = "xenrouter-local"
    context_length: Optional[int] = None
    created: int = 1700000000


class KeyState(BaseModel):
    key: str
    masked_key: str
    usage_count: int = 0
    failure_count: int = 0
    cooldown_until: float = 0.0
    is_active: bool = True


class RequestLog(BaseModel):
    id: str
    timestamp: float
    client_ip: str
    model_requested: str
    resolved_model: str
    backend_used: str
    path: str
    status_code: int = 0
    duration_ms: float = 0.0
    ttft_ms: Optional[float] = None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_per_sec: float = 0.0
    streaming: bool = False
    key_used_masked: Optional[str] = None
    error: Optional[str] = None


class ServerMetrics(BaseModel):
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    active_requests: int = 0
    uptime_seconds: float = 0.0
    provider_tokens: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    model_tokens: Dict[str, Dict[str, int]] = Field(default_factory=dict)
