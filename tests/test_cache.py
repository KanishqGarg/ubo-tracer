"""Unit tests for Entity Resolution Cache with TTL and staleness detection."""

import pytest
from datetime import datetime, timezone, timedelta
from ubo_tracer.cache import EntityCache


@pytest.fixture
def tmp_cache(tmp_path):
    db_file = tmp_path / "test_cache.db"
    return EntityCache(db_path=str(db_file), default_ttl_days=30)


def test_cache_set_and_get_fresh(tmp_cache):
    cache = tmp_cache
    edges = [{"owner_id": "alice_smith", "percentage_min": 60.0}]
    cache.set(
        entity_id="target_corp_1",
        entity_name="Target Corp 1 Ltd",
        entity_type="company",
        edges=edges,
        source_name="companies_house",
        ttl_days=30,
    )

    item = cache.get("target_corp_1")
    assert item is not None
    assert item.entity_name == "Target Corp 1 Ltd"
    assert item.is_stale is False
    assert len(item.edges) == 1


def test_cache_staleness_expiration(tmp_cache):
    cache = tmp_cache
    past_date = datetime.now(timezone.utc) - timedelta(days=40)
    cache.set(
        entity_id="target_corp_stale",
        entity_name="Old Stale Corp",
        entity_type="company",
        edges=[],
        source_name="companies_house",
        ttl_days=30,
        retrieved_at=past_date,
    )

    item = cache.get("target_corp_stale")
    assert item is not None
    assert item.is_stale is True  # 40 days old > 30 day TTL

