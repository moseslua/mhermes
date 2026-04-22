# Hierarchical Multi-Agent Orchestration Mesh (HMAOM)

A production-grade, fault-tolerant architecture for hierarchical multi-agent orchestration built atop hermes-agent. Implements a **Mixture-of-Experts (MoE) routing pattern** where a lightweight gateway harness distributes tasks across domain-isolated specialist sub-harnesses, enabling recursive subagent spawning with strict guardrails.

## Architecture

```
                    +------------------+
                    |      USER        |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  +-------------+  |
                    |  |   INTENT    |  |
                    |  | CLASSIFIER  |  |
                    |  +------+------+  |
                    |         |         |
                    |  +------v------+  |
                    |  |   TASK      |  |
                    |  | DECOMPOSER  |  |
                    |  +------+------+  |
                    |         |         |
          +---------+  MAIN HARNESS   +----------+
          |         |   (Gateway)     |          |
          |         +--------+--------+          |
          |                  |                   |
          |    +-------------+-------------+     |
          |    |         USER MODEL        |     |
          |    +-------------+-------------+     |
          |                  |                   |
          |  +---------------v---------------+   |
          |  |    GLOBAL BUDGET MANAGER      |   |
          |  +---------------+---------------+   |
          |                  |                   |
   +------v------+   +------v------+   +------v------+
   |   FINANCE   |   |    MATHS    |   |    CODE     |
   | HARNESS xN  |   | HARNESS xN  |   | HARNESS xN  |
   +------+------+   +------+------+   +------+------+
   +------v------+   +------v------+   +------v------+
   |  RESEARCH   |   |   PHYSICS   |   |   REPORTER  |
   | HARNESS xN  |   | HARNESS xN  |   |   HARNESS   |
   +------+------+   +------+------+   +------+------+
          |                  |                   |
          +------------------+----+------------------+
                               |
                    +----------v-----------+
                    |     LOAD BALANCER    |
                    +----------+-----------+
                               |
                    +----------v-----------+
                    |     SYNTHESIS        |
                    |      LAYER           |
                    +----------+-----------+
                               |
                    +----------v-----------+
                    |  METRICS COLLECTOR   |
                    +----------+-----------+
                               |
                    +----------v-----------+
                    |   STRUCTURED OUTPUT  |
                    +----------------------+
```

## Quick Start

```python
import asyncio
from hmaom.gateway.router import GatewayRouter

async def main():
    router = GatewayRouter()
    await router.start()

    # Phase 1: Single-domain routing
    result = await router.route("Calculate the Black-Scholes option price for AAPL")
    print(f"Finance: {result['routing_decision']['primary_domain']}")

    # Phase 2: Task decomposition (cross-domain)
    result = await router.route(
        "Calculate option price, then write Python to plot the Greeks, "
        "and generate a risk report"
    )
    print(f"Decomposed into {len(result['specialist_results'])} sub-results")

    # Phase 2: Adaptive routing (explore-then-route)
    result = await router.route(
        "Explore the best approach for combining physics simulation and code visualization"
    )
    print(f"Adaptive mode: {result['routing_decision']['routing_mode']}")

    # Phase 4: Session-aware routing (user model)
    result = await router.route(
        "Debug this Python function",
        session_id="user-123"
    )
    print(f"Personalized route: {result['routing_decision']['primary_domain']}")

    # Phase 3 & 5: System status (budget, metrics, load balancer)
    status = await router.status()
    print(f"Budget remaining: {status['budget']['tokens_remaining']} tokens")
    print(f"Load balancer: {list(status['load_balancer'].keys())}")

    await router.stop()

asyncio.run(main())
```

## Components

### Phase 1: Core Infrastructure

#### Gateway Router (`hmaom/gateway/`)
- **Intent Classifier**: Dual-classifier (SLM + LLM fallback) with keyword/regex/semantic routing
- **Routing Modes**: Single, Parallel, Sequential, Adaptive

#### Specialist Harnesses (`hmaom/specialists/`)
Each specialist is a domain-isolated execution environment:
- **Finance**: Quant analysis, risk modeling, market data
- **Maths**: Symbolic math, numerical methods, statistics
- **Code**: Software engineering, debugging, architecture
- **Physics**: Thermodynamics, mechanics, simulations
- **Research**: Web search, paper analysis, data collection

#### Protocol Layer (`hmaom/protocol/`)
- **Message Bus**: Structured inter-agent communication (SQLite-backed)
- **Spawn Protocol**: Hierarchical spawning with depth/token/time/cost budgets
- **Schemas**: Pydantic models for all message types

#### State Management (`hmaom/state/`)
- **State Store**: Hierarchical key-value store with access control
- **Checkpoints**: Resumable execution after failure
- **Memory Manager**: Three-layer architecture (Working / Session / Long-term)

#### Observability (`hmaom/observability/`)
- **Distributed Tracing**: Correlation-ID propagation across the entire tree
- **Circuit Breakers**: Per-specialist failure isolation
- **Health Monitor**: Stuck detection and queue depth tracking

#### Fault Tolerance (`hmaom/fault_tolerance/`)
- **Four-Level Escalation**: Retry → Replan → Decompose → Escalate to user
- **Recovery Orchestrator**: Automatic recovery strategies per failure type

### Phase 2: Task Decomposition & Synthesis

- **Task Decomposer** (`hmaom/gateway/decomposer.py`): Breaks cross-domain tasks into subtasks with dependency graphs; detects circular dependencies
- **Reporter Harness** (`hmaom/specialists/reporter.py`): Document generation, cross-domain synthesis, conflict detection and resolution
- **Reporter Debate Mode** (`hmaom/specialists/reporter.py`): Adversarial multi-round debate between reporter instances for high-confidence synthesis
- **Adaptive Routing** (`hmaom/gateway/router.py`): Explore-then-adjust routing with domain hint parsing; automatically selects routing mode based on task complexity

### Phase 3: Global Budget & Context Management

- **Global Budget Manager** (`hmaom/state/budget_manager.py`): Enforces global token, cost, and concurrent-tree limits across all spawn trees; supports headroom checks and tree kill operations
- **Context Slicer** (`hmaom/state/context_slicer.py`): Splits long contexts into bounded slices on sentence boundaries; merges overlapping slices with relevance scoring

### Phase 4: Learning Loop & User Modeling

- **Hire Activation Triggers** (`hmaom/hire/triggers.py`): Threshold-based triggers for automatic specialist creation when low-confidence or out-of-domain patterns exceed configured thresholds
- **User Model** (`hmaom/state/user_model.py`): Per-session preference tracking with domain success-rate EMA, rolling average confidence, and routing suggestions based on user history and query keywords

### Phase 5: Horizontal Scaling & Observability

- **Specialist Pool** (`hmaom/observability/pool.py`): Per-domain replica management with health tracking and max-replica limits
- **Metrics Collector** (`hmaom/observability/metrics.py`): Counter, gauge, and histogram metrics with Prometheus-compatible output and label support
- **Load Balancer** (`hmaom/gateway/load_balancer.py`): Multi-strategy routing (round-robin, least-loaded, healthiest, random) across specialist replicas; dynamic scale-up/scale-down with health exclusion

### Integrations

- **Specialist Hire CLI** (`hmaom/hire/`): Full hire pipeline — observation logging, gap analysis, config generation, harness creation, and persistence
- **MiroAlligator** (`hmaom/integrations/miroalligator.py`): Provider resolution with environment fallback and model mapping
- **AgentFlow Bridge** (`hmaom/integrations/agentflow.py`): Graph builder API for AgentFlow orchestration with credential caching and environment injection

## Configuration

```python
from hmaom.config import HMAOMConfig

config = HMAOMConfig.default()
# Phase 1-2 core settings
config.spawn.max_depth = 4
config.spawn.max_cost_usd = 5.0
config.gateway.slm_model = "qwen2.5-7b"

# Phase 3: Global budget and context slicing
config.budget.max_global_tokens = 1_000_000
config.budget.max_global_cost_usd = 50.0
config.budget.max_concurrent_trees = 10

# Phase 4: User modeling and hire triggers
config.user_model.enabled = True
config.user_model.prune_inactive_days = 30
config.hire_triggers.enabled = True
config.hire_triggers.confidence_threshold = 0.6
config.hire_triggers.min_observations = 5

# Phase 5: Load balancing and metrics
config.load_balancer.enabled = True
config.load_balancer.strategy = "least_loaded"
config.load_balancer.max_replicas_per_domain = 3
config.metrics.enabled = True
config.metrics.prometheus_port = 9090

router = GatewayRouter(config=config)

## Docker Deployment

```bash
cd hmaom
docker-compose up -d
```

This starts:
- Gateway router on port 8080
- All 6 specialist harnesses
- Redis (optional message bus backend)
- Prometheus + Grafana for monitoring

## Design Principles

1. **Gateway is dumb by design**: The main harness only routes. It never executes domain logic.
2. **Context slicing over full context**: Never pass full parent context to children.
3. **Structured over prompt-based communication**: All inter-agent communication uses JSON Schema.
4. **Budgets are protocol-level**: Token, time, and cost budgets are enforced at the protocol level.
5. **Synthesis is first-class**: The synthesis layer is a dedicated harness with its own skills.
6. **Fault isolation at every boundary**: Every component can fail independently without cascading.

## Phase Status

### Phase 1: Complete (45 tests)
- [x] Gateway Router with intent classification
- [x] First 3 specialists (Finance, Maths, Code)
- [x] Structured message bus
- [x] Distributed tracing infrastructure
- [x] State management (3-layer memory)
- [x] Fault tolerance (escalation, circuit breakers)
- [x] Security sandboxing

### Phase 2: Complete (18 tests)
- [x] Task Decomposer with dependency graph and circular-dependency guard
- [x] Reporter Harness for cross-domain synthesis
- [x] Reporter Debate Mode (adversarial multi-round validation)
- [x] Adaptive Routing (explore-then-adjust with complexity detection)

### Phase 3: Complete (21 tests)
- [x] Global Budget Manager (token/cost/tree limits with headroom checks)
- [x] Context Slicer (sentence-boundary splitting with overlap merging)

### Phase 4: Complete (26 tests)
- [x] Hire Activation Triggers (threshold-based automatic specialist creation)
- [x] User Model (per-session preference tracking with success-rate EMA)

### Phase 5: Complete (18 tests)
- [x] Specialist Pool (per-domain replica management with health tracking)
- [x] Metrics Collector (counter/gauge/histogram with Prometheus output)
- [x] Load Balancer (round-robin, least-loaded, healthiest, random strategies)

**Total: 223 tests passing**
## License

MIT
