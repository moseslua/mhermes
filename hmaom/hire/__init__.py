"""HMAOM Specialist Hire system.

Observes routing decisions, detects coverage gaps, and auto-creates new
specialists when usage patterns cross defined thresholds.
"""

from hmaom.hire.analyzer import HireAnalyzer, HireSuggestion
from hmaom.hire.creator import HireCreator
from hmaom.hire.observer import HireObserver
from hmaom.hire.persistence import HireDecision, HireObservation, HirePersistence
from hmaom.hire.triggers import HireActivationTriggers, HireTriggerConfig, HireTriggerEvent

__all__ = [
    "HireActivationTriggers",
    "HireAnalyzer",
    "HireCreator",
    "HireDecision",
    "HireObservation",
    "HireObserver",
    "HirePersistence",
    "HireSuggestion",
    "HireTriggerConfig",
    "HireTriggerEvent",
]