"""HMAOM Prompt Injection Guardrails.

Pattern-based scanner for prompt-injection and jailbreak attempts.
"""

from __future__ import annotations

import re
import threading
from typing import Optional


class GuardrailScanner:
    """Scan input text for prompt-injection patterns.

    Maintains a list of compiled regex patterns and produces a
    (blocked, score, matched_patterns) verdict.
    """

    _DEFAULT_PATTERNS: list[str] = [
        # Delimiter injection
        r"<\|end\|>",
        r"###",
        r"---\s*SYSTEM\s*---",
        # Role-play jailbreaks
        r"(?i)\b(DAN|developer mode|jailbreak)\b",
        # Ignore-instruction attacks
        r"(?i)(ignore previous|disregard all|forget prior)",
        # System prompt override
        r"(?i)(system prompt|you are now)",
    ]

    def __init__(self, patterns: Optional[list[str]] = None, block_threshold: Optional[float] = None) -> None:
        self._lock = threading.Lock()
        self._weights: dict[str, float] = {}
        self._block_threshold = block_threshold if block_threshold is not None else 0.0
        raw_patterns = list(patterns) if patterns is not None else list(self._DEFAULT_PATTERNS)
        self._patterns: list[tuple[re.Pattern[str], str, float]] = []
        for pat in raw_patterns:
            self._add_compiled(pat)

    # ── Public API ──────────────────────────────────────────────────────────

    def scan(self, input_text: str) -> tuple[bool, float, list[str]]:
        """Scan *input_text* and return (blocked, score, matched_patterns).

        *blocked* is ``True`` when the normalized score >= threshold.
        *score* is the weighted average of matched patterns.
        """

        if not isinstance(input_text, str):
            input_text = str(input_text)

        matched: list[str] = []
        with self._lock:
            items = list(self._patterns)

        for compiled, name, weight in items:
            if compiled.search(input_text):
                matched.append(name)

        if not items:
            return False, 0.0, []

        total_weight = sum(w for _, _, w in items)
        matched_weight = sum(
            w for _, name, w in items if name in matched
        )
        score = matched_weight / total_weight if total_weight > 0 else 0.0
        blocked = score > 0.0 and score >= self._block_threshold
        return blocked, round(score, 4), matched

    def add_pattern(self, pattern: str, weight: Optional[float] = None) -> None:
        """Add a new regex pattern dynamically."""
        if weight is not None:
            with self._lock:
                self._weights[pattern] = float(weight)
        self._add_compiled(pattern)

    def list_patterns(self) -> list[str]:
        """Return all registered pattern strings."""
        with self._lock:
            return [name for _, name, _ in self._patterns]

    def remove_pattern(self, pattern: str) -> bool:
        """Remove a pattern by its raw string. Returns True if removed."""
        with self._lock:
            original_len = len(self._patterns)
            self._patterns = [
                (c, n, w) for c, n, w in self._patterns if n != pattern
            ]
            return len(self._patterns) < original_len

    # ── Internals ───────────────────────────────────────────────────────────

    def _add_compiled(self, pattern: str) -> None:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {pattern}: {exc}")
        with self._lock:
            weight = self._weights.get(pattern, 1.0)
            self._patterns.append((compiled, pattern, weight))
