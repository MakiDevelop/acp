"""ACP API Server — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import db
from .models import (
    AgentOut,
    AgentRegister,
    AuditEventOut,
    EventIn,
    HeartbeatIn,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.get_pool()
    yield
    await db.close_pool()


app = FastAPI(
    title="ACP — Agent Control Plane",
    description="AI Production Governance",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return html_path.read_text()


@app.post("/v1/agents/register", response_model=AgentOut)
async def register_agent(body: AgentRegister):
    agent = await db.upsert_agent(
        slug=body.slug,
        display_name=body.display_name,
        kind=body.kind,
        provider=body.provider,
        source=body.source,
        owner_user=body.owner_user,
        owner_team=body.owner_team,
        metadata=body.metadata,
    )
    await db.append_audit_event(
        event_type="registered",
        agent_id=agent["id"],
        actor=body.owner_user,
        payload={"slug": body.slug, "source": body.source},
    )
    return agent


@app.get("/v1/agents", response_model=list[AgentOut])
async def list_agents():
    return await db.list_agents()


@app.get("/v1/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: UUID):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@app.post("/v1/agents/{agent_id}/heartbeat")
async def heartbeat(agent_id: UUID, body: HeartbeatIn):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    instance_id = await db.record_heartbeat(
        agent_id=agent_id,
        host_fingerprint=body.host_fingerprint,
        workspace=body.workspace,
        session_id=body.session_id,
        metadata=body.metadata,
    )
    return {"status": "ok", "instance_id": str(instance_id)}


@app.post("/v1/agents/{agent_id}/events", response_model=AuditEventOut)
async def report_event(agent_id: UUID, body: EventIn):
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    event = await db.append_audit_event(
        event_type=body.event_type,
        agent_id=agent_id,
        instance_id=body.instance_id,
        actor=body.actor,
        payload=body.payload,
    )
    return event


@app.get("/v1/audit-events", response_model=list[AuditEventOut])
async def list_audit_events(agent_id: UUID | None = None, limit: int = 50):
    return await db.list_audit_events(agent_id=agent_id, limit=limit)
