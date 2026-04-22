"""HMAOM Specialist Hire analyzer.

Detects usage patterns suggesting a new specialist is needed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from hmaom.hire.persistence import HireObservation, HirePersistence


@dataclass
class HireSuggestion:
    """A suggestion to create a new specialist."""

    suggested_name: str
    suggested_domain: str
    keywords: list[str] = field(default_factory=list)
    observation_count: int = 0
    confidence_avg: float = 0.0
    reason: str = ""


class HireAnalyzer:
    """Analyzes routing observations to detect gaps in specialist coverage.

    Threshold: if >10 requests in 24h share keywords not well-covered by
    existing domains AND confidence < 0.7, suggest a new specialist.
    """

    def __init__(
        self,
        persistence: Optional[HirePersistence] = None,
        existing_domains: Optional[set[str]] = None,
    ) -> None:
        self.persistence = persistence or HirePersistence()
        self.existing_domains = existing_domains or set()

    def analyze(self) -> list[HireSuggestion]:
        """Run analysis and return a list of hire suggestions."""
        since = time.time() - 86400  # 24 hours ago
        observations = self.persistence.get_observations(since=since, limit=5000)

        # Filter to low-confidence or problematic outcomes
        candidates = self._filter_candidates(observations)

        # Extract keyword clusters
        clusters = self._cluster_by_keywords(candidates)

        suggestions: list[HireSuggestion] = []
        for keywords, obs_list in clusters.items():
            if len(obs_list) <= 10:
                continue

            avg_confidence = self._average_confidence(obs_list)
            if avg_confidence >= 0.7:
                continue

            # Check whether these keywords are covered by existing domains
            if self._covered_by_existing(keywords, obs_list):
                continue

            suggested_name, suggested_domain = self._derive_name(keywords)
            suggestions.append(
                HireSuggestion(
                    suggested_name=suggested_name,
                    suggested_domain=suggested_domain,
                    keywords=list(keywords),
                    observation_count=len(obs_list),
                    confidence_avg=avg_confidence,
                    reason=(
                        f"{len(obs_list)} requests in 24h share keywords "
                        f"{list(keywords)} with avg confidence {avg_confidence:.2f}"
                    ),
                )
            )

        # Sort by observation count descending
        suggestions.sort(key=lambda s: s.observation_count, reverse=True)
        return suggestions

    def _filter_candidates(self, observations: list[HireObservation]) -> list[HireObservation]:
        """Select observations that indicate a coverage gap."""
        candidates = []
        for obs in observations:
            if obs.result_status in ("out_of_domain", "no_specialists", "failure"):
                candidates.append(obs)
                continue
            # Include low-confidence successful routes too
            try:
                import json
                decision = json.loads(obs.routing_decision)
                confidence = float(decision.get("confidence", 1.0))
                if confidence < 0.7:
                    candidates.append(obs)
            except Exception:
                pass
        return candidates

    def _cluster_by_keywords(
        self, observations: list[HireObservation]
    ) -> dict[frozenset[str], list[HireObservation]]:
        """Group observations by overlapping keyword sets."""
        clusters: dict[frozenset[str], list[HireObservation]] = {}
        for obs in observations:
            words = self._extract_keywords(obs.user_input)
            if not words:
                continue
            matched = False
            for key in list(clusters.keys()):
                if key & words:
                    merged = key | words
                    entries = clusters.pop(key)
                    entries.append(obs)
                    clusters[merged] = entries
                    matched = True
                    break
            if not matched:
                clusters[words] = [obs]
        return clusters

    @staticmethod
    def _extract_keywords(text: str) -> frozenset[str]:
        """Extract meaningful keywords from user input."""
        # Simple keyword extraction: lowercase, strip punctuation, drop stopwords
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "and", "but", "or", "yet", "so", "if",
            "because", "although", "though", "while", "where", "when",
            "that", "which", "who", "whom", "whose", "what", "this",
            "these", "those", "i", "you", "he", "she", "it", "we", "they",
            "me", "him", "her", "us", "them", "my", "your", "his", "its",
            "our", "their", "how", "why", "please", "help", "me", "my",
        }
        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return frozenset(w for w in words if w not in stopwords)

    @staticmethod
    def _average_confidence(observations: list[HireObservation]) -> float:
        total = 0.0
        count = 0
        for obs in observations:
            try:
                import json
                decision = json.loads(obs.routing_decision)
                total += float(decision.get("confidence", 1.0))
                count += 1
            except Exception:
                pass
        return total / count if count else 0.0

    def _covered_by_existing(
        self, keywords: frozenset[str], observations: list[HireObservation]
    ) -> bool:
        """Heuristic: are these keywords already covered by an existing domain?"""
        # If any existing domain name appears directly in keywords, consider covered
        for domain in self.existing_domains:
            if domain.lower() in keywords:
                return True
        # Also check if most observations were routed to a single known domain
        domain_counts: dict[str, int] = {}
        for obs in observations:
            primary = obs.specialist_used.split("+")[0]
            domain_counts[primary] = domain_counts.get(primary, 0) + 1
        for domain, count in domain_counts.items():
            if domain in self.existing_domains and count > len(observations) * 0.5:
                return True
        return False

    @staticmethod
    def _derive_name(keywords: frozenset[str]) -> tuple[str, str]:
        """Derive a specialist name and domain from keyword cluster."""
        # Pick the most frequent / longest keyword as the domain name
        ordered = sorted(keywords, key=lambda w: (-len(w), w))
        chosen = ordered[0] if ordered else "custom"
        domain = chosen.lower().replace(" ", "_")
        name = f"{domain}_specialist"
        return name, domain
