"""HMAOM MCP Server.

Exposes HMAOM specialists as MCP tools via stdio or SSE transport.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from typing import Any, Optional

from hmaom.config import MCPConfig
from hmaom.gateway.router import GatewayRouter


class HMAOMMCPServer:
    """MCP server that exposes HMAOM specialists as tools.

    Each specialist domain becomes one MCP tool named ``hmaom_<domain>``.
    Tool calls are routed through the gateway router.
    """

    def __init__(self, router: GatewayRouter, config: MCPConfig) -> None:
        self.router = router
        self.config = config
        self._shutdown_event = asyncio.Event()

    # ── Public API ──

    def list_tools(self) -> list[dict[str, Any]]:
        """Return one MCP tool definition per specialist domain."""
        prefix = self.config.tool_name_prefix
        tools: list[dict[str, Any]] = []
        for domain, harness in getattr(self.router, "_specialists", {}).items():
            domain_str = str(domain.value) if hasattr(domain, "value") else str(domain)
            system_prompt = getattr(harness, "system_prompt", "") or ""
            default_tools = getattr(harness, "default_tools", []) or []
            description = system_prompt
            if default_tools:
                description += f"\nAvailable tools: {', '.join(default_tools)}."
            tool: dict[str, Any] = {
                "name": f"{prefix}_{domain_str}",
                "description": description.strip(),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "Task description for the specialist",
                        },
                    },
                    "required": ["input"],
                },
            }
            tools.append(tool)
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call through the gateway."""
        prefix = self.config.tool_name_prefix
        if not name.startswith(f"{prefix}_"):
            return {
                "error": f"Unknown tool: {name}. Expected prefix: {prefix}_",
            }
        user_input = arguments.get("input", "")
        if not isinstance(user_input, str):
            return {"error": "Invalid input: expected string"}
        result = await self.router.route(user_input)
        return result

    def start(self, transport: str) -> None:
        """Start the MCP server on the given transport."""
        if transport == "stdio":
            asyncio.run(self._run_stdio())
        elif transport == "sse":
            asyncio.run(self._run_sse())
        else:
            raise ValueError(f"Unknown transport: {transport}. Use 'stdio' or 'sse'.")

    async def start_async(self, transport: str) -> None:
        """Async variant of ``start`` for use in existing event loops."""
        if transport == "stdio":
            await self._run_stdio()
        elif transport == "sse":
            await self._run_sse()
        else:
            raise ValueError(f"Unknown transport: {transport}. Use 'stdio' or 'sse'.")

    def stop(self) -> None:
        """Signal the server to shut down."""
        self._shutdown_event.set()

    # ── JSON-RPC handling ──

    async def _handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single JSON-RPC request and return a response (or None for notifications)."""
        method = request.get("method")
        req_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hmaom-mcp", "version": "0.1.0"},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            tools = self.list_tools()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools},
            }

        if method == "tools/call":
            params = request.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = await self.call_tool(name, arguments)
                is_error = bool(result.get("error"))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, default=str)}
                        ],
                        "isError": is_error,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    # ── stdio transport ──

    async def _run_stdio(self) -> None:
        """Read JSON-RPC requests from stdin and write responses to stdout."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        write_lock = asyncio.Lock()

        while not self._shutdown_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            try:
                request = json.loads(line.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            try:
                response = await self._handle_jsonrpc(request)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                continue
            if response is not None:
                async with write_lock:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
    # ── SSE transport ──

    async def _run_sse(self) -> None:
        """Start a minimal SSE server."""
        host = self.config.sse_host
        port = self.config.sse_port
        server = await asyncio.start_server(self._handle_sse_client, host, port)
        async with server:
            await self._shutdown_event.wait()

    async def _handle_sse_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single SSE client connection."""
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            parts = header.split(b" ")
            path = parts[1] if len(parts) > 1 else b"/"

            if path == b"/sse":
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/event-stream\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Connection: keep-alive\r\n"
                    b"\r\n"
                )
                writer.write(response)
                await writer.drain()
                while not self._shutdown_event.is_set():
                    await asyncio.sleep(1)
            else:
                writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                await writer.drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
