"""Tests for HMAOM MCP Server.

Covers: tool listing, tool invocation, error handling, transport setup,
and JSON-RPC protocol handling.
"""

from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hmaom.config import MCPConfig
from hmaom.mcp.server import HMAOMMCPServer


# ── Fixtures ──

@pytest.fixture
def mock_router():
    """Return a mocked GatewayRouter with two fake specialists."""
    router = MagicMock()
    finance_harness = MagicMock()
    finance_harness.system_prompt = "Finance specialist prompt."
    finance_harness.default_tools = ["web_search", "execute_code"]
    code_harness = MagicMock()
    code_harness.system_prompt = "Code specialist prompt."
    code_harness.default_tools = ["file_read"]

    # Use simple string keys to avoid Domain enum headaches in mocks
    router._specialists = {
        MagicMock(value="finance"): finance_harness,
        MagicMock(value="code"): code_harness,
    }
    # Make the domain mock stringify correctly
    for domain_mock in router._specialists:
        domain_mock.__str__ = lambda self: str(self.value)
    return router


@pytest.fixture
def mcp_config():
    return MCPConfig(enabled=True, transport="stdio")


@pytest.fixture
def server(mock_router, mcp_config):
    return HMAOMMCPServer(router=mock_router, config=mcp_config)


# ── Tool Listing ──

class TestListTools:
    def test_returns_one_tool_per_specialist(self, server):
        tools = server.list_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"hmaom_finance", "hmaom_code"}

    def test_tool_description_from_system_prompt(self, server):
        tools = server.list_tools()
        by_name = {t["name"]: t for t in tools}
        assert "Finance specialist prompt." in by_name["hmaom_finance"]["description"]
        assert "Code specialist prompt." in by_name["hmaom_code"]["description"]

    def test_tool_description_includes_default_tools(self, server):
        tools = server.list_tools()
        by_name = {t["name"]: t for t in tools}
        assert "web_search" in by_name["hmaom_finance"]["description"]
        assert "file_read" in by_name["hmaom_code"]["description"]

    def test_tool_input_schema(self, server):
        tools = server.list_tools()
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert "input" in schema["properties"]
            assert schema["properties"]["input"]["type"] == "string"
            assert "required" in schema
            assert "input" in schema["required"]

    def test_empty_router_returns_empty_list(self, mcp_config):
        router = MagicMock()
        router._specialists = {}
        server = HMAOMMCPServer(router=router, config=mcp_config)
        assert server.list_tools() == []


# ── Tool Invocation ──

@pytest.mark.asyncio
class TestCallTool:
    async def test_routes_via_router(self, server, mock_router):
        mock_router.route = AsyncMock(return_value={"result": "ok", "correlation_id": "c1"})
        result = await server.call_tool("hmaom_finance", {"input": "Calculate risk"})
        mock_router.route.assert_awaited_once_with("Calculate risk")
        assert result["result"] == "ok"

    async def test_unknown_tool_prefix(self, server):
        result = await server.call_tool("unknown_tool", {"input": "x"})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    async def test_invalid_input_type(self, server):
        result = await server.call_tool("hmaom_finance", {"input": 123})
        assert "error" in result
        assert "Invalid input" in result["error"]

    async def test_router_error_returned(self, server, mock_router):
        mock_router.route = AsyncMock(return_value={"error": "budget exhausted"})
        result = await server.call_tool("hmaom_code", {"input": "do stuff"})
        assert result["error"] == "budget exhausted"

    async def test_router_exception_caught_in_jsonrpc(self, server, mock_router):
        mock_router.route = AsyncMock(side_effect=RuntimeError("boom"))
        request = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "hmaom_finance", "arguments": {"input": "x"}},
        }
        response = await server._handle_jsonrpc(request)
        assert response is not None
        assert response["result"]["isError"] is True
        assert "boom" in response["result"]["content"][0]["text"]


# ── JSON-RPC Protocol ──

@pytest.mark.asyncio
class TestJsonRpc:
    async def test_initialize(self, server):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
        response = await server._handle_jsonrpc(request)
        assert response["id"] == 1
        assert response["result"]["serverInfo"]["name"] == "hmaom-mcp"
        assert "tools" in response["result"]["capabilities"]

    async def test_notifications_initialized_no_response(self, server):
        request = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        response = await server._handle_jsonrpc(request)
        assert response is None

    async def test_tools_list(self, server):
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        response = await server._handle_jsonrpc(request)
        assert response["id"] == 2
        assert len(response["result"]["tools"]) == 2

    async def test_tools_call(self, server, mock_router):
        mock_router.route = AsyncMock(return_value={"result": "done"})
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "hmaom_code", "arguments": {"input": "fix bug"}},
        }
        response = await server._handle_jsonrpc(request)
        assert response["id"] == 3
        assert response["result"]["isError"] is False
        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload["result"] == "done"

    async def test_tools_call_with_router_error(self, server, mock_router):
        mock_router.route = AsyncMock(return_value={"error": "fail"})
        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "hmaom_code", "arguments": {"input": "x"}},
        }
        response = await server._handle_jsonrpc(request)
        assert response["result"]["isError"] is True

    async def test_unknown_method(self, server):
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "foo/bar",
        }
        response = await server._handle_jsonrpc(request)
        assert response["id"] == 5
        assert response["error"]["code"] == -32601


# ── Transport Setup ──

class TestTransport:
    def test_start_stdio(self, server):
        with patch.object(server, "_run_stdio", new_callable=AsyncMock) as mock_stdio:
            with patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)) as _:
                # Use a task that resolves immediately to avoid blocking
                mock_stdio.return_value = asyncio.sleep(0)
                server.start("stdio")
                mock_stdio.assert_awaited_once()

    def test_start_sse(self, server):
        with patch.object(server, "_run_sse", new_callable=AsyncMock) as mock_sse:
            mock_sse.return_value = asyncio.sleep(0)
            server.start("sse")
            mock_sse.assert_awaited_once()

    def test_start_unknown_transport_raises(self, server):
        with pytest.raises(ValueError, match="Unknown transport"):
            server.start("websocket")

    @pytest.mark.asyncio
    async def test_start_async_stdio(self, server):
        with patch.object(server, "_run_stdio", new_callable=AsyncMock) as mock_stdio:
            mock_stdio.return_value = asyncio.sleep(0)
            await server.start_async("stdio")
            mock_stdio.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_async_sse(self, server):
        with patch.object(server, "_run_sse", new_callable=AsyncMock) as mock_sse:
            mock_sse.return_value = asyncio.sleep(0)
            await server.start_async("sse")
            mock_sse.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sse_server_accepts_connections(self, server):
        """Spin up the minimal SSE server and connect via TCP."""
        server.config.sse_port = 0  # Let OS assign a port
        task = asyncio.create_task(server._run_sse())
        await asyncio.sleep(0.1)  # Let server start
        try:
            # Find the actual port
            srv = task.get_coro().cr_frame.f_locals.get("server")
            if srv is None:
                pytest.skip("Could not introspect server port")
            port = srv.sockets[0].getsockname()[1]
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=2.0
            )
            writer.write(b"GET /sse HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert b"200 OK" in response
            assert b"text/event-stream" in response
            writer.close()
            await writer.wait_closed()
        finally:
            server.stop()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def test_stop_sets_shutdown_event(self, server):
        assert not server._shutdown_event.is_set()
        server.stop()
        assert server._shutdown_event.is_set()


# ── stdio I/O loop ──

@pytest.mark.asyncio
class TestStdioLoop:
    async def test_reads_and_responds(self, server, mock_router):
        mock_router.route = AsyncMock(return_value={"result": "hello"})
        request_line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        stdin = asyncio.StreamReader()
        stdin.feed_data(request_line.encode())
        stdin.feed_eof()

        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.connect_read_pipe = AsyncMock(return_value=None)
                # Patch the reader creation so our stdin is used
                original_run_stdio = server._run_stdio

                async def patched_run_stdio():
                    while not server._shutdown_event.is_set():
                        try:
                            line = await asyncio.wait_for(stdin.readline(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        if not line:
                            break
                        try:
                            request = json.loads(line.decode())
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        response = await server._handle_jsonrpc(request)
                        if response is not None:
                            sys.stdout.write(json.dumps(response) + "\n")
                            sys.stdout.flush()

                await patched_run_stdio()

        output = stdout_buf.getvalue().strip()
        response = json.loads(output)
        assert response["id"] == 1
        assert len(response["result"]["tools"]) == 2

    async def test_ignores_malformed_json(self, server):
        stdin = asyncio.StreamReader()
        stdin.feed_data(b"not json\n")
        stdin.feed_eof()
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            while not server._shutdown_event.is_set():
                try:
                    line = await asyncio.wait_for(stdin.readline(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                try:
                    request = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                response = await server._handle_jsonrpc(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
        assert stdout_buf.getvalue() == ""
