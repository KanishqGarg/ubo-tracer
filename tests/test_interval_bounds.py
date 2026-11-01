"""Unit tests for exact open and closed interval classification under both gt (>) and gte (>=) operators."""

import pytest
from ubo_tracer.models import UBOStatus
from ubo_tracer.calculator import OwnershipCalculator


def test_closed_interval_boundary_gt():
    # Operator: strictly > 25.0
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")

    # [25.0, 50.0] (Closed lower bound at 25.0, can be exactly 25.0 which is NOT > 25.0)
    # Spans boundary -> UNCERTAIN
    assert calc.classify_status(25.0, 50.0, is_lower_open=False, is_upper_open=False) == UBOStatus.UNCERTAIN

    # (25.0, 50.0] (Open lower bound at 25.0, i.e. "more than 25%")
    # Every element x satisfies x > 25.0 -> ABOVE
    assert calc.classify_status(25.0, 50.0, is_lower_open=True, is_upper_open=False) == UBOStatus.ABOVE

    # [10.0, 25.0] (Closed upper bound at 25.0)
    # Every element x <= 25.0 -> BELOW
    assert calc.classify_status(10.0, 25.0, is_lower_open=False, is_upper_open=False) == UBOStatus.BELOW

    # [10.0, 25.0) (Open upper bound at 25.0, i.e. "less than 25%")
    # Every element x < 25.0 -> BELOW
    assert calc.classify_status(10.0, 25.0, is_lower_open=False, is_upper_open=True) == UBOStatus.BELOW

    # Exactly 25.0 scalar [25.0, 25.0]
    # Under strictly >, 25.0 is NOT > 25.0 -> BELOW
    assert calc.classify_status(25.0, 25.0, is_lower_open=False, is_upper_open=False) == UBOStatus.BELOW


def test_closed_interval_boundary_gte():
    # Operator: >= 25.0
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gte")

    # [25.0, 50.0] (Closed lower bound at 25.0)
    # Every element x >= 25.0 -> ABOVE
    assert calc.classify_status(25.0, 50.0, is_lower_open=False, is_upper_open=False) == UBOStatus.ABOVE

    # (25.0, 50.0] (Open lower bound at 25.0)
    # Every element x >= 25.0 -> ABOVE
    assert calc.classify_status(25.0, 50.0, is_lower_open=True, is_upper_open=False) == UBOStatus.ABOVE

    # [10.0, 25.0] (Closed upper bound at 25.0, x can be 25.0 which satisfies >= 25.0)
    # Spans boundary [10.0, 25.0] -> UNCERTAIN
    assert calc.classify_status(10.0, 25.0, is_lower_open=False, is_upper_open=False) == UBOStatus.UNCERTAIN

    # [10.0, 25.0) (Open upper bound at 25.0, i.e. x < 25.0)
    # Every element is strictly < 25.0 -> BELOW
    assert calc.classify_status(10.0, 25.0, is_lower_open=False, is_upper_open=True) == UBOStatus.BELOW

    # Exactly 25.0 scalar [25.0, 25.0]
    # Under >=, 25.0 >= 25.0 is True -> ABOVE
    assert calc.classify_status(25.0, 25.0, is_lower_open=False, is_upper_open=False) == UBOStatus.ABOVE

