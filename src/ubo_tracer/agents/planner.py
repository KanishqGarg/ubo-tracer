"""Planner Agent: queue management, depth/step limits, cycle tracking, orchestration.

NON-NEGOTIABLE DESIGN RULES:
7. Hard limits: max graph depth (default 8), max agent steps (default 40),
   max retries per entity (default 2). Detect cycles in ownership and handle
   them explicitly without infinite loops.
3. Verifier checks quotes and numbers; unverified edges are discarded.
4. "Unresolved" is a valid output. Never invent or guess a missing owner.
"""

from __future__ import annotations
import uuid
from collections import deque
from typing import Dict, List, Set, Optional, Any
from ubo_tracer.models import Entity, EntityType, OwnershipEdge, EffectiveOwnershipResult, UBOStatus
from ubo_tracer.calculator import OwnershipGraph, OwnershipCalculator
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.verifier import EdgeVerifier
from ubo_tracer.checkpoint import CheckpointStore
from ubo_tracer.cache import EntityCache
from ubo_tracer.llm import OllamaClient


class PlannerAgent:
    """Coordinates the search frontier, limits, verification, and graph construction."""

    def __init__(
        self,
        retrieval_agent: RetrievalAgent,
        extraction_agent: ExtractionAgent,
        calculator: OwnershipCalculator,
        llm_client: Optional[OllamaClient] = None,
        max_depth: int = 8,
        max_steps: int = 40,
        max_retries: int = 2,
        checkpoint_store: Optional[CheckpointStore] = None,
        entity_cache: Optional[EntityCache] = None,
        pause_on_review: bool = False,
    ):
        self.retrieval = retrieval_agent
        self.extraction = extraction_agent
        self.calculator = calculator
        self.llm = llm_client
        self.max_depth = max_depth
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.checkpoint_store = checkpoint_store
        self.entity_cache = entity_cache
        self.pause_on_review = pause_on_review

    def trace_entity(
        self,
        target_id: str,
        target_name: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute autonomous ownership tracing starting from target_id with durable checkpoints."""
        run_id = run_id or str(uuid.uuid4())[:8]
        graph = OwnershipGraph()
        initial_entity = Entity(
            id=target_id,
            name=target_name or target_id,
            entity_type=EntityType.COMPANY,
        )
        graph.add_entity(initial_entity)

        # Check if resuming from existing checkpoint
        if self.checkpoint_store:
            existing = self.checkpoint_store.load_checkpoint(run_id)
            if existing and existing.get("queue") is not None:
                queue = deque([(item["entity_id"], item["depth"]) for item in existing["queue"]])
                explored_entities: Set[str] = set(existing.get("visited", []))
                retries_per_entity: Dict[str, int] = existing.get("retries", {})
                step_count = existing.get("current_step", 0)
                # Reconstruct entities and edges
                for eid, edata in existing.get("entities", {}).items():
                    ent = Entity(
                        id=eid,
                        name=edata.get("name", eid),
                        entity_type=EntityType(edata.get("entity_type", "unknown")),
                        is_terminal=edata.get("is_terminal", False),
                        is_unresolved=edata.get("is_unresolved", False),
                    )
                    graph.add_entity(ent)
                for ed in existing.get("edges", []):
                    from ubo_tracer.models import Evidence, ControlNature
                    e = OwnershipEdge(
                        owner_id=ed["owner_id"],
                        owner_name=ed["owner_name"],
                        owner_type=EntityType(ed["owner_type"]),
                        owned_id=ed["owned_id"],
                        percentage_min=ed["percentage_min"],
                        percentage_max=ed["percentage_max"],
                        evidence=Evidence(
                            document_id=ed["evidence"]["document_id"],
                            quote=ed["evidence"]["quote"],
                            source_name=ed["evidence"]["source_name"],
                            verified=ed["evidence"]["verified"],
                        ),
                        is_disputed=ed.get("is_disputed", False),
                        dispute_reason=ed.get("dispute_reason"),
                    )
                    graph.add_edge(e)
            else:
                queue = deque([(target_id, 0)])
                explored_entities = set()
                retries_per_entity = {}
                step_count = 0
        else:
            queue = deque([(target_id, 0)])
            explored_entities = set()
            retries_per_entity = {}
            step_count = 0

        rejected_edges: List[Dict[str, Any]] = []
        pending_reviews: List[Dict[str, Any]] = []
        limit_reached = False
        status = "running"

        while queue and step_count < self.max_steps:
            curr_id, curr_depth = queue.popleft()

            if curr_id in explored_entities:
                continue

            curr_entity = graph.entities.get(curr_id) or graph.get_or_create_entity(curr_id)

            # Stop expansion condition: Person or Listed Public Company
            if self.calculator.is_terminal_entity(curr_entity):
                curr_entity.is_terminal = True
                explored_entities.add(curr_id)
                continue

            # Check depth limit
            if curr_depth >= self.max_depth:
                limit_reached = True
                if self.llm:
                    self.llm.log_trace("depth_limit_hit", {"entity_id": curr_id, "depth": curr_depth})
                continue

            step_count += 1
            if self.llm:
                self.llm.log_trace("planner_step", {
                    "step": step_count,
                    "entity_id": curr_id,
                    "depth": curr_depth,
                })

            # Check entity cache first
            cached = self.entity_cache.get(curr_id) if self.entity_cache else None
            docs = []
            if cached and not cached.is_stale and cached.edges:
                # Use cached edges
                found_edges_for_node = True
                for ed in cached.edges:
                    from ubo_tracer.models import Evidence
                    edge = OwnershipEdge(
                        owner_id=ed["owner_id"],
                        owner_name=ed["owner_name"],
                        owner_type=EntityType(ed["owner_type"]),
                        owned_id=curr_id,
                        percentage_min=ed["percentage_min"],
                        percentage_max=ed["percentage_max"],
                        evidence=Evidence(
                            document_id=ed["evidence"]["document_id"],
                            quote=ed["evidence"]["quote"],
                            source_name=cached.source_name,
                            verified=True,
                        ),
                    )
                    graph.add_edge(edge)
                    owner_entity = graph.entities.get(edge.owner_id) or graph.get_or_create_entity(
                        edge.owner_id, edge.owner_name, edge.owner_type
                    )
                    if not self.calculator.is_terminal_entity(owner_entity) and edge.owner_id not in explored_entities:
                        queue.append((edge.owner_id, curr_depth + 1))
                explored_entities.add(curr_id)
                continue
            else:
                # Fetch fresh documents
                docs = self.retrieval.fetch_documents_for_entity(curr_id, curr_entity.name)

            if not docs:
                retries = retries_per_entity.get(curr_id, 0)
                if retries < self.max_retries:
                    retries_per_entity[curr_id] = retries + 1
                    queue.append((curr_id, curr_depth))
                else:
                    curr_entity.is_unresolved = True
                    curr_entity.notes.append(f"No source documents found after {retries} retries.")
                    explored_entities.add(curr_id)
                    pending_reviews.append({
                        "item_id": f"rev_deadend_{curr_id}",
                        "type": "dead_end",
                        "entity_id": curr_id,
                        "entity_name": curr_entity.name,
                        "reason": "Missing parent corporate documents",
                    })
                    if self.pause_on_review:
                        status = "awaiting_review"
                        break
                continue

            # Extract edges from docs
            found_edges_for_node = False
            for doc in docs:
                candidate_edges = self.extraction.extract_edges_from_doc(
                    doc_id=doc.document_id,
                    doc_text=doc.content_text,
                    owned_entity_id=curr_id,
                    source_name=doc.source_name,
                ) if self.extraction else []

                # Deterministic Verification step (Rule #3)
                node_verified_edges = []
                for edge in candidate_edges:
                    verified_edge = EdgeVerifier.verify_edge(edge, doc.content_text)
                    if verified_edge.evidence.verified:
                        graph.add_edge(verified_edge)
                        node_verified_edges.append(verified_edge.to_dict())
                        found_edges_for_node = True

                        if verified_edge.is_disputed:
                            pending_reviews.append({
                                "item_id": f"rev_dispute_{verified_edge.owner_id}",
                                "type": "dispute",
                                "entity_id": verified_edge.owner_id,
                                "entity_name": verified_edge.owner_name,
                                "reason": verified_edge.dispute_reason or "Self-consistency dispute",
                            })

                        # Check if parent owner needs exploration
                        owner_entity = graph.entities.get(edge.owner_id) or graph.get_or_create_entity(
                            edge.owner_id, edge.owner_name, edge.owner_type
                        )
                        if not self.calculator.is_terminal_entity(owner_entity) and edge.owner_id not in explored_entities:
                            queue.append((edge.owner_id, curr_depth + 1))
                    else:
                        rejection_record = {
                            "edge": edge.to_dict(),
                            "reason": verified_edge.evidence.verification_error,
                            "doc_id": doc.document_id,
                        }
                        rejected_edges.append(rejection_record)
                        if self.llm:
                            self.llm.log_trace("edge_rejected", rejection_record)

                # Save to entity cache
                if self.entity_cache and node_verified_edges:
                    self.entity_cache.set(
                        entity_id=curr_id,
                        entity_name=curr_entity.name,
                        entity_type=curr_entity.entity_type.value,
                        edges=node_verified_edges,
                        source_name=doc.source_name,
                    )

            explored_entities.add(curr_id)
            if not found_edges_for_node and not curr_entity.is_terminal:
                curr_entity.is_unresolved = True
                curr_entity.notes.append("No verified ownership edges could be extracted from sources.")
                pending_reviews.append({
                    "item_id": f"rev_noedges_{curr_id}",
                    "type": "unresolved_node",
                    "entity_id": curr_id,
                    "entity_name": curr_entity.name,
                    "reason": "No verifiable ownership statements found in filing",
                })
                if self.pause_on_review:
                    status = "awaiting_review"
                    break

            # Persist checkpoint after step
            if self.checkpoint_store:
                q_list = [{"entity_id": q_eid, "depth": q_d} for q_eid, q_d in queue]
                all_edges_dict = [e.to_dict() for el in graph.incoming_edges.values() for e in el]
                ent_dict = {eid: {"name": e.name, "entity_type": e.entity_type.value, "is_terminal": e.is_terminal, "is_unresolved": e.is_unresolved} for eid, e in graph.entities.items()}
                self.checkpoint_store.save_checkpoint(
                    run_id=run_id,
                    target_id=target_id,
                    status=status,
                    current_step=step_count,
                    queue=q_list,
                    visited=list(explored_entities),
                    retries=retries_per_entity,
                    edges=all_edges_dict,
                    entities=ent_dict,
                    pending_reviews=pending_reviews,
                )

        # Compute deterministic effective ownership via exact code (Rule #1, #6)
        results: List[EffectiveOwnershipResult] = self.calculator.compute_ubo_results(graph, target_id)
        if status != "awaiting_review":
            status = "completed"

        # Final checkpoint save with results
        if self.checkpoint_store:
            q_list = [{"entity_id": q_eid, "depth": q_d} for q_eid, q_d in queue]
            all_edges_dict = [e.to_dict() for el in graph.incoming_edges.values() for e in el]
            ent_dict = {eid: {"name": e.name, "entity_type": e.entity_type.value, "is_terminal": e.is_terminal, "is_unresolved": e.is_unresolved} for eid, e in graph.entities.items()}
            self.checkpoint_store.save_checkpoint(
                run_id=run_id,
                target_id=target_id,
                status=status,
                current_step=step_count,
                queue=q_list,
                visited=list(explored_entities),
                retries=retries_per_entity,
                edges=all_edges_dict,
                entities=ent_dict,
                pending_reviews=pending_reviews,
                results=[r.to_dict() for r in results],
            )

        return {
            "run_id": run_id,
            "status": status,
            "target_id": target_id,
            "target_name": target_name or target_id,
            "steps_taken": step_count,
            "limit_reached": limit_reached or (step_count >= self.max_steps),
            "results": results,
            "graph": graph,
            "rejected_edges": rejected_edges,
            "pending_reviews": pending_reviews,
        }

