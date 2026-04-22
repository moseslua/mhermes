"""HMAOM Specialist Hire creator.

Generates SpecialistConfig and empty harness files for newly hired specialists.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

from hmaom.config import SpecialistConfig
from hmaom.hire.analyzer import HireSuggestion
from hmaom.hire.persistence import HirePersistence


class HireCreator:
    """Creates new specialist configurations and harness files.

    When a hire suggestion is approved, this generates:
    - A SpecialistConfig instance
    - A harness Python file in hmaom/specialists/
    """

    def __init__(
        self,
        persistence: Optional[HirePersistence] = None,
        specialists_dir: Optional[str] = None,
    ) -> None:
        self.persistence = persistence or HirePersistence()
        if specialists_dir is None:
            # Derive from this file's location
            self.specialists_dir = Path(__file__).parent.parent / "specialists"
        else:
            self.specialists_dir = Path(specialists_dir)

    def create_specialist(self, suggestion: HireSuggestion) -> SpecialistConfig:
        """Generate and persist a new specialist from a hire suggestion.

        Returns the generated SpecialistConfig.
        """
        config = self._build_config(suggestion)
        self._write_harness_file(config, suggestion)
        self.persistence.log_decision(
            specialist_name=config.name,
            domain=config.domain,
            reason=suggestion.reason,
            config_json=json.dumps(
                {
                    "name": config.name,
                    "domain": config.domain,
                    "description": config.description,
                    "model_override": config.model_override,
                    "lazy_load_areas": config.lazy_load_areas,
                    "max_subagent_depth": config.max_subagent_depth,
                }
            ),
        )
        return config

    def _build_config(self, suggestion: HireSuggestion) -> SpecialistConfig:
        """Build a SpecialistConfig from a hire suggestion."""
        return SpecialistConfig(
            name=suggestion.suggested_name,
            domain=suggestion.suggested_domain,
            description=f"Auto-created specialist covering: {', '.join(suggestion.keywords)}",
            model_override=None,
            lazy_load_areas=[k.replace("_", "-") for k in suggestion.keywords[:4]],
            max_subagent_depth=2,
        )

    def _write_harness_file(
        self, config: SpecialistConfig, suggestion: HireSuggestion
    ) -> None:
        """Write the harness Python file for the new specialist."""
        class_name = self._to_class_name(config.domain)
        filename = f"{config.domain}.py"
        filepath = self.specialists_dir / filename

        # Avoid overwriting existing files
        if filepath.exists():
            raise FileExistsError(f"Specialist harness already exists: {filepath}")

        harness_code = textwrap.dedent(
            f'''\
            """HMAOM {config.domain.title()} Specialist.

            Auto-generated specialist covering: {', '.join(suggestion.keywords)}.
            """

            from typing import Any

            from hmaom.config import SpecialistConfig
            from hmaom.protocol.schemas import SpawnRequest
            from hmaom.specialists.dynamic import DynamicSpecialistHarness


            class {class_name}Harness(DynamicSpecialistHarness):
                """Dynamically created specialist for the {config.domain} domain."""

                @property
                def default_tools(self) -> list[str]:
                    return [
                        "web_search",
                        "file_read",
                        "file_write",
                        "execute_code",
                    ]

                @property
                def _default_system_prompt(self) -> str:
                    return (
                        "You are the {config.domain.title()} Specialist in the HMAOM mesh. "
                        "Your expertise includes: {', '.join(suggestion.keywords)}. "
                        "Follow best practices and prefer simplicity over cleverness."
                    )

                async def _handle_task(self, request: SpawnRequest) -> Any:
                    """Handle tasks for the {config.domain} domain."""
                    result = await self.spawn_subagent(
                        parent_request=request,
                        subagent_type="explore",
                        task=request.task,
                        context_slice=self.memory_manager.working_slice(request.task.description),
                    )
                    return result.result
            '''
        )

        filepath.write_text(harness_code, encoding="utf-8")

    @staticmethod
    def _to_class_name(domain: str) -> str:
        """Convert a domain slug to a PascalCase class name prefix."""
        return "".join(part.capitalize() for part in domain.replace("_", "-").split("-"))
