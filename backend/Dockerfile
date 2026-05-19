# Backend container for Railway / Render / Fly / anything that runs OCI images.
# Uses uv for fast, reproducible Python installs.

FROM python:3.12-slim

# uv lives in /usr/local/bin so it's on the default PATH.
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first so layer caching doesn't bust on app-code edits.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# Application source + artifacts + parquet cache.
COPY app ./app
COPY artifacts ./artifacts
COPY results ./results
COPY data_cache ./data_cache

# Railway and Render both inject PORT; default to 8000 for local Docker runs.
ENV PORT=8000
EXPOSE 8000

# Shell form so ${PORT} interpolates at container start.
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
