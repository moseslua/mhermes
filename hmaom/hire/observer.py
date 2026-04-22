"""HMAOM Specialist Hire observer.

Attaches to GatewayRouter.route() to log every routing interaction.
"""

from __future__ import annotations

from typing import Any, Optional

from hmaom.hire.persistence import HirePersistence


class HireObserver:
    """Observes routing decisions and persists them for pattern analysis.

    Attach to GatewayRouter; after each route() call, invoke observe()
    to record the interaction.
    """

    def __init__(self, persistence: Optional[HirePersistence] = None) -> None:
        self.persistence = persistence or HirePersistence()

    def observe(self, user_input: str, result: dict[str, Any]) -> None:
        """Log a routing result.

        Args:
            user_input: The original user request text.
            result: The dict returned by GatewayRouter.route().
        """
        routing_decision = result.get("routing_decision", {})
        specialist_results = result.get("specialist_results", [])

        # Derive specialist_used from routing decision or results
        primary_domain = routing_decision.get("primary_domain", "unknown")
        secondary_domains = routing_decision.get("secondary_domains", [])
        if secondary_domains:
            specialist_used = f"{primary_domain}+{','.join(secondary_domains)}"
        else:
            specialist_used = str(primary_domain)

        # Determine result status
        if not specialist_results:
            result_status = "no_specialists"
        else:
            statuses = [r.get("status", "unknown") for r in specialist_results]
            failures = [s for s in statuses if s != "success"]
            if failures and "success" in statuses:
                result_status = "partial"
            elif failures:
                # Distinguish out-of-domain / missing specialist
                errors = [r.get("error", "") for r in specialist_results]
                if any("No specialist" in str(e) for e in errors):
                    result_status = "out_of_domain"
                else:
                    result_status = "failure"
            else:
                result_status = "success"

        self.persistence.log_observation(
            user_input=user_input,
            routing_decision=routing_decision,
            specialist_used=specialist_used,
            result_status=result_status,
        )
