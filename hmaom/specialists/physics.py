"""HMAOM Physics Specialist.

Thermodynamics, mechanics, simulations, unit analysis.
"""

from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
from hmaom.specialists.base import SpecialistHarness


class PhysicsHarness(SpecialistHarness):
    """Physics domain specialist with simulation capabilities."""

    @property
    def default_tools(self) -> list[str]:
        return [
            "execute_code",
            "web_search",
            "file_read",
            "file_write",
        ]

    def _default_system_prompt(self) -> str:
        return (
            "You are the Physics Specialist in the HMAOM mesh. "
            "Your expertise includes thermodynamics, mechanics, "
            "electromagnetism, and computational physics simulations. "
            "You have access to a Python execution environment with "
            "NumPy, SciPy, and matplotlib. Always include units and "
            "dimensional analysis in your answers."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        desc = request.task.description.lower()

        if any(term in desc for term in ["thermo", "entropy", "heat", "temperature", "energy"]):
            return await self._handle_thermodynamics(request)
        elif any(term in desc for term in ["mechanic", "force", "motion", "kinematic", "dynamic"]):
            return await self._handle_mechanics(request)
        elif any(term in desc for term in ["simulate", "simulation", "model"]):
            return await self._handle_simulation(request)
        else:
            return await self._handle_general_physics(request)

    async def _handle_thermodynamics(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="physics",
                relevance_score=0.95,
                content="Thermodynamic laws and entropy calculations.",
                memory_keys=["physics/thermo"],
            ),
        )
        return result.result

    async def _handle_mechanics(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="physics",
                relevance_score=0.95,
                content="Classical mechanics: Newtonian, Lagrangian, Hamiltonian.",
                memory_keys=["physics/mechanics"],
            ),
        )
        return result.result

    async def _handle_simulation(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="physics",
                relevance_score=0.95,
                content="Computational physics simulation setup.",
                memory_keys=["physics/simulation"],
            ),
        )
        return result.result

    async def _handle_general_physics(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="physics",
                relevance_score=0.8,
                content="General physics inquiry.",
            ),
        )
        return result.result
