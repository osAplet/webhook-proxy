import hashlib
import hmac
import json
from typing import Any, Dict

import dramatiq
import httpx
import sentry_sdk
from dramatiq.brokers.redis import RedisBroker
from prometheus_client import Counter
from sentry_sdk.integrations.dramatiq import DramatiqIntegration

from circuit_breaker import CircuitBreaker, RedisBackend
from main import settings

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[DramatiqIntegration()],
    )

redis_broker = RedisBroker(url=settings.redis_url)
dramatiq.set_broker(redis_broker)

redis_backend = RedisBackend(url=settings.redis_url)
target_circuit = CircuitBreaker(
    backend=redis_backend,
    key="target-service",
    failure_threshold=10,
    reset_timeout=120,
    half_open_timeout=60,
)

WEBHOOK_FORWARDS = Counter(
    "webhook_forwards_total",
    "Total number of webhook forwards to target service",
    ["status"],
)


@dramatiq.actor(priority=0)
def update_ci_status(repo: str, sha: str) -> None:
    try:
        with httpx.Client() as client:
            response = client.post(
                f"https://api.github.com/repos/{repo}/statuses/{sha}",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "Authorization": f"token {settings.github_token}",
                },
                json={
                    "state": "pending",
                    "context": "builds/x86_64",
                    "description": "Build pending",
                },
                timeout=10.0,
            )
            response.raise_for_status()
    except Exception as e:
        sentry_sdk.set_context(
            "github_api", {"repo": repo, "sha": sha, "operation": "update_ci_status"}
        )
        print(f"Error updating CI status: {str(e)}")
        raise


@dramatiq.actor(priority=10)
def forward_webhook(payload: Dict[str, Any], event_type: str) -> None:
    try:
        with target_circuit.acquire():
            circuit_state = target_circuit.get_state()
            if circuit_state == "half-open":
                print(
                    "Circuit breaker in half-open state for "
                    f"{settings.target_service_url}, attempting recovery"
                )
                sentry_sdk.set_context(
                    "circuit_breaker",
                    {
                        "state": "half-open",
                        "target_url": settings.target_service_url,
                        "event_type": event_type,
                    },
                )

            payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
            signature_sha1 = hmac.new(
                settings.target_service_secret.encode("utf-8"),
                payload_bytes,
                hashlib.sha1,
            ).hexdigest()

            signature_sha256 = hmac.new(
                settings.target_service_secret.encode("utf-8"),
                payload_bytes,
                hashlib.sha256,
            ).hexdigest()

            with httpx.Client() as client:
                response = client.post(
                    settings.target_service_url,
                    json=payload,
                    headers={
                        "X-GitHub-Event": event_type,
                        "X-Hub-Signature": f"sha1={signature_sha1}",
                        "X-Hub-Signature-256": f"sha256={signature_sha256}",
                    },
                    timeout=30.0,
                )
                print(f"Target service response: {response.status_code} - {response.text}")
                response.raise_for_status()
                WEBHOOK_FORWARDS.labels(status="success").inc()

    except Exception as e:
        WEBHOOK_FORWARDS.labels(status="error").inc()
        sentry_sdk.set_context(
            "webhook_forward",
            {
                "event_type": event_type,
                "target_url": settings.target_service_url,
                "circuit_breaker_state": target_circuit.get_state(),
                "payload_size": len(json.dumps(payload)),
            },
        )
        print(f"Error forwarding webhook: {str(e)}")
        raise
