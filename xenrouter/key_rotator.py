"""
Intelligent API Key rotation, cooldown, and health tracking module.
Supports round-robin, random, and failover key distribution.
"""

import random
import time
from typing import Dict, List, Optional
from xenrouter.types import KeyRotationStrategy, KeyState


def mask_key(key: str) -> str:
    """Mask key for safe logging and UI display."""
    if not key:
        return "None"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


class KeyRotator:
    """Manages an active pool of API keys with rotation and cooldown semantics."""

    def __init__(
        self,
        backend_name: str,
        keys: List[str],
        strategy: KeyRotationStrategy = KeyRotationStrategy.ROUND_ROBIN,
        cooldown_seconds: float = 60.0
    ):
        self.backend_name = backend_name
        self.strategy = strategy
        self.cooldown_seconds = cooldown_seconds
        self._index = 0

        self._states: Dict[str, KeyState] = {}
        for k in keys:
            clean_k = k.strip()
            if clean_k and clean_k not in self._states:
                self._states[clean_k] = KeyState(
                    key=clean_k,
                    masked_key=mask_key(clean_k),
                    usage_count=0,
                    failure_count=0,
                    cooldown_until=0.0,
                    is_active=True
                )

    @property
    def total_keys(self) -> int:
        return len(self._states)

    def has_keys(self) -> bool:
        return len(self._states) > 0

    def get_next_key(self) -> Optional[str]:
        """Retrieve next operational API key according to configured strategy."""
        if not self._states:
            return None

        keys = list(self._states.keys())
        now = time.time()

        # Identify operational keys (not currently cooling down)
        available_keys = [k for k in keys if now >= self._states[k].cooldown_until]

        # If all keys are in cooldown, pick the one expiring soonest
        if not available_keys:
            sorted_by_cooldown = sorted(keys, key=lambda k: self._states[k].cooldown_until)
            selected_key = sorted_by_cooldown[0]
        else:
            if self.strategy == KeyRotationStrategy.RANDOM:
                selected_key = random.choice(available_keys)
            elif self.strategy == KeyRotationStrategy.FAILOVER:
                # Primary key is always preferred until degraded
                selected_key = available_keys[0]
            else:
                # Default ROUND_ROBIN
                self._index = (self._index + 1) % len(available_keys)
                selected_key = available_keys[self._index]

        # Record usage
        self._states[selected_key].usage_count += 1
        return selected_key

    def report_result(self, key: Optional[str], status_code: int, is_error: bool = False) -> None:
        """Report execution outcome to adjust key health and cooldown."""
        if not key or key not in self._states:
            return

        state = self._states[key]
        now = time.time()

        # Rate-limiting (429) or Authentication failure (401, 403)
        if status_code in [401, 403, 429] or is_error:
            state.failure_count += 1
            # Exponential backoff multiplier if consecutive failures
            multiplier = min(state.failure_count, 5)
            state.cooldown_until = now + (self.cooldown_seconds * multiplier)
        else:
            if state.failure_count > 0:
                state.failure_count = max(0, state.failure_count - 1)

    def get_states(self) -> List[KeyState]:
        """Return snapshot of all key states."""
        now = time.time()
        result = []
        for state in self._states.values():
            state_copy = state.model_copy()
            state_copy.is_active = (now >= state.cooldown_until)
            result.append(state_copy)
        return result
