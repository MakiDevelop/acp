# ACP — Agent Control Plane

**AI Production Governance.** Discover, register, and govern AI agents across your organization.

> Not the model. Not the agent. **The governance.**

## The Problem

Your team uses Claude Code, Codex CLI, Gemini, Cursor, custom bots, and who knows what else. **Nobody knows how many AI agents are running, who owns them, or what data they touch.**

ACP finds them for you — without requiring anyone to register anything.

## Quick Start

```bash
# Install
pip install -e .

# Discover agents on your machine (no server needed)
acpctl scan

# Start the control plane
docker compose up -d

# List registered agents
acpctl list

# View audit trail
acpctl audit

# Check governance gaps
acpctl gaps
```

## What It Does

- **Scan** — Auto-discovers AI agents by scanning configs, processes, Docker, env vars, MCP servers, and installed SDKs
- **Register** — Tracks agent identity, owner, permissions, and capabilities
- **Wrap** — `acpctl run -- codex exec ...` adds heartbeat + audit with zero code changes
- **Audit** — Append-only event log with hash-chain integrity (tamper-detectable)
- **Gaps** — Reports unowned agents, stale agents, and permission mismatches

## Architecture

Open `docs/architecture.html` in a browser for the full picture.

## License

Apache 2.0
