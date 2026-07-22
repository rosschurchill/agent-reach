# -*- coding: utf-8 -*-
"""
Agent Reach MCP Server — expose doctor/status as MCP tool.

Run: python -m agent_reach.integrations.mcp_server

Agent Reach is an installer + doctor tool. For actual reading/searching,
agents should call upstream tools directly (twitter-cli, yt-dlp, mcporter, etc.).
"""

import asyncio
import json
import sys

from agent_reach.config import Config
from agent_reach.core import AgentReach

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def create_server():
    if not HAS_MCP:
        print("MCP not installed. Install: pip install agent-reach[mcp]", file=sys.stderr)
        sys.exit(1)

    server = Server("agent-reach")
    config = Config()
    eyes = AgentReach(config)

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_status",
                 description=(
                     "Get Agent Reach status: which channels are installed and active. "
                     "NOTE: this runs live diagnostics — it spawns local probe "
                     "subprocesses and makes outbound network calls to third-party "
                     "services (e.g. x.com, xueqiu.com) to determine each channel's "
                     "current availability. It is not a passive/cached read."
                 ),
                 inputSchema={"type": "object", "properties": {}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "get_status":
                # The tool advertises LIVE diagnostics — force a fresh OpenCLI
                # probe so a long-running server never serves startup-frozen
                # state (CR-014).
                from agent_reach.backends import reset_opencli_status_cache
                reset_opencli_status_cache()
                result = eyes.doctor_report()
            else:
                result = f"Unknown tool: {name}"

            text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
            return [TextContent(type="text", text=text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
