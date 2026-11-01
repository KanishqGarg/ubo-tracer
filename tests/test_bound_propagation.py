"""Test propagation of open/closed bounds through multiplication and addition."""

import pytest
from ubo_tracer.models import OwnershipEdge, Evidence, EntityType, UBOStatus
from ubo_tracer.calculator import OwnershipCalculator, OwnershipGraph


def test_open_bound_multiplication_propagation():
    # Scenario: Person owns (25, 50]% in HoldCo, HoldCo owns 60% in Target
    # Product: (25% * 60%, 50% * 60%] = (15%, 30%]
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    graph = OwnershipGraph()
    graph.get_or_create_entity("target")
    graph.get_or_create_entity("holdco")
    graph.get_or_create_entity("person", "Test Person", EntityType.PERSON)

    # Edge 1: HoldCo -> Target = 60% (closed)
    graph.add_edge(OwnershipEdge(
        owner_id="holdco", owner_name="HoldCo", owner_type=EntityType.COMPANY,
        owned_id="target", percentage_min=60.0, percentage_max=60.0,
        evidence=Evidence("d1", "60%", "mock", verified=True)
    ))

    # Edge 2: Person -> HoldCo = (25, 50]% (lower open)
    graph.add_edge(OwnershipEdge(
        owner_id="person", owner_name="Test Person", owner_type=EntityType.PERSON,
        owned_id="holdco", percentage_min=25.0, percentage_max=50.0,
        is_lower_open=True, is_upper_open=False,
        evidence=Evidence("d2", "more than 25% but not more than 50%", "mock", verified=True)
    ))

    results = calc.compute_ubo_results(graph, "target")
    person_res = next(r for r in results if r.owner_id == "person")

    # Min = 25% * 60% = 15.0%, Max = 50% * 60% = 30.0%
    assert person_res.effective_percentage_min == 15.0
    assert person_res.effective_percentage_max == 30.0
    assert person_res.is_lower_open is True
    # (15, 30] spans 25.0% -> UNCERTAIN
    assert person_res.status == UBOStatus.UNCERTAIN


def test_open_bound_at_threshold_below():
    # Scenario: Interval is (20.0, 25.0] under strictly > 25 rule.
    # Since all elements are <= 25.0, this MUST be BELOW.
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    status = calc.classify_status(
        lower=20.0,
        upper=25.0,
        is_lower_open=True,
        is_upper_open=False, # closed upper bound at 25.0
    )
    assert status == UBOStatus.BELOW

