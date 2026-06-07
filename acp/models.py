"""Pydantic models for ACP API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentRegister(BaseModel):
    slug: str = Field(..., description="Unique human-readable identifier")
    display_name: str | None = None
    kind: str = "cli"
    provider: str | None = None
    source: str = "manual"
    owner_user: str | None = None
    owner_team: str | None = None
    host_fingerprint: str | None = None
    workspace: str | None = None
    metadata: dict | None = None


class AgentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    slug: str
    display_name: str
    kind: str
    provider: str | None = None
    owner_user: str | None = None
    owner_team: str | None = None
    status: str = "unknown"
    source: str = "manual"
    max_permission_level: str = "L0"
    risk_profile: str = "low"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    metadata: dict | None = None
    model_allowlist: list[str] | None = None
    tool_allowlist: list[str] | None = None


class HeartbeatIn(BaseModel):
    instance_id: UUID | None = None
    host_fingerprint: str | None = None
    workspace: str | None = None
    session_id: str | None = None
    metadata: dict | None = None


class EventIn(BaseModel):
    event_type: str
    actor: str | None = None
    payload: dict = Field(default_factory=dict)
    instance_id: UUID | None = None


class AuditEventOut(BaseModel):
    id: UUID
    agent_id: UUID | None
    event_type: str
    actor: str | None
    occurred_at: datetime
    hash_self: str
    payload: dict


class ScanResultOut(BaseModel):
    detected_slug: str
    detected_kind: str
    detected_provider: str | None
    scanner_type: str
    evidence: dict
    matched_agent_id: UUID | None
    status: str


class ScanReport(BaseModel):
    scan_id: UUID
    scanned_at: datetime
    host_fingerprint: str
    total_found: int
    registered: int
    unregistered: int
    results: list[ScanResultOut]
