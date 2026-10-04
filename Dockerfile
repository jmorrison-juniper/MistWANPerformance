# MistWANPerformance - Production Container
#
# Multi-stage build for smaller final image.
# Runs the Dash dashboard with Redis for caching.
#
# Build: podman build -t mistwan-performance .
# Run:   podman-compose up -d

FROM python:3.13.16-slim-bookworm AS builder

# Set APT_PROXY at build time to use an optional local package cache.
ARG APT_PROXY=
RUN if [ -n "${APT_PROXY}" ]; then \
    echo "Acquire::http::Proxy \"${APT_PROXY}\";" > /etc/apt/apt.conf.d/00proxy; fi

# Install build dependencies (uses apt-cacher-ng for caching)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Public defaults also support clean builds outside the deployment network.
ARG PIP_INDEX_URL=https://pypi.org/simple/
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Offline validation uses the same runtime packages and Python base.
FROM builder AS tests
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
WORKDIR /app
COPY src/ ./src/
COPY tests/ ./tests/
COPY run_dashboard.py wsgi.py gunicorn_config.py pyproject.toml ./
CMD ["python", "-m", "pytest", "-q"]


# Production stage
FROM python:3.13.16-slim-bookworm AS production

# Labels for container metadata
LABEL org.opencontainers.image.title="MistWANPerformance"
LABEL org.opencontainers.image.description="WAN Performance Dashboard for Juniper Mist"
LABEL org.opencontainers.image.version="1.0.0"

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup run_dashboard.py .
COPY --chown=appuser:appgroup wsgi.py .
COPY --chown=appuser:appgroup gunicorn_config.py .
COPY --chown=appuser:appgroup pyproject.toml .
COPY --chown=appuser:appgroup entrypoint.sh .

# Make entrypoint executable
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Create data directories with correct permissions
RUN mkdir -p /app/data/logs /app/data/cache /app/data/exports && \
    chown -R appuser:appgroup /app/data

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DASH_HOST=0.0.0.0
ENV DASH_PORT=8050
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379

# Expose dashboard port
EXPOSE 8050

# Health check - verify dashboard responds
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD python -c "import requests; requests.get('http://localhost:8050/', timeout=5)" || exit 1

# Use entrypoint script for crash handling and auto-restart
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
