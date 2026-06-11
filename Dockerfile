# Use a slim Python base image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Sync dependencies (frozen ensures it respects lock file, no-dev skips development dependencies)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Final slim runner stage
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source files and data
COPY monitor_votes.py monitor_config.json gemeinden_vote_pages.csv ./

# Create directories for volumes
RUN mkdir -p monitor_cache monitor_changes

# Define volumes for persistence
VOLUME ["/app/monitor_changes", "/app/monitor_cache"]

# Default command to run
ENTRYPOINT ["python", "monitor_votes.py"]
