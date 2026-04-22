"""HMAOM Quick Start Example.

Demonstrates all 5 phases of the Hierarchical Multi-Agent Orchestration Mesh:
- Phase 1: Single-domain routing
- Phase 2: Task decomposition and adaptive routing
- Phase 3: Global budget management
- Phase 4: User modeling and personalization
- Phase 5: Metrics, load balancing, and monitoring
"""

from __future__ import annotations

import asyncio

from hmaom.gateway.router import GatewayRouter


async def main():
    router = GatewayRouter()
    await router.start()

    print("=" * 60)
    print("HMAOM Gateway Router — All 5 Phases Demo")
    print("=" * 60)

    # ── Phase 1: Single-domain routing ──
    print("\n--- Phase 1: Single-Domain Routing ---")

    print("\n1. Finance")
    result = await router.route("Calculate the Black-Scholes option price for AAPL")
    print(f"   Domain:     {result['routing_decision']['primary_domain']}")
    print(f"   Mode:       {result['routing_decision']['routing_mode']}")
    print(f"   Result:     {result['result']}")

    print("\n2. Maths")
    result = await router.route("Solve the eigenvalues for this symmetric matrix")
    print(f"   Domain:     {result['routing_decision']['primary_domain']}")
    print(f"   Mode:       {result['routing_decision']['routing_mode']}")
    print(f"   Result:     {result['result']}")

    print("\n3. Code")
    result = await router.route("Debug this Python function that keeps crashing")
    print(f"   Domain:     {result['routing_decision']['primary_domain']}")
    print(f"   Mode:       {result['routing_decision']['routing_mode']}")
    print(f"   Result:     {result['result']}")

    # ── Phase 2: Task decomposition ──
    print("\n--- Phase 2: Task Decomposition ---")
    print("\n4. Complex cross-domain request (triggers decomposition)")
    result = await router.route(
        "Calculate the Black-Scholes price for an option, then write Python code "
        "to plot the Greeks, and finally generate a report summarizing the risk metrics."
    )
    print(f"   Primary:    {result['routing_decision']['primary_domain']}")
    print(f"   Mode:       {result['routing_decision']['routing_mode']}")
    print(f"   Sub-results: {len(result['specialist_results'])}")
    for i, sr in enumerate(result["specialist_results"][:3]):
        status = sr.get("status", "?")
        snippet = str(sr.get("result", ""))[:60]
        print(f"      [{i}] {status} — {snippet}")

    # ── Phase 2: Adaptive routing ──
    print("\n--- Phase 2: Adaptive Routing (explore-then-route) ---")
    print("\n5. Explore-then-route request")
    result = await router.route(
        "Explore the best approach for a project combining physics simulation and code visualization"
    )
    print(f"   Primary:    {result['routing_decision']['primary_domain']}")
    print(f"   Mode:       {result['routing_decision']['routing_mode']}")
    print(f"   Sub-results: {len(result['specialist_results'])}")
    print("   (Adaptive routing starts with an explore subagent, then adjusts routing)")

    # ── Phase 4: User model / personalization ──
    print("\n--- Phase 4: User Model & Personalization ---")
    session_id = "demo-user-42"

    print(f"\n6. First interaction (session_id={session_id})")
    result = await router.route(
        "Analyze the volatility of this stock portfolio", session_id=session_id
    )
    print(f"   Domain:     {result['routing_decision']['primary_domain']}")
    print(f"   Confidence: {result['routing_decision']['confidence']}")

    print(f"\n7. Second interaction — user model boosts familiar domain")
    result = await router.route(
        "Calculate Value at Risk for a diversified portfolio", session_id=session_id
    )
    print(f"   Domain:     {result['routing_decision']['primary_domain']}")
    print(f"   Confidence: {result['routing_decision']['confidence']}")
    print("   (Repeated finance requests train the user model for this session)")

    # ── Phase 3 & 5: Status (budget, metrics, load balancer) ──
    print("\n--- Phase 3 & 5: System Status ---")
    print("\n8. Gateway status")
    status = await router.status()
    print(f"   Gateway:      {status['gateway']['name']}")
    print(f"   Active reqs:  {status['gateway']['active_requests']}")
    print(f"   Specialists:  {list(status['specialists'].keys())}")

    print("\n   Phase 3 — Global Budget:")
    budget = status.get("budget", {})
    print(f"      tokens_remaining:   {budget.get('tokens_remaining', 'N/A')}")
    print(f"      cost_remaining_usd: {budget.get('cost_remaining_usd', 'N/A')}")

    print("\n   Phase 5 — Metrics & Load Balancer:")
    metrics = status.get("metrics", {})
    print(f"      metrics_available:  {'prometheus' in metrics}")
    lb = status.get("load_balancer", {})
    for domain, info in lb.items():
        print(f"      {domain}: replicas={info.get('replicas', 0)}, health={info.get('replica_health', {})}")

    # ── Hire trigger monitoring note ──
    print("\n--- Hire Trigger Monitoring ---")
    print("\n9. The gateway continuously monitors for repeated low-confidence")
    print("   or out-of-domain requests. When thresholds are crossed,")
    print("   a hire_trigger event is included in the route result,")
    print("   suggesting new specialist domains to onboard.")

    await router.stop()
    print("\n" + "=" * 60)
    print("Demo complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
