"""Unit tests for adversarial scenarios 12 to 16."""

import pytest
from ubo_tracer.models import OwnershipEdge, Evidence, EntityType
from ubo_tracer.agents.verifier import EdgeVerifier
from ubo_tracer.calculator import OwnershipCalculator, OwnershipGraph


def test_adversarial_scenario_14_cross_company_quote():
    # Document belongs to Target Corp 14 Ltd, but quote is about Unrelated Corp Ltd
    doc_text = "Omnibus Filing Extract: Registered office notice for Target Corp 14 Ltd. In other news, Unrelated Corp Ltd is owned 90% by Victoria Secret."
    
    # If LLM extracts Victoria Secret as owner of Target Corp 14 Ltd:
    # Verifier checks if target or owner appears in context, or if quote refers to owned_id
    edge = OwnershipEdge(
        owner_id="victoria_secret",
        owner_name="Victoria Secret",
        owner_type=EntityType.PERSON,
        owned_id="target_corp_14",
        percentage_min=90.0,
        percentage_max=90.0,
        evidence=Evidence(
            document_id="syn_doc_1401",
            quote="Unrelated Corp Ltd is owned 90% by Victoria Secret",
            source_name="mock",
        ),
    )
    # The quote exists in the doc, but the owned company in quote is Unrelated Corp Ltd, NOT Target Corp 14
    # The verifier checks that quote does not state an ownership relation for target_corp_14
    # Check if target name or ID is in the quote
    target_mentioned = "target corp 14" in edge.evidence.quote.lower() or "target_corp_14" in edge.evidence.quote.lower()
    assert target_mentioned is False


def test_adversarial_scenario_15_cap_and_review_over_100():
    # Two paths each claiming 60% summing to 120%
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    graph = OwnershipGraph()
    graph.get_or_create_entity("target_corp_15")
    graph.get_or_create_entity("branch_a_ltd")
    graph.get_or_create_entity("branch_b_ltd")
    graph.get_or_create_entity("geiley", "George Smiley", EntityType.PERSON)

    # Branch A -> Target 60%
    graph.add_edge(OwnershipEdge(
        owner_id="branch_a_ltd", owner_name="Branch A Ltd", owner_type=EntityType.COMPANY,
        owned_id="target_corp_15", percentage_min=60.0, percentage_max=60.0,
        evidence=Evidence("d1", "60%", "mock", verified=True)
    ))
    # Branch B -> Target 60%
    graph.add_edge(OwnershipEdge(
        owner_id="branch_b_ltd", owner_name="Branch B Ltd", owner_type=EntityType.COMPANY,
        owned_id="target_corp_15", percentage_min=60.0, percentage_max=60.0,
        evidence=Evidence("d2", "60%", "mock", verified=True)
    ))
    # Smiley -> Branch A 100%
    graph.add_edge(OwnershipEdge(
        owner_id="geiley", owner_name="George Smiley", owner_type=EntityType.PERSON,
        owned_id="branch_a_ltd", percentage_min=100.0, percentage_max=100.0,
        evidence=Evidence("d3", "100%", "mock", verified=True)
    ))
    # Smiley -> Branch B 100%
    graph.add_edge(OwnershipEdge(
        owner_id="geiley", owner_name="George Smiley", owner_type=EntityType.PERSON,
        owned_id="branch_b_ltd", percentage_min=100.0, percentage_max=100.0,
        evidence=Evidence("d4", "100%", "mock", verified=True)
    ))

    results = calc.compute_ubo_results(graph, "target_corp_15")
    smiley = next(r for r in results if r.owner_id == "geiley")
    # Must cap upper bound at 100.0%
    assert smiley.effective_percentage_min == 100.0
    assert smiley.effective_percentage_max == 100.0


def test_adversarial_scenario_16_decimal_drift_rejection():
    # Text says 2.5%, but edge claims 25.0%
    doc_text = "PSC Register Extract for Target Corp 16 Ltd: Minor Investor holds 2.5% of shares."
    edge = OwnershipEdge(
        owner_id="minor_investor",
        owner_name="Minor Investor",
        owner_type=EntityType.PERSON,
        owned_id="target_corp_16",
        percentage_min=25.0,  # Decimal drift: extracted 25 instead of 2.5
        percentage_max=25.0,
        evidence=Evidence(
            document_id="syn_doc_1601",
            quote="Minor Investor holds 2.5% of shares",
            source_name="mock",
        ),
    )
    verified = EdgeVerifier.verify_edge(edge, doc_text)
    # Verifier MUST reject because 25.0 is not in quote containing 2.5
    assert verified.evidence.verified is False
    assert "does not appear in quote" in verified.evidence.verification_error
