FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY pyproject.toml ./
COPY hmaom/ ./hmaom/
COPY hermes_cli/ ./hermes_cli/
COPY agent/ ./agent/
COPY tools/ ./tools/
COPY hermes_constants.py hermes_state.py hermes_logging.py ./

RUN pip install --no-cache-dir -e ".[dev]"
RUN pip install --no-cache-dir -e .

# Create state directories
RUN mkdir -p /app/state /app/checkpoints /app/skills

# Expose gateway port
EXPOSE 8080

# Default: run gateway
CMD ["python", "-m", "hmaom.gateway.router"]
