from typing import Any, Dict

import dramatiq
import httpx
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage
from prometheus_client import Counter

from main import settings

# Configure Dramatiq with Redis broker
redis_broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(redis_broker)

WEBHOOK_FORWARDS = Counter(
    "webhook_forwards_total",
    "Total number of webhook forwards to target service",
    ["status"],
)


@dramatiq.actor(
    queue_name="webhooks",
    max_retries=settings.max_retries,
    min_backoff=settings.min_backoff,
    max_backoff=settings.max_backoff,
    priority=0,  # Ensure sequential processing
)
def forward_webhook(payload: Dict[str, Any], event_type: str) -> None:
    message = CurrentMessage.get_current_message()

    try:
        # Using httpx in sync mode since Dramatiq workers are already concurrent
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
        raise  # Let Dramatiq handle retries
