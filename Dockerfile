# Agent image for LiveKit Cloud (`lk agent create` / `lk agent deploy` build this).
# Based on LiveKit's pip Dockerfile template. The web server is deployed
# separately (Render, see render.yaml) and doesn't use this file.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Unprivileged user, as in LiveKit's template.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /home/appuser/app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . .
USER appuser

# Bake model weights (VAD, turn-detector fallback) into the image.
RUN python agent/agent.py download-files

# LiveKit Cloud injects LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET.
# `start` = production mode: connect to LiveKit and wait for dispatches.
CMD ["python", "agent/agent.py", "start"]
