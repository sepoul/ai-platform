# Base image used by the `api` and `worker` services in docker-compose.yml.
# It is intentionally minimal: no ENTRYPOINT, no port, no service-specific env.
# The compose file specifies the command for each service.
#
# REQUIREMENTS selects the worker runtime's dependency set:
#   - requirements.txt          → default runtime (pydantic_ai + logfire)
#   - requirements-crewai.txt   → crewai runtime (no logfire; otel-sdk <1.35)
# These two stacks can't share an interpreter (CrewAI vs Logfire pin
# opentelemetry-sdk to disjoint ranges), so each worker pool builds its own
# image. See ai_platform/jobs/runtimes.py.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS=requirements.txt
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

COPY src/ ./src/
COPY instructions/ ./instructions/
