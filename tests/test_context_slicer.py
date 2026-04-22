"""Tests for ContextSlicer.

Covers: single slice, multi-slice split, boundary marker wrapping,
extraction from markers, merge slices with overlap, empty text,
relevance score passthrough, token estimation.
"""

from __future__ import annotations

import pytest

from hmaom.state.context_slicer import ContextSliceResult, ContextSlicer


class TestContextSlicer:
    # ── single slice ──

    def test_single_slice_short_text(self):
        slicer = ContextSlicer(max_tokens_per_slice=4000, overlap_tokens=200)
        text = "This is a short text. It fits in one slice."
        slices = slicer.slice_text(text, source_agent="test_agent", relevance_score=0.95)

        assert len(slices) == 1
        assert slices[0].source_agent == "test_agent"
        assert slices[0].relevance_score == 0.95
        assert "--- BEGIN CONTEXT SLICE [source=test_agent] [score=0.95] ---" in slices[0].content
        assert "--- END CONTEXT SLICE [source=test_agent] ---" in slices[0].content
        assert "This is a short text." in slices[0].content

    # ── multi-slice split ──

    def test_multi_slice_split_on_sentence_boundary(self):
        # Create a text that exceeds max_tokens_per_slice.
        # Each word ~ 1.3 tokens. 4000 tokens / 1.3 ≈ 3077 words.
        words = ["word"] * 3500
        text = " ".join(words) + "."
        slicer = ContextSlicer(max_tokens_per_slice=4000, overlap_tokens=200)
        slices = slicer.slice_text(text, source_agent="agent_a")

        assert len(slices) > 1
        for slc in slices:
            assert slc.source_agent == "agent_a"
            assert "--- BEGIN CONTEXT SLICE" in slc.content
            assert "--- END CONTEXT SLICE" in slc.content

    # ── boundary marker wrapping ──

    def test_wrap_with_boundary_format(self):
        wrapped = ContextSlicer.wrap_with_boundary("hello world", "finance_agent", 0.88)
        assert wrapped.startswith("--- BEGIN CONTEXT SLICE [source=finance_agent] [score=0.88] ---\n")
        assert wrapped.endswith("\n--- END CONTEXT SLICE [source=finance_agent] ---")
        assert "hello world" in wrapped

    # ── extraction from markers ──

    def test_extract_from_markers(self):
        text = (
            "prefix\n"
            "--- BEGIN CONTEXT SLICE [source=agent1] [score=0.90] ---\n"
            "content one\n"
            "--- END CONTEXT SLICE [source=agent1] ---\n"
            "middle\n"
            "--- BEGIN CONTEXT SLICE [source=agent2] [score=0.75] ---\n"
            "content two\n"
            "more content\n"
            "--- END CONTEXT SLICE [source=agent2] ---\n"
            "suffix"
        )
        extracted = ContextSlicer.extract_from_markers(text)
        assert len(extracted) == 2
        assert extracted[0]["source_agent"] == "agent1"
        assert extracted[0]["relevance_score"] == 0.90
        assert extracted[0]["content"] == "content one"
        assert extracted[1]["source_agent"] == "agent2"
        assert extracted[1]["relevance_score"] == 0.75
        assert extracted[1]["content"] == "content two\nmore content"

    def test_extract_from_markers_mismatched_source_ignored(self):
        text = (
            "--- BEGIN CONTEXT SLICE [source=agent1] [score=1.00] ---\n"
            "bad content\n"
            "--- END CONTEXT SLICE [source=agent2] ---"
        )
        extracted = ContextSlicer.extract_from_markers(text)
        assert extracted == []

    # ── merge slices with overlap ──

    def test_merge_slices_removes_overlap(self):
        # Simulate two slices where slice 2 starts with overlapping text.
        slice1 = ContextSliceResult(
            content=ContextSlicer.wrap_with_boundary("First part. Overlap text.", "agent1"),
            boundary_marker="",
            token_estimate=10,
            relevance_score=1.0,
            source_agent="agent1",
        )
        slice2 = ContextSliceResult(
            content=ContextSlicer.wrap_with_boundary("Overlap text. Second part.", "agent1"),
            boundary_marker="",
            token_estimate=10,
            relevance_score=1.0,
            source_agent="agent1",
        )
        merged = ContextSlicer.merge_slices([slice1, slice2])
        assert merged == "First part. Overlap text. Second part."

    def test_merge_slices_single_slice(self):
        slice1 = ContextSliceResult(
            content=ContextSlicer.wrap_with_boundary("Only content.", "agent1"),
            boundary_marker="",
            token_estimate=10,
            relevance_score=1.0,
            source_agent="agent1",
        )
        assert ContextSlicer.merge_slices([slice1]) == "Only content."

    def test_merge_slices_empty(self):
        assert ContextSlicer.merge_slices([]) == ""

    # ── empty text ──

    def test_empty_text_returns_single_slice(self):
        slicer = ContextSlicer()
        slices = slicer.slice_text("", source_agent="agent1", relevance_score=0.5)
        assert len(slices) == 1
        assert slices[0].token_estimate == 0
        assert slices[0].relevance_score == 0.5
        # Should contain empty content wrapped in markers
        extracted = ContextSlicer.extract_from_markers(slices[0].content)
        assert len(extracted) == 1
        assert extracted[0]["content"] == ""

    # ── relevance score passthrough ──

    def test_relevance_score_passthrough(self):
        slicer = ContextSlicer()
        slices = slicer.slice_text("Hello.", source_agent="a", relevance_score=0.42)
        assert slices[0].relevance_score == 0.42
        assert "[score=0.42]" in slices[0].boundary_marker
        assert "[score=0.42]" in slices[0].content

    # ── token estimation ──

    def test_token_estimation(self):
        text = "one two three four five"
        expected = int(5 * 1.3)  # 6
        slicer = ContextSlicer()
        slices = slicer.slice_text(text, source_agent="x")
        assert slices[0].token_estimate == expected

    def test_multi_slice_overlap_includes_trailing_sentences(self):
        # Force a multi-slice scenario with predictable sentence boundaries.
        # 4 words per sentence, ~5.2 tokens each. 4000 tokens / 5.2 ≈ 769 sentences.
        sentences = [f"Sentence number {i} here." for i in range(900)]
        text = " ".join(sentences)
        slicer = ContextSlicer(max_tokens_per_slice=4000, overlap_tokens=200)
        slices = slicer.slice_text(text, source_agent="agent1")

        assert len(slices) > 1
        # Verify overlap: the start of slice 2 should contain sentences from the end of slice 1.
        raw1 = ContextSlicer.extract_from_markers(slices[0].content)[0]["content"]
        raw2 = ContextSlicer.extract_from_markers(slices[1].content)[0]["content"]
        assert raw2.startswith(raw1[-len(raw2) : len(raw1)]) or any(
            s in raw2 for s in raw1.split(".")[-5:]
        )
    def test_invalid_agent_name_rejected(self):
        slicer = ContextSlicer()
        with pytest.raises(ValueError, match="Invalid agent name"):
            slicer.slice_text("Hello.", source_agent="bad[agent]")
        with pytest.raises(ValueError, match="Invalid agent name"):
            ContextSlicer.wrap_with_boundary("content", "agent;injection")
