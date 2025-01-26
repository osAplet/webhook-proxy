# webhook-proxy

Takes incoming webhooks from GitHub and forwards them to the target service.

## Development

To run the service locally for development:

```bash
docker-compose up --build
```

This will start:
- The webhook proxy service on port 8000
- A Redis instance for message queuing
- A worker process for handling webhooks
- A webhook tester service on port 8080

## API endpoints

### GitHub webhook endpoint

```
POST /webhook/github
```

This endpoint accepts GitHub webhook payloads and forwards them to the configured target service.

#### Example Usage

```bash
curl -X POST http://localhost:8000/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"ref":"refs/heads/main"}' | openssl dgst -sha256 -hmac "secret" | cut -d' ' -f2)" \
  -d '{"ref":"refs/heads/main"}'

curl -X POST http://localhost:8000/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: sha256=$(echo -n '{"action":"opened"}' | openssl dgst -sha256 -hmac "secret" | cut -d' ' -f2)" \
  -d '{"action":"opened"}'
```

### Metrics endpoint

```
GET /metrics
```

Returns Prometheus metrics including:
- Total number of webhook submissions
- Submission status (success, error, invalid signature, etc.)
- Event types received

Example:
```bash
curl http://localhost:8000/metrics
```
