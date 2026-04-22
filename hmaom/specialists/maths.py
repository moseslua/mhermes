"""HMAOM Maths Specialist.

Symbolic math, numerical methods, statistics, proof verification.
"""

from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
from hmaom.specialists.base import SpecialistHarness


class MathsHarness(SpecialistHarness):
    """Mathematics domain specialist with symbolic and numerical capabilities."""

    @property
    def default_tools(self) -> list[str]:
        return [
            "execute_code",
            "file_read",
            "file_write",
        ]

    def _default_system_prompt(self) -> str:
        return (
            "You are the Maths Specialist in the HMAOM mesh. "
            "Your expertise includes symbolic mathematics, numerical methods, "
            "statistics, and proof verification. You have access to a Python "
            "execution environment with numpy, scipy, sympy, and pandas. "
            "Show your work step by step and verify numerical results."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        """Handle mathematics-specific tasks."""
        desc = request.task.description.lower()

        if any(term in desc for term in ["proof", "theorem", "lemma", "axiom", "prove"]):
            return await self._handle_proof(request)
        elif any(term in desc for term in ["integral", "derivative", "differential", "calculus"]):
            return await self._handle_calculus(request)
        elif any(term in desc for term in ["matrix", "eigenvalue", "linear", "vector"]):
            return await self._handle_linear_algebra(request)
        elif any(term in desc for term in ["statistics", "probability", "distribution", "regression", "hypothesis"]):
            return await self._handle_statistics(request)
        else:
            return await self._handle_general_maths(request)

    async def _handle_proof(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="verify",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="maths",
                relevance_score=0.95,
                content="Formal proof verification and logical structure analysis.",
                memory_keys=["maths/proofs"],
            ),
        )
        return result.result

    async def _handle_calculus(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="maths",
                relevance_score=0.95,
                content="Symbolic integration/differentiation using SymPy.",
                memory_keys=["maths/calculus"],
            ),
        )
        return result.result

    async def _handle_linear_algebra(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="maths",
                relevance_score=0.95,
                content="Matrix operations, eigenvalues, SVD using NumPy.",
                memory_keys=["maths/linear-algebra"],
            ),
        )
        return result.result

    async def _handle_statistics(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="maths",
                relevance_score=0.95,
                content="Statistical analysis using SciPy and pandas.",
                memory_keys=["maths/statistics"],
            ),
        )
        return result.result

    async def _handle_general_maths(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="maths",
                relevance_score=0.8,
                content="General mathematical computation and analysis.",
            ),
        )
        return result.result
