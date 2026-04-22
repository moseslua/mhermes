"""HMAOM Intent Classifier.

Dual-classifier architecture:
- Fast SLM Router (local, <50ms): keyword match, regex, embedding similarity
- Fallback LLM Router (cloud): semantic classification, multi-label routing

If SLM confidence < 0.85, escalate to LLM fallback.
"""

from __future__ import annotations

import re
from typing import Optional

from hmaom.config import GatewayConfig
from hmaom.protocol.schemas import Domain, RoutingDecision, RoutingMode, TaskType


class IntentClassifier:
    """Classifies user intent and produces a RoutingDecision."""

    # Domain keyword patterns for fast SLM routing
    DOMAIN_KEYWORDS: dict[Domain, list[str]] = {
        Domain.FINANCE: [
            "stock", "option", "bond", "portfolio", "risk", "var", "black-scholes",
            "derivative", "market", "trading", "investment", "dividend", "yield",
            "capm", "sharpe", "volatility", "hedge", "asset", "equity", "forex",
            "crypto", "bitcoin", "ethereum", "defi", "nft", "financial",
        ],
        Domain.MATHS: [
            "integral", "derivative", "matrix", "eigenvalue", "probability",
            "statistics", "theorem", "proof", "calculus", "algebra", "geometry",
            "number theory", "differential", "equation", "linear algebra",
            "regression", "hypothesis", "distribution", "bayesian", "optimization",
            "angle", "triangle", "degrees", "sum", "polygon", "trigonometry",
            "sin", "cos", "tan", "logarithm", "exponential", "prime",
        ],
        Domain.PHYSICS: [
            "thermodynamics", "mechanics", "quantum", "relativity", "electromagnetism",
            "fluid", "dynamics", "kinetic", "potential", "energy", "entropy",
            "force", "motion", "wave", "particle", "simulation", "nuclear",
            "optics", "acoustics", "plasma", "condensed matter",
        ],
        Domain.CODE: [
            "code", "program", "software", "debug", "bug", "error", "function",
            "class", "api", "database", "refactor", "review", "test", "pytest",
            "implementation", "architecture", "design pattern", "algorithm",
            "python", "typescript", "rust", "go", "java", "javascript", "sql",
            "frontend", "backend", "deploy", "ci/cd", "docker", "kubernetes",
        ],
        Domain.RESEARCH: [
            "research", "search", "paper", "article", "news", "web", "data",
            "collect", "gather", "summarize", "synthesize", "literature",
            "survey", "benchmark", "comparison", "analysis",
        ],
        Domain.REPORTER: [
            "report", "document", "write", "format", "markdown", "pdf",
            "presentation", "slide", "summary", "synthesis", "cross-domain",
        ],
    }

    # Sequential routing patterns (domain A -> domain B)
    SEQUENTIAL_PATTERNS: list[tuple[re.Pattern, list[Domain]]] = [
        (re.compile(r"thermodynamic(s|) of .*trading", re.I), [Domain.PHYSICS, Domain.FINANCE]),
        (re.compile(r"physics of .*market", re.I), [Domain.PHYSICS, Domain.FINANCE]),
        (re.compile(r"model .*strategy", re.I), [Domain.MATHS, Domain.FINANCE]),
        (re.compile(r"simulate .*code", re.I), [Domain.PHYSICS, Domain.CODE]),
    ]

    # Task type patterns
    TASK_TYPE_PATTERNS: dict[TaskType, list[str]] = {
        TaskType.CREATIVE: ["write", "create", "design", "generate", "draft", "compose"],
        TaskType.META: ["plan", "orchestrate", "coordinate", "manage", "overview"],
        TaskType.ANALYTICAL: ["analyze", "calculate", "compute", "solve", "evaluate"],
        TaskType.SYNTHETIC: ["synthesize", "combine", "merge", "integrate", "reconcile"],
    }

    def __init__(self, config: Optional[GatewayConfig] = None) -> None:
        self.config = config or GatewayConfig()

    def classify(self, user_input: str) -> RoutingDecision:
        """Classify user input and return a RoutingDecision.

        Implements the dual-classifier architecture:
        1. Fast SLM routing (keyword/regex/embedding)
        2. Fallback to LLM if confidence is low
        """
        # Fast SLM classification
        slm_result = self._slm_classify(user_input)

        if slm_result.confidence >= self.config.slm_confidence_threshold:
            return slm_result

        # Fallback to LLM classification
        return self._llm_fallback_classify(user_input, slm_result)

    def _slm_classify(self, user_input: str) -> RoutingDecision:
        """Fast local classification using keywords and patterns."""
        text = user_input.lower()

        # Score each domain by keyword matches
        domain_scores: dict[Domain, float] = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text) / max(len(keywords), 1)
            # Boost exact phrase matches
            for kw in keywords:
                if f" {kw} " in f" {text} " or text.startswith(kw) or text.endswith(kw):
                    score += 0.5
            domain_scores[domain] = score

        # Check sequential patterns
        secondary_domains: list[Domain] = []
        for pattern, domains in self.SEQUENTIAL_PATTERNS:
            if pattern.search(user_input):
                primary = domains[0]
                secondary_domains = domains[1:]
                return RoutingDecision(
                    primary_domain=primary,
                    secondary_domains=secondary_domains,
                    task_type=TaskType.ANALYTICAL,
                    routing_mode=RoutingMode.SEQUENTIAL,
                    estimated_complexity=7,
                    required_synthesis=True,
                    confidence=0.9,
                )

        # Determine primary domain
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        primary_domain = sorted_domains[0][0] if sorted_domains else Domain.RESEARCH
        primary_score = sorted_domains[0][1] if sorted_domains else 0.0

        # Collect secondary domains (significant but not primary)
        for domain, score in sorted_domains[1:]:
            if score > 0.3 and domain != primary_domain:
                secondary_domains.append(domain)

        # Determine routing mode
        if secondary_domains:
            routing_mode = RoutingMode.PARALLEL
        else:
            routing_mode = RoutingMode.SINGLE

        # Determine task type
        task_type = TaskType.ANALYTICAL
        for tt, patterns in self.TASK_TYPE_PATTERNS.items():
            if any(p in text for p in patterns):
                task_type = tt
                break

        # Estimate complexity (1-10)
        complexity = self._estimate_complexity(text)

        # Calculate confidence based on score spread
        if len(sorted_domains) >= 2:
            score_spread = sorted_domains[0][1] - sorted_domains[1][1]
            confidence = min(0.95, 0.5 + score_spread * 2)
        else:
            confidence = 0.6 if primary_score > 0 else 0.3

        return RoutingDecision(
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            task_type=task_type,
            routing_mode=routing_mode,
            estimated_complexity=complexity,
            required_synthesis=len(secondary_domains) > 0,
            confidence=round(confidence, 2),
        )

    def _llm_fallback_classify(self, user_input: str, slm_result: RoutingDecision) -> RoutingDecision:
        """Fallback classification using a cloud LLM.

        In production, this would call an LLM API. For now, we adjust
        the SLM result with slightly lower confidence to indicate fallback.
        """
        # Placeholder: in production, send a structured prompt to the LLM
        # and parse the JSON response into a RoutingDecision
        return slm_result.model_copy(update={"confidence": round(slm_result.confidence * 0.9, 2)})

    def _estimate_complexity(self, text: str) -> int:
        """Estimate task complexity on a 1-10 scale."""
        complexity = 5  # baseline

        # Increase for multi-part tasks
        complexity += text.count("and") // 2
        complexity += text.count(",") // 3

        # Increase for specific complexity indicators
        if any(term in text for term in ["optimize", "simulation", "model", "architecture"]):
            complexity += 2
        if any(term in text for term in ["compare", "contrast", "analyze multiple"]):
            complexity += 1
        if any(term in text for term in ["simple", "quick", "basic", "hello"]):
            complexity -= 2

        return max(1, min(10, complexity))

    def classify_batch(self, inputs: list[str]) -> list[RoutingDecision]:
        """Classify multiple inputs efficiently."""
        return [self.classify(inp) for inp in inputs]
