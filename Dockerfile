# ╔══════════════════════════════════════════════════════════════╗
# ║   TG FORM BLASTER v3.0 — Standalone Dockerfile             ║
# ║   Requires: bot.py                                           ║
# ╚══════════════════════════════════════════════════════════════╝

FROM python:3.11-slim

# ── Environment ────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data \
    TZ=UTC

# ── System packages ────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# ── Work directory ─────────────────────────────────────────────
WORKDIR /app

# ── Upgrade packaging tools ────────────────────────────────────
RUN python -m pip install --upgrade \
        pip \
        setuptools \
        wheel

# ── Python dependencies ────────────────────────────────────────
# aiohttp-socks 0.9.x requires aiohttp >= 3.10
RUN python -m pip install --no-cache-dir \
        "python-telegram-bot==21.6" \
        "aiohttp>=3.10,<4" \
        "aiohttp-socks==0.9.0" \
        "python-socks[asyncio]>=2.4.3,<3"

# ── Copy bot ────────────────────────────────────────────────────
COPY bot.py /app/bot.py

# ── Persistent data ────────────────────────────────────────────
RUN mkdir -p /app/data/logs

VOLUME ["/app/data"]

# ── Healthcheck ─────────────────────────────────────────────────
HEALTHCHECK \
    --interval=60s \
    --timeout=10s \
    --start-period=45s \
    --retries=3 \
    CMD python -c "import os; raise SystemExit(0 if os.path.isfile('/app/bot.py') else 1)"

# ── Start bot ───────────────────────────────────────────────────
CMD ["python", "-u", "/app/bot.py"]
