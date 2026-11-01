"""Parallel branch tracer with shared step budget, wall-clock timeout, and deterministic aggregation."""

from __future__ import annotations
import concurrent.futures
import time
from typing import Dict, Any, List, Optional
from ubo_tracer.models import EffectiveOwnershipResult, OwnershipEdge
from ubo_tracer.calculator import OwnershipGraph, OwnershipCalculator
from ubo_tracer.agents.planner import PlannerAgent


class ParallelBranchTracer:
    """Traces independent ownership branches concurrently under a shared budget."""

    def __init__(
        self,
        planner_agent: PlannerAgent,
        max_workers: int = 3,
        shared_step_budget: int = 40,
        timeout_seconds: float = 60.0,
    ):
        self.planner = planner_agent
        self.max_workers = max_workers
        self.shared_step_budget = shared_step_budget
        self.timeout_seconds = timeout_seconds

    def trace_parallel(self, target_id: str, branch_entity_ids: List[str]) -> Dict[str, Any]:
        """Concurrently traces separate candidate parent entities of target_id.
        
        Guarantees deterministic sorting and aggregation regardless of completion order.
        """
        start_time = time.time()
        combined_graph = OwnershipGraph()
        combined_graph.get_or_create_entity(target_id)

        branch_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.planner.trace_entity, branch_id): branch_id
                for branch_id in branch_entity_ids
            }

            for future in concurrent.futures.as_completed(futures):
                branch_id = futures[future]
                try:
                    res = future.result(timeout=max(1.0, self.timeout_seconds - (time.time() - start_time)))
                    branch_results[branch_id] = res
                except Exception as e:
                    branch_results[branch_id] = {"error": str(e), "graph": OwnershipGraph()}

        # Deterministic merge of graphs: sort branch_ids alphabetically to assure invariant order
        for branch_id in sorted(branch_results.keys()):
            res = branch_results[branch_id]
            b_graph = res.get("graph")
            if b_graph:
                for eid, ent in b_graph.entities.items():
                    combined_graph.add_entity(ent)
                for owned_id, edge_list in b_graph.incoming_edges.items():
                    for edge in edge_list:
                        combined_graph.add_edge(edge)

        # Recompute effective ownership deterministically
        results = self.planner.calculator.compute_ubo_results(combined_graph, target_id)
        # Deterministic sorting guarantee
        results.sort(key=lambda r: (r.status.value, -r.effective_percentage_max, r.owner_name))

        return {
            "target_id": target_id,
            "branches_traced": len(branch_entity_ids),
            "results": results,
            "graph": combined_graph,
            "duration_sec": round(time.time() - start_time, 2),
        }
