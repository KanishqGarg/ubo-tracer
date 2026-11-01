"""Tests for pure deterministic OwnershipCalculator."""

import pytest
from ubo_tracer.models import (
    Entity,
    EntityType,
    OwnershipEdge,
    Evidence,
    ControlNature,
    UBOStatus,
)
from ubo_tracer.calculator import OwnershipGraph, OwnershipCalculator


def dummy_evidence(quote="100% owned"):
    return Evidence(document_id="doc1", quote=quote, source_name="mock", verified=True)


def test_scenario_1_direct_ownership():
    # Direct: Person owns 60% of Target. Expect ABOVE (>25%).
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_1", name="Target Corp", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="alice", name="Alice Smith", entity_type=EntityType.PERSON))

    edge = OwnershipEdge(
        owner_id="alice",
        owner_name="Alice Smith",
        owner_type=EntityType.PERSON,
        owned_id="target_1",
        percentage_min=60.0,
        percentage_max=60.0,
        evidence=dummy_evidence("Alice owns 60% of Target Corp"),
    )
    graph.add_edge(edge)

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_1")

    assert len(results) == 1
    res = results[0]
    assert res.owner_id == "alice"
    assert res.effective_percentage_min == 60.0
    assert res.effective_percentage_max == 60.0
    assert res.status == UBOStatus.ABOVE
    assert not res.requires_human_review


def test_scenario_2_two_layers():
    # Two layers: HoldCo owns 60% of Target; Bob owns 50% of HoldCo (= 30%). Expect ABOVE.
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_2", name="Target 2 Ltd", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="holdco", name="HoldCo Ltd", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="bob", name="Bob Jones", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge(
        owner_id="holdco",
        owner_name="HoldCo Ltd",
        owner_type=EntityType.COMPANY,
        owned_id="target_2",
        percentage_min=60.0,
        percentage_max=60.0,
        evidence=dummy_evidence(),
    ))
    graph.add_edge(OwnershipEdge(
        owner_id="bob",
        owner_name="Bob Jones",
        owner_type=EntityType.PERSON,
        owned_id="holdco",
        percentage_min=50.0,
        percentage_max=50.0,
        evidence=dummy_evidence(),
    ))

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_2")

    assert len(results) == 1
    res = results[0]
    assert res.owner_id == "bob"
    # 0.5 * 0.6 = 0.30 -> 30%
    assert pytest.approx(res.effective_percentage_min, 0.001) == 30.0
    assert pytest.approx(res.effective_percentage_max, 0.001) == 30.0
    assert res.status == UBOStatus.ABOVE


def test_scenario_3_multiple_paths():
    # Multiple paths: Carol owns:
    # Path 1: Carol -> SubA (40%) -> Target (30%) = 12%
    # Path 2: Carol -> SubB (50%) -> Target (30%) = 15%
    # Total = 12% + 15% = 27% -> Expect ABOVE.
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_3", name="Target 3 Ltd", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="sub_a", name="Sub A", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="sub_b", name="Sub B", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="carol", name="Carol Danvers", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge(
        owner_id="sub_a", owner_name="Sub A", owner_type=EntityType.COMPANY,
        owned_id="target_3", percentage_min=30.0, percentage_max=30.0, evidence=dummy_evidence()
    ))
    graph.add_edge(OwnershipEdge(
        owner_id="sub_b", owner_name="Sub B", owner_type=EntityType.COMPANY,
        owned_id="target_3", percentage_min=30.0, percentage_max=30.0, evidence=dummy_evidence()
    ))
    graph.add_edge(OwnershipEdge(
        owner_id="carol", owner_name="Carol Danvers", owner_type=EntityType.PERSON,
        owned_id="sub_a", percentage_min=40.0, percentage_max=40.0, evidence=dummy_evidence()
    ))
    graph.add_edge(OwnershipEdge(
        owner_id="carol", owner_name="Carol Danvers", owner_type=EntityType.PERSON,
        owned_id="sub_b", percentage_min=50.0, percentage_max=50.0, evidence=dummy_evidence()
    ))

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_3")

    assert len(results) == 1
    res = results[0]
    assert res.owner_id == "carol"
    assert len(res.paths) == 2
    assert pytest.approx(res.effective_percentage_min, 0.001) == 27.0
    assert pytest.approx(res.effective_percentage_max, 0.001) == 27.0
    assert res.status == UBOStatus.ABOVE


def test_scenario_4_boundary_25_percent():
    # Exactly 25.0%.
    # If operator is 'gt' (strictly > 25%): 25.0% -> BELOW
    # If operator is 'gte' (>= 25%): 25.0% -> ABOVE
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_4", name="Target 4 Ltd", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="dave", name="Dave Miller", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge(
        owner_id="dave", owner_name="Dave Miller", owner_type=EntityType.PERSON,
        owned_id="target_4", percentage_min=25.0, percentage_max=25.0, evidence=dummy_evidence()
    ))

    # Test 'gt'
    calc_gt = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    res_gt = calc_gt.compute_ubo_results(graph, "target_4")[0]
    assert res_gt.status == UBOStatus.BELOW

    # Test 'gte'
    calc_gte = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gte")
    res_gte = calc_gte.compute_ubo_results(graph, "target_4")[0]
    assert res_gte.status == UBOStatus.ABOVE


def test_scenario_5_below_threshold_chain():
    # Long chain: Eve (50%) -> C1 (40%) -> C2 (50%) -> Target (= 10%). Expect BELOW.
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_5", name="Target 5", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="c2", name="C2", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="c1", name="C1", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="eve", name="Eve Clark", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge("c2", "C2", EntityType.COMPANY, "target_5", 50.0, 50.0, dummy_evidence()))
    graph.add_edge(OwnershipEdge("c1", "C1", EntityType.COMPANY, "c2", 40.0, 40.0, dummy_evidence()))
    graph.add_edge(OwnershipEdge("eve", "Eve Clark", EntityType.PERSON, "c1", 50.0, 50.0, dummy_evidence()))

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_5")
    assert len(results) == 1
    res = results[0]
    assert pytest.approx(res.effective_percentage_min, 0.001) == 10.0
    assert res.status == UBOStatus.BELOW


def test_scenario_6_circular_ownership():
    # Circular: Target owned 50% by A, 50% by Frank (Person).
    # A is owned 50% by B. B is owned 50% by A.
    # Must terminate without infinite recursion, flag cycle, Frank is 50% ABOVE.
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_6", name="Target 6", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="comp_a", name="Comp A", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="comp_b", name="Comp B", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="frank", name="Frank Castle", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge("frank", "Frank Castle", EntityType.PERSON, "target_6", 50.0, 50.0, dummy_evidence()))
    graph.add_edge(OwnershipEdge("comp_a", "Comp A", EntityType.COMPANY, "target_6", 50.0, 50.0, dummy_evidence()))
    graph.add_edge(OwnershipEdge("comp_b", "Comp B", EntityType.COMPANY, "comp_a", 50.0, 50.0, dummy_evidence()))
    graph.add_edge(OwnershipEdge("comp_a", "Comp A", EntityType.COMPANY, "comp_b", 50.0, 50.0, dummy_evidence()))

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_6")

    frank_res = next(r for r in results if r.owner_id == "frank")
    assert frank_res.status == UBOStatus.ABOVE
    assert pytest.approx(frank_res.effective_percentage_min, 0.001) == 50.0


def test_scenario_7_bands_interval_arithmetic():
    # Bands: Grace owns "more than 25% but not more than 50%" of Target [25.0, 50.0].
    # Lower bound 25.0% is not > 25.0%, but Upper bound 50.0% is > 25.0%.
    # Therefore, status must be UNCERTAIN and require human review!
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_7", name="Target 7", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="grace", name="Grace Hopper", entity_type=EntityType.PERSON))

    graph.add_edge(OwnershipEdge(
        "grace", "Grace Hopper", EntityType.PERSON, "target_7", 25.01, 50.0, dummy_evidence("between 25% and 50%")
    ))

    # With strictly > 25%: lower bound 25.01 > 25.0 -> ABOVE
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    res = calc.compute_ubo_results(graph, "target_7")[0]
    assert res.status == UBOStatus.ABOVE

    # If band was [20.0, 50.0]:
    graph2 = OwnershipGraph()
    graph2.add_entity(Entity(id="target_7b", name="Target 7b", entity_type=EntityType.COMPANY))
    graph2.add_edge(OwnershipEdge(
        "grace", "Grace Hopper", EntityType.PERSON, "target_7b", 20.0, 50.0, dummy_evidence()
    ))
    res2 = calc.compute_ubo_results(graph2, "target_7b")[0]
    assert res2.status == UBOStatus.UNCERTAIN
    assert res2.requires_human_review


def test_scenario_10_control_without_ownership():
    # Control without ownership: Henry owns only 5% of Target,
    # but has voting rights (80%) and is trustee.
    # Percentage must remain 5% (BELOW threshold), but flagged for human review!
    graph = OwnershipGraph()
    graph.add_entity(Entity(id="target_10", name="Target 10", entity_type=EntityType.COMPANY))
    graph.add_entity(Entity(id="henry", name="Henry Ford", entity_type=EntityType.PERSON))

    control = ControlNature(
        has_significant_influence=True,
        voting_percentage_min=80.0,
        voting_percentage_max=80.0,
        trustee_or_nominee=True,
        details="Appoints board via trust",
    )
    graph.add_edge(OwnershipEdge(
        "henry", "Henry Ford", EntityType.PERSON, "target_10", 5.0, 5.0, dummy_evidence(),
        control=control,
    ))

    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    results = calc.compute_ubo_results(graph, "target_10")
    assert len(results) == 1
    res = results[0]
    assert res.effective_percentage_min == 5.0
    assert res.status == UBOStatus.BELOW
    assert res.requires_human_review
    assert len(res.control_flags) >= 2
    assert any("Voting rights" in f for f in res.control_flags)

