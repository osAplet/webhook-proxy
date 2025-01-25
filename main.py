import hashlib
import hmac

import orjson
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic_settings import BaseSettings


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

        payload = orjson.loads(payload_body)
        print(orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode('utf-8'))

        WEBHOOK_SUBMISSIONS.labels(status="success", event_type=event_type).inc()
        return {"status": "success"}
    except orjson.JSONDecodeError as err:
        WEBHOOK_SUBMISSIONS.labels(status="invalid_json", event_type=event_type).inc()
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err
    except Exception as err:
        WEBHOOK_SUBMISSIONS.labels(status="error", event_type=event_type).inc()
        raise err from err


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
