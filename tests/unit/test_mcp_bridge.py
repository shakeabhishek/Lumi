"""Tests for the MCP bridge scaffolding.

The bridge is intentionally not wired into the live router in V1. These tests
exercise the contract:
  - MCPServerConfig defaults
  - MCPBridge.is_available() reflects the presence of the `mcp` package
  - Calls raise clearly when the package isn't installed
  - When V2 wires `_list_tools_async` / `_call_tool_async`, the sync wrappers
    will catch exceptions and return safe fallbacks (verified by patching).
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from lumi.skills.mcp_bridge import MCPBridge, MCPServerConfig, MCPTool


def test_config_defaults() -> None:
    c = MCPServerConfig(name="drive", command="mcp-server-google-drive")
    assert c.args == []
    assert c.env == {}
    assert c.enabled is False


def test_bridge_name_passthrough() -> None:
    b = MCPBridge(MCPServerConfig(name="slack", command="slack-mcp"))
    assert b.name == "slack"


def test_is_available_false_when_mcp_missing() -> None:
    """With no `mcp` package installed (default state in this repo), reports False."""
    saved = sys.modules.get("mcp")
    sys.modules["mcp"] = None  # type: ignore[assignment]
    try:
        assert MCPBridge.is_available() is False
    finally:
        if saved is None:
            sys.modules.pop("mcp", None)
        else:
            sys.modules["mcp"] = saved


def test_is_available_true_when_mcp_present() -> None:
    """With a stand-in `mcp` module, reports True."""
    fake = type(sys)("mcp")
    with patch.dict(sys.modules, {"mcp": fake}):
        assert MCPBridge.is_available() is True


def test_list_tools_raises_when_unavailable() -> None:
    b = MCPBridge(MCPServerConfig(name="x", command="missing"))
    with patch.object(MCPBridge, "is_available", staticmethod(lambda: False)):
        with pytest.raises(RuntimeError, match="mcp package"):
            b.list_tools()


def test_call_tool_raises_when_unavailable() -> None:
    b = MCPBridge(MCPServerConfig(name="x", command="missing"))
    with patch.object(MCPBridge, "is_available", staticmethod(lambda: False)):
        with pytest.raises(RuntimeError, match="mcp package"):
            b.call_tool("foo", {"bar": 1})


def test_list_tools_returns_empty_on_async_failure() -> None:
    """When the package is available but the async call blows up, return []."""
    b = MCPBridge(MCPServerConfig(name="x", command="missing"))
    with patch.object(MCPBridge, "is_available", staticmethod(lambda: True)):
        # _list_tools_async raises NotImplementedError in the V1 scaffold;
        # the sync wrapper should swallow it and return [].
        assert b.list_tools() == []


def test_call_tool_returns_empty_on_async_failure() -> None:
    """Same fallback contract for call_tool: failures → empty string."""
    b = MCPBridge(MCPServerConfig(name="x", command="missing"))
    with patch.object(MCPBridge, "is_available", staticmethod(lambda: True)):
        assert b.call_tool("nonexistent", {}) == ""


def test_mcp_tool_dataclass_shape() -> None:
    t = MCPTool(
        server="drive",
        name="search",
        description="Search Drive",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
    )
    assert t.server == "drive"
    assert t.input_schema["type"] == "object"
