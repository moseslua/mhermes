"""Hermes-to-AgentFlow credential bridge.

Resolves API keys, base URLs, and model names using the Hermes auth system so
that AgentFlow graphs can run with the same providers configured for Hermes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from hermes_cli.auth import (
    PROVIDER_REGISTRY,
    AuthError,
    get_auth_status,
    resolve_api_key_provider_credentials,
    resolve_external_process_provider_credentials,
    resolve_provider,
)
from hermes_cli.config import read_raw_config
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

# Sensible defaults when the user has not set a model override in config.yaml.
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4",
    "openrouter": "openai/gpt-4o",
    "gemini": "gemini-2.0-flash",
    "deepseek": "deepseek-chat",
    "xai": "grok-2",
    "zai": "glm-5",
    "kimi-coding": "kimi-k2",
    "minimax": "minimax-text-01",
    "copilot": "github-copilot",
    "qwen-oauth": "qwen-max",
    "nous": "nous-hermes",
    "openai-codex": "codex",
    "alibaba": "qwen-max",
    "arcee": "arcee-agent",
    "nvidia": "nvidia/llama-3.1-nemotron-70b",
    "ai-gateway": "gpt-4o",
    "opencode-zen": "opencode-zen",
    "opencode-go": "opencode-go",
    "kilocode": "kilocode",
    "huggingface": "huggingface/meta-llama-3-70b",
    "xiaomi": "xiaomi-mimo",
    "ollama-cloud": "llama3.3",
    "custom": "custom",
}


def _load_hermes_env() -> None:
    """Load ``~/.hermes/.env`` into ``os.environ`` if python-dotenv is absent.

    Falls back to a lightweight parser so that ``resolve_agentflow_credentials``
    works even when the caller has not explicitly sourced the file.
    """
    env_path = get_hermes_home() / ".env"
    if not env_path.exists():
        return

    # Prefer the canonical loader when available
    try:
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv()
        return
    except Exception:
        pass

    # Lightweight fallback parser (KEY=VALUE, no export prefix, skips comments)
    try:
        with env_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        logger.debug("Could not parse %s: %s", env_path, exc)


# Ensure Hermes env vars are visible to this module
_load_hermes_env()


def resolve_agentflow_credentials(provider_id: str) -> dict[str, Any]:
    """Return AgentFlow-compatible credentials for a Hermes provider.

    Looks up credentials in the following priority:

    1. API-key providers – env vars / ``~/.hermes/.env`` / ``~/.hermes/auth.json``.
    2. External-process providers – command + base URL.
    3. OAuth providers – access token from the auth store.
    4. Fallback – provider-specific env vars.

    Args:
        provider_id: Hermes provider identifier (e.g. ``"anthropic"``).

    Returns:
        ``{"api_key": str, "base_url": str, "model": str}``

    Raises:
        AuthError: When no usable credentials are found.
    """
    # Normalise aliases (e.g. "claude" → "anthropic")
    try:
        resolved = resolve_provider(provider_id)
    except AuthError:
        resolved = provider_id.lower().strip()

    # Optional model override from raw config.yaml
    model = _model_for_provider(resolved)

    pconfig = PROVIDER_REGISTRY.get(resolved)
    if pconfig is None:
        return _fallback_env_credentials(resolved, model)

    # 1. API-key providers -----------------------------------------------------
    if pconfig.auth_type == "api_key":
        creds = resolve_api_key_provider_credentials(resolved)
        return {
            "api_key": creds.get("api_key", ""),
            "base_url": creds.get("base_url", ""),
            "model": model,
        }

    # 2. External-process providers --------------------------------------------
    if pconfig.auth_type == "external_process":
        creds = resolve_external_process_provider_credentials(resolved)
        return {
            "api_key": creds.get("api_key", ""),
            "base_url": creds.get("base_url", ""),
            "model": model,
        }

    # 3. OAuth providers -------------------------------------------------------
    if pconfig.auth_type in ("oauth_device_code", "oauth_external"):
        from hermes_cli.auth import _load_auth_store

        auth_store = _load_auth_store()
        provider_state = auth_store.get("providers", {}).get(resolved, {})
        access_token = provider_state.get("access_token") or provider_state.get("token", "")
        if not access_token:
            raise AuthError(
                f"OAuth provider '{resolved}' is not logged in.",
                provider=resolved,
                code="oauth_not_logged_in",
            )
        return {
            "api_key": access_token,
            "base_url": pconfig.inference_base_url,
            "model": model,
        }

    # 4. Fallback --------------------------------------------------------------
    return _fallback_env_credentials(resolved, model)


def list_available_providers() -> list[str]:
    """List providers that have configured credentials.

    Returns:
        Sorted list of provider IDs.
    """
    available: set[str] = set()
    for pid in PROVIDER_REGISTRY:
        try:
            status = get_auth_status(pid)
            if status.get("logged_in") or status.get("configured"):
                available.add(pid)
        except Exception:
            # Probe env vars as a last resort
            pconfig = PROVIDER_REGISTRY.get(pid)
            if pconfig and pconfig.auth_type == "api_key":
                for env_var in pconfig.api_key_env_vars:
                    if os.getenv(env_var, "").strip():
                        available.add(pid)
                        break
    return sorted(available)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _model_for_provider(provider_id: str) -> str:
    """Return the model name for *provider_id*, preferring config.yaml override."""
    raw_cfg = read_raw_config()
    if isinstance(raw_cfg, dict):
        model_cfg = raw_cfg.get("model") or {}
        if isinstance(model_cfg, dict) and model_cfg.get("provider") == provider_id:
            override = model_cfg.get("model")
            if override:
                return str(override)
    return _DEFAULT_MODELS.get(provider_id, "")


def _fallback_env_credentials(provider_id: str, model: str) -> dict[str, Any]:
    """Last-resort credential resolution from env vars."""
    prefix = provider_id.upper().replace("-", "_")
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip()
    if not api_key:
        # Also try the generic OPENAI_API_KEY for openrouter/custom
        if provider_id in ("openrouter", "custom"):
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise AuthError(
                f"No credentials found for provider '{provider_id}'.",
                provider=provider_id,
                code="missing_credentials",
            )
    return {"api_key": api_key, "base_url": base_url, "model": model}
