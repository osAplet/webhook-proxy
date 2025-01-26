#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    web)
        exec uvicorn main:app --host 0.0.0.0 --port 8000
        ;;
    worker)
        exec dramatiq-gevent worker:redis_broker \
            --processes 1 \
            --threads 1 \
            --verbose
        ;;
    *)
        # Execute remaining arguments
        exec "${@:-}"
        ;;
esac 
