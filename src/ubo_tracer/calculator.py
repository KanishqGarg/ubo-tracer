"""Deterministic Ownership Graph & Effective Ownership Calculator.

NON-NEGOTIABLE DESIGN RULES:
1. Pure deterministic code - NO LLM is ever used for arithmetic.
2. Effective ownership of person P in target T = sum over all paths from P to T
   of the product of percentages along each path.
3. Interval arithmetic:
   - lower bound = sum of products of lower bounds
   - upper bound = sum of products of upper bounds (capped at 100.0%)
4. Threshold classification:
   - If comparison is 'gt':
       lower > threshold -> ABOVE
       upper <= threshold -> BELOW
       else -> UNCERTAIN
   - If comparison is 'gte':
       lower >= threshold -> ABOVE
       upper < threshold -> BELOW
       else -> UNCERTAIN
5. Cycle handling:
   - Traversal must detect cycles (revisiting a node currently in the active path),
     safely break them, log the cycle, and flag the result for human review.
6. Stop criteria:
   - Stop expanding at natural person, listed public company, or dead end.
7. Full audit trail:
   - Output every path, formula, and step so an auditor can recompute by hand.
"""

from __future__ import annotations
import re
from typing import List, Dict, Set, Optional, Tuple
from ubo_tracer.models import (
    Entity,
    EntityType,
    OwnershipEdge,
    OwnershipPath,
    EffectiveOwnershipResult,
    UBOStatus,
)


class OwnershipGraph:
    """Directed graph representing corporate ownership relationships."""

    def __init__(self):
        # Map: entity_id -> Entity
        self.entities: Dict[str, Entity] = {}
        # Map: owned_id -> list of incoming OwnershipEdges (parent owners)
        self.incoming_edges: Dict[str, List[OwnershipEdge]] = {}
        # Map: owner_id -> list of outgoing OwnershipEdges (subsidiaries)
        self.outgoing_edges: Dict[str, List[OwnershipEdge]] = {}

    def add_entity(self, entity: Entity) -> None:
        if entity.id not in self.entities:
            self.entities[entity.id] = entity

    def get_or_create_entity(self, entity_id: str, name: Optional[str] = None, entity_type: EntityType = EntityType.UNKNOWN) -> Entity:
        if entity_id not in self.entities:
            self.entities[entity_id] = Entity(
                id=entity_id,
                name=name or entity_id,
                entity_type=entity_type
            )
        elif name and self.entities[entity_id].name == entity_id:
            self.entities[entity_id].name = name
        return self.entities[entity_id]

    def add_edge(self, edge: OwnershipEdge) -> None:
        """Add an ownership edge from owner to owned entity."""
        # Ensure entities exist
        self.get_or_create_entity(edge.owner_id, edge.owner_name, edge.owner_type)
        self.get_or_create_entity(edge.owned_id)

        # Append to incoming (owned_id gets owner)
        if edge.owned_id not in self.incoming_edges:
            self.incoming_edges[edge.owned_id] = []
        self.incoming_edges[edge.owned_id].append(edge)

        # Append to outgoing (owner_id gets child)
        if edge.owner_id not in self.outgoing_edges:
            self.outgoing_edges[edge.owner_id] = []
        self.outgoing_edges[edge.owner_id].append(edge)

    def get_owners_of(self, entity_id: str) -> List[OwnershipEdge]:
        """Return all direct ownership edges pointing to entity_id."""
        return self.incoming_edges.get(entity_id, [])


class OwnershipCalculator:
    """Exact deterministic effective ownership calculator with interval arithmetic."""

    def __init__(
        self,
        threshold_percentage: float = 25.0,
        comparison_operator: str = "gt",
        max_depth: int = 8,
        listed_company_identifiers: Optional[List[str]] = None,
    ):
        self.threshold = float(threshold_percentage)
        self.comparison_operator = comparison_operator.lower()
        if self.comparison_operator not in ("gt", "gte"):
            raise ValueError(f"Unsupported comparison operator: {comparison_operator}. Must be 'gt' or 'gte'.")
        self.max_depth = max_depth
        self.listed_company_identifiers = [
            s.lower() for s in (listed_company_identifiers or ["plc", "lse:", "nyse:", "nasdaq:"])
        ]

    def is_listed_company(self, entity: Entity) -> bool:
        """Check if an entity is identified as a listed public company."""
        if entity.entity_type == EntityType.LISTED_COMPANY:
            return True
        name_lower = entity.name.lower()
        return any(ident in name_lower for ident in self.listed_company_identifiers)

    def is_terminal_entity(self, entity: Entity) -> bool:
        """Terminal condition: natural person or listed company."""
        if entity.entity_type == EntityType.PERSON:
            return True
        if self.is_listed_company(entity):
            return True
        return False

    def find_all_paths_to_target(
        self,
        graph: OwnershipGraph,
        target_id: str,
    ) -> Tuple[Dict[str, List[OwnershipPath]], List[str]]:
        """Traverse backwards from target_id to find all paths from terminal entities.
        
        Returns:
            - Dict mapping candidate_owner_id -> List[OwnershipPath]
            - List of detected cycle descriptions
        """
        paths_by_owner: Dict[str, List[OwnershipPath]] = {}
        detected_cycles: List[str] = []

        # Depth-first search backtracking from target upwards
        # Stack items: (current_node_id, current_path_nodes, current_edges, current_visited_set)
        # Note: visited set tracks nodes currently in the active DFS recursion branch to detect cycles.
        def dfs(
            curr_node_id: str,
            current_nodes_reversed: List[str],
            current_edges_reversed: List[OwnershipEdge],
            branch_visited: Set[str],
            depth: int,
        ):
            if depth >= self.max_depth:
                detected_cycles.append(f"Depth limit ({self.max_depth}) exceeded at {curr_node_id}")
                return

            incoming = graph.get_owners_of(curr_node_id)
            if not incoming:
                # No further owners known -> if this is target itself, empty; otherwise curr_node is dead end
                return

            for edge in incoming:
                owner_id = edge.owner_id
                owner_entity = graph.entities.get(owner_id) or graph.get_or_create_entity(owner_id)

                # Check for cycle: is owner_id already in active recursion branch?
                if owner_id in branch_visited:
                    cycle_path = " -> ".join(list(reversed(current_nodes_reversed)) + [owner_id])
                    detected_cycles.append(f"Circular ownership detected: {cycle_path}")
                    continue

                new_nodes_rev = current_nodes_reversed + [owner_id]
                new_edges_rev = current_edges_reversed + [edge]

                # If this owner is a terminal entity (person or listed company), record the completed path
                if self.is_terminal_entity(owner_entity):
                    # Path from terminal owner -> target:
                    # reverse the reversed lists to get [owner, ..., target]
                    full_nodes = list(reversed(new_nodes_rev))
                    full_edges = list(reversed(new_edges_rev))

                    # Compute path product of percentages (as fractional 0.0-1.0 then back to %)
                    prod_min = 1.0
                    prod_max = 1.0
                    path_lower_open = False
                    path_upper_open = False
                    for e in full_edges:
                        prod_min *= (e.percentage_min / 100.0)
                        prod_max *= (e.percentage_max / 100.0)
                        if getattr(e, "is_lower_open", False):
                            path_lower_open = True
                        if getattr(e, "is_upper_open", False):
                            path_upper_open = True

                    path_obj = OwnershipPath(
                        path_nodes=full_nodes,
                        edges=full_edges,
                        effective_min=prod_min * 100.0,
                        effective_max=prod_max * 100.0,
                        is_lower_open=path_lower_open,
                        is_upper_open=path_upper_open,
                    )
                    if owner_id not in paths_by_owner:
                        paths_by_owner[owner_id] = []
                    paths_by_owner[owner_id].append(path_obj)
                    # Stop expanding further up beyond terminal entity
                    continue

                # Otherwise, continue traversing upwards
                branch_visited.add(owner_id)
                dfs(
                    curr_node_id=owner_id,
                    current_nodes_reversed=new_nodes_rev,
                    current_edges_reversed=new_edges_rev,
                    branch_visited=branch_visited,
                    depth=depth + 1,
                )
                branch_visited.remove(owner_id)

        dfs(
            curr_node_id=target_id,
            current_nodes_reversed=[target_id],
            current_edges_reversed=[],
            branch_visited={target_id},
            depth=0,
        )

        return paths_by_owner, detected_cycles

    def classify_status(
        self,
        lower: float,
        upper: float,
        is_lower_open: bool = False,
        is_upper_open: bool = False,
    ) -> UBOStatus:
        """Classify interval against threshold deterministically with explicit open/closed bound logic.
        
        Using configurable comparison operator ('gt' or 'gte').
        
        Boundary Analysis:
        - If comparison_operator == 'gt' (Strictly greater than, e.g. UK PSC > 25%):
            * An owner is ABOVE if every possible value in the interval satisfies x > threshold.
              - If lower > threshold -> ABOVE.
              - If lower == threshold and is_lower_open is True:
                The interval is (threshold, upper]. Every element x in (threshold, upper] is strictly > threshold.
                Therefore, the owner is definitely ABOVE threshold!
              - If lower == threshold and is_lower_open is False:
                The value x = threshold is possible, and threshold is NOT > threshold.
                If upper > threshold, it spans the boundary -> UNCERTAIN.
                If upper == threshold, x = threshold <= threshold -> BELOW.
            * An owner is BELOW if every possible value in the interval satisfies x <= threshold.
              - If upper < threshold -> BELOW.
              - If upper == threshold (whether closed or open) -> BELOW (since all x <= threshold).
            * Otherwise -> UNCERTAIN.
            
        - If comparison_operator == 'gte' (Greater than or equal to, e.g. FATF >= 25%):
            * An owner is ABOVE if every possible value satisfies x >= threshold.
              - If lower > threshold -> ABOVE.
              - If lower == threshold:
                Whether lower is closed [threshold, upper] or open (threshold, upper], every element satisfies x >= threshold.
                Therefore -> ABOVE.
            * An owner is BELOW if every possible value satisfies x < threshold.
              - If upper < threshold -> BELOW.
              - If upper == threshold and is_upper_open is True:
                The interval is [lower, threshold). Every element satisfies x < threshold.
                Therefore -> BELOW.
              - If upper == threshold and is_upper_open is False:
                The value x = threshold is possible, which is >= threshold. Thus spans -> UNCERTAIN.
            * Otherwise -> UNCERTAIN.
        """
        if self.comparison_operator == "gt":
            # Rule: x > threshold
            if lower > self.threshold:
                return UBOStatus.ABOVE
            elif lower == self.threshold and is_lower_open and upper > self.threshold:
                # Interval (threshold, upper] => every element x > threshold
                return UBOStatus.ABOVE
            elif upper < self.threshold or upper == self.threshold:
                # If upper < threshold or upper == threshold, then every possible value in [lower, upper] or (lower, upper] is <= threshold.
                # Under strictly '>', any x <= threshold is NOT above threshold, so the entire interval is definitively BELOW.
                return UBOStatus.BELOW
            else:
                return UBOStatus.UNCERTAIN
        else:
            # Rule: x >= threshold
            if lower >= self.threshold:
                return UBOStatus.ABOVE
            elif upper < self.threshold:
                return UBOStatus.BELOW
            elif upper == self.threshold and is_upper_open:
                # Interval [lower, threshold) => every element x < threshold
                return UBOStatus.BELOW
            else:
                return UBOStatus.UNCERTAIN

    def compute_ubo_results(
        self,
        graph: OwnershipGraph,
        target_id: str,
    ) -> List[EffectiveOwnershipResult]:
        """Calculate effective ownership for all candidate terminal owners of target_id."""
        paths_by_owner, detected_cycles = self.find_all_paths_to_target(graph, target_id)
        results: List[EffectiveOwnershipResult] = []

        # Also identify any entities that have control or dead ends
        all_candidate_ids = set(paths_by_owner.keys())

        # Check for control flags or direct links on non-terminal or terminal entities
        control_by_owner: Dict[str, List[str]] = {}
        for edge_list in graph.incoming_edges.values():
            for edge in edge_list:
                if edge.control and edge.control.is_controlled():
                    cid = edge.owner_id
                    flags = []
                    if edge.control.has_significant_influence:
                        flags.append(f"Significant influence/control over {edge.owned_id}")
                    if edge.control.voting_percentage_min is not None:
                        flags.append(f"Voting rights: {edge.control.voting_percentage_min}% - {edge.control.voting_percentage_max}% over {edge.owned_id}")
                    if edge.control.trustee_or_nominee:
                        flags.append(f"Trustee / Nominee arrangement for {edge.owned_id}")
                    if edge.control.right_to_appoint_directors:
                        flags.append(f"Right to appoint/remove directors of {edge.owned_id}")
                    if edge.control.details:
                        flags.append(edge.control.details)
                    control_by_owner.setdefault(cid, []).extend(flags)
                    all_candidate_ids.add(cid)

        for owner_id in all_candidate_ids:
            entity = graph.entities.get(owner_id) or graph.get_or_create_entity(owner_id)
            paths = paths_by_owner.get(owner_id, [])

            # Sum over all paths from owner to target
            sum_min = sum(p.effective_min for p in paths)
            sum_max = sum(p.effective_max for p in paths)

            # Cap upper bound at 100.0%
            sum_min = min(100.0, max(0.0, sum_min))
            sum_max = min(100.0, max(0.0, sum_max))

            review_reasons: List[str] = []
            requires_review = False

            # Check if any path has open lower/upper bounds
            is_lower_open = any(getattr(p, "is_lower_open", False) for p in paths) if paths else False
            is_upper_open = any(getattr(p, "is_upper_open", False) for p in paths) if paths else False

            # Check status
            status = self.classify_status(
                lower=sum_min,
                upper=sum_max,
                is_lower_open=is_lower_open,
                is_upper_open=is_upper_open,
            )
            if status == UBOStatus.UNCERTAIN:
                requires_review = True
                review_reasons.append(f"Ownership interval [{sum_min:.2f}%, {sum_max:.2f}%] spans threshold ({self.threshold}%)")

            # Check cycles
            has_cycle = False
            cycle_desc = None
            for c in detected_cycles:
                if owner_id in c:
                    has_cycle = True
                    cycle_desc = c
                    requires_review = True
                    review_reasons.append(f"Involved in cycle: {c}")

            # Check control: flag if there is distinct non-ownership control (trustee/nominee, director appointment rights, significant influence, or voting percentage exceeding economic ownership)
            control_flags = control_by_owner.get(owner_id, [])
            distinct_control = []
            for cf in control_flags:
                cf_lower = cf.lower()
                if "trustee" in cf_lower or "nominee" in cf_lower or "appoint" in cf_lower or "board" in cf_lower or "trust" in cf_lower or "significant influence" in cf_lower:
                    distinct_control.append(cf)
                elif "voting rights" in cf_lower:
                    # Parse voting rights numbers to check if voting rights exceed ownership
                    nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", cf)]
                    if nums and any(n > sum_max for n in nums):
                        distinct_control.append(cf)

            if distinct_control:
                requires_review = True
                review_reasons.append("Non-ownership control mechanisms present (Rule 5: separate from percentage)")

            # Check if any edge in paths is disputed by self-consistency check
            is_disputed = False
            dispute_msgs = []
            for p in paths:
                for edge in p.edges:
                    if getattr(edge, "is_disputed", False):
                        is_disputed = True
                        dispute_msgs.append(f"Disputed edge ({edge.owner_name} -> {edge.owned_id}): {edge.dispute_reason or 'Self-consistency mismatch'}")

            if is_disputed:
                status = UBOStatus.DISPUTED
                requires_review = True
                review_reasons.extend(dispute_msgs)

            # Check if dead-end or unresolved
            if not paths and not distinct_control:
                status = UBOStatus.UNRESOLVED
                requires_review = True
                review_reasons.append("No viable path resolved to target entity (missing parent documents or dead end)")
            elif entity.is_unresolved:
                status = UBOStatus.UNRESOLVED
                requires_review = True
                review_reasons.append("Entity ownership could not be resolved from sources (dead end)")

            results.append(
                EffectiveOwnershipResult(
                    owner_id=owner_id,
                    owner_name=entity.name,
                    owner_type=entity.entity_type,
                    effective_percentage_min=sum_min,
                    effective_percentage_max=sum_max,
                    is_lower_open=is_lower_open,
                    is_upper_open=is_upper_open,
                    status=status,
                    paths=paths,
                    requires_human_review=requires_review,
                    review_reasons=review_reasons,
                    control_flags=control_flags,
                    has_cycle=has_cycle,
                    cycle_details=cycle_desc,
                )
            )

        # Sort results: ABOVE first, then UNCERTAIN, then UNRESOLVED, then BELOW; secondary sort by % max desc
        status_priority = {UBOStatus.ABOVE: 0, UBOStatus.UNCERTAIN: 1, UBOStatus.UNRESOLVED: 2, UBOStatus.BELOW: 3}
        results.sort(key=lambda r: (status_priority.get(r.status, 4), -r.effective_percentage_max, r.owner_name))
        return results
