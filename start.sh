#!/usr/bin/env bash
# Container entrypoint: web server + agent worker in one machine.
# If either process exits, the container exits and the host restarts it.
set -uo pipefail

uvicorn web.server:app --host 0.0.0.0 --port "${PORT:-8080}" \
  --proxy-headers --forwarded-allow-ips='*' &

if [[ -n "${LIVEKIT_URL:-}" && -n "${LIVEKIT_API_KEY:-}" && -n "${LIVEKIT_API_SECRET:-}" ]]; then
  python agent/agent.py start &
else
  # Keys missing: keep the page, text chat, and reviewer mode up without the agent.
  echo "LIVEKIT_* not set: agent worker not started (voice disabled)."
fi

wait -n
exit $?
