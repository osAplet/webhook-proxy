import hashlib
import hmac
from datetime import datetime

import orjson
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_webhook_secret: str
    redis_url: str = "redis://localhost:6379/0"
    target_service_url: str
    target_service_secret: str


settings = Settings()
app = FastAPI()

WEBHOOK_SUBMISSIONS = Counter(
    "webhook_github_submissions_total",
    "Total number of GitHub webhook submissions",
    ["status", "event_type"],
)


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False

    expected_signature = hmac.new(
        settings.github_webhook_secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()

    received_signature = signature_header.replace("sha256=", "")

    return hmac.compare_digest(expected_signature, received_signature)


@app.post("/webhook/github")
async def webhook_github(request: Request):
    try:
        event_type = request.headers.get("X-GitHub-Event", "unknown")

        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            WEBHOOK_SUBMISSIONS.labels(
                status="missing_signature", event_type=event_type
            ).inc()
            raise HTTPException(
                status_code=400, detail="X-Hub-Signature-256 header is missing"
            )

        payload_body = await request.body()

        if not verify_signature(payload_body, signature):
            WEBHOOK_SUBMISSIONS.labels(
                status="invalid_signature", event_type=event_type
            ).inc()
            raise HTTPException(status_code=401, detail="Invalid signature")

        payload = orjson.loads(payload_body)

        # Import here to avoid circular imports
        from worker import forward_webhook

        webhook_data = {
            "payload": payload,
            "event_type": event_type,
            "received_at": datetime.utcnow().isoformat(),
        }
        forward_webhook.send(webhook_data["payload"], webhook_data["event_type"])

        WEBHOOK_SUBMISSIONS.labels(status="success", event_type=event_type).inc()
        return {"status": "queued"}
    except orjson.JSONDecodeError as err:
        WEBHOOK_SUBMISSIONS.labels(status="invalid_json", event_type=event_type).inc()
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err
    except Exception as err:
        WEBHOOK_SUBMISSIONS.labels(status="error", event_type=event_type).inc()
        raise err from err


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/status", include_in_schema=False)
async def status():
    return {"status": "ok"}
