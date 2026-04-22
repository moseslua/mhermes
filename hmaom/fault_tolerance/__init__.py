"""HMAOM Fault Tolerance.

Four-level escalation, retry logic, recovery orchestration, and human escalation.
"""

from hmaom.fault_tolerance.recovery import RecoveryOrchestrator, EscalationLevel
from hmaom.fault_tolerance.human_escalation import (
    HumanEscalation,
    EscalationChannel,
    CLIPauseChannel,
    SlackChannel,
    EmailChannel,
    EscalationRecord,
)

__all__ = [
    "RecoveryOrchestrator",
    "EscalationLevel",
    "HumanEscalation",
    "EscalationChannel",
    "CLIPauseChannel",
    "SlackChannel",
    "EmailChannel",
    "EscalationRecord",
]
