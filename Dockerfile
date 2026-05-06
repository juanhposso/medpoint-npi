# ─── Base image ───────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ─── Environment ──────────────────────────────────────────────────────────────
# Prevents Python from writing .pyc files and enables unbuffered stdout/stderr
# (so logs appear immediately in docker logs — critical for debugging workers)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# ─── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ─── Dependencies (own layer — rebuilt only when requirements.txt changes) ────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Application code ─────────────────────────────────────────────────────────
# Copied after pip install so source changes don't invalidate the pip layer
COPY . .

# ─── No CMD here ──────────────────────────────────────────────────────────────
# Each service in docker-compose.yml overrides CMD with its own entrypoint:
#   fastapi-1 / fastapi-2 → uvicorn api.main:app --host 0.0.0.0 --port 8000
#   worker               → python -m workers.npi_fetcher   (Phase 5)