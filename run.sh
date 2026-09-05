#!/usr/bin/env bash
# Start the unified OpenAI-compatible server (lazy browser, true streaming, swarm).
set -e
cd "$(dirname "$0")"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
exec python3 -m uvicorn server_openai:app --host "$HOST" --port "$PORT"
