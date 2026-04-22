"""HMAOM Specialist Hire activation triggers.

Configurable activation triggers that observe routing decisions and
auto-fire when usage patterns cross defined thresholds.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from hmaom.hire.persistence import HirePersistence


@dataclass
class HireTriggerConfig:
    """Configuration for hire activation triggers."""

    min_observations: int = 5
    time_window_hours: int = 24
    confidence_threshold: float = 0.6
    subject_frequency_threshold: int = 3
    min_unique_users: int = 1
    require_low_confidence: bool = True
    require_out_of_domain: bool = False
    enabled: bool = True


@dataclass
class HireTriggerEvent:
    """Event fired when a subject crosses hire thresholds."""

    subject: str
    observation_count: int
    confidence_avg: float
    unique_users: int
    triggered_at: float
    reason: str


class HireActivationTriggers:
    """Evaluates routing interactions and fires hire events when thresholds cross."""

    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "and", "but", "or", "yet", "so", "if",
        "because", "although", "though", "while", "where", "when", "that",
        "which", "who", "whom", "whose", "what", "this", "these", "those",
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
        "us", "them", "my", "your", "his", "its", "our", "their", "mine",
        "yours", "hers", "ours", "theirs", "myself", "yourself", "himself",
        "herself", "itself", "ourselves", "yourselves", "themselves",
        "help", "assist", "need", "want", "like", "get", "use", "using",
    })

    def __init__(self, config: HireTriggerConfig, persistence: HirePersistence) -> None:
        self.config = config
        self.persistence = persistence
        self._lock = threading.Lock()
        # subject -> list of (timestamp, confidence, user_id)
        self._subject_entries: dict[str, list[tuple[float, float, str]]] = {}

    def _extract_keywords(self, user_input: str) -> list[str]:
        """Extract meaningful keywords from user input."""
        words = re.findall(r"[a-zA-Z]{3,}", user_input.lower())
        return [w for w in words if w not in self._STOP_WORDS]

    @staticmethod
    def _get_user_id(result: dict[str, Any]) -> str:
        return result.get("user_id", "anonymous")

    @staticmethod
    def _get_confidence(result: dict[str, Any]) -> float:
        rd = result.get("routing_decision", {})
        return rd.get("confidence", result.get("confidence", 1.0))

    def _is_low_confidence(self, result: dict[str, Any]) -> bool:
        return self._get_confidence(result) < self.config.confidence_threshold

    def _is_out_of_domain(self, result: dict[str, Any]) -> bool:
        rd = result.get("routing_decision", {})
        domain = rd.get("primary_domain", result.get("domain", ""))
        status = result.get("status", result.get("result_status", ""))
        return str(domain).lower() == "meta" or status in ("failure", "error", "out_of_domain", "no_specialists")

    def should_analyze(self, user_input: str, routing_decision: dict[str, Any]) -> bool:
        """Quick pre-filter: should this interaction be analyzed?"""
        if not self.config.enabled:
            return False
        if self.config.require_low_confidence:
            confidence = routing_decision.get("confidence", 1.0)
            if confidence >= self.config.confidence_threshold:
                return False
        if self.config.require_out_of_domain:
            domain = routing_decision.get("primary_domain", "")
            if str(domain).lower() != "meta":
                return False
        keywords = self._extract_keywords(user_input)
        return len(keywords) > 0

    def evaluate(self, user_input: str, result: dict[str, Any]) -> Optional[HireTriggerEvent]:
        """Evaluate a single interaction and return an event if thresholds are crossed."""
        if not self.config.enabled:
            return None
        return self.record_interaction(user_input, result)

    def check_thresholds(self) -> list[HireTriggerEvent]:
        """Scan persistence and return events for subjects crossing thresholds."""
        if not self.config.enabled:
            return []

        since = time.time() - (self.config.time_window_hours * 3600)
        observations = self.persistence.get_observations(since=since, limit=10000)

        # Rebuild subject stats from persistence observations
        subject_entries: dict[str, list[tuple[float, float, str]]] = {}
        for obs in observations:
            keywords = self._extract_keywords(obs.user_input)
            confidence = 1.0
            user_id = "anonymous"
            try:
                rd = json.loads(obs.routing_decision)
                confidence = float(rd.get("confidence", 1.0))
                user_id = rd.get("user_id", "anonymous")
            except Exception:
                pass

            for kw in keywords:
                subject_entries.setdefault(kw, []).append(
                    (obs.timestamp, confidence, user_id)
                )

        events: list[HireTriggerEvent] = []
        now = time.time()
        for subject, entries in subject_entries.items():
            if len(entries) < self.config.min_observations:
                continue
            if len(entries) < self.config.subject_frequency_threshold:
                continue

            users = {uid for _, _, uid in entries}
            if len(users) < self.config.min_unique_users:
                continue

            avg_confidence = sum(conf for _, conf, _ in entries) / len(entries)
            events.append(
                HireTriggerEvent(
                    subject=subject,
                    observation_count=len(entries),
                    confidence_avg=avg_confidence,
                    unique_users=len(users),
                    triggered_at=now,
                    reason=(
                        f"subject '{subject}' crossed threshold: "
                        f"{len(entries)} observations, {avg_confidence:.2f} avg confidence"
                    ),
                )
            )

        return events

    def record_interaction(
        self, user_input: str, result: dict[str, Any]
    ) -> Optional[HireTriggerEvent]:
        """Record an interaction, update counters, return event if any threshold crossed."""
        if not self.config.enabled:
            return None

        routing_decision = dict(result.get("routing_decision", {}))
        specialist_used = result.get("specialist_used", result.get("domain", "unknown"))
        result_status = result.get("status", result.get("result_status", "unknown"))
        user_id = self._get_user_id(result)
        routing_decision["user_id"] = user_id

        self.persistence.log_observation(
            user_input=user_input,
            routing_decision=routing_decision,
            specialist_used=str(specialist_used),
            result_status=result_status,
        )

        keywords = self._extract_keywords(user_input)
        confidence = self._get_confidence(result)
        user_id = self._get_user_id(result)

        with self._lock:
            now = time.time()
            cutoff = now - (self.config.time_window_hours * 3600)

            for kw in keywords:
                entries = self._subject_entries.get(kw, [])
                entries.append((now, confidence, user_id))
                # Prune stale entries
                entries = [e for e in entries if e[0] >= cutoff]
                self._subject_entries[kw] = entries

                if self._subject_crosses_threshold(kw, entries):
                    return self._build_event(kw, entries, now)

        return None

    def _subject_crosses_threshold(self, subject: str, entries: list[tuple[float, float, str]]) -> bool:
        count = len(entries)
        if count < self.config.min_observations:
            return False
        if count < self.config.subject_frequency_threshold:
            return False
        users = {uid for _, _, uid in entries}
        if len(users) < self.config.min_unique_users:
            return False
        return True

    def _build_event(
        self,
        subject: str,
        entries: list[tuple[float, float, str]],
        triggered_at: float,
    ) -> HireTriggerEvent:
        count = len(entries)
        avg_confidence = sum(conf for _, conf, _ in entries) / count
        users = {uid for _, _, uid in entries}
        return HireTriggerEvent(
            subject=subject,
            observation_count=count,
            confidence_avg=avg_confidence,
            unique_users=len(users),
            triggered_at=triggered_at,
            reason=(
                f"subject '{subject}' crossed threshold: "
                f"{count} observations in {self.config.time_window_hours}h window"
            ),
        )
