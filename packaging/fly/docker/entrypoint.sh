#!/bin/bash
set -e

HERMES_HOME="${HERMES_HOME:-/data/.hermes}"
INSTALL_DIR="/app"

# --- Volume bootstrap ---
# Create the canonical Hermes directory tree so the app never has to
# mkdir-p at runtime.  Projections subdirectories are included so
# one-way mirrors have stable targets from boot.
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home,fabric,obsidian,projections}

# Seed .env if absent
if [ ! -f "$HERMES_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env" 2>/dev/null || true
fi

# Seed config.yaml if absent
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml" 2>/dev/null || true
fi

# Sync bundled skills
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 -m tools.skills_sync 2>/dev/null || true
fi

exec hermes "$@"
