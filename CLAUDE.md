# ACP — Agent Control Plane

## Project Overview
AI Production Governance tool. Discovers, registers, and governs AI agents across an organization.

Core value: "You don't know how many agents you have. ACP finds them for you."

## Tech Stack
- **Language**: Python 3.12+
- **API**: FastAPI + uvicorn
- **DB**: PostgreSQL 16
- **CLI**: typer
- **Deployment**: Docker Compose (api + postgres)
- **License**: Apache 2.0

## Project Structure
```
acp/
├── server.py      # FastAPI app
├── models.py      # Pydantic models (request/response)
├── db.py          # Async database layer (asyncpg)
├── scanner.py     # Agent auto-discovery (acpctl scan)
├── audit.py       # Append-only audit trail with hash chain
└── cli.py         # acpctl CLI (typer)
```

## Development
```bash
docker compose up -d          # Start API + Postgres
pip install -e ".[dev]"       # Install for local dev
acpctl scan                   # Discover local agents
acpctl list                   # List registered agents
```

## Key Design Decisions
- Metadata only — never capture prompt content (PII/secrets risk)
- Append-only audit — hash chain for tamper detection
- Zero intrusion — wrapper approach, agents don't know ACP exists
- Scan first — active discovery before manual registration
- Vendor agnostic — any AI CLI, any model, any framework

## Testing
```bash
pytest tests/
```

## Git Conventions
- Commit messages in English (OSS project)
- Conventional commits: feat/fix/docs/test/chore
