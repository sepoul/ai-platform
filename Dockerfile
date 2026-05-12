# Base image used by both `api` and `worker` services in docker-compose.yml.
# It is intentionally minimal: no ENTRYPOINT, no port, no service-specific env.
# The compose file specifies the command for each service.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY instructions/ ./instructions/
