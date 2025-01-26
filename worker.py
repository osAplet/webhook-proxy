from typing import Any, Dict

import dramatiq
import httpx
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage
from prometheus_client import Counter

from circuit_breaker import CircuitBreaker, RedisBackend
from main import settings

redis_broker = RedisBroker(url=settings.redis_url)
redis_broker.add_middleware(CurrentMessage())
dramatiq.set_broker(redis_broker)

redis_backend = RedisBackend(url=settings.redis_url)
target_circuit = CircuitBreaker(
    backend=redis_backend,
    key="target-service",
    failure_threshold=5,
    reset_timeout=60,
    half_open_timeout=30,
)

WEBHOOK_FORWARDS = Counter(
    "webhook_forwards_total",
    "Total number of webhook forwards to target service",
    ["status"],
)


@dramatiq.actor
def forward_webhook(payload: Dict[str, Any], event_type: str) -> None:
    message = CurrentMessage.get_current_message()

    try:
        with target_circuit.acquire():
            with httpx.Client() as client:
                response = client.post(
                    settings.target_service_url,
                    json=payload,
                    headers={"X-GitHub-Event": event_type},
                    timeout=30.0,
                )
                response.raise_for_status()
                WEBHOOK_FORWARDS.labels(status="success").inc()

    except Exception as e:
        WEBHOOK_FORWARDS.labels(status="error").inc()
        print(f"Error forwarding webhook (attempt {message.retries}): {str(e)}")
        raise
