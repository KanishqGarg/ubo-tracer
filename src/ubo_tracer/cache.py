"""Entity resolution cache with time-to-live (TTL) and source freshness tracking.

Handles the 'knowledge is no longer valid' problem in compliance investigations:
- Caches extracted corporate ownership edges, entity metadata, and verification results
- Stores source retrieval date and expiration timestamp
- Flags stale data for human re-verification
"""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class CachedEntity(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    edges: List[Dict[str, Any]]
    source_name: str
    retrieved_at: str
    expires_at: str
    is_stale: bool = False


class EntityCache:
    """Thread-safe SQLite persistent cache for resolved entities."""

    def __init__(self, db_path: str = "ubo_tracer/logs/entity_cache.db", default_ttl_days: int = 30):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_ttl = timedelta(days=default_ttl_days)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_cache (
                    entity_id TEXT PRIMARY KEY,
                    entity_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    edges_json TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def set(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        edges: List[Dict[str, Any]],
        source_name: str,
        ttl_days: Optional[int] = None,
        retrieved_at: Optional[datetime] = None,
    ) -> None:
        now = retrieved_at or datetime.now(timezone.utc)
        ttl = timedelta(days=ttl_days) if ttl_days is not None else self.default_ttl
        expires = now + ttl

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO entity_cache (
                    entity_id, entity_name, entity_type, edges_json,
                    source_name, retrieved_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    entity_name=excluded.entity_name,
                    entity_type=excluded.entity_type,
                    edges_json=excluded.edges_json,
                    source_name=excluded.source_name,
                    retrieved_at=excluded.retrieved_at,
                    expires_at=excluded.expires_at
            """, (
                entity_id,
                entity_name,
                entity_type,
                json.dumps(edges),
                source_name,
                now.isoformat(),
                expires.isoformat(),
            ))
            conn.commit()

    def get(self, entity_id: str) -> Optional[CachedEntity]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM entity_cache WHERE entity_id = ?", (entity_id,))
            row = cursor.fetchone()
            if not row:
                return None

            now = datetime.now(timezone.utc)
            expires_at = datetime.fromisoformat(row["expires_at"])
            is_stale = now > expires_at

            return CachedEntity(
                entity_id=row["entity_id"],
                entity_name=row["entity_name"],
                entity_type=row["entity_type"],
                edges=json.loads(row["edges_json"]),
                source_name=row["source_name"],
                retrieved_at=row["retrieved_at"],
                expires_at=row["expires_at"],
                is_stale=is_stale,
            )

    def list_all(self) -> List[CachedEntity]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM entity_cache ORDER BY retrieved_at DESC")
            now = datetime.now(timezone.utc)
            results = []
            for row in cursor.fetchall():
                expires_at = datetime.fromisoformat(row["expires_at"])
                results.append(
                    CachedEntity(
                        entity_id=row["entity_id"],
                        entity_name=row["entity_name"],
                        entity_type=row["entity_type"],
                        edges=json.loads(row["edges_json"]),
                        source_name=row["source_name"],
                        retrieved_at=row["retrieved_at"],
                        expires_at=row["expires_at"],
                        is_stale=now > expires_at,
                    )
                )
            return results

