"""Model Context Protocol (MCP) Servers for UBO Tracer Sources.

Exposes each corporate registry/document source via the official Python MCP SDK:
- mock_source: Synthetic offline compliance test scenarios
- companies_house: UK PSC API (official corporate register)
- gleif: Global Legal Entity Identifier Foundation relationship API
- filing_text: Unstructured PDF / raw text document directories

Architecture & Fallback Trade-offs:
- Primary Path: Agent issues standard MCP tool calls ('fetch_documents') to isolated MCP servers.
- Fallback Path: In-process direct source call (`source.fetch(entity_id)`).
- Trade-off Analysis:
  * MCP provides strict protocol boundaries, observability, schema contract validation,
    and capability negotiation between host and external servers.
  * Direct call eliminates IPC overhead and dependency on network sockets or subprocess stdio,
    ensuring continuous operation during local air-gapped test execution.
"""

from __future__ import annotations
import asyncio
import json
from typing import List, Dict, Any, Optional, Tuple
from mcp.server.mcpserver import MCPServer
from ubo_tracer.sources.base import BaseSource, Document
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.sources.companies_house import CompaniesHouseSource
from ubo_tracer.sources.gleif import GLEIFSource
from ubo_tracer.sources.filing_text import FilingTextSource


def create_source_mcp_server(source_name: str, source_instance: BaseSource) -> MCPServer:
    """Create an MCPServer exposing a source's fetch method as a standardized tool."""
    server = MCPServer(name=f"ubo_source_{source_name}", description=f"MCP Source Server for {source_name}")

    @server.tool(name=f"fetch_from_{source_name}", description=f"Fetch compliance ownership documents for an entity from {source_name}")
    async def fetch_documents(entity_id: str) -> str:
        """Fetch documents for entity_id from the underlying source."""
        # Sources are synchronous, run in executor or direct call
        docs = source_instance.fetch(entity_id)
        docs_payload = [d.model_dump() for d in docs]
        return json.dumps(docs_payload)

    return server


class MCPSourceClient:
    """Client for querying sources via MCP protocol, with graceful direct-call fallback."""

    def __init__(self, sources: Dict[str, BaseSource]):
        self.sources = sources
        self.mcp_servers: Dict[str, MCPServer] = {}
        for name, src in sources.items():
            self.mcp_servers[name] = create_source_mcp_server(name, src)

    def fetch(self, source_name: str, entity_id: str, use_mcp: bool = True) -> Tuple[List[Document], bool, Optional[str]]:
        """Fetch documents from a source using MCP server tool call with fallback.
        
        Returns:
            (documents, used_mcp_flag, error_message)
        """
        if source_name not in self.sources:
            return [], False, f"Unknown source: {source_name}"

        # 1. Primary MCP call
        if use_mcp and source_name in self.mcp_servers:
            server = self.mcp_servers[source_name]
            tool_name = f"fetch_from_{source_name}"
            try:
                # Call tool on MCPServer
                tool_res = asyncio.run(server.call_tool(tool_name, {"entity_id": entity_id}))
                if not tool_res.is_error and tool_res.content:
                    text_content = tool_res.content[0].text
                    raw_docs = json.loads(text_content)
                    docs = [Document(**d) for d in raw_docs]
                    return docs, True, None
            except Exception as e:
                # MCP tool call failed, degrade gracefully to direct call
                pass

        # 2. Direct-call fallback
        try:
            docs = self.sources[source_name].fetch(entity_id)
            return docs, False, None
        except Exception as e:
            return [], False, str(e)
