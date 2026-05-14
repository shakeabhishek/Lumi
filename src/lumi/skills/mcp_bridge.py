"""MCP (Model Context Protocol) bridge — scaffolding for V2.

MCP is Anthropic's open protocol for exposing tools and resources to LLMs.
An MCP *server* publishes tools (e.g. "read_email", "search_drive"); an MCP
*client* (Lumi) discovers and calls them. The protocol speaks JSON-RPC over
stdio or HTTP+SSE.

Why this is a scaffold, not a wired integration:
  Lumi's V1 LLM is Qwen2.5 1.5B. Multi-step MCP tool orchestration needs a
  larger model than that to be reliable. Real MCP comes online in V2
  alongside the cloud-LLM fallback (Claude API). What lives here now is the
  shape of the integration — types, lifecycle, sync wrapper — so the V2
  plug-in is "implement the bodies", not "design from scratch".

What's stubbed:
  - MCPServerConfig: how Lumi stores an MCP server endpoint in settings.
  - MCPBridge.list_tools / call_tool: the two calls the router would make.
  - Lazy import of the official `mcp` package. Until the user installs it
    AND the bridge is wired into the router, this module is dormant.

To experiment in V2:
  uv pip install mcp
  Add an entry to cfg.mcp_servers (see config.py); restart Lumi.
  The skill router gains an MCP fallback tier between OpenClaw and the LLM.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..log import get_logger

log = get_logger(__name__)


@dataclass
class MCPServerConfig:
    """One MCP server endpoint. Persisted in user settings."""

    name: str                                # human label, e.g. "Google Drive"
    command: str                             # executable for stdio servers
    args: list[str] = field(default_factory=list)
    enabled: bool = False                    # off until user opts in
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    """A tool advertised by an MCP server, normalized into Lumi's shape."""

    server: str            # MCPServerConfig.name
    name: str              # tool name as advertised
    description: str       # one-line summary
    input_schema: dict     # JSON Schema for arguments


class MCPBridge:
    """Sync wrapper over the async `mcp` Python client.

    One bridge instance manages one MCP server connection. The router can hold
    a list of bridges, one per enabled MCPServerConfig. Calls block; a future
    refactor could make the router async to avoid the asyncio.run() per call.

    All methods raise RuntimeError if the `mcp` package isn't installed — the
    router treats that as "no MCP available" and falls through.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._client: object | None = None

    @property
    def name(self) -> str:
        return self._config.name

    @staticmethod
    def is_available() -> bool:
        try:
            import mcp  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def list_tools(self) -> list[MCPTool]:
        """Discover the tools the server exposes. Returns empty if unreachable."""
        if not self.is_available():
            raise RuntimeError("mcp package not installed")
        try:
            return asyncio.run(self._list_tools_async())
        except Exception as exc:
            log.warning("mcp.list_tools_failed", server=self._config.name, error=str(exc))
            return []

    def call_tool(self, tool_name: str, args: dict) -> str:
        """Invoke a tool on the connected server; return its text result.

        Returns the empty string on any failure so the router can fall through.
        Logs the call for the audit trail.
        """
        if not self.is_available():
            raise RuntimeError("mcp package not installed")
        try:
            result = asyncio.run(self._call_tool_async(tool_name, args))
            log.info("mcp.tool_called", server=self._config.name, tool=tool_name)
            return result
        except Exception as exc:
            log.warning(
                "mcp.tool_call_failed",
                server=self._config.name, tool=tool_name, error=str(exc),
            )
            return ""

    # ── async internals (V2 wires real bodies; V1 raises NotImplementedError) ─

    async def _list_tools_async(self) -> list[MCPTool]:
        # In V2:
        #   server_params = StdioServerParameters(
        #       command=self._config.command, args=self._config.args, env=self._config.env)
        #   async with stdio_client(server_params) as (read, write):
        #       async with ClientSession(read, write) as session:
        #           await session.initialize()
        #           tools = await session.list_tools()
        #           return [MCPTool(server=self._config.name, name=t.name, ...) for t in tools]
        raise NotImplementedError("MCP client wiring is V2 — see module docstring")

    async def _call_tool_async(self, tool_name: str, args: dict) -> str:
        # In V2: open session like above, then await session.call_tool(tool_name, args).
        raise NotImplementedError("MCP client wiring is V2 — see module docstring")
