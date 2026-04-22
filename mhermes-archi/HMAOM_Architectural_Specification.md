# Hierarchical Multi-Agent Orchestration Mesh (HMAOM)
## Architectural Specification v1.0

---

## Executive Summary

This document specifies a production-grade, fault-tolerant architecture for a hierarchical multi-agent orchestration system built atop oh-my-pi. The design implements a **Mixture-of-Experts (MoE) routing pattern** where a lightweight gateway harness distributes 4,000+ skills across domain-isolated specialist sub-harnesses, enabling recursive subagent spawning with strict guardrails.

**Key Design Principles:**
- **Gateway Decomposition**: The main harness is purely a router/intent-classifier, never executing domain logic
- **Domain Isolation**: Each specialist maintains its own skill registry, tool sandbox, and memory space
- **Controlled Recursion**: Recursive spawning is treated as a structured concurrency primitive with hard limits
- **Deterministic Synthesis**: Cross-domain results are reconciled through a typed message bus, not prompt injection
- **Failure Containment**: Fault isolation at every layer with automatic escalation and recovery

**Reference Architectures Integrated:**
- **oh-my-pi** (can1357): Core harness, Task Tool, subagent isolation, Agent Control Center
- **OpenClaw**: Gateway pattern, channel adapters, context assembly, session management
- **Hermes Agent**: Learning loop, multi-agent coordination, adversarial debate, skill sharing

---

## 1. System Architecture Overview

### 1.1 High-Level Topology

The system follows a hub-and-spoke topology centered on the Gateway Router:

```
                    +------------------+
                    |      USER        |
                    |  (Any Channel)   |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  +-------------+  |
                    |  |   INTENT    |  |
                    |  | CLASSIFIER  |  |
                    |  |  (SLM/LLM)  |  |
                    |  +------+------+  |
                    |        |         |
          +---------+  MAIN HARNESS   +----------+
          |         |   (Gateway)     |          |
          |         |   SOUL.md       |          |
          |         +--------+--------+          |
          |                  |                   |
   +------v------+   +------v------+   +------v------+
   |   FINANCE   |   |    MATHS    |   |   PHYSICS   |
   |  HARNESS    |   |   HARNESS   |   |   HARNESS   |
   |             |   |             |   |             |
   | +---------+ |   | +---------+ |   | +---------+ |
   | | Skills/ | |   | | Skills/ | |   | | Skills/ | |
   | | Tools   | |   | | Tools   | |   | | Tools   | |
   | | Memory  | |   | | Memory  | |   | | Memory  | |
   | | Sandbox | |   | | Sandbox | |   | | Sandbox | |
   | +----+----+ |   | +----+----+ |   | +----+----+ |
   |      |      |   |      |      |   |      |      |
   |   +--v--+   |   |   +--v--+   |   |   +--v--+   |
   |   |Sub- |   |   |   |Sub- |   |   |   |Sub- |   |
   |   |Agent|   |   |   |Agent|   |   |   |Agent|   |
   |   +--v--+   |   |   +--v--+   |   |   +--v--+   |
   |      |      |   |      |      |   |      |      |
   |   +--v--+   |   |   +--v--+   |   |   +--v--+   |
   |   |Sub- |   |   |   |Sub- |   |   |   |Sub- |   |
   |   |Agent|   |   |   |Agent|   |   |   |Agent|   |
   |   +-----+   |   |   +-----+   |   |   +-----+   |
   +------+------+   +------+------+   +------+------+
          |                  |                   |
          +------------------+----+------------------+
                               |
                    +----------v-----------+
                    |     SYNTHESIS        |
                    |      LAYER           |
                    |  (Reporter Harness)  |
                    +----------+-----------+
                               |
                    +----------v-----------+
                    |   STRUCTURED OUTPUT  |
                    +----------------------+
```

### 1.2 Component Registry

| Component | Role | Tech Stack | Failure Mode |
|-----------|------|------------|--------------|
| **Gateway Router** | Intent classification, task decomposition, routing | oh-my-pi main harness + SLM classifier | Misrouting to wrong specialist |
| **Specialist Harness** | Domain-isolated execution environment with deep skill registry | oh-my-pi sub-harness per domain | Tool error or hallucination within domain |
| **Subagent Spawner** | Controlled recursive agent creation within specialists | oh-my-pi Task Tool + custom isolation | Depth explosion, state fragmentation |
| **Message Bus** | Structured inter-agent communication with schemas | JSON Schema + gRPC/WebSocket | Message loss, schema mismatch |
| **Synthesis Layer** | Cross-domain result aggregation and reconciliation | Dedicated "Reporter" harness | Incomplete context for reconciliation |
| **State Store** | Shared persistence for distributed agent state | SQLite/Redis with vector search | Data inconsistency, split-brain |
| **Observability** | Distributed tracing, checkpointing, health monitoring | OpenTelemetry + custom dashboard | Blind spots in recursive trees |

---

## 2. The Gateway Router (Main Harness)

### 2.1 Design Philosophy

The main harness is **intentionally stripped**. It does not execute domain logic, load skills, or call tools. It is purely a control plane with three responsibilities:

1. **Intent Classification**: Determine which specialist domain(s) a task requires
2. **Task Decomposition**: Break cross-domain tasks into routed subtasks
3. **Orchestration**: Manage the lifecycle of specialist executions and synthesis

### 2.2 Intent Classification System

**Dual-Classifier Architecture:**

```
User Input
    |
    v
+---------------------+     +---------------------+
|   Fast SLM Router   |---->|   Fallback LLM      |
|   (local, <50ms)    |     |   Router (cloud)    |
|                     |     |                     |
| - Keyword match     |     | - Semantic          |
| - Regex patterns    |     |   classification    |
| - Embedding         |     | - Multi-label       |
|   similarity        |     |   routing           |
+---------------------+     +---------------------+
    |                             |
    +-------------+---------------+
                  v
         +-----------------+
         | Routing Decision |
         | - Single domain  |
         | - Multi-domain   |
         | - Meta-task      |
         +-----------------+
```

**SLM Router Specifications:**
- Model: Lightweight local model (e.g., Phi-4, Llama-3.2-3B, or Qwen2.5-7B)
- Latency budget: <50ms for classification
- Training data: Historical routing decisions + synthetic multi-domain edge cases
- Confidence threshold: If confidence <0.85, escalate to LLM fallback

**Classification Schema:**
```typescript
interface RoutingDecision {
  primaryDomain: Domain;        // e.g., "finance", "maths", "physics"
  secondaryDomains: Domain[];   // Cross-domain dependencies
  taskType: "analytical" | "creative" | "synthetic" | "meta";
  routingMode: "single" | "parallel" | "sequential" | "adaptive";
  estimatedComplexity: 1-10;    // For recursion depth budgeting
  requiredSynthesis: boolean;   // Whether results need cross-domain merging
}
```

### 2.3 Routing Modes

| Mode | Description | Example |
|------|-------------|---------|
| **Single** | One specialist handles the entire task | "Calculate Black-Scholes option price" -> Finance |
| **Parallel** | Multiple specialists work simultaneously | "Compare financial risk models and write a report" -> Finance + Maths + Reporter |
| **Sequential** | Specialists feed into each other | "Model the thermodynamics of this trading strategy" -> Physics -> Finance |
| **Adaptive** | Dynamic routing based on intermediate results | "Research this topic and analyze the data" -> explore subagent decides routing |

### 2.4 Integration with oh-my-pi

The Gateway leverages oh-my-pi's native capabilities:
- **AGENTS.md**: Defines gateway-specific behavior (routing rules, not domain rules)
- **SOUL.md**: Gateway personality (helpful router, not executor)
- **TTSR Rules**: Pattern-triggered routing shortcuts (e.g., "thermodynamics of" -> Physics first)
- **Session Management**: Each routed task gets a session for tracking
- **Custom Slash Commands**: `/route`, `/status`, `/kill-tree` for manual control

---

## 3. Specialist Sub-Harnesses

### 3.1 Harness Structure

Each specialist is a standalone oh-my-pi instance with:

```
specialist/
|-- .omp/
|   |-- agents/              # Specialist-specific subagent definitions
|   |   |-- explore.agent
|   |   |-- execute.agent
|   |   |-- verify.agent
|   |-- SOUL.md             # Specialist personality + constraints
|   |-- AGENTS.md           # Specialist-specific dev rules
|   |-- TOOLS.md            # Tool conventions for this domain
|-- skills/                  # Domain-specific skill library
|   |-- skill-a/
|   |   |-- SKILL.md
|   |-- skill-b/
|   |   |-- SKILL.md
|   |-- ...
|-- memory/                  # Vector-indexed domain memory
|   |-- embeddings.sqlite
|   |-- long-term/
|-- tools/                   # Domain-specific tool implementations
|   |-- custom-tools.ts
|   |-- sandbox/
|-- config.json              # Harness configuration
```

### 3.2 Domain Isolation Boundaries

| Boundary | Mechanism | Purpose |
|----------|-----------|---------|
| **Process** | Separate oh-my-pi process per specialist | Crash isolation, resource limits |
| **Filesystem** | FUSE overlay / git worktree (from oh-my-pi) | Prevent cross-domain file corruption |
| **Network** | Separate network namespaces (optional) | Isolate browser automation sessions |
| **Memory** | Separate SQLite databases per domain | Prevent cross-domain memory leakage |
| **Tool Registry** | Only domain-relevant tools loaded | Reduce context bloat (~1,000 vs 4,000 skills) |
| **Model** | Per-agent model overrides | Use cheaper models for simple domains |

### 3.3 Pre-Defined Specialists

| Specialist | Domain Scope | Bundled Subagents | Model Override |
|------------|-------------|-------------------|----------------|
| **Finance** | Quant analysis, risk modeling, market data, portfolio optimization | explore, calculate, verify, backtest | Claude Sonnet |
| **Maths** | Symbolic math, numerical methods, statistics, proof verification | explore, calculate, prove, verify | Claude Sonnet |
| **Physics** | Thermodynamics, mechanics, simulations, unit analysis | explore, simulate, calculate, verify | Claude Sonnet |
| **Code** | Software engineering, debugging, architecture, review | plan, implement, review, test, debug | Claude Opus |
| **Research** | Web search, paper analysis, data collection, synthesis | explore, search, extract, summarize | Claude Sonnet |
| **Reporter** | Document generation, formatting, cross-domain synthesis | draft, review, format, synthesize | Claude Sonnet |

### 3.4 Custom Agent Creation

Following oh-my-pi's Agent Control Center pattern, specialists support AI-powered agent creation:

```typescript
// Specialist receives task -> determines needed subagent type
// -> Either uses bundled agent or creates custom one

interface AgentCreationRequest {
  name: string;
  role: string;
  tools: string[];           // From specialist's tool registry
  model?: string;            // Override default
  isolation: "none" | "git-worktree" | "fuse-overlay";
  maxDepth: number;          // Recursion limit for this agent
  parentContext: ContextSlice; // Relevant context from parent
}
```

### 3.5 Skill Distribution Strategy

Instead of 4,000 skills in one harness:

| Specialist | Skill Count | Loading Strategy |
|------------|-------------|------------------|
| Finance | ~800 | Lazy-load by subtask (risk, derivatives, portfolio, etc.) |
| Maths | ~600 | Lazy-load by area (calculus, linear algebra, stats, etc.) |
| Physics | ~500 | Lazy-load by domain (thermo, mechanics, EM, etc.) |
| Code | ~1,200 | Lazy-load by language/framework |
| Research | ~400 | Lazy-load by source type |
| Reporter | ~300 | Load all (small, formatting-focused) |
| Gateway | ~200 | Routing + meta-skills only |

**Total**: ~4,000 skills, but any single agent sees max ~1,200 (Code specialist at peak)

---

## 4. Recursive Subagent Spawning System

### 4.1 The Core Problem

Recursive spawning is the highest-value and highest-risk feature. Without guardrails, it becomes uncontrolled concurrency with exponential token cost and state fragmentation.

### 4.2 Hierarchical Spawn Control

```
Level 0: Gateway Router (Main Harness)
    |
    | spawn(maxDepth=3)
    v
Level 1: Specialist Harness (e.g., Finance)
    |
    | spawn(maxDepth=2)
    v
Level 2: Subagent (e.g., explore)
    |
    | spawn(maxDepth=1)
    v
Level 3: Leaf Subagent (e.g., data extraction)
    |
    | NO FURTHER SPAWNING
    v
  RESULT
```

**Hard Limits (enforced at the protocol level):**

| Parameter | Default | Max | Enforcement |
|-----------|---------|-----|-------------|
| `MAX_DEPTH` | 3 | 5 | Protocol rejects spawn requests exceeding depth |
| `MAX_BREADTH` | 10 parallel | 50 | Concurrency semaphore per parent |
| `MAX_TOKENS_PER_TREE` | 100K | 500K | Token budget manager kills tree |
| `MAX_WALL_TIME` | 5 min | 30 min | Timeout kills entire branch |
| `MAX_COST_USD` | $2.00 | $10.00 | Cost accumulator kills tree |

### 4.3 Spawn Request Protocol

```typescript
interface SpawnRequest {
  // Identity
  spawnId: string;              // UUID for this spawn
  parentId: string;             // Parent agent ID
  correlationId: string;        // Traces back to root request
  depth: number;                // Current depth in tree

  // Context
  task: TaskDescription;        // Structured task definition
  contextSlice: ContextSlice;   // Relevant context (not full parent context)
  memoryKeys: string[];         // Keys to shared memory entries

  // Constraints
  constraints: {
    maxDepth: number;           // Remaining depth budget
    maxTokens: number;          // Token budget for this subtree
    maxTimeMs: number;          // Wall time budget
    tools: string[];            // Allowed tool whitelist
  };

  // Return format
  outputSchema: JSONSchema;     // Structured output requirement
}

interface SpawnResult {
  spawnId: string;
  status: "success" | "failure" | "timeout" | "killed";
  result: unknown;              // Validated against outputSchema
  tokensUsed: number;
  timeMs: number;
  checkpointUrl: string;        // For resumable execution
  childSpawns: SpawnResult[];   // Recursive results (tree structure)
}
```

### 4.4 Context Slicing (Critical Innovation)

Instead of passing full parent context to children (which causes exponential context growth), implement **context slicing**:

```
Full Parent Context (100K tokens)
    |
    |-- Relevant slice for child A (5K tokens)
    |       |-- Child A's full output (returned to parent)
    |
    |-- Relevant slice for child B (5K tokens)
    |       |-- Child B's full output (returned to parent)
    |
    |-- Relevant slice for child C (5K tokens)
            |-- Child C's full output (returned to parent)

Parent synthesizes children outputs (15K tokens) + original context
= Only 115K tokens total, not 400K+
```

**ContextSlice selection methods:**
1. **Semantic search**: Find most relevant context chunks for the child's task
2. **Explicit keys**: Parent specifies which memory entries child needs
3. **Lazy loading**: Child can request additional context via `request_context` tool

### 4.5 The Task Tool Integration (oh-my-pi Native)

oh-my-pi already provides a Task Tool with:
- 6 bundled agents (explore, plan, designer, reviewer, task, quick_task)
- Parallel exploration with real-time streaming
- Isolation backends (git worktrees, fuse-overlay, ProjFS)
- Async background jobs (up to 100 concurrent)
- Full output access via `agent://<id>` resources

**Our Enhancement**: Wrap the native Task Tool with the hierarchical spawn protocol above, adding:
- Depth tracking across the entire tree
- Global token/cost/time budgets
- Structured output schemas
- Automatic checkpointing for recovery

### 4.6 oh-my-pi Native Integration Points

| oh-my-pi Feature | How We Use It | Enhancement |
|-----------------|---------------|-------------|
| Task Tool | Spawn subagents within specialists | Add hierarchical budget tracking |
| Isolation backends | Sandbox subagent execution | Per-domain default isolation |
| `/agents` dashboard | Monitor active agents | Cross-harness tree visualization |
| AI agent creation | Create specialist subagents | Template library per domain |
| Per-agent model overrides | Optimize cost/quality | Automatic model selection |
| `agent://<id>` resources | Access subagent outputs | Schema-validated output streams |

---

## 5. Inter-Agent Communication Protocol

### 5.1 The Message Bus

Don't pass state via prompt injection. Use a structured message bus:

```
+---------------+     +---------------+     +---------------+
|  Specialist   |<--->|  Message Bus  |<--->|  Specialist   |
|  Finance      |     |  (Redis/      |     |   Physics     |
+---------------+     |   SQLite)     |     +---------------+
                      +-------+-------+
                              |
                       +------v------+
                       |  Synthesis   |
                       |    Layer     |
                       +--------------+
```

### 5.2 Message Types

```typescript
interface AgentMessage {
  messageId: string;
  correlationId: string;        // Links to root request
  timestamp: number;
  sender: AgentAddress;         // { harness: string, agent: string, depth: number }
  recipient: AgentAddress | "broadcast" | "synthesis";
  type: MessageType;
  payload: unknown;
}

type MessageType =
  | "task_request"       // Parent -> Child: spawn request
  | "task_result"        // Child -> Parent: structured result
  | "partial_result"     // Child -> Parent: streaming intermediate
  | "context_request"    // Child -> Parent: "I need more context"
  | "context_response"   // Parent -> Child: additional context
  | "error"              // Any -> Parent: failure notification
  | "checkpoint"         // Any -> Bus: persistence checkpoint
  | "synthesis_request"  // Router -> Synthesis: merge results
  | "health_ping";       // Any -> Monitor: heartbeat
```

### 5.3 Communication Levels (Hermes-Inspired)

| Level | Mechanism | Isolation | Use Case |
|-------|-----------|-----------|----------|
| **L0: Isolated** | No sharing, parent relays everything | Maximum | Simple delegation, untrusted inputs |
| **L1: Result Passing** | Upstream results auto-injected downstream | High | Workflow DAGs with sequential deps |
| **L2: Shared Scratchpad** | Read/write shared key-value store | Medium | Complex workflows needing fine-grained sharing |
| **L3: Live Dialogue** | Turn-based agent-to-agent conversation | Low | Debate/review modes (Hermes-style) |

### 5.4 The Synthesis Protocol

```typescript
interface SynthesisRequest {
  correlationId: string;
  sources: AgentResult[];       // Results from all specialists
  synthesisType: "unify" |      // Merge similar results
                 "reconcile" |  // Resolve conflicts
                 "sequential" | // Chain results in order
                 "debate";      // Hermes-inspired adversarial review
  outputSchema: JSONSchema;     // Required output format
  constraints: {
    maxTokens: number;
    requireCitations: boolean;   // Trace claims to source agents
  };
}

interface AgentResult {
  source: AgentAddress;
  result: unknown;
  confidence: number;           // Agent's self-reported confidence
  evidence: Evidence[];         // Supporting data/trace
  caveats: string[];            // Known limitations
}
```

### 5.5 Hermes-Inspired Debate Mode

For synthesis conflicts, implement adversarial debate (from Hermes):

1. Reporter harness detects conflicting results from two specialists
2. Spawns **Proponent Agent** (defends Specialist A's result)
3. Spawns **Opponent Agent** (challenges, defends Specialist B's result)
4. Both agents engage in structured debate with evidence
5. **Judge Agent** (neutral) evaluates and decides
6. Result includes full debate transcript for user review

---

## 6. State Management & Memory

### 6.1 Three-Layer Memory Architecture

```
+-------------------------------------------------------------+
|  Layer 3: Long-Term Memory (Cross-Session, Persistent)      |
|  - Domain-specific knowledge bases                           |
|  - Learned skills (Hermes learning loop)                     |
|  - User preferences and patterns                             |
|  Storage: SQLite + vector embeddings                         |
+-------------------------------------------------------------+
                           ^
                           | (async flush)
+-------------------------------------------------------------+
|  Layer 2: Session Memory (Current Conversation)             |
|  - Conversation history                                    |
|  - Tool call results                                       |
|  - Compacted summaries                                     |
|  Storage: oh-my-pi session files (JSON)                    |
+-------------------------------------------------------------+
                           ^
                           | (real-time)
+-------------------------------------------------------------+
|  Layer 1: Working Memory (Current Turn)                      |
|  - Active context window                                   |
|  - Retrieved skill definitions                             |
|  - Relevant memory chunks                                  |
|  Storage: In-context (LLM prompt)                          |
+-------------------------------------------------------------+
```

### 6.2 Shared State Store

For cross-domain synthesis, specialists write to a shared state store:

```typescript
interface StateEntry {
  key: string;                  // Hierarchical: "finance/risk-model/output"
  value: unknown;
  schema: JSONSchema;           // For validation
  writtenBy: AgentAddress;
  writtenAt: number;
  ttl?: number;                 // Auto-expiry for temporary state
  accessControl: {              // Who can read/write
    read: string[];             // Harness patterns
    write: string[];            // Harness patterns
  };
}
```

### 6.3 Checkpointing & Recovery

Every subagent execution is checkpointed after each tool call:

```
~/.omp/checkpoints/
|-- {correlationId}/
|   |-- checkpoint-001.json    # After tool call 1
|   |-- checkpoint-002.json    # After tool call 2
|   |-- ...
```

**Recovery flow:**
1. Parent detects child failure (timeout, error, bad output)
2. Parent checks last checkpoint
3. Options: Resume from checkpoint / Retry with modified params / Decompose further / Escalate to user

### 6.4 Hermes-Inspired Learning Loop

```
Execute -> Evaluate -> Extract -> Refine -> Retrieve

1. EXECUTE: Specialist completes task
2. EVALUATE: Success? Novel approach? Worth remembering?
3. EXTRACT: Convert reasoning pattern to structured skill
4. REFINE: Compare with existing skills, merge or create new
5. RETRIEVE: Future tasks search skill library first
```

Skills are stored as `SKILL.md` files in the specialist's `skills/` directory and are selectively injected into context based on semantic relevance.

### 6.5 OpenClaw Memory Integration

Adopt from OpenClaw:
- **MEMORY.md**: Long-term curated facts (loaded only in trusted sessions)
- **memory/YYYY-MM-DD.md**: Daily running log
- **Hybrid search**: Vector similarity + BM25 keyword relevance
- **Auto-compaction**: Summarize old conversation parts
- **Memory flush**: Promote durable info before compaction

---

## 7. Fault Tolerance & Recovery

### 7.1 Failure Taxonomy

| Failure Type | Detection | Response |
|-------------|-----------|----------|
| **Tool Error** | Non-zero exit, timeout, malformed output | Retry -> Fallback tool -> Escalate |
| **Hallucination** | Output validation fails schema check | Re-prompt with constraints -> Different model |
| **Misrouting** | Specialist reports "out of domain" | Re-route via LLM fallback -> User confirmation |
| **Infinite Loop** | Stuck detector: no tool calls for N seconds | Kill -> Resume from checkpoint |
| **Budget Exhaustion** | Token/time/cost limit reached | Graceful degradation -> Partial results -> User notify |
| **Cascading Failure** | Multiple specialists fail simultaneously | Circuit breaker -> Simplified single-path execution |
| **Synthesis Conflict** | Specialists disagree irreconcilably | Adversarial debate (L3) -> User arbitration |

### 7.2 Three-Level Escalation (Inspired by Hermes/CAMEL-AI)

```
Level 1: RETRY
  |-- Same agent, same task, try again
  |-- If transient failure (network, timeout)

Level 2: REPLAN
  |-- Meta-agent rewrites task description
  |-- Based on failure reason
  |-- May change approach or tools

Level 3: DECOMPOSE
  |-- Break into smaller subtasks
  |-- Spawn multiple smaller agents
  |-- May change routing strategy

Level 4: ESCALATE (Final)
  |-- Notify user with:
  |   - What was attempted
  |   - What failed
  |   - Partial results
  |   - Suggested next steps
```

### 7.3 Circuit Breaker Pattern

```typescript
interface CircuitBreaker {
  harness: string;              // Which specialist
  failures: number;             // Consecutive failures
  lastFailure: number;          // Timestamp
  state: "closed" | "open" | "half-open";

  // Config
  failureThreshold: 5;          // Open after N failures
  resetTimeoutMs: 30000;        // Try half-open after 30s
  halfOpenMaxCalls: 2;          // Test with N calls in half-open
}
```

When a specialist's circuit is OPEN, tasks are routed to alternative specialists or the Reporter harness with a note about the failure.

### 7.4 Distributed Tracing

Every request gets a correlation ID that propagates through the entire tree:

```
User Request: corr-id = "req-abc-123"
  |-- Gateway Router: corr-id = "req-abc-123", span = "router"
  |     |-- Finance Harness: corr-id = "req-abc-123", span = "finance"
  |     |     |-- Subagent explore: corr-id = "req-abc-123", span = "finance.explore.1"
  |     |     |-- Subagent calculate: corr-id = "req-abc-123", span = "finance.calc.2"
  |     |-- Physics Harness: corr-id = "req-abc-123", span = "physics"
  |     |     |-- Subagent simulate: corr-id = "req-abc-123", span = "physics.sim.1"
  |     |-- Synthesis: corr-id = "req-abc-123", span = "synthesis"
```

All spans are logged with timing, token usage, and status for post-hoc analysis.

---

## 8. Observability & Control

### 8.1 Agent Control Center

oh-my-pi provides an `/agents` dashboard. Extended for multi-harness:

```
+--------------------------------------------------------------+
|  AGENT CONTROL CENTER                                        |
+--------------------------------------------------------------+
|  Active Trees: 3    |    Total Agents: 12    |    Queue: 0  |
+--------------+--------------+--------------+-----------------+
| Gateway      | Finance      | Physics      | Reporter        |
| * 1 active   | * 2 active   | * 1 active   | o idle          |
|              |              |              |                 |
| Router:      | explore-1    | simulate-1   | Last: 2m ago    |
| classify     | #########    | #########    |                 |
|              | calc-2       |              |                 |
|              | ######       |              |                 |
+--------------+--------------+--------------+-----------------+
|  Tree: req-abc-123                                           |
|  |-- router (45ms, 1.2K tokens) [OK]                         |
|  |-- finance (2.3s, 8.5K tokens) [OK]                        |
|  |   |-- explore (1.8s, 4.2K tokens) [OK]                    |
|  |   |-- calc (2.1s, 3.8K tokens) [OK]                       |
|  |-- physics (3.1s, 12K tokens) [OK]                         |
|  |   |-- simulate (2.9s, 11K tokens) [OK]                    |
|  |-- synthesis (1.2s, 6K tokens) [OK]                        |
|                                                              |
|  [Kill Tree] [Checkpoint] [View Logs] [Download Results]     |
+--------------------------------------------------------------+
```

### 8.2 Metrics

| Metric | Type | Alert Threshold |
|--------|------|----------------|
| Routing accuracy | Gauge | <95% triggers retraining |
| Average tree depth | Gauge | >2.5 indicates over-spawning |
| Token cost per request | Counter | >$5 triggers budget review |
| P95 latency | Histogram | >30s triggers performance review |
| Specialist error rate | Gauge per specialist | >5% triggers circuit breaker |
| Synthesis conflict rate | Gauge | >10% indicates routing issues |

---

## 9. Security Model

### 9.1 Sandboxing (Leveraging oh-my-pi)

| Harness Type | Sandbox | Tool Access |
|-------------|---------|-------------|
| Gateway Router | None (no tool execution) | Read-only config |
| Main Specialists | FUSE overlay / git worktree | Domain tools only |
| Reporter | FUSE overlay | Read-only access to all results |
| Subagents | Full isolation (FUSE + network ns) | Whitelisted tools only |

### 9.2 Authentication Between Harnesses

```
Gateway ---mTLS---> Specialists
Specialists ---signed tokens---> Subagents

Each harness has:
- Ed25519 keypair
- Certificate signed by root CA
- Token-based auth for subagent spawning
```

### 9.3 Prompt Injection Defense

- **Input sanitization**: All user inputs normalized via channel adapters (OpenClaw pattern)
- **Tool output validation**: All tool outputs validated against JSON schemas before ingestion
- **Context boundary markers**: Delimiters between context slices to prevent context leakage
- **TTSR Rules**: Pattern-triggered safety rules (from oh-my-pi) that activate when dangerous patterns detected

---

## 10. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)
- [ ] Deploy oh-my-pi main harness as Gateway Router
- [ ] Implement SLM intent classifier
- [ ] Create first 3 specialists (Finance, Maths, Code) with isolated skill registries
- [ ] Implement structured message bus (JSON Schema over WebSocket)
- [ ] Build distributed tracing infrastructure

### Phase 2: Orchestration (Weeks 5-8)
- [ ] Implement task decomposition engine
- [ ] Build synthesis layer (Reporter harness)
- [ ] Add cross-domain routing modes (parallel, sequential, adaptive)
- [ ] Implement checkpointing and recovery
- [ ] Build Agent Control Center dashboard

### Phase 3: Recursion (Weeks 9-12)
- [ ] Implement hierarchical spawn protocol with depth tracking
- [ ] Add global budget management (tokens, time, cost)
- [ ] Build context slicing system
- [ ] Implement stuck detection and automatic intervention
- [ ] Add circuit breakers per specialist

### Phase 4: Intelligence (Weeks 13-16)
- [ ] Implement Hermes-inspired learning loop
- [ ] Build skill extraction and refinement pipeline
- [ ] Add adversarial debate mode for synthesis conflicts
- [ ] Implement user modeling across sessions
- [ ] Performance optimization and load testing

### Phase 5: Scale (Weeks 17-20)
- [ ] Add remaining specialists (Physics, Research, custom domains)
- [ ] Implement horizontal scaling for specialists
- [ ] Build load balancing across specialist replicas
- [ ] Add comprehensive monitoring and alerting
- [ ] Security audit and hardening

---

## 11. Integration Summary: What We Take From Each Reference

### From oh-my-pi (can1357)
| Feature | Usage |
|---------|-------|
| Task Tool | Core subagent spawning mechanism |
| Isolation backends | FUSE overlay / git worktree for sandboxing |
| Agent Control Center | Monitoring dashboard extended cross-harness |
| AI agent creation | Dynamic subagent definition per specialist |
| Per-agent model overrides | Cost optimization per task type |
| TTSR Rules | Safety guardrails triggered by patterns |
| Hash-anchored edits | Precise file modifications |
| Python/Browser tools | Available in all specialists |
| Session management | oh-my-pi native session persistence |

### From OpenClaw
| Feature | Usage |
|---------|-------|
| Gateway pattern | Hub-and-spoke architecture |
| Intent classification | Channel adapter normalization |
| Context assembly | Dynamic prompt composition |
| Memory system | Hybrid vector + keyword search |
| Session types | Main/DM/Group with different permissions |
| Heartbeat mechanism | Proactive agent behavior |
| Docker sandboxing | Isolated tool execution |

### From Hermes Agent
| Feature | Usage |
|---------|-------|
| Learning loop | Execute -> Evaluate -> Extract -> Refine -> Retrieve |
| Multi-agent orchestration | Coordinator routing with skill relevance |
| Adversarial debate | Conflict resolution in synthesis |
| Skill sharing | Cross-agent skill library inheritance |
| User modeling | Persistent user preference tracking |
| Shared memory pools | L2 communication level |
| Inception prompting | Hardened sub-agent prompts |

---

## 12. Key Design Decisions Summary

1. **Gateway is dumb by design**: The main harness only routes. It never executes domain logic. This is a feature, not a limitation.

2. **Context slicing over full context**: Never pass full parent context to children. Always slice to relevant chunks. This prevents exponential context growth.

3. **Structured over prompt-based communication**: All inter-agent communication uses JSON Schema. Never rely on prompt injection for state passing.

4. **Budgets are protocol-level**: Token, time, and cost budgets are enforced at the protocol level, not just advisory.

5. **Synthesis is first-class**: The synthesis layer is not an afterthought. It's a dedicated harness with its own skills and can spawn debate agents.

6. **Learn from Hermes**: Implement the learning loop (execute -> evaluate -> extract -> refine -> retrieve) so the system improves with use.

7. **Leverage oh-my-pi fully**: Use native Task Tool, isolation backends, Agent Control Center, and TTSR rules rather than rebuilding.

8. **OpenClaw for infrastructure inspiration**: Adopt the gateway pattern, channel adapters, and memory system, but keep the architecture terminal-first.

9. **Recursive spawning is opt-in**: Off by default, enabled per-task with explicit budget constraints.

10. **Fault isolation at every boundary**: Every component can fail independently without cascading.

---

## Appendix A: File Structure

```
hmaom/
|-- gateway/                     # Main harness (stripped router)
|   |-- .omp/
|   |   |-- SOUL.md             # Router personality
|   |   |-- AGENTS.md           # Router dev rules
|   |   |-- TOOLS.md            # No tools - routing only
|   |-- config.json             # Gateway config
|   |-- classifier/             # SLM + LLM classifiers
|   |   |-- slm-model/
|   |   |-- fallback-llm/
|   |-- routing/                # Routing logic
|   |   |-- single.ts
|   |   |-- parallel.ts
|   |   |-- sequential.ts
|   |   |-- adaptive.ts
|-- specialists/                 # Domain-isolated harnesses
|   |-- finance/
|   |   |-- .omp/
|   |   |   |-- agents/
|   |   |   |-- SOUL.md
|   |   |   |-- AGENTS.md
|   |   |   |-- TOOLS.md
|   |   |-- skills/             # ~800 finance skills
|   |   |-- memory/
|   |   |-- config.json
|   |-- maths/
|   |-- physics/
|   |-- code/
|   |-- research/
|   |-- reporter/
|-- protocol/                    # Shared communication
|   |-- schemas/                # JSON schemas for all message types
|   |-- message-bus.ts          # Message bus implementation
|   |-- spawn-protocol.ts       # Hierarchical spawn protocol
|-- state/                       # Shared state management
|   |-- store.ts                # State store implementation
|   |-- checkpoints/            # Checkpoint storage
|-- observability/               # Monitoring and tracing
|   |-- tracing.ts              # Distributed tracing
|   |-- dashboard/              # Agent Control Center
|-- security/                    # Security infrastructure
|   |-- certificates/           # mTLS certs
|   |-- sandbox.ts              # Sandbox management
|-- docker-compose.yml           # Multi-harness deployment
|-- README.md
```

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Harness** | An oh-my-pi instance running as either gateway or specialist |
| **Specialist** | A domain-isolated sub-harness with focused skills |
| **Spawn** | Creation of a subagent with inherited constraints |
| **Context Slice** | A filtered subset of parent context passed to children |
| **Correlation ID** | A unique identifier tracing a request through all agents |
| **Circuit Breaker** | A mechanism that stops routing to failing specialists |
| **TTSR** | Trigger-Then-Stream-Retry: oh-my-pi's pattern-triggered rules |
| **MoE** | Mixture-of-Experts: the routing pattern this architecture implements |

---

*This architecture is designed to evolve. Start with Phase 1, measure routing accuracy and latency, and expand incrementally. The recursive spawning capability is powerful but must be rolled out with strict guardrails in Phase 3.*

*Document version: 1.0*
*Last updated: 2026-04-21*
