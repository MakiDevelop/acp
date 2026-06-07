"""Database layer for ACP — asyncpg + PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

_pool: asyncpg.Pool | None = None


def _dsn() -> str:
    return os.getenv("DATABASE_URL", "postgresql://acp:acp@localhost:5432/acp")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(_dsn(), min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Agents ──


async def upsert_agent(
    slug: str,
    display_name: str | None = None,
    kind: str = "cli",
    provider: str | None = None,
    source: str = "manual",
    owner_user: str | None = None,
    owner_team: str | None = None,
    metadata: dict | None = None,
) -> dict:
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    name = display_name or slug
    meta = json.dumps(metadata or {})

    row = await pool.fetchrow(
        """
        INSERT INTO agents (slug, display_name, kind, provider, source,
                            owner_user, owner_team, first_seen_at, last_seen_at, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $9::jsonb)
        ON CONFLICT (slug) DO UPDATE SET
            last_seen_at = $8,
            updated_at = $8,
            status = CASE WHEN agents.status = 'unknown' THEN 'active' ELSE agents.status END,
            metadata = COALESCE(agents.metadata, '{}') || $9::jsonb
        RETURNING *
        """,
        slug, name, kind, provider, source, owner_user, owner_team, now, meta,
    )
    return dict(row)


async def list_agents() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM agents ORDER BY last_seen_at DESC")
    return [dict(r) for r in rows]


async def get_agent(agent_id: UUID) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    return dict(row) if row else None


async def get_agent_by_slug(slug: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM agents WHERE slug = $1", slug)
    return dict(row) if row else None


async def update_agent_status(agent_id: UUID, status: str):
    pool = await get_pool()
    await pool.execute(
        "UPDATE agents SET status = $1, updated_at = now() WHERE id = $2",
        status, agent_id,
    )


# ── Heartbeat ──


async def record_heartbeat(
    agent_id: UUID,
    host_fingerprint: str | None = None,
    workspace: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> UUID:
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    meta = json.dumps(metadata or {})

    instance_id = await pool.fetchval(
        """
        INSERT INTO agent_instances (agent_id, host_fingerprint, workspace, session_id,
                                      last_heartbeat_at, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        agent_id, host_fingerprint, workspace, session_id, now, meta,
    )

    if instance_id is None:
        instance_id = await pool.fetchval(
            """
            UPDATE agent_instances SET last_heartbeat_at = $1, metadata = metadata || $2::jsonb
            WHERE agent_id = $3 AND session_id = $4
            RETURNING id
            """,
            now, meta, agent_id, session_id,
        )

    await pool.execute(
        "UPDATE agents SET last_seen_at = $1, status = 'active', updated_at = $1 WHERE id = $2",
        now, agent_id,
    )
    return instance_id


# ── Audit Events ──


def _compute_hash(hash_prev: str, payload: dict, occurred_at: str) -> str:
    raw = f"{hash_prev}:{json.dumps(payload, sort_keys=True)}:{occurred_at}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def append_audit_event(
    event_type: str,
    agent_id: UUID | None = None,
    instance_id: UUID | None = None,
    actor: str | None = None,
    payload: dict | None = None,
) -> dict:
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    payload = payload or {}

    prev = await pool.fetchval(
        "SELECT hash_self FROM audit_events ORDER BY occurred_at DESC LIMIT 1"
    )
    hash_prev = prev or "GENESIS"
    hash_self = _compute_hash(hash_prev, payload, now.isoformat())

    row = await pool.fetchrow(
        """
        INSERT INTO audit_events (agent_id, instance_id, event_type, actor,
                                   occurred_at, hash_prev, hash_self, payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        RETURNING *
        """,
        agent_id, instance_id, event_type, actor,
        now, hash_prev, hash_self, json.dumps(payload),
    )
    return dict(row)


async def list_audit_events(
    agent_id: UUID | None = None,
    limit: int = 50,
) -> list[dict]:
    pool = await get_pool()
    if agent_id:
        rows = await pool.fetch(
            "SELECT * FROM audit_events WHERE agent_id = $1 ORDER BY occurred_at DESC LIMIT $2",
            agent_id, limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]


# ── Scan Results ──


async def save_scan_result(
    scan_id: UUID,
    scanner_type: str,
    host_fingerprint: str,
    detected_slug: str,
    detected_kind: str,
    detected_provider: str | None,
    evidence: dict,
    matched_agent_id: UUID | None = None,
) -> dict:
    pool = await get_pool()
    status = "matched" if matched_agent_id else "new"
    row = await pool.fetchrow(
        """
        INSERT INTO scan_results (scan_id, scanner_type, host_fingerprint,
                                   detected_slug, detected_kind, detected_provider,
                                   evidence, matched_agent_id, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
        RETURNING *
        """,
        scan_id, scanner_type, host_fingerprint,
        detected_slug, detected_kind, detected_provider,
        json.dumps(evidence), matched_agent_id, status,
    )
    return dict(row)
