"""HMAOM Research Specialist.

Web search, paper analysis, data collection, synthesis.
"""

from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
from hmaom.specialists.base import SpecialistHarness


class ResearchHarness(SpecialistHarness):
    """Research domain specialist with information retrieval capabilities."""

    @property
    def default_tools(self) -> list[str]:
        return [
            "web_search",
            "web_extract",
            "file_read",
            "file_write",
        ]

    def _default_system_prompt(self) -> str:
        return (
            "You are the Research Specialist in the HMAOM mesh. "
            "Your expertise includes web search, academic paper analysis, "
            "data collection, and information synthesis. Always cite sources "
            "and distinguish between factual claims and speculation."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="research",
                relevance_score=0.9,
                content="Research and information gathering.",
            ),
        )
        return result.result
