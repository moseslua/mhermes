"""HMAOM Streaming Response Pipeline.

Adds incremental event streaming to the GatewayRouter via a mixin.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator, Optional

from pydantic import BaseModel

from hmaom.gateway.decomposer import DecomposedTask
from hmaom.protocol.schemas import (
    AgentAddress,
    Domain,
    RoutingDecision,
    RoutingMode,
    SpawnConstraints,
    SpawnRequest,
    SpawnResult,
    StreamEvent,
    TaskDescription,
)


class StreamingMixin:
    """Mixin that adds route_stream() to GatewayRouter."""

    async def route_stream(
        self,
        user_input: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream routing events for a user request.

        Yields StreamEvent objects incrementally as the request progresses
        through classification, decomposition, specialist execution, and
        synthesis stages.
        """
        correlation_id = f"req-{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        self.spawn_protocol.init_tree_budgets(correlation_id)
        if not self.budget_manager.can_allocate(tokens=1000):
            yield StreamEvent(
                event_type="error",
                correlation_id=correlation_id,
                data={"error": "Global budget exhausted. Please try again later."},
                timestamp=time.time(),
            )
            return

        self.budget_manager.register_tree(correlation_id, limits={})

        root_span = self.tracer.start_span(
            correlation_id=correlation_id,
            agent_address=AgentAddress(harness="gateway", agent="router", depth=0),
            operation="route_stream",
        )

        try:
            # Step 1: Intent Classification
            classify_span = self.tracer.start_span(
                correlation_id=correlation_id,
                agent_address=AgentAddress(harness="gateway", agent="classifier", depth=0),
                operation="classify",
                parent_span_id=root_span.span_id,
            )
            decision = self.classifier.classify(user_input)
            self.tracer.finish_span(classify_span, status="ok", metadata={
                "primary_domain": decision.primary_domain.value,
                "routing_mode": decision.routing_mode.value,
                "confidence": decision.confidence,
            })
            self.metrics.counter(
                "routing_decisions_total",
                labels={"domain": decision.primary_domain.value, "mode": decision.routing_mode.value},
            )
            self.metrics.histogram("routing_confidence", decision.confidence)

            if session_id is not None:
                try:
                    user_domains = self.user_model.get_preferred_domains(session_id, top_n=3)
                    if decision.primary_domain.value in user_domains:
                        decision.confidence = min(1.0, decision.confidence + 0.05)
                except Exception:
                    pass

            yield StreamEvent(
                event_type="routing_decision",
                correlation_id=correlation_id,
                data={"decision": decision.model_dump()},
                timestamp=time.time(),
            )

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
                yield StreamEvent(
                    event_type="decomposition",
                    correlation_id=correlation_id,
                    data={"subtasks": [d.model_dump() for d in decomposed_subtasks]},
                    timestamp=time.time(),
                )

            results: list[SpawnResult] = []

            if decomposed_subtasks:
                async for event in self._stream_decomposed(correlation_id, decomposed_subtasks, decision, results):
                    yield event
            elif decision.routing_mode == RoutingMode.SINGLE:
                result = await self._route_single(correlation_id, decision, task)
                yield StreamEvent(
                    event_type="partial_result",
                    correlation_id=correlation_id,
                    data={"result": result.model_dump()},
                    timestamp=time.time(),
                )
                results.append(result)
            elif decision.routing_mode == RoutingMode.PARALLEL:
                async for event in self._stream_parallel(correlation_id, decision, task, results):
                    yield event
            elif decision.routing_mode == RoutingMode.SEQUENTIAL:
                async for event in self._stream_sequential(correlation_id, decision, task, results):
                    yield event
            elif decision.routing_mode == RoutingMode.ADAPTIVE:
                async for event in self._stream_adaptive(correlation_id, decision, task, results):
                    yield event

            # Step 3: Synthesis
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
                yield StreamEvent(
                    event_type="synthesis",
                    correlation_id=correlation_id,
                    data={"result": _serialize_for_stream(final_result)},
                    timestamp=time.time(),
                )
            else:
                final_result = results[0].result if results else None

            elapsed_ms = int((time.time() - start_time) * 1000)
            self.tracer.finish_span(root_span, status="ok", metadata={
                "routing_mode": decision.routing_mode.value,
                "specialist_count": len(results),
            })

            yield StreamEvent(
                event_type="complete",
                correlation_id=correlation_id,
                data={
                    "result": _serialize_for_stream(final_result),
                    "specialist_results": [r.model_dump() for r in results],
                    "elapsed_ms": elapsed_ms,
                },
                timestamp=time.time(),
            )

        except Exception as exc:
            self.tracer.finish_span(root_span, status="error", metadata={"error": str(exc)})
            yield StreamEvent(
                event_type="error",
                correlation_id=correlation_id,
                data={"error": str(exc)},
                timestamp=time.time(),
            )
        finally:
            self.budget_manager.unregister_tree(correlation_id)

    async def _stream_parallel(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        results_out: list[SpawnResult],
    ) -> AsyncGenerator[StreamEvent, None]:
        """Execute parallel specialists and yield partial_result events as each completes."""
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
            if not self.circuit_breakers.can_call(specialist.config.name):
                return SpawnResult(
                    spawn_id=f"cb-{uuid.uuid4().hex[:8]}",
                    status="failure",
                    error=f"Circuit breaker OPEN for {specialist.config.name}",
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
            )
            return await specialist.execute(request)

        tasks = [run_for_domain(d) for d in domains]
        for completed in asyncio.as_completed(tasks):
            result = await completed
            results_out.append(result)
            yield StreamEvent(
                event_type="partial_result",
                correlation_id=correlation_id,
                data={"result": result.model_dump()},
                timestamp=time.time(),
            )

    async def _stream_sequential(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        results_out: list[SpawnResult],
    ) -> AsyncGenerator[StreamEvent, None]:
        """Execute specialists sequentially and yield after each step."""
        domains = [decision.primary_domain] + decision.secondary_domains
        previous_result: Any = None

        for domain in domains:
            specialist = self._specialists.get(domain)
            if specialist is None:
                result = SpawnResult(
                    spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                    status="failure",
                    error=f"No specialist for {domain.value}",
                )
                yield StreamEvent(
                    event_type="partial_result",
                    correlation_id=correlation_id,
                    data={"result": result.model_dump()},
                    timestamp=time.time(),
                )
                results_out.append(result)
                continue

            task_with_context = task.model_copy()
            if previous_result is not None:
                task_with_context.description += (
                    f"\n\n[Previous stage result]: {json.dumps(previous_result)}"
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
            )

            result = await specialist.execute(request)
            yield StreamEvent(
                event_type="partial_result",
                correlation_id=correlation_id,
                data={"result": result.model_dump()},
                timestamp=time.time(),
            )
            results_out.append(result)

            if result.status == "success":
                previous_result = result.result
            else:
                break

    async def _stream_adaptive(
        self,
        correlation_id: str,
        decision: RoutingDecision,
        task: TaskDescription,
        results_out: list[SpawnResult],
    ) -> AsyncGenerator[StreamEvent, None]:
        """Adaptive routing with explore step, yielding events incrementally."""
        primary = self._specialists.get(decision.primary_domain)
        if primary is None:
            result = SpawnResult(
                spawn_id=f"err-{uuid.uuid4().hex[:8]}",
                status="failure",
                error=f"No specialist for {decision.primary_domain.value}",
            )
            yield StreamEvent(
                event_type="partial_result",
                correlation_id=correlation_id,
                data={"result": result.model_dump()},
                timestamp=time.time(),
            )
            results_out.append(result)
            return

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

        explore_result = await primary.execute(explore_request)
        yield StreamEvent(
            event_type="partial_result",
            correlation_id=correlation_id,
            data={"result": explore_result.model_dump(), "stage": "explore"},
            timestamp=time.time(),
        )
        results_out.append(explore_result)

        if explore_result.status == "success":
            adjusted = self._parse_explore_routing_hints(explore_result)
            if adjusted.primary_domain == Domain.META:
                adjusted.primary_domain = decision.primary_domain

            adjusted_decision = decision.model_copy(update={
                "primary_domain": adjusted.primary_domain,
                "secondary_domains": adjusted.secondary_domains or decision.secondary_domains,
                "routing_mode": adjusted.routing_mode,
                "required_synthesis": adjusted.required_synthesis or decision.required_synthesis,
                "confidence": adjusted.confidence,
            })

            if adjusted_decision.routing_mode == RoutingMode.SINGLE:
                main_result = await self._route_single(correlation_id, adjusted_decision, task)
                yield StreamEvent(
                    event_type="partial_result",
                    correlation_id=correlation_id,
                    data={"result": main_result.model_dump()},
                    timestamp=time.time(),
                )
                results_out.append(main_result)
            elif adjusted_decision.routing_mode == RoutingMode.PARALLEL:
                async for event in self._stream_parallel(correlation_id, adjusted_decision, task, results_out):
                    yield event
            elif adjusted_decision.routing_mode == RoutingMode.SEQUENTIAL:
                async for event in self._stream_sequential(correlation_id, adjusted_decision, task, results_out):
                    yield event
            else:
                main_result = await self._route_single(correlation_id, adjusted_decision, task)
                yield StreamEvent(
                    event_type="partial_result",
                    correlation_id=correlation_id,
                    data={"result": main_result.model_dump()},
                    timestamp=time.time(),
                )
                results_out.append(main_result)

    async def _stream_decomposed(
        self,
        correlation_id: str,
        decomposed_subtasks: list[DecomposedTask],
        decision: RoutingDecision,
        results_out: list[SpawnResult],
    ) -> AsyncGenerator[StreamEvent, None]:
        """Execute decomposed subtasks and yield partial_result events as each completes."""
        results_map: dict[str, SpawnResult] = {}
        pending = list(decomposed_subtasks)
        max_iterations = len(decomposed_subtasks) * 2
        iteration = 0

        while pending and iteration < max_iterations:
            iteration += 1
            ready = [s for s in pending if all(d in results_map for d in s.depends_on)]
            if not ready:
                break

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

                dep_context = ""
                for dep_id in subtask.depends_on:
                    dep_result = results_map.get(dep_id)
                    if dep_result and dep_result.status == "success":
                        dep_context += f"\n\n[Dependency {dep_id} result]: {json.dumps(dep_result.result, default=str)}"

                task_with_deps = subtask.task.model_copy()
                if dep_context:
                    task_with_deps.description += dep_context

                request = SpawnRequest(
                    spawn_id=f"spawn-{uuid.uuid4().hex[:8]}",
                    parent_id="gateway",
                    correlation_id=correlation_id,
                    depth=1,
                    task=task_with_deps,
                    context_slice=specialist.memory_manager.working_slice(task_with_deps.description),
                    constraints=SpawnConstraints(
                        max_depth=self.config.spawn.max_depth - 1,
                        max_tokens=self.config.spawn.max_tokens_per_tree // max(len(decomposed_subtasks), 1),
                        max_time_ms=self.config.spawn.max_wall_time_ms // max(len(decomposed_subtasks), 1),
                        tools=specialist.default_tools,
                    ),
                )

                result = await specialist.execute(request)
                return subtask.subtask_id, result

            tasks = [run_subtask(s) for s in ready]
            for completed in asyncio.as_completed(tasks):
                subtask_id, result = await completed
                results_map[subtask_id] = result
                pending.remove(next(s for s in pending if s.subtask_id == subtask_id))
                results_out.append(result)
                yield StreamEvent(
                    event_type="partial_result",
                    correlation_id=correlation_id,
                    data={"result": result.model_dump(), "subtask_id": subtask_id},
                    timestamp=time.time(),
                )


def _serialize_for_stream(value: Any) -> Any:
    """Serialize a value for inclusion in a StreamEvent's data dict."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_serialize_for_stream(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_for_stream(v) for k, v in value.items()}
    return value
