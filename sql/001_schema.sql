-- ACP Schema v1 — Agent Control Plane
-- Core tables for agent registry, instances, capabilities, and audit trail

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Agent registry: one row per logical agent
CREATE TABLE agents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                TEXT UNIQUE NOT NULL,
    display_name        TEXT NOT NULL,
    owner_user          TEXT,
    owner_team          TEXT,
    kind                TEXT NOT NULL DEFAULT 'cli',
    provider            TEXT,
    model_allowlist     TEXT[],
    tool_allowlist      TEXT[],
    max_permission_level TEXT DEFAULT 'L0',
    risk_profile        TEXT DEFAULT 'low',
    status              TEXT DEFAULT 'unknown',
    source              TEXT NOT NULL DEFAULT 'manual',
    first_seen_at       TIMESTAMPTZ DEFAULT now(),
    last_seen_at        TIMESTAMPTZ DEFAULT now(),
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

COMMENT ON COLUMN agents.kind IS 'cli, desktop, service, workflow, mcp_server';
COMMENT ON COLUMN agents.provider IS 'anthropic, openai, google, local, xai, mixed';
COMMENT ON COLUMN agents.max_permission_level IS 'L0=public, L1=internal, L2=customer, L3=financial, L4=production';
COMMENT ON COLUMN agents.risk_profile IS 'low, medium, high, critical';
COMMENT ON COLUMN agents.status IS 'active, idle, failed, suspended, unknown';
COMMENT ON COLUMN agents.source IS 'manual, wrapper, scan, otel, sdk, import';

-- Agent instances: one row per runtime session
CREATE TABLE agent_instances (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    host_fingerprint    TEXT,
    repo_path_hash      TEXT,
    workspace           TEXT,
    process_kind        TEXT,
    runtime_version     TEXT,
    session_id          TEXT,
    started_at          TIMESTAMPTZ DEFAULT now(),
    last_heartbeat_at   TIMESTAMPTZ DEFAULT now(),
    ended_at            TIMESTAMPTZ,
    status              TEXT DEFAULT 'running',
    metadata            JSONB DEFAULT '{}'
);

CREATE INDEX idx_instances_agent ON agent_instances(agent_id);
CREATE INDEX idx_instances_heartbeat ON agent_instances(last_heartbeat_at);

-- Agent capabilities: what tools/models/permissions an agent has
CREATE TABLE agent_capabilities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability_type     TEXT NOT NULL,
    capability_name     TEXT NOT NULL,
    permission_level    TEXT,
    constraints         JSONB DEFAULT '{}',
    discovered_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_id, capability_type, capability_name)
);

COMMENT ON COLUMN agent_capabilities.capability_type IS 'model, tool, memory, filesystem, network, deploy';

CREATE INDEX idx_capabilities_agent ON agent_capabilities(agent_id);

-- Audit events: append-only with hash chain
CREATE TABLE audit_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID,
    instance_id         UUID,
    event_type          TEXT NOT NULL,
    actor               TEXT,
    occurred_at         TIMESTAMPTZ DEFAULT now(),
    hash_prev           TEXT NOT NULL,
    hash_self           TEXT NOT NULL,
    payload             JSONB DEFAULT '{}'
);

COMMENT ON COLUMN audit_events.event_type IS 'registered, heartbeat, session_start, session_end, tool_seen, policy_changed, scan_discovered, scan_disappeared';

CREATE INDEX idx_audit_agent ON audit_events(agent_id);
CREATE INDEX idx_audit_time ON audit_events(occurred_at);
CREATE INDEX idx_audit_type ON audit_events(event_type);

-- Scan results: track what was found during each scan
CREATE TABLE scan_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id             UUID NOT NULL,
    scanned_at          TIMESTAMPTZ DEFAULT now(),
    scanner_type        TEXT NOT NULL,
    host_fingerprint    TEXT,
    detected_slug       TEXT,
    detected_kind       TEXT,
    detected_provider   TEXT,
    evidence            JSONB NOT NULL,
    matched_agent_id    UUID REFERENCES agents(id),
    status              TEXT DEFAULT 'new',
    metadata            JSONB DEFAULT '{}'
);

COMMENT ON COLUMN scan_results.scanner_type IS 'config_file, process, docker, env_var, shell_history, package, mcp_config';
COMMENT ON COLUMN scan_results.status IS 'new, matched, ignored, registered';

CREATE INDEX idx_scan_id ON scan_results(scan_id);
CREATE INDEX idx_scan_slug ON scan_results(detected_slug);
