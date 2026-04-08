FROM python:3.11-slim AS base

# Build arguments
ARG WHISPER_MODEL=medium
ARG WHISPER_COMPUTE_TYPE=int8

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Stage 1: System dependencies ────────────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 2: Python dependencies (cached layer) ────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 3: Pre-download Whisper model ─────────────────────────────
# This avoids ~1.5GB download on first run
RUN mkdir -p /app/data/cache && \
    python -c "\
from faster_whisper import WhisperModel; \
print(f'Downloading whisper model: ${WHISPER_MODEL} (${WHISPER_COMPUTE_TYPE})'); \
m = WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='${WHISPER_COMPUTE_TYPE}', download_root='/app/data/cache'); \
del m; \
print('Model downloaded successfully')"

# ── Stage 4: Copy application code ──────────────────────────────────
COPY . .

# Create runtime directories
RUN mkdir -p /app/data/audio

# ── Runtime configuration ───────────────────────────────────────────
# Default environment variables (can be overridden at runtime)
ENV WHISPER_MODEL_SIZE=${WHISPER_MODEL} \
    WHISPER_COMPUTE_TYPE=${WHISPER_COMPUTE_TYPE} \
    WHISPER_DEVICE=cpu

EXPOSE 7860

# Health check: verify Gradio is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

CMD ["python", "app.py"]
