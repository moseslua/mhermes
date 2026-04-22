"""HMAOM Gateway Router.

Pure control plane with three responsibilities:
1. Intent Classification: Determine which specialist domain(s) a task requires
2. Task Decomposition: Break cross-domain tasks into routed subtasks
3. Orchestration: Manage the lifecycle of specialist executions and synthesis

The gateway never executes domain logic, loads skills, or calls tools.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional
from dataclasses import replace

from pydantic import BaseModel

from hmaom.hire.observer import HireObserver

from hmaom.specialists.physics import PhysicsHarness
from hmaom.specialists.research import ResearchHarness
from hmaom.specialists.reporter import ReporterHarness
from hmaom.prompts.registry import PromptRegistry

from hmaom.config import GatewayConfig, HMAOMConfig
from hmaom.fault_tolerance.recovery import RecoveryOrchestrator
from hmaom.gateway.classifier import IntentClassifier
from hmaom.observability.health import CircuitBreakerRegistry, HealthMonitor
from hmaom.observability.tracing import Tracer
from hmaom.protocol.message_bus import MessageBus
from hmaom.protocol.schemas import (
    AgentAddress,
    AgentMessage,
    AgentResult,
    Domain,
    MessageType,
    RoutingDecision,
    RoutingMode,
    SpawnConstraints,
    SpawnRequest,
    SpawnResult,
    SynthesisRequest,
    TaskDescription,
)
from hmaom.protocol.spawn import SpawnProtocol
from hmaom.protocol.validator import SchemaValidator
from hmaom.specialists.base import SpecialistHarness
from hmaom.specialists.code import CodeHarness
from hmaom.specialists.finance import FinanceHarness
from hmaom.specialists.maths import MathsHarness

from hmaom.gateway.decomposer import DecomposedTask, TaskDecomposer
from hmaom.state.user_model import UserModel
from hmaom.state.budget_manager import GlobalBudgetManager
from hmaom.hire.triggers import HireActivationTriggers, HireTriggerConfig
from hmaom.observability.metrics import MetricsCollector
from hmaom.observability.pool import SpecialistPool
from hmaom.gateway.streaming import StreamingMixin
from hmaom.gateway.load_balancer import LoadBalancer
from hmaom.observability.elastic import ElasticReplicaManager, ReplicaMetrics
from hmaom.gateway.model_router import CostAwareRouter



class GatewayRouter(StreamingMixin):
    """Main gateway router for the HMAOM mesh.

    Entry point for all user requests. Routes to specialists based on
    intent classification, then synthesizes results.
    """

    def __init__(self, config: Optional[HMAOMConfig] = None, hire_observer: Optional[HireObserver] = None) -> None:
        self.config = config or HMAOMConfig.default()
        self.gateway_config = self.config.gateway
        self.hire_observer = hire_observer

        # Core subsystems
        self.classifier = IntentClassifier(self.gateway_config)
        self.message_bus = MessageBus()
        self.tracer = Tracer()
        self.health_monitor = HealthMonitor()
        self.circuit_breakers = CircuitBreakerRegistry()
        self.spawn_protocol = SpawnProtocol(self.config.spawn)
        self.recovery = RecoveryOrchestrator()
        # Task decomposition
        self.decomposer = TaskDecomposer()
        # Global budget manager
        self.budget_manager = GlobalBudgetManager(
            max_global_tokens=self.config.budget.max_global_tokens,
            max_global_cost_usd=self.config.budget.max_global_cost_usd,
            max_global_time_ms=self.config.budget.max_global_time_ms,
            max_concurrent_trees=self.config.budget.max_concurrent_trees,
        )
        # User modeling
        self.user_model = UserModel(db_path=self.config.user_model.db_path)
        # Hire activation triggers
        if self.config.hire_triggers.enabled:
            from hmaom.hire.persistence import HirePersistence
            self.hire_triggers = HireActivationTriggers(
                config=self.config.hire_triggers,
                persistence=HirePersistence(),
            )
        else:
            self.hire_triggers: Optional[HireActivationTriggers] = None
        # Load balancer for horizontal scaling
        self.load_balancer = LoadBalancer()
        # Metrics collection
        self.metrics = MetricsCollector(prefix=self.config.metrics.prefix)
        # Cost-aware model router
        self.model_router = CostAwareRouter(
            config=self.config.cost_aware,
            budget_manager=self.budget_manager,
            user_model=self.user_model,
        )

        # Elastic replica manager
        if getattr(self.config, 'elastic', None) and self.config.elastic.enabled:
            self.elastic_manager = ElasticReplicaManager(
                load_balancer=self.load_balancer,
                config=self.config.elastic,
                pool_factory=self._create_specialist_for_domain,
            )
            self.elastic_manager.start_monitoring()
        else:
            self.elastic_manager = None

        # Prompt registry
        if self.config.prompt_registry.enabled:
            self.prompt_registry = PromptRegistry(db_path=self.config.prompt_registry.db_path)
        else:
            self.prompt_registry: Optional[PromptRegistry] = None

        # Specialist registry
        self._specialists: dict[Domain, SpecialistHarness] = {}
        self._init_specialists()

        # Runtime state
        self._active_requests: dict[str, dict[str, Any]] = {}

    def _init_specialists(self) -> None:
        """Initialize all configured specialists."""
        for spec_config in self.config.specialists:
            if spec_config.domain == "finance":
                specialist = FinanceHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            elif spec_config.domain == "maths":
                specialist = MathsHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            elif spec_config.domain == "code":
                specialist = CodeHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            elif spec_config.domain == "physics":
                specialist = PhysicsHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            elif spec_config.domain == "research":
                specialist = ResearchHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            elif spec_config.domain == "reporter":
                specialist = ReporterHarness(
                    config=spec_config,
                    message_bus=self.message_bus,
                    tracer=self.tracer,
                    health_monitor=self.health_monitor,
                    circuit_breakers=self.circuit_breakers,
                    prompt_registry=self.prompt_registry,
                )
            else:
                raise ValueError(f"Unknown specialist domain: {spec_config.domain}")

            self._specialists[Domain(spec_config.domain)] = specialist
            # Register in load balancer pool for horizontal scaling
            domain_enum = Domain(spec_config.domain)
            if domain_enum not in self.load_balancer._pools:
                self.load_balancer.register_pool(domain_enum, SpecialistPool(domain=domain_enum))
            pool = self.load_balancer._pools[domain_enum]
            pool.add_replica(specialist)


    def _create_specialist_for_domain(self, domain: Domain) -> SpecialistHarness:
        """Factory for creating new specialist harness instances."""
        base = self._specialists.get(domain)
        if base is None:
            raise ValueError(f"No base specialist for domain: {domain.value}")

        pool = self.load_balancer._pools.get(domain)
        replica_count = pool.replica_count() if pool else 0
        new_config = replace(base.config, name=f"{domain.value}-{replica_count + 1}")

        kwargs = {
            "config": new_config,
            "message_bus": self.message_bus,
            "tracer": self.tracer,
            "health_monitor": self.health_monitor,
            "circuit_breakers": self.circuit_breakers,
            "prompt_registry": self.prompt_registry,
        }

        if domain == Domain.FINANCE:
            from hmaom.specialists.finance import FinanceHarness
            return FinanceHarness(**kwargs)
        elif domain == Domain.MATHS:
            from hmaom.specialists.maths import MathsHarness
            return MathsHarness(**kwargs)
        elif domain == Domain.CODE:
            from hmaom.specialists.code import CodeHarness
            return CodeHarness(**kwargs)
        elif domain == Domain.PHYSICS:
            from hmaom.specialists.physics import PhysicsHarness
            return PhysicsHarness(**kwargs)
        elif domain == Domain.RESEARCH:
            from hmaom.specialists.research import ResearchHarness
            return ResearchHarness(**kwargs)
        elif domain == Domain.REPORTER:
            from hmaom.specialists.reporter import ReporterHarness
            return ReporterHarness(**kwargs)
        else:
            raise ValueError(f"Unknown domain: {domain.value}")

    async def route(self, user_input: str, session_id: Optional[str] = None) -> dict[str, Any]:
        """Main entry point: route a user request through the mesh.

        Args:
            user_input: The user's request text
            session_id: Optional session ID for tracking

        Returns:
            A dict with the final result, routing info, and metadata.
        """
        correlation_id = f"req-{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        # Initialize tree budgets
        self.spawn_protocol.init_tree_budgets(correlation_id)

        # Check global budget before proceeding
        if not self.budget_manager.can_allocate(tokens=1000):
            return {
                "correlation_id": correlation_id,
                "routing_decision": {"error": "global_budget_exhausted"},
                "result": None,
                "error": "Global budget exhausted. Please try again later.",
                "specialist_results": [],
                "elapsed_ms": 0,
                "budget_remaining": self.budget_manager.get_global_status(),
            }
        self.budget_manager.register_tree(correlation_id, limits={})

        # Start root trace span
        root_span = self.tracer.start_span(
            correlation_id=correlation_id,
            agent_address=AgentAddress(harness="gateway", agent="router", depth=0),
            operation="route",
        )

        # Step 1: Intent Classification
        classify_span = self.tracer.start_span(
            correlation_id=correlation_id,
            agent_address=AgentAddress(harness="gateway", agent="classifier", depth=0),
            operation="classify",
            parent_span_id=root_span.span_id,
        )
        try:
            classification = self.classifier.classify(user_input)
        except Exception as e:
            classify_span.finish(status="error", error=str(e))
            root_span.finish(status="error", error=str(e))
            self.budget_manager.unregister_tree(correlation_id)
            return {
                "correlation_id": correlation_id,
                "routing_decision": {"primary_domain": "unknown", "confidence": 0.0},
                "specialist_results": [],
                "synthesis": {"status": "error", "error": str(e)},
            }
        decision = classification
        self.tracer.finish_span(classify_span, status="ok", metadata={
            "primary_domain": decision.primary_domain.value,
            "routing_mode": decision.routing_mode.value,
            "confidence": decision.confidence,
        })
        # Metrics: record routing decision
        self.metrics.counter(
            "routing_decisions_total",
            labels={"domain": decision.primary_domain.value, "mode": decision.routing_mode.value},
        )
        self.metrics.histogram("routing_confidence", decision.confidence)

        # User model: personalize routing if session_id provided
        if session_id is not None:
            try:
                user_prefs = self.user_model.get_or_create(session_id)
                user_domains = self.user_model.get_preferred_domains(session_id, top_n=3)
                if decision.primary_domain.value in user_domains:
                    decision.confidence = min(1.0, decision.confidence + 0.05)
            except Exception:
                pass  # User model is best-effort

        # Step 2: Decompose if needed
        task = TaskDescription(
            title=user_input[:80],
            description=user_input,
        )

        decomposed_subtasks: list[DecomposedTask] = []
        should_decompose = (
            decision.estimated_complexity >= 7
            or len(decision.secondary_domains) > 0
            or decision.routing_mode != RoutingMode.SINGLE
        )

        if should_decompose:
            decompose_span = self.tracer.start_span(
                correlation_id=correlation_id,
                agent_address=AgentAddress(harness="gateway", agent="decomposer", depth=0),
                operation="decompose",
                parent_span_id=root_span.span_id,
            )
            decomposed_subtasks = self.decomposer.decompose(task, decision)
            self.tracer.finish_span(decompose_span, status="ok", metadata={
                "subtask_count": len(decomposed_subtasks),
                "domains": list(set(d.domain.value for d in decomposed_subtasks)),
            })

        results: list[SpawnResult] = []

        if decomposed_subtasks:
            results = await self._execute_decomposed(correlation_id, decomposed_subtasks, decision, session_id)
        elif decision.routing_mode == RoutingMode.SINGLE:
            result = await self._route_single(correlation_id, decision, task, session_id)
            results.append(result)

        elif decision.routing_mode == RoutingMode.PARALLEL:
            results = await self._route_parallel(correlation_id, decision, task, session_id)

        elif decision.routing_mode == RoutingMode.SEQUENTIAL:
            results = await self._route_sequential(correlation_id, decision, task, session_id)

        elif decision.routing_mode == RoutingMode.ADAPTIVE:
            results = await self._route_adaptive(correlation_id, decision, task, session_id)

        # Step 3: Synthesis (if needed)
        final_result: Any = None
        if decision.required_synthesis and len(results) > 1:
            synth_span = self.tracer.start_span(
                correlation_id=correlation_id,
                agent_address=AgentAddress(harness="gateway", agent="synthesis", depth=0),
                operation="synthesize",
                parent_span_id=root_span.span_id,
            )
            final_result = await self._synthesize(correlation_id, decision, results)
            self.tracer.finish_span(synth_span, status="ok")
        else:
            final_result = results[0].result if results else None

        # Finish root span
        elapsed_ms = int((time.time() - start_time) * 1000)
        self.tracer.finish_span(root_span, status="ok", metadata={
            "routing_mode": decision.routing_mode.value,
            "specialist_count": len(results),
        })

        # Budget report
        budget = self.spawn_protocol.remaining_budget(correlation_id)

        result = {
            "correlation_id": correlation_id,
            "routing_decision": decision.model_dump(),
            "result": final_result,
            "specialist_results": [r.model_dump() for r in results],
            "elapsed_ms": elapsed_ms,
            "budget_remaining": budget,
            "trace_summary": self.tracer.summary(correlation_id),
        }
        # Metrics: record request latency and result
        self.metrics.histogram("request_duration_ms", elapsed_ms)
        success = all(r.status == "success" for r in results) if results else False
        self.metrics.counter("requests_total", labels={"status": "success" if success else "failure"})

        if self.hire_observer is not None:
            self.hire_observer.observe(user_input, result)

        # Hire activation triggers: check if any subject crossed threshold
        if self.hire_triggers is not None:
            try:
                trigger_event = self.hire_triggers.record_interaction(user_input, result)
                if trigger_event is not None:
                    result["hire_trigger"] = {
                        "subject": trigger_event.subject,
                        "observation_count": trigger_event.observation_count,
                        "reason": trigger_event.reason,
                    }
            except Exception:
                pass  # Trigger checking is best-effort

        # User model: record interaction outcome
        if session_id is not None:
            try:
                primary = result["routing_decision"].get("primary_domain", "unknown")
                success = all(r.get("status") == "success" for r in result.get("specialist_results", []))
                self.user_model.record_interaction(
                    session_id, domain=primary, confidence=result["routing_decision"].get("confidence", 0.5), success=success,
                )
            except Exception:
                pass  # User model is best-effort

        # Budget cleanup
        self.budget_manager.unregister_tree(correlation_id)

        return result

    async def _route_single(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        session_id: Optional[str] = None,
    ) -> SpawnResult:
        """Route to a single specialist."""
        if self.elastic_manager is not None:
            self.elastic_manager.tick()

        if self.config.load_balancer.enabled:
            specialist = self.load_balancer.route(
                decision.primary_domain,
                strategy=self.config.load_balancer.strategy,
            )
        else:
            specialist = self._specialists.get(decision.primary_domain)

        if specialist is None:
            return SpawnResult(
                spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                status="failure",
                error=f"No specialist available for domain: {decision.primary_domain.value}",
            )

        # Check circuit breaker
        if not self.circuit_breakers.can_call(specialist.config.name):
            return SpawnResult(
                spawn_id=f"cb-{uuid.uuid4().hex[:8]}",
                status="failure",
            error=f"Circuit breaker OPEN for {specialist.config.name}",
            )
        model = None
        if self.config.cost_aware.enabled:
            model = self.model_router.select_model(
                decision.primary_domain, task, decision.estimated_complexity, session_id
            )

        request = SpawnRequest(
            spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
            parent_id="gateway",
            correlation_id=correlation_id,
            depth=1,
            task=task,
            context_slice=specialist.memory_manager.working_slice(task.description),
            constraints=SpawnConstraints(
                max_depth=self.config.spawn.max_depth - 1,
                max_tokens=self.config.spawn.max_tokens_per_tree // 2,
                max_time_ms=self.config.spawn.max_wall_time_ms // 2,
                tools=specialist.default_tools,
            ),
            model_override=model,
        )
        result = await specialist.execute(request, model_override_dynamic=model)

        if model is not None:
            self.model_router.record_outcome(
                decision.primary_domain,
                model,
                result.status == "success",
                result.tokens_used,
                result.time_ms,
                session_id=session_id,
            )

        if self.elastic_manager is not None:
            self.elastic_manager.monitor(
                decision.primary_domain,
                ReplicaMetrics(
                    domain=decision.primary_domain,
                    replica_id=specialist.config.name,
                    queue_depth=0,
                    p95_latency_ms=result.time_ms,
                    in_flight_count=len(specialist._active_spawns),
                    last_activity=time.time(),
                ),
            )

        # Validate against expected output schema if present
        if task.expected_output_schema is not None:
            validator = SchemaValidator()
            is_valid, errors = validator.validate_spawn_result(result, task)
            if not is_valid:
                self.metrics.counter(
                    "validation_failures_total",
                    labels={"domain": decision.primary_domain.value},
                )
                failed_result = SpawnResult(
                    spawn_id=result.spawn_id,
                    status="failure",
                    error=f"Schema validation failed: {'; '.join(errors)}",
                    tokens_used=result.tokens_used,
                    time_ms=result.time_ms,
                )
                recovered = await self.recovery.execute_recovery(
                    failed_result,
                    request,
                    lambda req: specialist.execute(req),
                    message_bus=self.message_bus,
                )
                return recovered

        return result

    async def _route_parallel(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        session_id: Optional[str] = None,
    ) -> list[SpawnResult]:
        """Route to multiple specialists in parallel."""
        if self.elastic_manager is not None:
            self.elastic_manager.tick()

        domains = [decision.primary_domain] + decision.secondary_domains
        domains = domains[:self.config.spawn.max_breadth]

        async def run_for_domain(domain: Domain) -> SpawnResult:
            if self.config.load_balancer.enabled:
                specialist = self.load_balancer.route(
                    domain, strategy=self.config.load_balancer.strategy
                )
            else:
                specialist = self._specialists.get(domain)
            if specialist is None:
                return SpawnResult(
                    spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                    status="failure",
                    error=f"No specialist for {domain.value}",
                )

            model = None
            if self.config.cost_aware.enabled:
                model = self.model_router.select_model(
                    domain, task, decision.estimated_complexity, session_id
                )

            request = SpawnRequest(
                spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
                parent_id="gateway",
                correlation_id=correlation_id,
                depth=1,
                task=task,
                context_slice=specialist.memory_manager.working_slice(task.description),
                constraints=SpawnConstraints(
                    max_depth=self.config.spawn.max_depth - 1,
                    max_tokens=self.config.spawn.max_tokens_per_tree // len(domains),
                    max_time_ms=self.config.spawn.max_wall_time_ms // 2,
                    tools=specialist.default_tools,
                ),
                model_override=model,
            )
            result = await specialist.execute(request, model_override_dynamic=model)

            if model is not None:
                self.model_router.record_outcome(
                    domain,
                    model,
                    result.status == "success",
                    result.tokens_used,
                    result.time_ms,
                    session_id=session_id,
                )

            return result
        

        results = await asyncio.gather(*[run_for_domain(d) for d in domains], return_exceptions=True)
        spawn_results: list[SpawnResult] = []
        for domain, result in zip(domains, results):
            if isinstance(result, Exception):
                spawn_results.append(SpawnResult(
                    spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                    status="failure",
                    error=f"Exception in {domain.value}: {result}",
                ))
            else:
                spawn_results.append(result)
        return spawn_results

    async def _route_sequential(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        session_id: Optional[str] = None,
) -> list[SpawnResult]:
        """Route to specialists sequentially, feeding results forward."""
        domains = [decision.primary_domain] + decision.secondary_domains
        results: list[SpawnResult] = []
        previous_result: Any = None

        for domain in domains:
            if self.config.load_balancer.enabled:
                specialist = self.load_balancer.route(
                    domain, strategy=self.config.load_balancer.strategy
                )
            else:
                specialist = self._specialists.get(domain)
            if specialist is None:
                results.append(SpawnResult(
                    spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                    status="failure",
                    error=f"No specialist for {domain.value}",
                ))
                continue

            # Build task with previous result context
            task_with_context = task.model_copy()
            if previous_result is not None:
                task_with_context.description += (
                    f"\n\n[Previous stage result]: {json.dumps(previous_result, default=str)}"
                )

            model = None
            if self.config.cost_aware.enabled:
                model = self.model_router.select_model(
                    domain, task_with_context, decision.estimated_complexity, session_id
                )

            request = SpawnRequest(
                spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
                parent_id="gateway",
                correlation_id=correlation_id,
                depth=1,
                task=task_with_context,
                context_slice=specialist.memory_manager.working_slice(task_with_context.description),
                constraints=SpawnConstraints(
                    max_depth=self.config.spawn.max_depth - 1,
                    max_tokens=self.config.spawn.max_tokens_per_tree // len(domains),
                    max_time_ms=self.config.spawn.max_wall_time_ms // len(domains),
                    tools=specialist.default_tools,
                ),
                model_override=model,
            )

            result = await specialist.execute(request, model_override_dynamic=model)
            results.append(result)

            if model is not None:
                self.model_router.record_outcome(
                    domain,
                    model,
                    result.status == "success",
                    result.tokens_used,
                    result.time_ms,
                    session_id=session_id,
                )

            if result.status == "success":
                previous_result = result.result
            else:
                # Stop sequential chain on failure
                break

        return results

    async def _route_adaptive(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        session_id: Optional[str] = None,
    ) -> list[SpawnResult]:
        """Adaptive routing: start with explore subagent, then decide."""
        # Start with primary domain explore
        if self.config.load_balancer.enabled:
            primary = self.load_balancer.route(
                decision.primary_domain, strategy=self.config.load_balancer.strategy
            )
        else:
            primary = self._specialists.get(decision.primary_domain)
        if primary is None:
            return [SpawnResult(
                spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                status="failure",
                error=f"No specialist for {decision.primary_domain.value}",
            )]

        explore_request = SpawnRequest(
            spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
            parent_id="gateway",
            correlation_id=correlation_id,
            depth=1,
            task=TaskDescription(
                title=f"Explore: {task.title}",
                description=f"Explore the problem space and determine the best approach.\n\n{task.description}",
            ),
            context_slice=primary.memory_manager.working_slice(task.description),
            constraints=SpawnConstraints(
                max_depth=1,
                max_tokens=10_000,
                max_time_ms=60_000,
                tools=primary.default_tools,
            ),
        )

        model = None
        if self.config.cost_aware.enabled:
            model = self.model_router.select_model(
                decision.primary_domain, task, decision.estimated_complexity, session_id
            )
            explore_request = explore_request.model_copy(update={"model_override": model})

        explore_result = await primary.execute(explore_request, model_override_dynamic=model)

        if model is not None:
            self.model_router.record_outcome(
                decision.primary_domain,
                model,
                explore_result.status == "success",
                explore_result.tokens_used,
                explore_result.time_ms,
                session_id=session_id,
            )
        # Parse explore result for routing hints and re-route accordingly
        if explore_result.status == "success":
            adjusted = self._parse_explore_routing_hints(explore_result)

            # Merge adjusted decision with original (keep original primary if parse fails)
            if adjusted.primary_domain == Domain.META:
                adjusted.primary_domain = decision.primary_domain

            adjusted_decision = decision.model_copy(update={
                "primary_domain": adjusted.primary_domain,
                "secondary_domains": adjusted.secondary_domains or decision.secondary_domains,
                "routing_mode": adjusted.routing_mode,
                "required_synthesis": adjusted.required_synthesis or decision.required_synthesis,
                "confidence": adjusted.confidence,
            })

            # Re-route using adjusted decision
            if adjusted_decision.routing_mode == RoutingMode.SINGLE:
                main_result = await self._route_single(correlation_id, adjusted_decision, task, session_id)
                return [explore_result, main_result]
            elif adjusted_decision.routing_mode == RoutingMode.PARALLEL:
                main_results = await self._route_parallel(correlation_id, adjusted_decision, task, session_id)
                return [explore_result] + main_results
            elif adjusted_decision.routing_mode == RoutingMode.SEQUENTIAL:
                main_results = await self._route_sequential(correlation_id, adjusted_decision, task, session_id)
                return [explore_result] + main_results
            else:
                main_result = await self._route_single(correlation_id, adjusted_decision, task, session_id)
                return [explore_result, main_result]

        return [explore_result]

    def _parse_explore_routing_hints(self, explore_result: SpawnResult) -> RoutingDecision:
        """Parse an explore result for routing hints.

        Looks for domain names and routing keywords in the explore result text
        to determine how to route the main task. Returns an adjusted RoutingDecision.
        """
        if explore_result.status != "success" or not explore_result.result:
            return RoutingDecision(
                primary_domain=Domain.META,
                routing_mode=RoutingMode.SINGLE,
                confidence=0.5,
            )

        text = str(explore_result.result).lower()

        # Detect additional domains mentioned in the explore result
        domain_keywords: dict[str, Domain] = {
            "finance": Domain.FINANCE,
            "math": Domain.MATHS,
            "physics": Domain.PHYSICS,
            "code": Domain.CODE,
            "research": Domain.RESEARCH,
            "report": Domain.REPORTER,
        }

        detected_domains: list[Domain] = []
        for keyword, domain in domain_keywords.items():
            if keyword in text:
                detected_domains.append(domain)

        # Determine routing mode from keywords
        routing_mode = RoutingMode.SINGLE
        if "parallel" in text or "simultaneously" in text or "both" in text:
            routing_mode = RoutingMode.PARALLEL
        elif "sequential" in text or "first" in text or "then" in text:
            routing_mode = RoutingMode.SEQUENTIAL
        elif "adaptive" in text or "explore" in text:
            routing_mode = RoutingMode.ADAPTIVE

        # If multiple domains detected, upgrade to parallel or sequential
        if len(detected_domains) > 1 and routing_mode == RoutingMode.SINGLE:
            routing_mode = RoutingMode.PARALLEL

        primary = detected_domains[0] if detected_domains else Domain.META
        secondary = detected_domains[1:] if len(detected_domains) > 1 else []

        return RoutingDecision(
            primary_domain=primary,
            secondary_domains=secondary,
            routing_mode=routing_mode,
            confidence=0.7,
            required_synthesis=len(detected_domains) > 1,
        )

    async def _synthesize(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        results: list[SpawnResult],
    ) -> Any:
        """Synthesize results from multiple specialists.

        Uses ReporterHarness when available for structured synthesis with
        conflict detection and debate mode. Falls back to simple merge.
        """
        agent_results: list[AgentResult] = []
        for result in results:
            agent_results.append(AgentResult(
                source=AgentAddress(harness="unknown", agent="specialist", depth=1),
                result=result.result,
                confidence=1.0 if result.status == "success" else 0.0,
                tokens_used=result.tokens_used,
                time_ms=result.time_ms,
            ))

        # Try to use ReporterHarness for structured synthesis
        reporter = self._specialists.get(Domain.REPORTER)
        if reporter is not None and len(agent_results) > 0:
            def _serialize(val: Any) -> Any:
                if isinstance(val, BaseModel):
                    return val.model_dump()
                if isinstance(val, list):
                    return [_serialize(v) for v in val]
                if isinstance(val, dict):
                    return {k: _serialize(v) for k, v in val.items()}
                return val

            source_payload = json.dumps([{
                "source": {
                    "harness": r.source.harness if hasattr(r.source, 'harness') else "unknown",
                    "agent": r.source.agent if hasattr(r.source, 'agent') else "specialist",
                    "depth": r.source.depth if hasattr(r.source, 'depth') else 1,
                },
                "result": _serialize(r.result),
                "confidence": r.confidence,
                "tokens_used": r.tokens_used,
                "time_ms": r.time_ms,
            } for r in agent_results])

            synth_task = TaskDescription(
                title=f"Synthesize: {decision.primary_domain.value}",
                description=(
                    f"Synthesize results from {len(agent_results)} source(s).\n\n"
                    f"[HMAOM_SYNTHESIS_SOURCES]:{source_payload}"
                ),
                tags=["synthesis", "reporter"],
            )

            spawn_request = SpawnRequest(
                spawn_id=f"synth-{uuid.uuid4().hex[:8]}",
                parent_id="gateway",
                correlation_id=correlation_id,
                depth=1,
                task=synth_task,
                context_slice=reporter.memory_manager.working_slice(
                    f"Synthesize results from {len(agent_results)} source(s)."
                ),
                constraints=SpawnConstraints(
                    max_depth=self.config.spawn.max_depth - 1,
                    max_tokens=self.config.spawn.max_tokens_per_tree // 2,
                    max_time_ms=self.config.spawn.max_wall_time_ms // 2,
                    tools=reporter.default_tools,
                ),
            )

            try:
                synth_result = await reporter.execute(spawn_request)
                if synth_result.status == "success" and synth_result.result is not None:
                    return synth_result.result
            except Exception:
                # Fall through to simple merge on reporter failure
                pass

        # Publish synthesis request to bus for observability
        synthesis_request = SynthesisRequest(
            correlation_id=correlation_id,
            sources=agent_results,
            synthesis_type="unify",
        )

        try:
            await self.message_bus.publish(
                AgentMessage(
                    message_id=f"synth-{uuid.uuid4().hex[:8]}",
                    correlation_id=correlation_id,
                    timestamp=time.time(),
                    sender=AgentAddress(harness="gateway", agent="synthesis", depth=0),
                    recipient="synthesis",
                    type=MessageType.SYNTHESIS_REQUEST,
                    payload=synthesis_request.model_dump(),
                )
            )
        except Exception:
            pass  # Best-effort telemetry

        # Simple unification: merge all successful results
        successful = [r for r in results if r.status == "success"]
        if not successful:
            return {"error": "All specialist executions failed", "details": [r.model_dump() for r in results]}

        if len(successful) == 1:
            return successful[0].result

        # Merge multiple results
        merged: dict[str, Any] = {
            "_synthesis": {
                "mode": decision.routing_mode.value,
                "domains": [decision.primary_domain.value] + [d.value for d in decision.secondary_domains],
                "successful_count": len(successful),
                "total_count": len(results),
            }
        }
        for i, result in enumerate(successful):
            merged[f"result_{i}"] = result.result

        return merged

    async def _execute_decomposed(
        self,
        correlation_id: str,
        subtasks: list[DecomposedTask],
        decision: RoutingDecision,
        session_id: Optional[str] = None,
    ) -> list[SpawnResult]:
        """Execute decomposed subtasks respecting dependencies.

        Subtasks with dependencies are executed sequentially;
        independent subtasks are executed in parallel.
        """
        results_map: dict[str, SpawnResult] = {}

        # Group by dependency sets: first pass = no deps, second pass = deps resolved
        pending = list(subtasks)
        max_iterations = len(subtasks) * 2  # safety limit
        iteration = 0

        while pending and iteration < max_iterations:
            iteration += 1
            ready = [s for s in pending if all(d in results_map for d in s.depends_on)]
            if not ready:
                # Circular or unresolvable dependency — break and report
                break

            # Execute ready subtasks in parallel
            async def run_subtask(subtask: DecomposedTask) -> tuple[str, SpawnResult]:
                specialist = self._specialists.get(subtask.domain)
                if specialist is None:
                    return subtask.subtask_id, SpawnResult(
                        spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                        status="failure",
                        error=f"No specialist for {subtask.domain.value}",
                    )

                if not self.circuit_breakers.can_call(specialist.config.name):
                    return subtask.subtask_id, SpawnResult(
                        spawn_id=f"cb-{uuid.uuid4().hex[:8]}",
                        status="failure",
                        error=f"Circuit breaker OPEN for {specialist.config.name}",
                    )
                # Build task with dependency results injected
                dep_context = ""
                for dep_id in subtask.depends_on:
                    dep_result = results_map.get(dep_id)
                    if dep_result and dep_result.status == "success":
                        dep_context += f"\n\n[Dependency {dep_id} result]: {json.dumps(dep_result.result, default=str)}"

                task_with_deps = subtask.task.model_copy()
                if dep_context:
                    task_with_deps.description += dep_context



                model = None
                if self.config.cost_aware.enabled:
                    model = self.model_router.select_model(
                        subtask.domain, task_with_deps, decision.estimated_complexity, session_id
                    )

                request = SpawnRequest(
                    spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
                    parent_id="gateway",
                    correlation_id=correlation_id,
                    depth=1,
                    task=task_with_deps,
                    context_slice=specialist.memory_manager.working_slice(task_with_deps.description),
                    constraints=SpawnConstraints(
                        max_depth=self.config.spawn.max_depth - 1,
                        max_tokens=self.config.spawn.max_tokens_per_tree // max(len(subtasks), 1),
                        max_time_ms=self.config.spawn.max_wall_time_ms // max(len(subtasks), 1),
                        tools=specialist.default_tools,
                    ),
                    model_override=model,
                )

                result = await specialist.execute(request, model_override_dynamic=model)

                if model is not None:
                    self.model_router.record_outcome(
                        subtask.domain,
                        model,
                        result.status == "success",
                        result.tokens_used,
                        result.time_ms,
                        session_id=session_id,
                    )

                return subtask.subtask_id, result


            batch_results = await asyncio.gather(*[run_subtask(s) for s in ready], return_exceptions=True)
            for subtask_id, result in batch_results:
                if isinstance(result, Exception):
                    results_map[subtask_id] = SpawnResult(
                        spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                        status="failure",
                        error=f"Exception in subtask {subtask_id}: {result}",
                    )
                else:
                    results_map[subtask_id] = result
                matched = next((s for s in pending if s.subtask_id == subtask_id), None)
                if matched:
                    pending.remove(matched)

        # Return results in original subtask order
        return [results_map[s.subtask_id] for s in subtasks if s.subtask_id in results_map]

    # ── Control Commands ──

    async def status(self) -> dict[str, Any]:
        """Return the current status of the gateway and all specialists."""
        specialist_statuses = {}
        for domain, specialist in self._specialists.items():
            specialist_statuses[domain.value] = specialist.health()

        return {
            "gateway": {
                "name": self.gateway_config.gateway_name,
                "active_requests": len(self._active_requests),
                "slm_model": self.gateway_config.slm_model,
                "fallback_model": self.gateway_config.fallback_llm_model,
            },
            "specialists": specialist_statuses,
            "health": self.health_monitor.summary(),
            "circuit_breakers": {
                name: cb.model_dump()
                for name, cb in self.circuit_breakers.all_states().items()
            },
            "metrics": {
                "prometheus": self.metrics.prometheus_exposition_format(),
            },
            "load_balancer": self.load_balancer.health_summary(),
            "budget": self.budget_manager.get_global_status(),
        }

    async def kill_tree(self, correlation_id: str) -> dict[str, Any]:
        """Kill all agents in a request tree."""
        # Cancel any tracked tasks
        # In a full implementation, this would traverse the spawn tree
        return {
            "correlation_id": correlation_id,
            "action": "kill_tree",
            "status": "requested",
        }

    async def start(self) -> None:
        """Start the gateway router."""
        for specialist in self._specialists.values():
            await specialist.start()

    async def stop(self) -> None:
        """Stop the gateway router and all specialists."""
        for specialist in self._specialists.values():
            await specialist.stop()
        self.message_bus.close()
        self.tracer.close()
