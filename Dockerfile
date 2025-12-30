# Multi-stage build for Kimai MCP Remote Server
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install the package with server dependencies
RUN pip install --no-cache-dir -e ".[server]"


# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Create config directory
RUN mkdir -p /app/config

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash kimai && \
    chown -R kimai:kimai /app

# Switch to non-root user
USER kimai

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Default: Run the new Streamable HTTP server (for Claude.ai Connectors)
# Use kimai-mcp-server for the legacy SSE server
CMD ["kimai-mcp-streamable"]
