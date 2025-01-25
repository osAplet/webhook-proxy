import hmac
import hashlib
import json
from fastapi import FastAPI, Request, HTTPException, Response
from pydantic_settings import BaseSettings
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST


class Settings(BaseSettings):
    github_webhook_secret: str


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

        payload = json.loads(payload_body)
        print(json.dumps(payload, indent=2))

        WEBHOOK_SUBMISSIONS.labels(status="success", event_type=event_type).inc()
        return {"status": "success"}
    except json.JSONDecodeError:
        WEBHOOK_SUBMISSIONS.labels(status="invalid_json", event_type=event_type).inc()
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception:
        WEBHOOK_SUBMISSIONS.labels(status="error", event_type=event_type).inc()
        raise


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
