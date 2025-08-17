# Slim Python base; small and reliable
FROM python:3.11-slim-bookworm

# Faster, cleaner installs & logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps that some wheels/tools want (git optional but handy)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Install CPU-only PyTorch explicitly from the official index
#    (keep torch OUT of requirements.txt to avoid conflicts)
RUN python -m pip install --upgrade pip \
 && python -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.2.2

# 2) Install the rest of the deps
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# 3) Copy the app
COPY . .

# Entrypoint comes from docker-compose.yml (gunicorn)
