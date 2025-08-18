# Small, reliable base image
FROM python:3.11-slim-bookworm

# --- Base env & faster installs ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Optional: keep HF caches ephemeral (Cloud Run allows writing to /tmp)
ENV TRANSFORMERS_CACHE=/tmp/hf \
    HF_HOME=/tmp/hf

# System deps some wheels/tools may need
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Install CPU-only PyTorch (keep torch OUT of requirements.txt) ---
RUN python -m pip install --upgrade pip \
 && python -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.2.2

# --- Install the rest of your deps ---
# (requirements.txt should NOT include torch)
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# --- Copy the app source ---
COPY . .

# Expose for local runs (Cloud Run ignores EXPOSE and uses $PORT)
EXPOSE 8000

# Default port for local "docker run"; Cloud Run overrides $PORT
ENV PORT=8000

# Gunicorn entrypoint; Cloud Run sets $PORT at runtime
CMD gunicorn -w 2 --preload -b 0.0.0.0:$PORT app.main:app
