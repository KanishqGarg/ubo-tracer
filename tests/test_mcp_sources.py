"""Unit tests for MCP source servers and graceful fallback."""

import pytest
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.sources.mcp_server import MCPSourceClient, create_source_mcp_server
from ubo_tracer.agents.retrieval import RetrievalAgent


def test_mcp_source_server_creation():
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    server = create_source_mcp_server("mock", mock_src)
    assert server.name == "ubo_source_mock"


def test_mcp_source_client_fetch_success():
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    client = MCPSourceClient({"mock": mock_src})
    docs, used_mcp, err = client.fetch("mock", "target_corp_1", use_mcp=True)
    assert used_mcp is True
    assert err is None
    assert len(docs) >= 1
    assert "target_corp_1" in docs[0].entity_id


def test_mcp_source_client_fallback_when_mcp_disabled():
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    client = MCPSourceClient({"mock": mock_src})
    docs, used_mcp, err = client.fetch("mock", "target_corp_1", use_mcp=False)
    assert used_mcp is False
    assert err is None
    assert len(docs) >= 1


def test_retrieval_agent_mcp_integration():
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    retrieval = RetrievalAgent(sources={"mock": mock_src}, default_order=["mock"], use_mcp=True)
    docs = retrieval.fetch_documents_for_entity("target_corp_1")
    assert len(docs) >= 1
    assert "Alice Smith" in docs[0].content_text

