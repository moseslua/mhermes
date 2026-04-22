# Multi-stage build for Hermes Fly.io deployment.
# Uses official Python image; keeps the final layer minimal.

# ── Stage 1: Python builder ────────────────────────────────────────────────
FROM python:3.13-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md MANIFEST.in ./
COPY agent/ ./agent/
COPY tools/ ./tools/
COPY hermes_cli/ ./hermes_cli/
COPY gateway/ ./gateway/
COPY tui_gateway/ ./tui_gateway/
COPY cron/ ./cron/
COPY acp_adapter/ ./acp_adapter/
COPY plugins/ ./plugins/
COPY hmaom/ ./hmaom/
COPY skills/ ./skills/
COPY optional-skills/ ./optional-skills/
COPY hermes_constants.py hermes_logging.py hermes_state.py hermes_time.py ./
COPY utils.py model_tools.py run_agent.py cli.py toolsets.py toolset_distributions.py ./
COPY trajectory_compressor.py batch_runner.py mini_swe_runner.py mcp_serve.py ./
COPY .env.example cli-config.yaml.example ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir ".[all]"

# ── Stage 2: Web assets builder ────────────────────────────────────────────
FROM node:22-slim AS web-builder
WORKDIR /app
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci --prefer-offline --no-audit
COPY web/ ./web/
RUN cd web && npm run build

# ── Stage 3: Runtime ───────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV HERMES_HOME=/data/.hermes
ENV HERMES_WEB_DIST=/app/hermes_cli/web_dist
ENV PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY --from=web-builder /app/web/dist /app/hermes_cli/web_dist
COPY packaging/fly/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# One-way projections volume (sessions, missions, fabric, obsidian)
VOLUME ["/data/.hermes"]

EXPOSE 9119

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dashboard", "--host", "0.0.0.0", "--port", "9119", "--insecure", "--no-open"]
