"""Retrieval Agent: decides source order with LLM tool-choice and deterministic fallback.

NON-NEGOTIABLE DESIGN RULE 1:
"The LLM never does arithmetic. It only (a) decides which source to query next
and (b) extracts ownership statements from text."
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any
from ubo_tracer.sources.base import BaseSource, Document
from ubo_tracer.sources.mcp_server import MCPSourceClient
from ubo_tracer.llm import OllamaClient


SOURCE_SELECTION_SYSTEM_PROMPT = """You are a legal entity researcher selecting the best data source to query next.
Given the target entity identifier, entity jurisdiction, and available data sources,
decide which source to query next.

Available sources:
- 'mock': local synthetic benchmark data source (always reliable for test scenarios)
- 'companies_house': UK government registry for UK Ltd / PLC / PSC records
- 'gleif': global LEI relationship registry for legal entities with LEIs or corporate parents
- 'filing_text': local plain text/PDF regulatory filings and annual reports

OUTPUT FORMAT (JSON ONLY):
{
  "selected_source": "mock" | "companies_house" | "gleif" | "filing_text",
  "reasoning": "Brief explanation of why this source was selected"
}
"""


class RetrievalAgent:
    """Coordinates document retrieval across multiple configured data sources."""

    def __init__(
        self,
        sources: Dict[str, BaseSource],
        llm_client: Optional[OllamaClient] = None,
        default_order: Optional[List[str]] = None,
        use_mcp: bool = True,
    ):
        self.sources = sources
        self.llm = llm_client
        self.default_order = default_order or ["mock", "companies_house", "gleif", "filing_text"]
        self.use_mcp = use_mcp
        self.mcp_client = MCPSourceClient(sources)

    def select_source_order(
        self,
        entity_id: str,
        entity_name: Optional[str] = None,
        visited_sources: Optional[List[str]] = None,
    ) -> List[str]:
        """Determine ordered list of sources to query.
        
        Attempts LLM recommendation first; falls back to deterministic default order.
        """
        visited = set(visited_sources or [])
        available_names = [name for name, src in self.sources.items() if src.is_available() and name not in visited]

        if not available_names:
            return []

        # If LLM available, ask LLM for preferred top choice
        if self.llm:
            try:
                prompt = (
                    f"Entity ID: {entity_id}\n"
                    f"Entity Name: {entity_name or entity_id}\n"
                    f"Available unqueried sources: {', '.join(available_names)}\n"
                    f"Which source should be queried next?"
                )
                res = self.llm.generate_json(prompt, system_prompt=SOURCE_SELECTION_SYSTEM_PROMPT)
                preferred = res.get("selected_source")
                if preferred in available_names:
                    # Place preferred source first, followed by remainder in default order
                    remainder = [s for s in self.default_order if s in available_names and s != preferred]
                    return [preferred] + remainder
            except Exception:
                pass  # Fall back to deterministic default order

        # Deterministic fallback order
        return [s for s in self.default_order if s in available_names]

    def fetch_documents_for_entity(
        self,
        entity_id: str,
        entity_name: Optional[str] = None,
    ) -> List[Document]:
        """Query sources according to prioritized order until documents are found.
        
        Attempts MCP server tool call first; falls back to direct call if MCP fails.
        """
        order = self.select_source_order(entity_id, entity_name)
        all_docs: List[Document] = []

        for source_name in order:
            source = self.sources.get(source_name)
            if not source or not source.is_available():
                continue

            try:
                # 1. MCP Tool call route
                docs, used_mcp, err = self.mcp_client.fetch(source_name, entity_id, use_mcp=self.use_mcp)
                if docs:
                    all_docs.extend(docs)
                    break
            except Exception:
                # 2. Direct fallback
                try:
                    docs = source.fetch(entity_id, entity_name)
                    if docs:
                        all_docs.extend(docs)
                        break
                except Exception:
                    continue

        return all_docs

