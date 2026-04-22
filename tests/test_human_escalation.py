"""Tests for the HMAOM Human Escalation system."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest

from hmaom.config import EscalationConfig
from hmaom.fault_tolerance.human_escalation import (
    CLIPauseChannel,
    EmailChannel,
    EscalationChannel,
    EscalationRecord,
    HumanEscalation,
    SlackChannel,
)
from hmaom.gateway.router import GatewayRouter
from hmaom.protocol.schemas import AgentAddress, ContextSlice, SpawnConstraints, SpawnRequest, SpawnResult, TaskDescription


class TestCLIPauseChannel:
    def test_send_writes_to_output_stream(self):
        out = io.StringIO()
        ch = CLIPauseChannel(output_stream=out)
        assert ch.send({"key": "value"}) is True
        text = out.getvalue()
        assert "HUMAN ESCALATION" in text
        assert '"key": "value"' in text

    def test_await_response_reads_json(self):
        inp = io.StringIO('{"action": "retry_same"}\n')
        out = io.StringIO()
        ch = CLIPauseChannel(input_stream=inp, output_stream=out)
        resp = ch.await_response(timeout=10)
        assert resp == {"action": "retry_same"}

    def test_await_response_skip_returns_none(self):
        inp = io.StringIO("skip\n")
        out = io.StringIO()
        ch = CLIPauseChannel(input_stream=inp, output_stream=out)
        resp = ch.await_response(timeout=10)
        assert resp is None

    def test_await_response_eof_returns_none(self):
        inp = io.StringIO("")
        out = io.StringIO()
        ch = CLIPauseChannel(input_stream=inp, output_stream=out)
        resp = ch.await_response(timeout=10)
        assert resp is None

    def test_send_failure_on_broken_stream(self):
        broken = MagicMock()
        broken.write.side_effect = OSError("broken")
        ch = CLIPauseChannel(output_stream=broken)
        assert ch.send({"x": 1}) is False


class TestSlackChannel:
    def test_inject_response_and_await(self):
        ch = SlackChannel(webhook_url="http://example.com/hook")
        assert ch.await_response(timeout=1) is None
        ch.inject_response({"action": "abort"})
        assert ch.await_response(timeout=1) == {"action": "abort"}

    def test_send_returns_false_on_bad_url(self):
        ch = SlackChannel(webhook_url="not-a-valid-url")
        assert ch.send({"correlation_id": "c1"}) is False


class TestEmailChannel:
    def test_send_with_mock_smtp(self):
        mock_smtp = MagicMock()
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_addr="bot@example.com",
            to_addrs=["ops@example.com"],
        )
        ch.set_mock_smtp(mock_smtp)
        assert ch.send({"correlation_id": "c1"}) is True
        mock_smtp.sendmail.assert_called_once()

    def test_await_response_with_injected_response(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_addr="bot@example.com",
            to_addrs=["ops@example.com"],
        )
        ch.inject_response({"action": "retry_same"})
        assert ch.await_response(timeout=1) == {"action": "retry_same"}

    def test_send_without_mock_fails_gracefully(self):
        ch = EmailChannel(
            smtp_host="invalid.host.local",
            smtp_port=25,
            from_addr="a@b.com",
            to_addrs=["c@d.com"],
        )
        assert ch.send({"x": 1}) is False


class TestHumanEscalationPackageContext:
    def test_package_context_structure(self):
        he = HumanEscalation()
        req = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="t", description="d"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        ctx = he.package_context(
            correlation_id="c1",
            trace_summary={"steps": ["a", "b"]},
            failed_attempts=[
                SpawnResult(spawn_id="s1", status="failure", error="oom", tokens_used=100, time_ms=500),
            ],
            request_context=req,
            checkpoint_url="chk://1",
        )
        assert ctx["correlation_id"] == "c1"
        assert ctx["trace_summary"] == {"steps": ["a", "b"]}
        assert len(ctx["failed_attempts"]) == 1
        assert ctx["failed_attempts"][0]["error"] == "oom"
        assert ctx["checkpoint_url"] == "chk://1"
        assert "suggested_actions" in ctx
        assert ctx["request_context"]["spawn_id"] == "s1"

    def test_package_context_empty_failed_attempts(self):
        he = HumanEscalation()
        req = SpawnRequest(
            spawn_id="s2",
            parent_id="p1",
            correlation_id="c2",
            depth=0,
            task=TaskDescription(title="t2", description="d2"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        ctx = he.package_context(
            correlation_id="c2",
            trace_summary={},
            failed_attempts=[],
            request_context=req,
        )
        assert ctx["failed_attempts"] == []
        assert ctx["checkpoint_url"] is None


class TestHumanEscalationEscalate:
    def test_escalate_success(self):
        he = HumanEscalation(EscalationConfig(human_response_timeout_seconds=5))
        ch = MagicMock(spec=EscalationChannel)
        ch.send.return_value = True
        ch.await_response.return_value = {"action": "retry_same"}

        req = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="t", description="d"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        resp = he.escalate(
            correlation_id="c1",
            trace_summary={},
            failed_attempts=[],
            request_context=req,
            channel=ch,
        )
        assert resp == {"action": "retry_same"}
        ch.send.assert_called_once()
        ch.await_response.assert_called_once_with(timeout=5)

    def test_escalate_channel_failure(self):
        he = HumanEscalation()
        ch = MagicMock(spec=EscalationChannel)
        ch.send.return_value = False

        req = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="t", description="d"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        resp = he.escalate(
            correlation_id="c1",
            trace_summary={},
            failed_attempts=[],
            request_context=req,
            channel=ch,
        )
        assert resp["action"] == "abort"
        assert resp["reason"] == "escalation_channel_failed"

    def test_escalate_human_timeout(self):
        he = HumanEscalation(EscalationConfig(human_response_timeout_seconds=1))
        ch = MagicMock(spec=EscalationChannel)
        ch.send.return_value = True
        ch.await_response.return_value = None

        req = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="t", description="d"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        resp = he.escalate(
            correlation_id="c1",
            trace_summary={},
            failed_attempts=[],
            request_context=req,
            channel=ch,
        )
        assert resp["action"] == "abort"
        assert resp["reason"] == "human_timeout"

    def test_escalate_history_recorded(self):
        he = HumanEscalation()
        ch = MagicMock(spec=EscalationChannel)
        ch.send.return_value = True
        ch.__class__.__name__ = "MockChannel"
        ch.await_response.return_value = {"action": "decompose"}

        req = SpawnRequest(
            spawn_id="s1",
            parent_id="p1",
            correlation_id="c1",
            depth=1,
            task=TaskDescription(title="t", description="d"),
            context_slice=ContextSlice(source_agent="test", relevance_score=1.0, content="ctx"),
        )
        he.escalate(
            correlation_id="c1",
            trace_summary={},
            failed_attempts=[],
            request_context=req,
            channel=ch,
        )
        history = he.get_history()
        assert len(history) == 1
        assert history[0].correlation_id == "c1"
        assert history[0].channel_type == "MockChannel"
        assert history[0].response == {"action": "decompose"}


class TestHumanEscalationResume:
    def test_resume_retry_same(self):
        he = HumanEscalation()
        resp = he.resume_from_human(
            {"action": "retry_same", "correlation_id": "c1"},
            router=MagicMock(),
        )
        assert resp["action"] == "retry_same"
        assert resp["correlation_id"] == "c1"

    def test_resume_replan(self):
        he = HumanEscalation()
        resp = he.resume_from_human(
            {"action": "replan", "correlation_id": "c1", "new_task_description": "do X"},
            router=MagicMock(),
        )
        assert resp["action"] == "replan"
        assert resp["new_task_description"] == "do X"

    def test_resume_decompose(self):
        he = HumanEscalation()
        resp = he.resume_from_human(
            {"action": "decompose", "correlation_id": "c1", "subtasks": ["a", "b"]},
            router=MagicMock(),
        )
        assert resp["action"] == "decompose"
        assert resp["subtasks"] == ["a", "b"]

    def test_resume_abort(self):
        he = HumanEscalation()
        resp = he.resume_from_human(
            {"action": "abort", "correlation_id": "c1", "reason": "user_cancelled"},
            router=MagicMock(),
        )
        assert resp["action"] == "abort"
        assert resp["reason"] == "user_cancelled"

    def test_resume_default_abort_on_unknown_action(self):
        he = HumanEscalation()
        resp = he.resume_from_human(
            {"action": "unknown", "correlation_id": "c1"},
            router=MagicMock(),
        )
        assert resp["action"] == "abort"

    def test_resume_uses_gateway_router_import(self):
        he = HumanEscalation()
        router = MagicMock(spec=GatewayRouter)
        resp = he.resume_from_human(
            {"action": "retry_same", "correlation_id": "c1"},
            router=router,
        )
        assert resp["action"] == "retry_same"
