"""Tests for EdgeVerifier (verbatim quote verification and number grounding)."""

import pytest
from ubo_tracer.models import OwnershipEdge, Evidence, EntityType
from ubo_tracer.agents.verifier import EdgeVerifier


def test_valid_quote_and_number():
    doc = "Companies House filing: John Doe holds directly 60% of voting rights and shares."
    edge = OwnershipEdge(
        owner_id="john_doe",
        owner_name="John Doe",
        owner_type=EntityType.PERSON,
        owned_id="target_corp",
        percentage_min=60.0,
        percentage_max=60.0,
        evidence=Evidence(
            document_id="doc_1",
            quote="John Doe holds directly 60% of voting rights and shares.",
            source_name="companies_house",
        ),
    )

    verified_edge = EdgeVerifier.verify_edge(edge, doc)
    assert verified_edge.evidence.verified is True
    assert verified_edge.evidence.verification_error is None


def test_quote_not_in_document():
    doc = "Companies House filing: John Doe holds directly 60% of voting rights and shares."
    edge = OwnershipEdge(
        owner_id="john_doe",
        owner_name="John Doe",
        owner_type=EntityType.PERSON,
        owned_id="target_corp",
        percentage_min=60.0,
        percentage_max=60.0,
        evidence=Evidence(
            document_id="doc_1",
            quote="Jane Doe holds 90% of shares.",  # Hallucinated quote
            source_name="companies_house",
        ),
    )

    verified_edge = EdgeVerifier.verify_edge(edge, doc)
    assert verified_edge.evidence.verified is False
    assert "not found verbatim" in verified_edge.evidence.verification_error


def test_number_not_in_quote_hallucination_trap():
    # Scenario 9 trap: Quote is in doc, but edge claims 75% when quote says 10%
    doc = "Annual report: Mr. Smith holds a minor 10% equity stake in the venture."
    edge = OwnershipEdge(
        owner_id="smith",
        owner_name="Mr. Smith",
        owner_type=EntityType.PERSON,
        owned_id="target_corp",
        percentage_min=75.0,  # Hallucinated number!
        percentage_max=75.0,
        evidence=Evidence(
            document_id="doc_2",
            quote="Mr. Smith holds a minor 10% equity stake in the venture.",
            source_name="annual_report",
        ),
    )

    verified_edge = EdgeVerifier.verify_edge(edge, doc)
    assert verified_edge.evidence.verified is False
    assert "does not appear in quote" in verified_edge.evidence.verification_error


def test_range_bands_in_quote():
    doc = "PSC register: ownership of shares - more than 25% but not more than 50%."
    edge = OwnershipEdge(
        owner_id="alice",
        owner_name="Alice",
        owner_type=EntityType.PERSON,
        owned_id="target_corp",
        percentage_min=25.01,
        percentage_max=50.0,
        evidence=Evidence(
            document_id="psc_1",
            quote="ownership of shares - more than 25% but not more than 50%",
            source_name="companies_house",
        ),
    )

    verified_edge = EdgeVerifier.verify_edge(edge, doc)
    assert verified_edge.evidence.verified is True


def test_word_numbers_wholly_owned_and_quarter():
    doc = "Exhibit A: Target Corp is wholly owned subsidiary of ParentCo."
    edge = OwnershipEdge(
        owner_id="parent_co",
        owner_name="ParentCo",
        owner_type=EntityType.COMPANY,
        owned_id="target_corp",
        percentage_min=100.0,
        percentage_max=100.0,
        evidence=Evidence(
            document_id="exhibit_a",
            quote="Target Corp is wholly owned subsidiary of ParentCo.",
            source_name="filing",
        ),
    )
    verified = EdgeVerifier.verify_edge(edge, doc)
    assert verified.evidence.verified is True

