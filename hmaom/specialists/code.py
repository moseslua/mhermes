"""HMAOM Code Specialist.

Software engineering, debugging, architecture, review.
"""

from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
from hmaom.specialists.base import SpecialistHarness


class CodeHarness(SpecialistHarness):
    """Software engineering domain specialist with deep coding capabilities."""

    @property
    def default_tools(self) -> list[str]:
        return [
            "file_read",
            "file_write",
            "file_search",
            "file_patch",
            "execute_code",
            "web_search",
        ]

    def _default_system_prompt(self) -> str:
        return (
            "You are the Code Specialist in the HMAOM mesh. "
            "Your expertise includes software engineering, debugging, "
            "system architecture, and code review. You have access to "
            "file tools, code execution, and web search. "
            "Follow best practices: write tests, document public APIs, "
            "and prefer simplicity over cleverness."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        """Handle code-specific tasks."""
        desc = request.task.description.lower()

        if any(term in desc for term in ["debug", "fix", "bug", "error", "crash"]):
            return await self._handle_debug(request)
        elif any(term in desc for term in ["review", "audit", "quality", "lint"]):
            return await self._handle_review(request)
        elif any(term in desc for term in ["architecture", "design", "refactor", "structure"]):
            return await self._handle_architecture(request)
        elif any(term in desc for term in ["implement", "write", "create", "build", "add feature"]):
            return await self._handle_implementation(request)
        elif any(term in desc for term in ["test", "coverage", "pytest", "unit test"]):
            return await self._handle_testing(request)
        else:
            return await self._handle_general_code(request)

    async def _handle_debug(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.95,
                content="Systematic debugging: reproduce, isolate, fix, verify.",
                memory_keys=["code/debugging"],
            ),
        )
        # Follow up with verification
        verify_result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="verify",
            task=TaskDescription(
                title=f"Verify fix: {request.task.title}",
                description=f"Verify the fix for: {request.task.description}",
            ),
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.9,
                content="Run tests and verify the fix works correctly.",
            ),
        )
        return {
            "debug_result": result.result,
            "verification": verify_result.result,
        }

    async def _handle_review(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="verify",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.95,
                content="Code review: correctness, security, performance, maintainability.",
                memory_keys=["code/review"],
            ),
        )
        return result.result

    async def _handle_architecture(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.95,
                content="Architecture analysis: tradeoffs, patterns, scalability.",
                memory_keys=["code/architecture"],
            ),
        )
        return result.result

    async def _handle_implementation(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.95,
                content="Implementation with tests and documentation.",
                memory_keys=["code/implementation"],
            ),
        )
        return result.result

    async def _handle_testing(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="verify",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.95,
                content="Test design: unit, integration, edge cases, mocks.",
                memory_keys=["code/testing"],
            ),
        )
        return result.result

    async def _handle_general_code(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="code",
                relevance_score=0.8,
                content="General software engineering task.",
            ),
        )
        return result.result
