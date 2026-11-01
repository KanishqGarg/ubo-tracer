"""Durable Checkpoint and State Persistence for UBO Tracer Runs.

Persists full run state to SQLite after every step:
- Run ID, Target Entity ID, Current Status ('running', 'awaiting_review', 'completed', 'failed')
- Active BFS Queue (queue of entities to trace with depths)
- Visited Entity IDs and Retries map
- Verified Ownership Edges
- Extracted Entities & Types
- Pending Review Items (dead end, control flag, uncertain result, verifier rejection, or self-consistency dispute)
- Reviewer Decision Audit Log (timestamp, reviewer name, action, notes, supplied owner)

Supports Pause, Resume, Approve, Reject, and Manual Owner Supply.
"""

from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ReviewDecision(BaseModel):
    decision_id: str
    run_id: str
    item_id: str
    reviewer_name: str
    action: str  # 'approve', 'reject', 'supply_owner'
    notes: str = ""
    supplied_owner: Optional[Dict[str, Any]] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CheckpointStore:
    """SQLite-backed persistent checkpoint manager for UBO Tracer agent runs."""

    def __init__(self, db_path: str = "ubo_tracer/logs/checkpoints.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    queue_json TEXT NOT NULL,
                    visited_json TEXT NOT NULL,
                    retries_json TEXT NOT NULL,
                    edges_json TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    pending_reviews_json TEXT NOT NULL,
                    results_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_decisions (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    reviewer_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    notes TEXT,
                    supplied_owner_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                )
            """)
            conn.commit()

    def save_checkpoint(
        self,
        run_id: str,
        target_id: str,
        status: str,
        current_step: int,
        queue: List[Any],
        visited: List[str],
        retries: Dict[str, int],
        edges: List[Dict[str, Any]],
        entities: Dict[str, Dict[str, Any]],
        pending_reviews: List[Dict[str, Any]],
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO runs (
                    run_id, target_id, status, current_step,
                    queue_json, visited_json, retries_json,
                    edges_json, entities_json, pending_reviews_json,
                    results_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    current_step=excluded.current_step,
                    queue_json=excluded.queue_json,
                    visited_json=excluded.visited_json,
                    retries_json=excluded.retries_json,
                    edges_json=excluded.edges_json,
                    entities_json=excluded.entities_json,
                    pending_reviews_json=excluded.pending_reviews_json,
                    results_json=excluded.results_json,
                    updated_at=excluded.updated_at
            """, (
                run_id,
                target_id,
                status,
                current_step,
                json.dumps(queue),
                json.dumps(visited),
                json.dumps(retries),
                json.dumps(edges),
                json.dumps(entities),
                json.dumps(pending_reviews),
                json.dumps(results) if results is not None else None,
                now,
                now,
            ))
            conn.commit()

    def load_checkpoint(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "run_id": row["run_id"],
                "target_id": row["target_id"],
                "status": row["status"],
                "current_step": row["current_step"],
                "queue": json.loads(row["queue_json"]),
                "visited": json.loads(row["visited_json"]),
                "retries": json.loads(row["retries_json"]),
                "edges": json.loads(row["edges_json"]),
                "entities": json.loads(row["entities_json"]),
                "pending_reviews": json.loads(row["pending_reviews_json"]),
                "results": json.loads(row["results_json"]) if row["results_json"] else None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def record_decision(self, decision: ReviewDecision) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO review_decisions (
                    decision_id, run_id, item_id, reviewer_name,
                    action, notes, supplied_owner_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision.decision_id,
                decision.run_id,
                decision.item_id,
                decision.reviewer_name,
                decision.action,
                decision.notes,
                json.dumps(decision.supplied_owner) if decision.supplied_owner else None,
                decision.created_at,
            ))
            conn.commit()

    def get_decisions(self, run_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM review_decisions WHERE run_id = ? ORDER BY created_at ASC", (run_id,))
            rows = cursor.fetchall()
            return [
                {
                    "decision_id": r["decision_id"],
                    "run_id": r["run_id"],
                    "item_id": r["item_id"],
                    "reviewer_name": r["reviewer_name"],
                    "action": r["action"],
                    "notes": r["notes"],
                    "supplied_owner": json.loads(r["supplied_owner_json"]) if r["supplied_owner_json"] else None,
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def list_runs(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT run_id, target_id, status, current_step, created_at, updated_at FROM runs ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

