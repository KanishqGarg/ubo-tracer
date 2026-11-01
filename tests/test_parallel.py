"""Unit tests for Parallel Branch Tracing determinism and shared budgets."""

import pytest
from ubo_tracer.models import OwnershipEdge, Evidence, EntityType
from ubo_tracer.calculator import OwnershipCalculator, OwnershipGraph
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.planner import PlannerAgent
from ubo_tracer.agents.parallel import ParallelBranchTracer


def test_parallel_branch_tracer_deterministic_order():
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    retrieval = RetrievalAgent(sources={"mock": mock_src}, default_order=["mock"])
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    # Planner with dummy extraction
    planner = PlannerAgent(retrieval, None, calc, max_depth=4, max_steps=10)
    tracer = ParallelBranchTracer(planner, max_workers=2, shared_step_budget=20)

    # Run 1
    res1 = tracer.trace_parallel("target_corp_3", ["midco_north", "midco_south"])
    # Run 2
    res2 = tracer.trace_parallel("target_corp_3", ["midco_south", "midco_north"])

    # Output ordering and results must be identical regardless of input or finish order
    names1 = [r.owner_name for r in res1["results"]]
    names2 = [r.owner_name for r in res2["results"]]
    assert names1 == names2

