"""End-to-end test scenarios on synthetic data."""

import pytest
from pathlib import Path
from ubo_tracer.models import UBOStatus, EntityType
from ubo_tracer.calculator import OwnershipCalculator
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.planner import PlannerAgent
from ubo_tracer.agents.verifier import EdgeVerifier
from ubo_tracer.llm import OllamaClient


@pytest.fixture(scope="session")
def setup_agent():
    # Attempt local LLM
    llm = OllamaClient(model="qwen2.5:3b")
    try:
        llm.check_health_and_model()
    except Exception:
        pytest.skip("Ollama is not running or model not found; skipping LLM e2e tests.")

    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    retrieval = RetrievalAgent(sources={"mock": mock_src}, default_order=["mock"])
    extraction = ExtractionAgent(llm_client=llm)
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")

    planner = PlannerAgent(
        retrieval_agent=retrieval,
        extraction_agent=extraction,
        calculator=calc,
        llm_client=llm,
        max_depth=8,
        max_steps=20,
    )
    return planner, calc


def test_e2e_scenario_1_direct(setup_agent):
    planner, _ = setup_agent
    res = planner.trace_entity("target_corp_1")
    ubos = [r for r in res["results"] if r.status == UBOStatus.ABOVE]
    assert len(ubos) >= 1
    alice = next((r for r in ubos if "alice" in r.owner_name.lower()), None)
    assert alice is not None
    assert alice.effective_percentage_min == 60.0


def test_e2e_scenario_2_two_layers(setup_agent):
    planner, _ = setup_agent
    res = planner.trace_entity("target_corp_2")
    ubos = [r for r in res["results"] if r.status == UBOStatus.ABOVE]
    assert len(ubos) >= 1
    bob = next((r for r in ubos if "bob" in r.owner_name.lower()), None)
    assert bob is not None
    assert pytest.approx(bob.effective_percentage_min, 0.1) == 30.0


def test_e2e_scenario_4_boundary_operator(setup_agent):
    planner, calc = setup_agent
    res = planner.trace_entity("target_corp_4")
    dave = next((r for r in res["results"] if "dave" in r.owner_name.lower()), None)
    assert dave is not None
    assert dave.effective_percentage_min == 25.0
    # strictly greater than 25% -> BELOW
    assert dave.status == UBOStatus.BELOW


def test_e2e_scenario_6_circular_termination(setup_agent):
    planner, _ = setup_agent
    res = planner.trace_entity("target_corp_6")
    # Must terminate without infinite loop and steps < max_steps
    assert res["steps_taken"] < 20
    frank = next((r for r in res["results"] if "frank" in r.owner_name.lower()), None)
    assert frank is not None
    assert frank.status == UBOStatus.ABOVE


def test_e2e_scenario_9_hallucination_trap_rejection():
    # Verify explicitly that the verifier rejects the hallucination trap in scenario 9
    doc_text = "Target Corp 9 Ltd is a wholly owned subsidiary of Alpha Parent Ltd, holding 100% of voting rights."
    from ubo_tracer.models import OwnershipEdge, Evidence

    # Trap edge
    trap_edge = OwnershipEdge(
        owner_id="phantom_swindler",
        owner_name="Phantom Swindler",
        owner_type=EntityType.PERSON,
        owned_id="target_corp_9",
        percentage_min=80.0,
        percentage_max=80.0,
        evidence=Evidence(
            document_id="syn_doc_901",
            quote="Phantom Swindler holds 80% of shares",  # Not in doc!
            source_name="mock",
        ),
    )
    verified = EdgeVerifier.verify_edge(trap_edge, doc_text)
    assert verified.evidence.verified is False
    assert "not found verbatim" in verified.evidence.verification_error

