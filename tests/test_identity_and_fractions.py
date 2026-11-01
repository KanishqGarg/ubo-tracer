"""Tests for fraction normalization and identity key disambiguation."""

import pytest
from ubo_tracer.models import EntityType, OwnershipEdge
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.verifier import EdgeVerifier
from ubo_tracer.calculator import OwnershipCalculator


def test_fraction_vs_percentage_normalization():
    # Test 1: Model returns 0.5 for "50%" -> must normalize to 50.0%
    agent = ExtractionAgent(None)
    raw_edges = [{
        "owner_name": "Bob Jones",
        "owner_type": "person",
        "percentage_min": 0.5,
        "percentage_max": 0.5,
        "quote": "Bob Jones holds 50% shares",
    }]
    edges = agent._parse_edge_items(raw_edges, "target_1", "doc_1", "mock")
    assert len(edges) == 1
    assert edges[0].percentage_min == 50.0
    assert edges[0].percentage_max == 50.0

    # Test 2: Model returns 0.5 for "0.5%" -> must remain 0.5%
    raw_edges_decimal = [{
        "owner_name": "Micro Holder",
        "owner_type": "person",
        "percentage_min": 0.5,
        "percentage_max": 0.5,
        "quote": "Micro Holder owns 0.5% of voting shares",
    }]
    edges_dec = agent._parse_edge_items(raw_edges_decimal, "target_1", "doc_2", "mock")
    assert len(edges_dec) == 1
    assert edges_dec[0].percentage_min == 0.5
    assert edges_dec[0].percentage_max == 0.5

    # Test 3: Model returns 5.0 for "0.5%" (decimal drift) -> Verifier must reject!
    bad_edge = OwnershipEdge(
        owner_id="micro_holder",
        owner_name="Micro Holder",
        owner_type=EntityType.PERSON,
        owned_id="target_1",
        percentage_min=5.0,
        percentage_max=5.0,
        evidence=edges_dec[0].evidence,
    )
    verified = EdgeVerifier.verify_edge(bad_edge, "Micro Holder owns 0.5% of voting shares")
    assert verified.evidence.verified is False
    assert "does not appear in quote" in verified.evidence.verification_error


def test_scenario_13_identity_disambiguation():
    agent = ExtractionAgent(None)
    # Person 1: John Smith born May 1970 London
    raw_1 = [{
        "owner_name": "John Smith",
        "owner_type": "person",
        "percentage_min": 15.0,
        "percentage_max": 15.0,
        "quote": "John Smith (DOB May 1970, London) holds 15% directly",
    }]
    # Person 2: John Smith born Nov 1985 Edinburgh
    raw_2 = [{
        "owner_name": "John Smith",
        "owner_type": "person",
        "percentage_min": 50.0,
        "percentage_max": 50.0,
        "quote": "John Smith (DOB Nov 1985, Edinburgh) holds 50% shares",
    }]
    e1 = agent._parse_edge_items(raw_1, "target_13", "doc_1301", "mock")[0]
    e2 = agent._parse_edge_items(raw_2, "smith_holdco", "doc_1302", "mock")[0]

    # Must produce distinct identity IDs rather than colliding
    assert e1.owner_id != e2.owner_id
    assert "1970" in e1.owner_id or "london" in e1.owner_id
    assert "1985" in e2.owner_id or "edinburgh" in e2.owner_id

