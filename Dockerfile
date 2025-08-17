# Use a PyTorch CPU base image so sentence-transformers installs smoothly without heavy build steps.
FROM pytorch/pytorch:2.2.2-cpu-py3.11

# All code lives under /app
WORKDIR /app

# Keep pip modern to avoid resolver quirks.
RUN pip install --no-cache-dir --upgrade pip

# Install Python dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the project files.
COPY . .

# Avoids Python buffering logs; makes container logs timely.
ENV PYTHONUNBUFFERED=1

# We specify the gunicorn command in docker-compose.yml so we can tweak workers easily there.
