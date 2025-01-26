import time
from contextlib import contextmanager
from enum import Enum

import redis


class RedisBackend:
    """Redis backend for circuit breaker state storage."""

    def __init__(self, redis_client=None, url=None):
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis.from_url(url or "redis://localhost:6379/0")

    def get(self, key):
        value = self.redis.get(key)
        return value.decode("utf-8") if value else None

    def set(self, key, value):
        self.redis.set(key, value)

    def delete(self, key):
        self.redis.delete(key)


class CircuitState(Enum):
    CLOSED = "closed"  # Circuit is closed, requests flow normally
    OPEN = "open"  # Circuit is open, requests are blocked
    HALF_OPEN = "half_open"  # Testing if service is healthy


class CircuitBreaker:
    """Circuit breaker pattern implementation.

    Parameters:
        backend: Backend to store circuit state and failure counts
        key: Key to identify this circuit breaker
        failure_threshold: Number of failures before opening circuit
        reset_timeout: Seconds to wait before attempting reset (half-open)
        half_open_timeout: Seconds to wait in half-open before closing
    """

    def __init__(
        self, backend, key, failure_threshold=5, reset_timeout=60, half_open_timeout=30
    ):
        self.backend = backend
        self.key = key
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_timeout = half_open_timeout

        # Keys for storing state in backend
        self._state_key = f"{key}:state"
        self._failures_key = f"{key}:failures"
        self._last_failure_key = f"{key}:last_failure"
        self._half_open_start_key = f"{key}:half_open_start"

    def get_state(self):
        """Get current circuit state."""
        state = self.backend.get(self._state_key)
        if not state:
            return CircuitState.CLOSED
        return CircuitState(state)

    def _should_allow_request(self):
        """Determine if request should be allowed based on circuit state."""
        state = self.get_state()

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            # Check if reset timeout has elapsed
            last_failure = float(self.backend.get(self._last_failure_key) or 0)
            if time.time() - last_failure > self.reset_timeout:
                # Transition to half-open
                self.backend.set(self._state_key, CircuitState.HALF_OPEN.value)
                self.backend.set(self._half_open_start_key, str(time.time()))
                return True
            return False

        if state == CircuitState.HALF_OPEN:
            # Only allow one request through in half-open state
            half_open_start = float(self.backend.get(self._half_open_start_key) or 0)
            if time.time() - half_open_start > self.half_open_timeout:
                # If successful for half_open_timeout, close circuit
                self.backend.set(self._state_key, CircuitState.CLOSED.value)
                self.backend.delete(self._failures_key)
                return True
            return True

        return False

    def record_failure(self):
        """Record a failure and potentially open the circuit."""
        failures = int(self.backend.get(self._failures_key) or 0) + 1
        self.backend.set(self._failures_key, str(failures))
        self.backend.set(self._last_failure_key, str(time.time()))

        if failures >= self.failure_threshold:
            self.backend.set(self._state_key, CircuitState.OPEN.value)

    def record_success(self):
        """Record a success and potentially close the circuit."""
        state = self.get_state()
        if state == CircuitState.HALF_OPEN:
            self.backend.set(self._state_key, CircuitState.CLOSED.value)
            self.backend.delete(self._failures_key)

    @contextmanager
    def acquire(self, *, raise_on_failure=True):
        """Attempt to acquire the circuit breaker.

        Parameters:
            raise_on_failure (bool): Whether to raise an exception if circuit is open

        Raises:
            CircuitOpenError: If circuit is open and raise_on_failure is True
        """
        allowed = self._should_allow_request()

        if not allowed and raise_on_failure:
            raise CircuitOpenError(f"Circuit {self.key} is open")

        try:
            yield allowed
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()


class CircuitOpenError(Exception):
    """Raised when attempting to use an open circuit."""

    pass
