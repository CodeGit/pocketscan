# The image every pipeline process runs in: fpocket, Python with Biopython, the two
# pipeline scripts, and the API package (for `python -m pocketscan_api.ingest`).
#
# Build from the repo root, because pipeline/ depends on ../api by path:
#   podman build -f pipeline/Dockerfile -t pocketscan-pipeline .
#
# Base images are pinned by digest. To bump one, pull the new tag, copy its digest
# here, and rebuild.

ARG PYTHON_IMAGE=docker.io/library/python:3.14-slim@sha256:cfe2e24a75302a15934d37c2d86412893c0aa934dc3a97cbb439d04c01890ca9
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11@sha256:8876e42c633ff18826b6bc2c1ebe8b4b0c4e056a2cab6e6a48e736ccc0bcad64

# --- fpocket, built from source -------------------------------------------------
FROM ${PYTHON_IMAGE} AS fpocket
# Keep in step with params.tool_version in pipeline/nextflow.config.
ARG FPOCKET_COMMIT=4bb0d84
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/Discngine/fpocket.git /src \
    && git -C /src checkout "${FPOCKET_COMMIT}"
WORKDIR /src
# Newer GCC rejects an incompatible pointer type that fpocket 4.0 relies on.
RUN make fpocket CWARN="-W -Wextra -Wwrite-strings -Wstrict-prototypes -Wno-error=incompatible-pointer-types" \
    && install -D bin/fpocket /out/fpocket

# --- uv (a named stage, because COPY --from cannot take an ARG) ------------------
FROM ${UV_IMAGE} AS uv

# --- Python environment ---------------------------------------------------------
FROM ${PYTHON_IMAGE} AS python-deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY api/ api/
COPY pipeline/pyproject.toml pipeline/uv.lock pipeline/
WORKDIR /app/pipeline
RUN uv sync --locked --no-dev

# --- runtime --------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
COPY --from=fpocket /out/fpocket /usr/local/bin/fpocket
COPY --from=python-deps /app /app
COPY pipeline/bin/ /app/pipeline/bin/
ENV PATH="/app/pipeline/.venv/bin:/app/pipeline/bin:${PATH}"
RUN useradd --create-home --uid 1000 pocketscan
USER pocketscan
WORKDIR /home/pocketscan
