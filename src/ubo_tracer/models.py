"""Data models for UBO Tracer.

All dataclasses define strictly-typed schemas for Entities, Ownership Edges,
Evidence quotes, and Calculation records.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class EntityType(str, Enum):
    """Categorization of entities encountered during graph traversal."""
    PERSON = "person"                  # Natural person (terminal UBO candidate)
    COMPANY = "company"                # Private or unlisted intermediate entity
    LISTED_COMPANY = "listed_company"  # Publicly traded company (terminal stop)
    TRUST = "trust"                    # Trust or legal arrangement
    UNKNOWN = "unknown"                # Unresolved entity type


class UBOStatus(str, Enum):
    """Deterministic classification against the ownership threshold."""
    ABOVE = "ABOVE"          # Lower bound > threshold (or >= if configured)
    BELOW = "BELOW"          # Upper bound <= threshold (or < if configured)
    UNCERTAIN = "UNCERTAIN"  # Interval spans across threshold (e.g. [20%, 35%])
    UNRESOLVED = "UNRESOLVED"# Missing data or dead end along ownership chain
    DISPUTED = "DISPUTED"    # Conflicting extraction outputs under self-consistency check


@dataclass
class Evidence:
    """Verbatim source evidence supporting an ownership claim."""
    document_id: str
    quote: str
    source_name: str
    verified: bool = False
    verification_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "quote": self.quote,
            "source_name": self.source_name,
            "verified": self.verified,
            "verification_error": self.verification_error,
        }


@dataclass
class ControlNature:
    """Non-ownership control mechanisms (voting rights, board seats, trusts).
    
    Rule #5: Control is strictly separate from economic ownership percentage.
    """
    has_significant_influence: bool = False
    voting_percentage_min: Optional[float] = None
    voting_percentage_max: Optional[float] = None
    right_to_appoint_directors: bool = False
    trustee_or_nominee: bool = False
    details: str = ""

    def is_controlled(self) -> bool:
        return (
            self.has_significant_influence
            or (self.voting_percentage_min is not None and self.voting_percentage_min > 25.0)
            or self.right_to_appoint_directors
            or self.trustee_or_nominee
            or bool(self.details)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_significant_influence": self.has_significant_influence,
            "voting_percentage_min": self.voting_percentage_min,
            "voting_percentage_max": self.voting_percentage_max,
            "right_to_appoint_directors": self.right_to_appoint_directors,
            "trustee_or_nominee": self.trustee_or_nominee,
            "details": self.details,
        }


@dataclass
class OwnershipEdge:
    """A single directed ownership link: owner -> owned_entity.
    
    Supports exact percentages or interval ranges (e.g., [25.0, 50.0]).
    """
    owner_id: str
    owner_name: str
    owner_type: EntityType
    owned_id: str
    percentage_min: float
    percentage_max: float
    evidence: Evidence
    is_lower_open: bool = False
    is_upper_open: bool = False
    control: Optional[ControlNature] = None
    is_disputed: bool = False
    dispute_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_range(self) -> bool:
        return self.percentage_min != self.percentage_max

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "owner_type": self.owner_type.value,
            "owned_id": self.owned_id,
            "percentage_min": self.percentage_min,
            "percentage_max": self.percentage_max,
            "is_lower_open": self.is_lower_open,
            "is_upper_open": self.is_upper_open,
            "is_disputed": self.is_disputed,
            "dispute_reason": self.dispute_reason,
            "evidence": self.evidence.to_dict(),
            "control": self.control.to_dict() if self.control else None,
            "metadata": self.metadata,
        }


@dataclass
class Entity:
    """An entity (node) in the corporate ownership graph."""
    id: str
    name: str
    entity_type: EntityType = EntityType.COMPANY
    jurisdiction: Optional[str] = None
    is_terminal: bool = False
    is_unresolved: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type.value,
            "jurisdiction": self.jurisdiction,
            "is_terminal": self.is_terminal,
            "is_unresolved": self.is_unresolved,
            "notes": self.notes,
        }


@dataclass
class OwnershipPath:
    """A single traversed path from a UBO candidate to the target entity."""
    path_nodes: List[str]  # e.g., ["Alice", "HoldCo", "TargetCorp"]
    edges: List[OwnershipEdge]
    effective_min: float   # Product of lower bounds along path
    effective_max: float   # Product of upper bounds along path
    is_lower_open: bool = False
    is_upper_open: bool = False

    @property
    def formula(self) -> str:
        factors_min = " * ".join(f"{e.percentage_min}%" for e in self.edges)
        factors_max = " * ".join(f"{e.percentage_max}%" for e in self.edges)
        if factors_min == factors_max:
            return factors_min
        return f"[{factors_min}] to [{factors_max}]"

    def formula_str(self) -> str:
        factors_min = " * ".join(f"{e.percentage_min}%" for e in self.edges)
        factors_max = " * ".join(f"{e.percentage_max}%" for e in self.edges)
        if factors_min == factors_max:
            return f"{' -> '.join(self.path_nodes)}: {factors_min} = {self.effective_min:.2f}%"
        return f"{' -> '.join(self.path_nodes)}: [{factors_min}] to [{factors_max}] = [{self.effective_min:.2f}%, {self.effective_max:.2f}%]"


@dataclass
class EffectiveOwnershipResult:
    """Final deterministically computed ownership for a specific candidate."""
    owner_id: str
    owner_name: str
    owner_type: EntityType
    effective_percentage_min: float
    effective_percentage_max: float
    status: UBOStatus
    paths: List[OwnershipPath]
    requires_human_review: bool
    review_reasons: List[str]
    is_lower_open: bool = False
    is_upper_open: bool = False
    control_flags: List[str] = field(default_factory=list)
    has_cycle: bool = False
    cycle_details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "owner_type": self.owner_type.value,
            "effective_percentage_min": round(self.effective_percentage_min, 4),
            "effective_percentage_max": round(self.effective_percentage_max, 4),
            "is_lower_open": self.is_lower_open,
            "is_upper_open": self.is_upper_open,
            "status": self.status.value,
            "paths": [
                {
                    "nodes": p.path_nodes,
                    "formula": p.formula_str(),
                    "min": round(p.effective_min, 4),
                    "max": round(p.effective_max, 4),
                }
                for p in self.paths
            ],
            "requires_human_review": self.requires_human_review,
            "review_reasons": self.review_reasons,
            "control_flags": self.control_flags,
            "has_cycle": self.has_cycle,
            "cycle_details": self.cycle_details,
        }

