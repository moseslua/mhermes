"""HMAOM Context Slicer.

Produces context slices with boundary markers to prevent leakage
across agent contexts.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class ContextSliceResult(BaseModel):
    """A single sliced context with metadata."""

    content: str = Field(description="The sliced content including boundary markers")
    boundary_marker: str = Field(description="The begin-boundary marker for this slice")
    token_estimate: int = Field(description="Rough token estimate for this slice")
    relevance_score: float = Field(ge=0.0, le=1.0, description="Relevance of this slice")
    source_agent: str = Field(description="Agent that produced the source content")


class ContextSlicer:
    """Split long text into context slices with boundary markers and overlap.

    Features:
    - Sentence-aware splitting
    - Overlap between adjacent slices
    - Boundary markers to prevent context leakage
    - Extraction and merging utilities
    """

    def __init__(self, max_tokens_per_slice: int = 4000, overlap_tokens: int = 200) -> None:
        self.max_tokens_per_slice = max_tokens_per_slice
        self.overlap_tokens = overlap_tokens

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token heuristic: len(words) * 1.3."""
        return int(len(text.split()) * 1.3)

    @staticmethod
    def _validate_agent_name(name: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            raise ValueError(f"Invalid agent name: {name}")
        return name

    @staticmethod
    def wrap_with_boundary(content: str, source_agent: str, relevance_score: float = 1.0) -> str:
        """Wrap content with begin/end boundary markers."""
        source_agent = ContextSlicer._validate_agent_name(source_agent)
        begin = f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---"
        end = f"--- END CONTEXT SLICE [source={source_agent}] ---"
        return f"{begin}\n{content}\n{end}"

    def slice_text(
        self,
        text: str,
        source_agent: str,
        relevance_score: float = 1.0,
    ) -> list[ContextSliceResult]:
        """Split long text into multiple slices with overlap.

        Splits on sentence boundaries where possible. Short text produces a
        single slice.
        """
        source_agent = self._validate_agent_name(source_agent)
        if not text:
            return [
                ContextSliceResult(
                    content=self.wrap_with_boundary("", source_agent, relevance_score),
                    boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                    token_estimate=0,
                    relevance_score=relevance_score,
                    source_agent=source_agent,
                )
            ]

        total_tokens = self._estimate_tokens(text)
        if total_tokens <= self.max_tokens_per_slice:
            wrapped = self.wrap_with_boundary(text, source_agent, relevance_score)
            return [
                ContextSliceResult(
                    content=wrapped,
                    boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                    token_estimate=total_tokens,
                    relevance_score=relevance_score,
                    source_agent=source_agent,
                )
            ]


        sentences = self._split_sentences(text)
        # If the whole text is one giant sentence, fall back to word chunks
        if len(sentences) <= 1:
            return self._slice_by_words(text, source_agent, relevance_score)

        slices: list[ContextSliceResult] = []
        current_sentences: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = self._estimate_tokens(sentence)

            if current_tokens + sentence_tokens > self.max_tokens_per_slice and current_sentences:
                # Finalise current slice
                slice_text_content = " ".join(current_sentences).strip()
                wrapped = self.wrap_with_boundary(slice_text_content, source_agent, relevance_score)
                slices.append(
                    ContextSliceResult(
                        content=wrapped,
                        boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                        token_estimate=self._estimate_tokens(slice_text_content),
                        relevance_score=relevance_score,
                        source_agent=source_agent,
                    )
                )

                # Compute overlap sentences based on overlap token budget
                overlap_sentences = self._compute_overlap(current_sentences)
                current_sentences = overlap_sentences + [sentence]
                current_tokens = self._estimate_tokens(" ".join(current_sentences))
            else:
                current_sentences.append(sentence)
                current_tokens += sentence_tokens

        # Final slice
        if current_sentences:
            slice_text_content = " ".join(current_sentences).strip()
            wrapped = self.wrap_with_boundary(slice_text_content, source_agent, relevance_score)
            slices.append(
                ContextSliceResult(
                    content=wrapped,
                    boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                    token_estimate=self._estimate_tokens(slice_text_content),
                    relevance_score=relevance_score,
                    source_agent=source_agent,
                )
            )

        return slices

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences, preserving sentence-ending punctuation."""
        # Split on period, exclamation, question mark followed by space or end
        raw = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in raw if s.strip()]

    def _compute_overlap(self, sentences: list[str]) -> list[str]:
        """Return the trailing sentences that fit within overlap_tokens."""
        overlap: list[str] = []
        token_count = 0
        for sentence in reversed(sentences):
            t = self._estimate_tokens(sentence)
            if token_count + t > self.overlap_tokens:
                break
            overlap.insert(0, sentence)
            token_count += t
        return overlap
    def _slice_by_words(
        self, text: str, source_agent: str, relevance_score: float
    ) -> list[ContextSliceResult]:
        """Fallback word-boundary slicer for single-sentence overflow."""
        words = text.split()
        slices: list[ContextSliceResult] = []
        current_words: list[str] = []
        current_tokens = 0.0
        word_token_estimate = 1.3  # per word

        for word in words:
            if current_tokens + word_token_estimate > self.max_tokens_per_slice and current_words:
                slice_text_content = " ".join(current_words)
                wrapped = self.wrap_with_boundary(slice_text_content, source_agent, relevance_score)
                slices.append(
                    ContextSliceResult(
                        content=wrapped,
                        boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                        token_estimate=self._estimate_tokens(slice_text_content),
                        relevance_score=relevance_score,
                        source_agent=source_agent,
                    )
                )
                # overlap
                overlap_words = int(self.overlap_tokens / word_token_estimate)
                current_words = current_words[-overlap_words:] + [word]
                current_tokens = len(current_words) * word_token_estimate
            else:
                current_words.append(word)
                current_tokens += word_token_estimate

        if current_words:
            slice_text_content = " ".join(current_words)
            wrapped = self.wrap_with_boundary(slice_text_content, source_agent, relevance_score)
            slices.append(
                ContextSliceResult(
                    content=wrapped,
                    boundary_marker=f"--- BEGIN CONTEXT SLICE [source={source_agent}] [score={relevance_score:.2f}] ---",
                    token_estimate=self._estimate_tokens(slice_text_content),
                    relevance_score=relevance_score,
                    source_agent=source_agent,
                )
            )

        return slices

    @staticmethod
    def extract_from_markers(text: str) -> list[dict[str, Any]]:
        """Parse text and extract all content between boundary markers.

        Returns a list of dicts with keys: source_agent, relevance_score, content.
        """
        pattern = re.compile(
            r"--- BEGIN CONTEXT SLICE \[source=([^\]]+)\] \[score=([\d.]+)\] ---\n"
            r"(.*?)"
            r"\n--- END CONTEXT SLICE \[source=([^\]]+)\] ---",
            re.DOTALL,
        )
        results: list[dict[str, Any]] = []
        for match in pattern.finditer(text):
            begin_source = match.group(1)
            score = float(match.group(2))
            content = match.group(3)
            end_source = match.group(4)
            # Only include if markers are self-consistent
            if begin_source == end_source:
                results.append(
                    {
                        "source_agent": begin_source,
                        "relevance_score": score,
                        "content": content,
                    }
                )
        return results

    @staticmethod
    def merge_slices(slices: list[ContextSliceResult]) -> str:
        """Merge multiple slices into one text, removing duplicate overlap.

        Uses a simple greedy overlap-detection: if the end of the accumulated
        text matches the start of the next slice's raw content, the overlapping
        portion is skipped.
        """
        if not slices:
            return ""

        # Extract raw content from each slice (strip boundary markers)
        raw_contents = []
        for slc in slices:
            extracted = ContextSlicer.extract_from_markers(slc.content)
            if extracted:
                raw_contents.append(extracted[0]["content"])
            else:
                # Fallback: treat the whole content as raw
                raw_contents.append(slc.content)

        merged = raw_contents[0]
        for nxt in raw_contents[1:]:
            # Find the longest suffix of `merged` that is a prefix of `nxt`
            overlap_len = 0
            max_possible = min(len(merged), len(nxt))
            for length in range(max_possible, 0, -1):
                if merged[-length:] == nxt[:length]:
                    overlap_len = length
                    break
            merged += nxt[overlap_len:]

        return merged
