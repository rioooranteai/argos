# ArgosAI image, one Dockerfile for both PyTorch variants (the extras in pyproject.toml):
#   docker compose --profile cpu up -d --build     → image argos:cpu
#   docker compose --profile gpu up -d --build     → image argos:cu129 (NVIDIA GPU)
# Two stages: the builder installs the locked environment with uv, the runtime image gets only
# that environment, the system libraries and the application files.

ARG PYTHON_VERSION=3.11

# ── builder ──────────────────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

# The uv version that wrote uv.lock
COPY --from=ghcr.io/astral-sh/uv:0.7.5 /uv /bin/uv

# PyTorch variant: "cpu" or "cu129" (an extra in pyproject.toml)
ARG TORCH_VARIANT=cpu

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Compilers for packages that have no wheel for this platform (not copied to the runtime image)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml uv.lock ./
# --frozen: exactly the versions in uv.lock (fails instead of re-resolving)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra ${TORCH_VARIANT}

# ── runtime ──────────────────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

# libgl1, libglib2.0-0: OpenCV (Docling layout/OCR). sqlite3: the CLI, for inspecting the database.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Runs as an unprivileged user. UID 1000 = the usual first user on a Linux host, so a bind-mounted
# ./data stays writable (otherwise: sudo chown -R 1000:1000 data, see README).
RUN useradd --create-home --uid 1000 argos

COPY --from=builder /opt/venv /opt/venv

# The token encoding (cl100k_base) ships in the image: otherwise tiktoken downloads it on every
# start of a new container, and the app does not start when that download fails.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

WORKDIR /app
COPY --chown=argos:argos app/ app/
COPY --chown=argos:argos prompts/ prompts/
COPY --chown=argos:argos web-app/ web-app/
RUN mkdir -p data && chown argos:argos data

USER argos
EXPOSE 8000

# MUST be a single process: the document queue worker runs inside the app, and the Chroma
# PersistentClient is not safe across processes (DESIGN_GROUP_B.md §3.4).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
