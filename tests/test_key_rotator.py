"""
Tests for API Key Rotator.
"""

import time
import pytest
from xenrouter.key_rotator import KeyRotator, mask_key
from xenrouter.types import KeyRotationStrategy


def test_mask_key():
    assert mask_key("sk-1234567890abcdef") == "sk-1...cdef"
    assert mask_key("short") == "****"
    assert mask_key("") == "None"


def test_round_robin_rotation():
    keys = ["key-alpha", "key-beta", "key-gamma"]
    rotator = KeyRotator("test_backend", keys, strategy=KeyRotationStrategy.ROUND_ROBIN)

    assert rotator.total_keys == 3
    assert rotator.has_keys()

    k1 = rotator.get_next_key()
    k2 = rotator.get_next_key()
    k3 = rotator.get_next_key()
    k4 = rotator.get_next_key()

    assert [k1, k2, k3, k4] == ["key-beta", "key-gamma", "key-alpha", "key-beta"]


def test_failover_strategy():
    keys = ["primary-key", "secondary-key"]
    rotator = KeyRotator("test_backend", keys, strategy=KeyRotationStrategy.FAILOVER)

    assert rotator.get_next_key() == "primary-key"
    assert rotator.get_next_key() == "primary-key"


def test_cooldown_on_rate_limit():
    keys = ["key-1", "key-2"]
    rotator = KeyRotator("test_backend", keys, strategy=KeyRotationStrategy.FAILOVER, cooldown_seconds=10.0)

    # First call yields primary key
    key = rotator.get_next_key()
    assert key == "key-1"

    # Report HTTP 429 Rate Limit
    rotator.report_result("key-1", status_code=429, is_error=True)

    # Next call should fail over to key-2 because key-1 is in cooldown
    next_key = rotator.get_next_key()
    assert next_key == "key-2"

    states = rotator.get_states()
    key1_state = next(s for s in states if s.key == "key-1")
    assert key1_state.failure_count == 1
    assert key1_state.is_active is False
