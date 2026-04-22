"""HMAOM Specialist Sub-Harnesses.

Domain-isolated execution environments with deep skill registries.
"""

from hmaom.specialists.base import SpecialistHarness
from hmaom.specialists.finance import FinanceHarness
from hmaom.specialists.maths import MathsHarness
from hmaom.specialists.code import CodeHarness
from hmaom.specialists.physics import PhysicsHarness
from hmaom.specialists.research import ResearchHarness
from hmaom.specialists.reporter import ReporterHarness

__all__ = [
    "SpecialistHarness",
    "FinanceHarness",
    "MathsHarness",
    "CodeHarness",
    "PhysicsHarness",
    "ResearchHarness",
    "ReporterHarness",
]
