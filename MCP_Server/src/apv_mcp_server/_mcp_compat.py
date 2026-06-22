"""Lightweight MCP server implementation for Python 3.8+.

Provides a FastMCP-compatible API without requiring the official mcp package.
Implements the Model Context Protocol (JSON-RPC 2.0) over stdio and HTTP transports.

Usage — drop-in replacement:
    from apv_mcp_server._mcp_compat import FastMCP   # Python 3.8+
    # from mcp.server.fastmcp import FastMCP         # Python 3.10+ (official SDK)

Protocol reference: https://spec.modelcontextprotocol.io/
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import sys
import typing
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# JSON Schema generation from Python function signatures
# ═══════════════════════════════════════════════════════════════════════

_PY_TYPE_TO_JSON: Dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _resolve_type(py_type: Any) -> Dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema type object.

    Handles: str, int, float, bool, Optional[X], and bare types.
    Returns a dict with at minimum {"type": "..."} — may include "default".
    """
    # Direct mapping
    if py_type in _PY_TYPE_TO_JSON:
        return {"type": _PY_TYPE_TO_JSON[py_type]}

    origin = typing.get_origin(py_type)
    if origin is not None:
        args = typing.get_args(py_type)
        # Optional[X] / Union[X, None]
        if origin is typing.Union:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _resolve_type(non_none[0])
        # Literal[...] → string enum
        if hasattr(typing, "Literal") and origin is typing.Literal:
            return {"type": "string", "enum": list(args)}

    # Fallback
    return {"type": "string"}


def _extract_docstring_summary(doc: str) -> str:
    """Extract the first line/sentence of a docstring as the tool description."""
    if not doc:
        return ""
    first_line = doc.strip().split("\n")[0].strip()
    # Truncate to a reasonable length
    return first_line[:200]


def _extract_arg_descriptions(doc: str) -> Dict[str, str]:
    """Extract per-parameter descriptions from a Google-style docstring Args block.

    Matches lines like:
        host: Device IP address (e.g., "172.16.34.70")
        command: CLI command to execute.
    """
    if not doc:
        return {}

    # Locate "Args:" block
    args_match = re.search(r"\nArgs:\s*\n(.*?)(?:\n\S|\Z)", doc, re.DOTALL)
    if not args_match:
        return {}

    args_block = args_match.group(1)
    descriptions: Dict[str, str] = {}

    # Match "    name: description" lines (description may span multiple indented lines)
    for match in re.finditer(r"^\s{4}(\w+)\s*:\s*(.+?)(?=\n\s{4}\w+\s*:|\n\S|\Z)", args_block, re.MULTILINE | re.DOTALL):
        name = match.group(1)
        desc = " ".join(match.group(2).strip().split())
        descriptions[name] = desc

    return descriptions



def _annotation_to_type(anno) -> type:
    """Resolve a type annotation (type or string) to a concrete Python type."""
    if not isinstance(anno, str):
        if anno in (str, int, float, bool):
            return anno
        origin = typing.get_origin(anno)
        if origin is typing.Union:
            args = [a for a in typing.get_args(anno) if a is not type(None)]
            if len(args) == 1:
                return _annotation_to_type(args[0])
        return str
    s = anno.strip()
    while s.startswith('Optional[') and s.endswith(']'):
        s = s[9:-1].strip()
    if s in ('str', 'string'): return str
    if s in ('int', 'integer'): return int
    if s in ('float', 'number'): return float
    if s in ('bool', 'boolean'): return bool
    return str


def _func_to_tool_schema(func: Callable) -> Dict[str, Any]:
    """Generate an MCP tool schema from a function (avoids typing.get_type_hints)."""
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ''
    description = _extract_docstring_summary(doc)
    arg_descriptions = _extract_arg_descriptions(doc)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for name, param in sig.parameters.items():
        if name in ('self', 'cls'):
            continue
        if param.annotation is not inspect.Parameter.empty:
            py_type = _annotation_to_type(param.annotation)
        else:
            py_type = str
        prop = _resolve_type(py_type)
        if name in arg_descriptions:
            prop['description'] = arg_descriptions[name]
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop['default'] = param.default
        properties[name] = prop
    return {
        'name': func.__name__,
        'description': description,
        'inputSchema': {'type': 'object', 'properties': properties, 'required': required},
    }

# ═══════════════════════════════════════════════════════════════════════
# FastMCP-compatible class
# ═══════════════════════════════════════════════════════════════════════

_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"


class _JSONRPCError(Exception):
    """Internal exception for JSON-RPC errors with standard codes."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


class FastMCP:
    """Lightweight FastMCP-compatible server.

    Drop-in replacement for ``mcp.server.fastmcp.FastMCP`` supporting the same
    ``@mcp.tool()`` decorator and ``mcp.run(transport=...)`` entry points.

    Implements the JSON-RPC 2.0 wire protocol directly — no external MCP
    dependencies.  Suitable for Python 3.8+.
    """

    def __init__(self, name: str = "", instructions: str = ""):
        self._name = name or "MCP Server"
        self._instructions = instructions
        self._tools: Dict[str, Dict[str, Any]] = {}

    # ── Tool registration ──────────────────────────────────────────

    def tool(self) -> Callable:
        """Register an async function as an MCP tool (decorator).

        Usage::

            mcp = FastMCP("my-server")

            @mcp.tool()
            async def my_tool(arg1: str, arg2: int = 5) -> str:
                '''Tool description.'''
                return f"result: {arg1} {arg2}"
        """

        def decorator(func: Callable) -> Callable:
            schema = _func_to_tool_schema(func)
            self._tools[func.__name__] = {"func": func, "schema": schema}
            return func

        return decorator

    # ── JSON-RPC dispatcher ────────────────────────────────────────

    async def _dispatch(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle a single JSON-RPC request.  Returns a response dict or None for notifications."""

        method: str = request.get("method", "")
        req_id = request.get("id")
        params: Dict[str, Any] = request.get("params", {})

        try:
            if method == "initialize":
                return self._mk_ok(req_id, result={
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self._name,
                        "version": "1.0.0",
                    },
                })

            if method == "tools/list":
                tools = [t["schema"] for t in self._tools.values()]
                return self._mk_ok(req_id, result={"tools": tools})

            if method == "tools/call":
                tool_name: str = params.get("name", "")
                arguments: Dict[str, Any] = params.get("arguments", {})

                entry = self._tools.get(tool_name)
                if entry is None:
                    raise _JSONRPCError(-32602, f"Unknown tool: {tool_name}")

                try:
                    result = await entry["func"](**arguments)
                except Exception as exc:
                    # Return tool error as content with isError flag
                    return self._mk_ok(req_id, result={
                        "content": [{"type": "text", "text": f"error: {exc}"}],
                        "isError": True,
                    })

                return self._mk_ok(req_id, result={
                    "content": [{"type": "text", "text": str(result)}],
                })

            if method == "ping":
                return self._mk_ok(req_id, result={})

            if method == "notifications/initialized":
                return None  # notification — no response

            # Unknown method
            raise _JSONRPCError(-32601, f"Method not found: {method}")

        except _JSONRPCError as exc:
            return self._mk_err(req_id, code=exc.code, message=exc.message)
        except Exception as exc:
            logger.exception("Unhandled error dispatching %s", method)
            return self._mk_err(req_id, code=-32603, message=str(exc))

    # ── Transport: stdio ───────────────────────────────────────────

    def run(self, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> None:
        """Start the server (blocking).  ``transport`` is 'stdio', 'http', or 'sse'."""
        valid = ("stdio", "http", "sse")
        if transport not in valid:
            raise ValueError(f"Unknown transport '{transport}'. Choose from: {', '.join(valid)}")

        if transport == "stdio":
            asyncio.run(self._serve_stdio())
        elif transport == "http":
            asyncio.run(self._serve_http(host, port))
        else:  # sse → fall back to HTTP
            logger.warning("SSE transport: falling back to HTTP (SSE not implemented in compat layer)")
            asyncio.run(self._serve_http(host, port))

    async def _serve_stdio(self) -> None:
        """JSON-RPC over stdin/stdout with Content-Length framing (MCP stdio transport)."""

        loop = asyncio.get_running_loop()

        # ── stdin reader ──────────────────────────────────────────
        stdin_reader = asyncio.StreamReader()
        stdin_protocol = asyncio.StreamReaderProtocol(stdin_reader)
        await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin)

        # ── stdout writer ─────────────────────────────────────────
        stdout_transport, _ = await loop.connect_write_pipe(
            lambda: asyncio.streams.FlowControlMixin(),
            sys.stdout.buffer,
        )
        stdout_writer = asyncio.StreamWriter(
            stdout_transport, None, stdin_reader, loop,
        )

        async def _send(message: Dict[str, Any]) -> None:
            body = json.dumps(message, ensure_ascii=False)
            frame = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}"
            stdout_writer.write(frame.encode("utf-8"))
            await stdout_writer.drain()

        # ── Read loop ─────────────────────────────────────────────
        buffer = b""
        while True:
            try:
                line = await stdin_reader.readline()
            except Exception:
                break
            if not line:
                break

            line_str = line.decode("ascii", errors="replace").strip()
            if not line_str:
                continue

            if line_str.lower().startswith("content-length:"):
                try:
                    content_length = int(line_str.split(":", 1)[1].strip())
                except ValueError:
                    continue

                try:
                    body_bytes = await stdin_reader.readexactly(content_length)
                except asyncio.IncompleteReadError:
                    break

                try:
                    request = json.loads(body_bytes)
                except json.JSONDecodeError:
                    continue
            else:
                # Plain line-delimited JSON (no Content-Length header)
                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

            response = await self._dispatch(request)
            if response is not None:
                await _send(response)

    # ── Transport: HTTP ───────────────────────────────────────────

    async def _serve_http(self, host: str, port: int) -> None:
        """JSON-RPC over HTTP POST (simplified MCP HTTP transport)."""

        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data = await asyncio.wait_for(reader.read(65536), timeout=30)
            except asyncio.TimeoutError:
                writer.close()
                return

            if not data:
                writer.close()
                return

            request_text = data.decode("utf-8", errors="replace")
            lines = request_text.split("\r\n")
            if not lines:
                writer.close()
                return

            # Parse request line
            parts = lines[0].split(" ", 2)
            http_method = parts[0] if len(parts) > 0 else ""
            path = parts[1] if len(parts) > 1 else "/"

            # Extract body
            body = ""
            if "\r\n\r\n" in request_text:
                body = request_text.split("\r\n\r\n", 1)[1]

            if http_method == "OPTIONS":
                response_body = ""
                status_line = "HTTP/1.1 204 No Content\r\n"
                headers = (
                    "Access-Control-Allow-Origin: *\r\n"
                    "Access-Control-Allow-Methods: POST, OPTIONS\r\n"
                    "Access-Control-Allow-Headers: Content-Type\r\n"
                )
            elif http_method == "POST" and path in ("/mcp", "/"):
                try:
                    json_req = json.loads(body)
                except json.JSONDecodeError:
                    resp = self._mk_err(None, code=-32700, message="Parse error")
                    response_body = json.dumps(resp, ensure_ascii=False)
                    status_line = "HTTP/1.1 400 Bad Request\r\n"
                    headers = "Content-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n"
                    self._write_http(writer, status_line, headers, response_body)
                    return

                resp = await self._dispatch(json_req)
                response_body = json.dumps(resp if resp is not None else {}, ensure_ascii=False)
                status_line = "HTTP/1.1 200 OK\r\n"
                headers = "Content-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n"
            else:
                # GET or other → simple status page
                response_body = json.dumps({
                    "server": self._name,
                    "status": "ok",
                    "tools": len(self._tools),
                }, ensure_ascii=False)
                status_line = "HTTP/1.1 200 OK\r\n"
                headers = "Content-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n"

            self._write_http(writer, status_line, headers, response_body)

        server = await asyncio.start_server(_handle, host, port)
        print(f"MCP HTTP server listening on http://{host}:{port}/mcp", file=sys.stderr)

        async with server:
            await server.serve_forever()

    @staticmethod
    def _write_http(writer: asyncio.StreamWriter, status_line: str, headers: str, body: str) -> None:
        """Write a complete HTTP response."""
        body_bytes = body.encode("utf-8")
        http = (
            f"{status_line}"
            f"{headers}"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"\r\n"
        ).encode("utf-8") + body_bytes
        writer.write(http)

    # ── Response helpers ───────────────────────────────────────────

    @staticmethod
    def _mk_ok(req_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": _JSONRPC_VERSION, "id": req_id, "result": result}

    @staticmethod
    def _mk_err(req_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": _JSONRPC_VERSION, "id": req_id, "error": {"code": code, "message": message}}
