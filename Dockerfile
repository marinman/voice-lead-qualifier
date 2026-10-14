# One image runs both the web server (page + token endpoint + dashboard) and the
# LiveKit agent worker, so they share the SQLite file on the mounted volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    VLQ_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bake model weights (VAD, turn-detector fallback) into the image.
RUN python agent/agent.py download-files

RUN chmod +x start.sh
EXPOSE 8080
CMD ["./start.sh"]
