"""HMAOM Dynamic Specialist Harness.

Base class for specialists that are auto-created by the Hire system.
"""

from typing import Any

from hmaom.protocol.schemas import SpawnRequest
from hmaom.specialists.base import SpecialistHarness


class DynamicSpecialistHarness(SpecialistHarness):
    """Base class for dynamically created specialists.

    Provides sensible defaults for specialists that were auto-generated
    by the HireCreator. Subclasses must still implement:
    - default_tools
    - system_prompt
    - _handle_task
    """

    @property
    def default_tools(self) -> list[str]:
        return [
            "web_search",
            "file_read",
            "file_write",
            "execute_code",
        ]

    @property
    @property
    def _default_system_prompt(self) -> str:
        return (
            "You are a dynamically created specialist in the HMAOM mesh. "
            "Provide domain-relevant assistance using the available tools."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        """Default handler delegates to an explore subagent.

        Subclasses should override this to provide domain-specific routing.
        """
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=self.memory_manager.working_slice(request.task.description),
        )
        return result.result
