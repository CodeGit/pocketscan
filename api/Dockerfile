# The API image. The same image runs the migrations:
#   serve:    (default command) uvicorn
#   migrate:  alembic -c /app/alembic.ini upgrade head
#
# Build from the repo root, so it shares .dockerignore with pipeline/Dockerfile:
#   podman build -f api/Dockerfile -t pocketscan-api .
#
# Base images are pinned by digest, as in pipeline/Dockerfile. Keep the two in step.

ARG PYTHON_IMAGE=docker.io/library/python:3.14-slim@sha256:cfe2e24a75302a15934d37c2d86412893c0aa934dc3a97cbb439d04c01890ca9
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11@sha256:8876e42c633ff18826b6bc2c1ebe8b4b0c4e056a2cab6e6a48e736ccc0bcad64

# --- uv (a named stage, because COPY --from cannot take an ARG) ------------------
FROM ${UV_IMAGE} AS uv

# --- Python environment ---------------------------------------------------------
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so editing the source does not reinstall them.
COPY api/pyproject.toml api/uv.lock api/README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY api/src/ src/
# --no-editable puts the package in the venv, so the source tree is not needed at runtime.
RUN uv sync --locked --no-dev --no-editable

# --- runtime --------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY api/alembic.ini ./
COPY api/migrations/ migrations/
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 1000 pocketscan
USER pocketscan
EXPOSE 8000
# The database comes from POCKETSCAN_DATABASE_URL (a Secret in the cluster).
# Probes: /healthz (liveness) and /readyz (readiness, checks the database).
CMD ["uvicorn", "pocketscan_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
