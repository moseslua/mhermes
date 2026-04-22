"""HMAOM Task Decomposition Engine.

Breaks user requests into subtasks with domain assignments and dependency tracking.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from pydantic import BaseModel, Field

from hmaom.gateway.classifier import IntentClassifier
from hmaom.protocol.schemas import Domain, RoutingDecision, RoutingMode, TaskDescription


class DecomposedTask(BaseModel):
    """A single subtask produced by the decomposition engine."""

    subtask_id: str = Field(description="Unique identifier for this subtask")
    domain: Domain = Field(description="Assigned specialist domain")
    task: TaskDescription = Field(description="The task description for this subtask")
    depends_on: list[str] = Field(default_factory=list, description="Subtask IDs that must complete first")
    estimated_tokens: int = Field(default=0, ge=0, description="Estimated token consumption")
    priority: int = Field(default=0, description="Lower = higher priority")


class TaskDecomposer:
    """Analyzes a user request and breaks it into subtasks.

    Supports four routing modes:
    - SINGLE: single subtask
    - PARALLEL: split by sentences/clauses, assign domains independently
    - SEQUENTIAL: split with each subtask depending on the previous
    - ADAPTIVE: single explore subtask followed by the main task
    """

    # Maps individual keywords to their primary domain
    _keyword_domain_map: dict[str, Domain] = {
        # Finance
        "stock": Domain.FINANCE,
        "option": Domain.FINANCE,
        "bond": Domain.FINANCE,
        "portfolio": Domain.FINANCE,
        "risk": Domain.FINANCE,
        "var": Domain.FINANCE,
        "black-scholes": Domain.FINANCE,
        "derivative": Domain.FINANCE,
        "market": Domain.FINANCE,
        "trading": Domain.FINANCE,
        "investment": Domain.FINANCE,
        "dividend": Domain.FINANCE,
        "yield": Domain.FINANCE,
        "capm": Domain.FINANCE,
        "sharpe": Domain.FINANCE,
        "volatility": Domain.FINANCE,
        "hedge": Domain.FINANCE,
        "asset": Domain.FINANCE,
        "equity": Domain.FINANCE,
        "forex": Domain.FINANCE,
        "crypto": Domain.FINANCE,
        "bitcoin": Domain.FINANCE,
        "ethereum": Domain.FINANCE,
        "defi": Domain.FINANCE,
        "nft": Domain.FINANCE,
        "financial": Domain.FINANCE,
        # Maths
        "integral": Domain.MATHS,
        "derivative": Domain.MATHS,
        "matrix": Domain.MATHS,
        "eigenvalue": Domain.MATHS,
        "probability": Domain.MATHS,
        "statistics": Domain.MATHS,
        "theorem": Domain.MATHS,
        "proof": Domain.MATHS,
        "calculus": Domain.MATHS,
        "algebra": Domain.MATHS,
        "geometry": Domain.MATHS,
        "number theory": Domain.MATHS,
        "differential": Domain.MATHS,
        "equation": Domain.MATHS,
        "linear algebra": Domain.MATHS,
        "regression": Domain.MATHS,
        "hypothesis": Domain.MATHS,
        "distribution": Domain.MATHS,
        "bayesian": Domain.MATHS,
        "optimization": Domain.MATHS,
        "angle": Domain.MATHS,
        "triangle": Domain.MATHS,
        "degrees": Domain.MATHS,
        "sum": Domain.MATHS,
        "polygon": Domain.MATHS,
        "trigonometry": Domain.MATHS,
        "sin": Domain.MATHS,
        "cos": Domain.MATHS,
        "tan": Domain.MATHS,
        "logarithm": Domain.MATHS,
        "exponential": Domain.MATHS,
        "prime": Domain.MATHS,
        # Physics
        "thermodynamics": Domain.PHYSICS,
        "mechanics": Domain.PHYSICS,
        "quantum": Domain.PHYSICS,
        "relativity": Domain.PHYSICS,
        "electromagnetism": Domain.PHYSICS,
        "fluid": Domain.PHYSICS,
        "dynamics": Domain.PHYSICS,
        "kinetic": Domain.PHYSICS,
        "potential": Domain.PHYSICS,
        "energy": Domain.PHYSICS,
        "entropy": Domain.PHYSICS,
        "force": Domain.PHYSICS,
        "motion": Domain.PHYSICS,
        "wave": Domain.PHYSICS,
        "particle": Domain.PHYSICS,
        "simulation": Domain.PHYSICS,
        "nuclear": Domain.PHYSICS,
        "optics": Domain.PHYSICS,
        "acoustics": Domain.PHYSICS,
        "plasma": Domain.PHYSICS,
        "condensed matter": Domain.PHYSICS,
        # Code
        "code": Domain.CODE,
        "program": Domain.CODE,
        "software": Domain.CODE,
        "debug": Domain.CODE,
        "bug": Domain.CODE,
        "error": Domain.CODE,
        "function": Domain.CODE,
        "class": Domain.CODE,
        "api": Domain.CODE,
        "database": Domain.CODE,
        "refactor": Domain.CODE,
        "review": Domain.CODE,
        "test": Domain.CODE,
        "pytest": Domain.CODE,
        "implementation": Domain.CODE,
        "architecture": Domain.CODE,
        "design pattern": Domain.CODE,
        "algorithm": Domain.CODE,
        "python": Domain.CODE,
        "typescript": Domain.CODE,
        "rust": Domain.CODE,
        "go": Domain.CODE,
        "java": Domain.CODE,
        "javascript": Domain.CODE,
        "sql": Domain.CODE,
        "frontend": Domain.CODE,
        "backend": Domain.CODE,
        "deploy": Domain.CODE,
        "ci/cd": Domain.CODE,
        "docker": Domain.CODE,
        "kubernetes": Domain.CODE,
        # Research
        "research": Domain.RESEARCH,
        "search": Domain.RESEARCH,
        "paper": Domain.RESEARCH,
        "article": Domain.RESEARCH,
        "news": Domain.RESEARCH,
        "web": Domain.RESEARCH,
        "data": Domain.RESEARCH,
        "collect": Domain.RESEARCH,
        "gather": Domain.RESEARCH,
        "summarize": Domain.RESEARCH,
        "synthesize": Domain.RESEARCH,
        "literature": Domain.RESEARCH,
        "survey": Domain.RESEARCH,
        "benchmark": Domain.RESEARCH,
        "comparison": Domain.RESEARCH,
        "analysis": Domain.RESEARCH,
        # Reporter
        "report": Domain.REPORTER,
        "document": Domain.REPORTER,
        "write": Domain.REPORTER,
        "format": Domain.REPORTER,
        "markdown": Domain.REPORTER,
        "pdf": Domain.REPORTER,
        "presentation": Domain.REPORTER,
        "slide": Domain.REPORTER,
        "summary": Domain.REPORTER,
        "cross-domain": Domain.REPORTER,
    }

    # Dependency-indicating phrases that link a subtask to a prior result
    _DEPENDENCY_PHRASES: list[str] = [
        "then",
        "after",
        "using the result",
        "based on",
        "from the",
        "with the output",
        "once",
        "subsequently",
        "following",
        "using that",
        "with that",
        "afterward",
        "next",
        "finally",
    ]

    def __init__(self, keyword_domain_map: Optional[dict[str, Domain]] = None) -> None:
        self._keyword_domain_map = keyword_domain_map or self._keyword_domain_map.copy()

    def decompose(
        self,
        task_description: TaskDescription,
        routing_decision: RoutingDecision,
    ) -> list[DecomposedTask]:
        """Decompose a task based on the routing decision."""
        description = task_description.description.strip()

        if not description:
            return [
                DecomposedTask(
                    subtask_id=self._new_id(),
                    domain=routing_decision.primary_domain,
                    task=TaskDescription(
                        title=task_description.title,
                        description=description,
                        expected_output_schema=task_description.expected_output_schema,
                        priority=task_description.priority,
                        tags=task_description.tags,
                    ),
                    estimated_tokens=self._estimate_tokens(description),
                    priority=1,
                )
            ]

        mode = routing_decision.routing_mode

        if mode == RoutingMode.SINGLE:
            return self._decompose_single(task_description, routing_decision)

        if mode == RoutingMode.PARALLEL:
            return self._decompose_parallel(task_description, routing_decision)

        if mode == RoutingMode.SEQUENTIAL:
            return self._decompose_sequential(task_description, routing_decision)

        if mode == RoutingMode.ADAPTIVE:
            return self._decompose_adaptive(task_description, routing_decision)

        # Fallback
        return self._decompose_single(task_description, routing_decision)

    def _decompose_single(
        self,
        task_description: TaskDescription,
        routing_decision: RoutingDecision,
    ) -> list[DecomposedTask]:
        """Single subtask, single domain."""
        description = task_description.description.strip()
        title = self._truncate_title(task_description.title)

        # Even in single mode, detect if the text contains cross-domain keywords
        subtasks_text = self._extract_subtasks(description)
        if len(subtasks_text) > 1:
            # Cross-domain within a single-mode task: split into multiple
            decomposed: list[DecomposedTask] = []
            for i, text in enumerate(subtasks_text):
                domain = self._assign_domain(text, fallback=routing_decision.primary_domain)
                subtask = DecomposedTask(
                    subtask_id=self._new_id(),
                    domain=domain,
                    task=TaskDescription(
                        title=f"{title} (part {i + 1})",
                        description=text,
                        expected_output_schema=task_description.expected_output_schema,
                        priority=task_description.priority,
                        tags=task_description.tags,
                    ),
                    estimated_tokens=self._estimate_tokens(text),
                    priority=i + 1,
                )
                decomposed.append(subtask)
            return self._detect_dependencies(decomposed)

        return [
            DecomposedTask(
                subtask_id=self._new_id(),
                domain=routing_decision.primary_domain,
                task=TaskDescription(
                    title=title,
                    description=description,
                    expected_output_schema=task_description.expected_output_schema,
                    priority=task_description.priority,
                    tags=task_description.tags,
                ),
                estimated_tokens=self._estimate_tokens(description),
                priority=1,
            )
        ]

    def _decompose_parallel(
        self,
        task_description: TaskDescription,
        routing_decision: RoutingDecision,
    ) -> list[DecomposedTask]:
        """Split by sentences/clauses and assign domains independently."""
        description = task_description.description.strip()
        title = self._truncate_title(task_description.title)
        subtasks_text = self._extract_subtasks(description)

        decomposed: list[DecomposedTask] = []
        for i, text in enumerate(subtasks_text):
            domain = self._assign_domain(text, fallback=routing_decision.primary_domain)
            subtask = DecomposedTask(
                subtask_id=self._new_id(),
                domain=domain,
                task=TaskDescription(
                    title=f"{title} (part {i + 1})",
                    description=text,
                    expected_output_schema=task_description.expected_output_schema,
                    priority=task_description.priority,
                    tags=task_description.tags,
                ),
                estimated_tokens=self._estimate_tokens(text),
                priority=i + 1,
            )
            decomposed.append(subtask)

        return self._detect_dependencies(decomposed)

    def _decompose_sequential(
        self,
        task_description: TaskDescription,
        routing_decision: RoutingDecision,
    ) -> list[DecomposedTask]:
        """Split with each subtask depending on the previous."""
        description = task_description.description.strip()
        title = self._truncate_title(task_description.title)
        subtasks_text = self._extract_subtasks(description)

        decomposed: list[DecomposedTask] = []
        prev_id: Optional[str] = None

        for i, text in enumerate(subtasks_text):
            domain = self._assign_domain(text, fallback=routing_decision.primary_domain)
            subtask_id = self._new_id()
            depends_on = [prev_id] if prev_id else []
            subtask = DecomposedTask(
                subtask_id=subtask_id,
                domain=domain,
                task=TaskDescription(
                    title=f"{title} (step {i + 1})",
                    description=text,
                    expected_output_schema=task_description.expected_output_schema,
                    priority=task_description.priority,
                    tags=task_description.tags,
                ),
                depends_on=depends_on,
                estimated_tokens=self._estimate_tokens(text),
                priority=i + 1,
            )
            decomposed.append(subtask)
            prev_id = subtask_id

        return self._detect_dependencies(decomposed)

    def _decompose_adaptive(
        self,
        task_description: TaskDescription,
        routing_decision: RoutingDecision,
    ) -> list[DecomposedTask]:
        """Return a single explore subtask followed by the main task."""
        description = task_description.description.strip()
        title = self._truncate_title(task_description.title)

        explore_id = self._new_id()
        explore = DecomposedTask(
            subtask_id=explore_id,
            domain=routing_decision.primary_domain,
            task=TaskDescription(
                title=f"Explore: {title}",
                description=f"Explore the problem space and determine the best approach.\n\n{description}",
                expected_output_schema=task_description.expected_output_schema,
                priority=task_description.priority,
                tags=task_description.tags,
            ),
            estimated_tokens=self._estimate_tokens(description) // 2,
            priority=1,
        )

        main = DecomposedTask(
            subtask_id=self._new_id(),
            domain=routing_decision.primary_domain,
            task=TaskDescription(
                title=title,
                description=description,
                expected_output_schema=task_description.expected_output_schema,
                priority=task_description.priority,
                tags=task_description.tags,
            ),
            depends_on=[explore_id],
            estimated_tokens=self._estimate_tokens(description),
            priority=2,
        )

        return [explore, main]

    def _extract_subtasks(self, text: str) -> list[str]:
        """Split text into sentences/clauses."""
        if not text.strip():
            return []

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        subtasks: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Try splitting on " and " when both sides contain domain keywords
            # (indicates two distinct subtasks joined by a conjunction)
            if " and " in sentence:
                parts = sentence.split(" and ")
                if len(parts) == 2:
                    left_has = any(kw in parts[0].lower() for kw in self._keyword_domain_map)
                    right_has = any(kw in parts[1].lower() for kw in self._keyword_domain_map)
                    if left_has and right_has:
                        for part in parts:
                            part = part.strip()
                            if part:
                                if part[-1] not in ".!?":
                                    part += "."
                                subtasks.append(part)
                        continue

            # Further split on strong clause boundaries: ";", ", and", "then"
            clauses = re.split(r'(?<!,)\s+;\s+|\s*,\s+and\s+|\s+then\s+', sentence)
            for clause in clauses:
                clause = clause.strip()
                if clause:
                    if clause[-1] not in ".!?":
                        clause += "."
                    subtasks.append(clause)

        return subtasks if subtasks else [text.strip()]

    def _assign_domain(self, subtask_text: str, fallback: Domain) -> Domain:
        """Keyword-based domain assignment with fallback."""
        text_lower = subtask_text.lower()
        scores: dict[Domain, int] = {}

        for keyword, domain in self._keyword_domain_map.items():
            if keyword in text_lower:
                scores[domain] = scores.get(domain, 0) + 1

        if not scores:
            return fallback

        # Return the domain with the highest score
        return max(scores.items(), key=lambda x: x[1])[0]

    def _detect_dependencies(self, subtasks: list[DecomposedTask]) -> list[DecomposedTask]:
        """Add depends_on when one subtask refers to another's output."""
        if len(subtasks) < 2:
            return subtasks

        ids = {st.subtask_id for st in subtasks}
        id_to_index = {st.subtask_id: i for i, st in enumerate(subtasks)}

        for i, subtask in enumerate(subtasks):
            text_lower = subtask.task.description.lower()
            added: set[str] = set(subtask.depends_on)

            for phrase in self._DEPENDENCY_PHRASES:
                if phrase in text_lower:
                    # Link to the immediately preceding subtask if available
                    for j in range(i - 1, -1, -1):
                        prev = subtasks[j]
                        if prev.subtask_id not in added:
                            subtask.depends_on.append(prev.subtask_id)
                            added.add(prev.subtask_id)
                            break
                    break  # only one backward link per phrase match

        # Validate no circular dependencies
        self._validate_no_cycles(subtasks, ids, id_to_index)

        return subtasks

    def _validate_no_cycles(
        self,
        subtasks: list[DecomposedTask],
        ids: set[str],
        id_to_index: dict[str, int],
    ) -> None:
        """Raise ValueError if any circular dependency exists."""
        # Only consider dependencies that point within the same decomposition
        graph: dict[str, list[str]] = {
            st.subtask_id: [d for d in st.depends_on if d in ids]
            for st in subtasks
        }

        visited: set[str] = set()
        rec_stack: set[str] = set()

        def _dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if _dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                if _dfs(node):
                    raise ValueError(
                        f"Circular dependency detected among subtasks: "
                        f"{[st.subtask_id for st in subtasks]}"
                    )

    def _new_id(self) -> str:
        return f"subtask-{uuid.uuid4().hex[:8]}"

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return max(1, len(text) // 4)

    def _truncate_title(self, title: str) -> str:
        if len(title) > 1000:
            return title[:997] + "..."
        return title
