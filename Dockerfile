# ╔══════════════════════════════════════════════════════════════╗
# ║   🚀 TG FORM BLASTER v3.0 — Standalone Dockerfile           ║
# ║   Sirf ye Dockerfile + bot.py chahiye, kuch aur nahi.       ║
# ╚══════════════════════════════════════════════════════════════╝

FROM python:3.11-slim

# ── Env ──────────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data \
    TZ=UTC

# ── System deps (curl for healthcheck, tzdata for logs, ca-certs for HTTPS) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# ── Workdir ──────────────────────────────────────────────────────
WORKDIR /app

# ── Python deps (inline — no requirements.txt needed) ────────────
RUN pip install --upgrade pip && \
    pip install \
        "python-telegram-bot==21.6" \
        "aiohttp==3.9.5" \
        "aiohttp-socks==0.9.0" \
        "python-socks[asyncio]==2.4.4"

# ── Copy bot ─────────────────────────────────────────────────────
COPY bot.py /app/bot.py

# ── Persistent data volume ───────────────────────────────────────
RUN mkdir -p /app/data/logs
VOLUME ["/app/data"]

# ── Healthcheck ──────────────────────────────────────────────────
HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD python -c "import os,sys; sys.exit(0 if os.path.exists('/app/bot.py') else 1)"

# ── Run ──────────────────────────────────────────────────────────
CMD ["python", "-u", "/app/bot.py"]
