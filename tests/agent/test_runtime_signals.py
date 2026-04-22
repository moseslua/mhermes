import pytest

from agent.runtime_signals import (
    RuntimeSignal,
    RuntimeSignalRef,
    emit_runtime_signal,
    make_runtime_signal,
)


class TestRuntimeSignalEmission:
    def test_signal_creation(self):
        signal = make_runtime_signal(
            event_type="test.event",
            phase="started",
            publisher="test",
        )
        assert signal.event_type == "test.event"
        assert signal.phase == "started"
        assert signal.publisher == "test"
        assert signal.provenance == "system"

    def test_signal_with_provenance(self):
        signal = make_runtime_signal(
            event_type="test.event",
            phase="completed",
            publisher="test",
            provenance="untrusted",
        )
        assert signal.provenance == "untrusted"

    def test_signal_with_trusted_provenance(self):
        signal = make_runtime_signal(
            event_type="test.event",
            phase="completed",
            publisher="test",
            provenance="trusted",
        )
        assert signal.provenance == "trusted"

    def test_signal_with_actor_and_subject(self):
        actor = RuntimeSignalRef(kind="user", id="u123")
        subject = RuntimeSignalRef(kind="tool", id="t456")
        signal = make_runtime_signal(
            event_type="tool.call",
            phase="started",
            publisher="test",
            actor=actor,
            subject=subject,
        )
        assert signal.actor == actor
        assert signal.subject == subject

    def test_signal_to_dict_roundtrip(self):
        signal = make_runtime_signal(
            event_type="tool.call",
            phase="completed",
            publisher="test",
            provenance="trusted",
            actor={"kind": "agent", "id": "a1"},
            subject={"kind": "file", "id": "/tmp/foo"},
            payload={"result": "ok"},
        )
        d = signal.to_dict()
        restored = RuntimeSignal.from_dict(d)
        assert restored.event_type == signal.event_type
        assert restored.phase == signal.phase
        assert restored.provenance == signal.provenance
        assert restored.actor == signal.actor
        assert restored.subject == signal.subject
        assert restored.payload == signal.payload

    def test_invalid_provenance_raises(self):
        with pytest.raises(ValueError, match="Unsupported runtime-signal provenance"):
            make_runtime_signal(
                event_type="test.event",
                phase="started",
                publisher="test",
                provenance="bogus",
            )

    def test_signal_with_system_provenance(self):
        signal = make_runtime_signal(
            event_type="session.lifecycle",
            phase="started",
            publisher="test",
            provenance="system",
        )
        assert signal.provenance == "system"


class TestSequenceNoMonotonicity:
    def test_sequence_no_increases_across_signals(self):
        base = {
            "event_type": "test.event",
            "phase": "started",
            "publisher": "test",
        }
        s1 = make_runtime_signal(sequence_no=1, **base)
        s2 = make_runtime_signal(sequence_no=2, **base)
        s3 = make_runtime_signal(sequence_no=3, **base)
        assert s1.sequence_no < s2.sequence_no < s3.sequence_no

    def test_sequence_no_zero_rejected(self):
        with pytest.raises(ValueError, match="sequence_no must be >= 1"):
            make_runtime_signal(
                event_type="test.event",
                phase="started",
                publisher="test",
                sequence_no=0,
            )

    def test_sequence_no_none_allowed(self):
        s = make_runtime_signal(
            event_type="test.event",
            phase="started",
            publisher="test",
            sequence_no=None,
        )
        assert s.sequence_no is None


class TestEmitRuntimeSignal:
    def test_emit_returns_none_without_db(self):
        signal = make_runtime_signal(
            event_type="test.event",
            phase="started",
            publisher="test",
        )
        result = emit_runtime_signal(signal)
        assert result is None

    def test_emit_with_provenance_untrusted(self):
        signal = make_runtime_signal(
            event_type="tool.call",
            phase="completed",
            publisher="test",
            provenance="untrusted",
        )
        result = emit_runtime_signal(signal)
        assert result is None

    def test_emit_with_provenance_trusted(self):
        signal = make_runtime_signal(
            event_type="user.intent",
            phase="started",
            publisher="test",
            provenance="trusted",
        )
        result = emit_runtime_signal(signal)
        assert result is None
