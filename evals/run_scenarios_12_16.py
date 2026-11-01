"""Run Scenarios 12 to 16 end-to-end with the real local LLM and print exact results."""

import json
from ubo_tracer.models import UBOStatus
from ubo_tracer.calculator import OwnershipCalculator
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.planner import PlannerAgent
from ubo_tracer.llm import OllamaClient


def run_e2e_12_16():
    llm = OllamaClient(model="qwen2.5:3b")
    mock_src = MockSource(synthetic_dir="ubo_tracer/data/synthetic")
    retrieval = RetrievalAgent(sources={"mock": mock_src})
    extraction = ExtractionAgent(llm_client=llm)
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")

    scenarios = [
        ("target_corp_12", "Scenario 12 (Word fractions / Approximations)"),
        ("target_corp_13", "Scenario 13 (Two John Smiths name collision)"),
        ("target_corp_14", "Scenario 14 (Quote belongs to Unrelated Corp)"),
        ("target_corp_15", "Scenario 15 (Ownership summing > 100%)"),
        ("target_corp_16", "Scenario 16 (Decimal drift: 2.5% in text)"),
    ]

    summary = []

    for target_id, label in scenarios:
        print(f"\n{'='*70}\nRunning: {label} [{target_id}]\n{'='*70}")
        planner = PlannerAgent(
            retrieval_agent=retrieval,
            extraction_agent=extraction,
            calculator=calc,
            llm_client=llm,
            max_depth=8,
            max_steps=15,
        )
        res = planner.trace_entity(target_id)
        
        graph = res["graph"]
        edges = [e for el in graph.incoming_edges.values() for e in el]
        results = res["results"]
        rejected = res.get("rejected_edges", [])
        reviews = res.get("pending_reviews", [])

        print(f"Edges extracted & verified ({len(edges)}):")
        for e in edges:
            print(f"  - {e.owner_id} ({e.owner_name}) -> {e.owned_id}: [{e.percentage_min}%, {e.percentage_max}%] quote: '{e.evidence.quote}'")
        
        print(f"Rejected edges ({len(rejected)}):")
        for r in rejected:
            print(f"  - Rejection: {r.get('reason')} | doc: {r.get('doc_id')}")

        print(f"Computed UBO Results ({len(results)}):")
        for u in results:
            print(f"  - Owner: {u.owner_id} ({u.owner_name}) | Type: {u.owner_type.value} | Eff: [{u.effective_percentage_min}%, {u.effective_percentage_max}%] | Status: {u.status.value}")

        print(f"Pending Reviews ({len(reviews)}):")
        for rev in reviews:
            print(f"  - Type: {rev.get('type')} | Reason: {rev.get('reason')}")

        summary.append({
            "scenario": target_id,
            "label": label,
            "edges_count": len(edges),
            "results_count": len(results),
            "rejected_count": len(rejected),
            "ubos": [{"name": u.owner_name, "status": u.status.value, "eff_min": u.effective_percentage_min} for u in results],
        })

    print("\n" + "="*70)
    print("FINAL SUMMARY OF SCENARIOS 12-16 E2E WITH REAL LLM:")
    print("="*70)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_e2e_12_16()
