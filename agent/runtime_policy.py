from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Provenance(str, Enum):
    trusted = "trusted"
    untrusted = "untrusted"


class Capability(str, Enum):
    terminal = "terminal"
    memory = "memory"
    plugin = "plugin"
    messaging = "messaging"
    scheduling = "scheduling"
    browser = "browser"
    file_write = "file_write"
    model_mutation = "model_mutation"


class PolicyMode(str, Enum):
    off = "off"
    monitor = "monitor"
    enforce = "enforce"


# Map common tool names to capabilities for thin policy enforcement.
_TOOL_CAPABILITY_MAP: dict[str, Capability] = {
    "terminal": Capability.terminal,
    "execute_code": Capability.terminal,
    "write_file": Capability.file_write,
    "patch": Capability.file_write,
    "browser_navigate": Capability.browser,
    "browser_click": Capability.browser,
    "browser_type": Capability.browser,
    "browser_scroll": Capability.browser,
    "browser_back": Capability.browser,
    "browser_press": Capability.browser,
    "browser_get_images": Capability.browser,
    "browser_vision": Capability.browser,
    "browser_console": Capability.browser,
    "browser_snapshot": Capability.browser,
    "memory": Capability.memory,
    "delegate_task": Capability.messaging,
    "send_message": Capability.messaging,
    "cronjob": Capability.scheduling,
    "skill_manage": Capability.plugin,
    "plugin_guard": Capability.plugin,
    "model_switch": Capability.model_mutation,
}


class RuntimePolicy:
    """CaMeL-style trust boundary enforcement.

    Thin wrapper — default mode is ``off`` so existing behavior is unchanged.
    """

    _SENSITIVE_CAPABILITIES: set[str] = {c.value for c in Capability}

    def evaluate(
        self,
        capability: Capability | str,
        provenance: Provenance | str,
        mode: PolicyMode | str,
    ) -> dict[str, Any]:
        """Evaluate whether a capability is allowed under the given provenance and mode.

        Returns:
            {"allowed": bool, "blocked": bool, "reason": str | None}
        """
        capability_str = capability.value if isinstance(capability, Capability) else str(capability)
        provenance_str = provenance.value if isinstance(provenance, Provenance) else str(provenance)
        mode_str = mode.value if isinstance(mode, PolicyMode) else str(mode)

        if mode_str == PolicyMode.off.value:
            return {"allowed": True, "blocked": False, "reason": None}

        if capability_str not in self._SENSITIVE_CAPABILITIES:
            return {"allowed": True, "blocked": False, "reason": None}

        if provenance_str == Provenance.trusted.value:
            return {"allowed": True, "blocked": False, "reason": None}

        # Untrusted provenance + sensitive capability
        if mode_str == PolicyMode.enforce.value:
            return {
                "allowed": False,
                "blocked": True,
                "reason": (
                    f"Blocked: {capability_str} capability from untrusted provenance "
                    f"is not allowed in enforce mode."
                ),
            }

        # monitor mode — allow but log
        logger.info(
            "Policy monitor: untrusted provenance accessing %s capability",
            capability_str,
        )
        return {"allowed": True, "blocked": False, "reason": None}

    def capability_for_tool(self, tool_name: str) -> Capability | None:
        """Return the Capability mapped to a tool name, or None."""
        return _TOOL_CAPABILITY_MAP.get(tool_name)


def strip_provider_metadata(payload: Any) -> Any:
    """Strip provider-specific metadata from a payload.

    Removes fields that providers inject for attribution/tracking so that
    downstream consumers see clean data.
    """
    if payload is None:
        return None

    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            cleaned = strip_provider_metadata(parsed)
            return json.dumps(cleaned, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return payload

    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            # Strip common provider metadata prefixes
            if key.startswith("_provider") or key.startswith("_source"):
                continue
            if key in ("provider_metadata", "provider_meta", "_meta"):
                continue
            result[key] = strip_provider_metadata(value)
        return result

    if isinstance(payload, list):
        return [strip_provider_metadata(item) for item in payload]

    return payload
