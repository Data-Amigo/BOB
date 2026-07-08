FROM python:3.11-slim

WORKDIR /app

# System deps: gcc for any C-extension wheels; curl for healthcheck debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy package definition and source
COPY pyproject.toml .
COPY src/ ./src/

# Editable install keeps source files in-place so Path(__file__).parent paths
# (e.g. static/, uploads/) resolve correctly relative to the source tree.
RUN pip install --no-cache-dir -e .

# Persistent upload dir (Railway FS is ephemeral — fine for v1)
RUN mkdir -p uploads/betslips

EXPOSE 8080

# Railway injects $PORT; fall back to 8080 for local docker run
CMD ["sh", "-c", "uvicorn ganji_mtaani_agent.webapp.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
