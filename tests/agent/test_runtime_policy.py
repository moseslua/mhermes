import json
import logging

import pytest

from agent.runtime_policy import (
    Capability,
    PolicyMode,
    Provenance,
    RuntimePolicy,
    _TOOL_CAPABILITY_MAP,
    strip_provider_metadata,
)


class TestRuntimePolicyEvaluate:
    def test_off_mode_allows_everything(self):
        p = RuntimePolicy()
        for cap in Capability:
            for prov in Provenance:
                result = p.evaluate(cap, prov, PolicyMode.off)
                assert result["allowed"] is True
                assert result["blocked"] is False
                assert result["reason"] is None

    def test_enforce_blocks_untrusted_terminal(self):
        p = RuntimePolicy()
        result = p.evaluate("terminal", "untrusted", "enforce")
        assert result["allowed"] is False
        assert result["blocked"] is True
        assert "terminal" in result["reason"]

    def test_enforce_allows_trusted_terminal(self):
        p = RuntimePolicy()
        result = p.evaluate(Capability.terminal, Provenance.trusted, PolicyMode.enforce)
        assert result["allowed"] is True
        assert result["blocked"] is False

    def test_enforce_allows_untrusted_non_sensitive(self):
        p = RuntimePolicy()
        result = p.evaluate("unknown_capability", "untrusted", "enforce")
        assert result["allowed"] is True
        assert result["blocked"] is False

    def test_monitor_allows_untrusted_but_does_not_block(self):
        p = RuntimePolicy()
        result = p.evaluate(Capability.file_write, Provenance.untrusted, PolicyMode.monitor)
        assert result["allowed"] is True
        assert result["blocked"] is False

    def test_monitor_logs_on_untrusted(self, caplog):
        p = RuntimePolicy()
        with caplog.at_level(logging.INFO, logger="agent.runtime_policy"):
            p.evaluate(Capability.browser, Provenance.untrusted, PolicyMode.monitor)
        assert "Policy monitor" in caplog.text
        assert "browser" in caplog.text


class TestProvenanceEnum:
    def test_values(self):
        assert Provenance.trusted.value == "trusted"
        assert Provenance.untrusted.value == "untrusted"


class TestCapabilityEnum:
    def test_values(self):
        assert Capability.terminal.value == "terminal"
        assert Capability.file_write.value == "file_write"


class TestPolicyModeEnum:
    def test_values(self):
        assert PolicyMode.off.value == "off"
        assert PolicyMode.monitor.value == "monitor"
        assert PolicyMode.enforce.value == "enforce"


class TestToolCapabilityMap:
    def test_common_tools_mapped(self):
        assert _TOOL_CAPABILITY_MAP["terminal"] == Capability.terminal
        assert _TOOL_CAPABILITY_MAP["write_file"] == Capability.file_write
        assert _TOOL_CAPABILITY_MAP["browser_navigate"] == Capability.browser


class TestStripProviderMetadata:
    def test_strips_provider_prefix_fields(self):
        payload = {"data": "value", "_provider": "openai", "_source": "mcp"}
        result = strip_provider_metadata(payload)
        assert result == {"data": "value"}

    def test_strips_nested(self):
        payload = {"outer": {"_provider_meta": "x", "keep": "yes"}}
        result = strip_provider_metadata(payload)
        assert result == {"outer": {"keep": "yes"}}

    def test_strips_from_json_string(self):
        payload = json.dumps({"text": "hello", "_provider": "x"})
        result = strip_provider_metadata(payload)
        assert json.loads(result) == {"text": "hello"}

    def test_passthrough_non_dict(self):
        assert strip_provider_metadata("plain string") == "plain string"
        assert strip_provider_metadata(42) == 42

    def test_strips_from_list(self):
        payload = [{"data": 1, "_source": "x"}, {"data": 2}]
        result = strip_provider_metadata(payload)
        assert result == [{"data": 1}, {"data": 2}]

    def test_preserves_legitimate_provider_field(self):
        # A field literally named "provider" with non-metadata value should be kept
        payload = {"provider": "aws", "data": 1}
        result = strip_provider_metadata(payload)
        assert result == {"provider": "aws", "data": 1}

    def test_strips_provider_metadata_key(self):
        payload = {"text": "hello", "provider_metadata": {"model": "gpt-4"}}
        result = strip_provider_metadata(payload)
        assert result == {"text": "hello"}
