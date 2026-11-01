"""Unit tests for Durable SQLite Checkpoints and HITL Reviewer Decisions."""

import os
import pytest
from ubo_tracer.checkpoint import CheckpointStore, ReviewDecision


@pytest.fixture
def tmp_checkpoint_db(tmp_path):
    db_file = tmp_path / "test_checkpoints.db"
    return CheckpointStore(db_path=str(db_file))


def test_checkpoint_save_and_load(tmp_checkpoint_db):
    store = tmp_checkpoint_db
    store.save_checkpoint(
        run_id="run_101",
        target_id="target_corp_1",
        status="awaiting_review",
        current_step=3,
        queue=[{"entity_id": "tier2_ltd", "depth": 1}],
        visited=["target_corp_1"],
        retries={"target_corp_1": 0},
        edges=[{"owner_id": "tier2_ltd", "owned_id": "target_corp_1", "percentage_min": 50.0}],
        entities={"target_corp_1": {"name": "Target Corp 1", "entity_type": "company"}},
        pending_reviews=[{
            "item_id": "rev_01",
            "type": "dead_end",
            "entity_id": "tier2_ltd",
            "reason": "Missing owner records"
        }]
    )

    data = store.load_checkpoint("run_101")
    assert data is not None
    assert data["run_id"] == "run_101"
    assert data["status"] == "awaiting_review"
    assert data["current_step"] == 3
    assert len(data["pending_reviews"]) == 1
    assert data["pending_reviews"][0]["item_id"] == "rev_01"


def test_record_reviewer_decision(tmp_checkpoint_db):
    store = tmp_checkpoint_db
    store.save_checkpoint(
        run_id="run_102",
        target_id="target_corp_8",
        status="awaiting_review",
        current_step=2,
        queue=[],
        visited=["target_corp_8"],
        retries={},
        edges=[],
        entities={},
        pending_reviews=[{"item_id": "rev_phantom", "type": "dead_end", "entity_id": "phantom_ltd"}]
    )

    decision = ReviewDecision(
        decision_id="dec_01",
        run_id="run_102",
        item_id="rev_phantom",
        reviewer_name="Jane Senior Compliance Officer",
        action="supply_owner",
        notes="Verified via off-line registry certificate dated Oct 2026",
        supplied_owner={"owner_name": "Verified Ultimate Parent", "percentage": 100.0}
    )
    store.record_decision(decision)

    decisions = store.get_decisions("run_102")
    assert len(decisions) == 1
    assert decisions[0]["reviewer_name"] == "Jane Senior Compliance Officer"
    assert decisions[0]["action"] == "supply_owner"
    assert decisions[0]["supplied_owner"]["percentage"] == 100.0

