"""acpctl — CLI for Agent Control Plane."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="acpctl", help="Agent Control Plane CLI")
console = Console()

ACP_URL = os.getenv("ACP_URL", "http://localhost:8700")


def _client() -> httpx.Client:
    token = os.getenv("ACP_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=ACP_URL, headers=headers, timeout=10)


# ── scan ──


@app.command()
def scan():
    """Discover AI agents on this machine without requiring registration."""
    from .scanner import host_fingerprint, scan_all

    console.print("\n[bold blue]Scanning for AI entities...[/]\n")
    findings = scan_all()

    if not findings:
        console.print("[yellow]No AI entities detected.[/]")
        return

    with _client() as client:
        try:
            resp = client.get("/v1/agents")
            resp.raise_for_status()
            known_slugs = {a["slug"] for a in resp.json()}
        except httpx.HTTPError:
            known_slugs = set()

    category_order = ["agent", "app", "tool", "runtime", "sdk", "extension"]
    category_styles = {
        "agent": ("bold cyan", "AGENTS"),
        "app": ("bold magenta", "APPS"),
        "tool": ("bold yellow", "TOOLS"),
        "runtime": ("bold blue", "RUNTIMES"),
        "sdk": ("dim", "SDKS"),
        "extension": ("dim cyan", "EXTENSIONS"),
    }
    grouped: dict[str, list] = {}
    for f in findings:
        grouped.setdefault(f.kind, []).append(f)

    total_reg = 0
    total_unreg = 0

    for cat in category_order:
        items = grouped.get(cat, [])
        if not items:
            continue
        style, label = category_styles.get(cat, ("", cat.upper()))
        table = Table(title=f"{label} ({len(items)})", show_lines=False, title_style=style)
        table.add_column("", width=3)
        table.add_column("Name", style="cyan", min_width=20)
        table.add_column("Provider", width=12)
        table.add_column("Found via", width=14)
        table.add_column("Evidence")

        for f in sorted(items, key=lambda x: x.slug):
            is_reg = f.slug in known_slugs
            icon = "✅" if is_reg else "⚠️"
            if is_reg:
                total_reg += 1
            else:
                total_unreg += 1
            evidence_str = _short_evidence(f.evidence)
            table.add_row(icon, f.slug, f.provider or "—", f.scanner_type, evidence_str)

        console.print(table)
        console.print()

    console.print(
        f"[bold]Total: {len(findings)} entities | "
        f"[green]{total_reg} registered[/] | "
        f"[yellow]{total_unreg} unregistered[/][/]\n"
    )

    unreg = [f for f in findings if f.slug not in known_slugs]
    if unreg:
        if typer.confirm("Register unregistered entities?"):
            fp = host_fingerprint()
            with _client() as client:
                for f in unreg:
                    resp = client.post("/v1/agents/register", json={
                        "slug": f.slug,
                        "kind": f.kind,
                        "provider": f.provider,
                        "source": "scan",
                        "metadata": {"scanner_evidence": f.evidence, "host": fp},
                    })
                    if resp.status_code == 200:
                        console.print(f"  [green]✓[/] Registered {f.slug}")
                    else:
                        console.print(f"  [red]✗[/] Failed to register {f.slug}: {resp.text}")


def _short_evidence(evidence: dict) -> str:
    if "path" in evidence:
        return evidence["path"]
    if "container" in evidence:
        return f"{evidence['container']} ({evidence.get('image', '')})"
    if "env_var" in evidence:
        return evidence["env_var"]
    if "server_name" in evidence:
        return evidence["server_name"]
    if "package" in evidence:
        return f"{evidence['package']}=={evidence.get('version', '?')}"
    if "process_line" in evidence:
        return evidence["process_line"][:60]
    return json.dumps(evidence)[:60]


# ── list ──


@app.command(name="list")
def list_agents():
    """List all registered agents."""
    with _client() as client:
        resp = client.get("/v1/agents")
        resp.raise_for_status()
        agents = resp.json()

    if not agents:
        console.print("[yellow]No agents registered. Run 'acpctl scan' first.[/]")
        return

    table = Table(title="Registered Agents", show_lines=False)
    table.add_column("Agent", style="cyan bold")
    table.add_column("Owner")
    table.add_column("Kind")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Last Seen")
    table.add_column("Source")

    for a in agents:
        status_style = {
            "active": "[green]active[/]",
            "idle": "[yellow]idle[/]",
            "stale": "[red]stale[/]",
            "failed": "[red bold]FAILED[/]",
            "suspended": "[dim]suspended[/]",
        }.get(a["status"], a["status"])

        owner = a.get("owner_user") or a.get("owner_team") or "[red]???[/]"
        table.add_row(
            a["slug"], owner, a["kind"], a.get("provider") or "—",
            status_style, a["last_seen_at"][:19], a["source"],
        )

    console.print(table)
    unowned = sum(1 for a in agents if not a.get("owner_user") and not a.get("owner_team"))
    if unowned:
        console.print(f"\n[yellow]⚠️  {unowned} agent(s) have no owner assigned.[/]")


# ── register ──


@app.command()
def register(
    slug: str = typer.Argument(..., help="Unique agent identifier"),
    kind: str = typer.Option("cli", help="Agent kind: cli, desktop, service, mcp_server"),
    provider: str = typer.Option(None, help="Provider: anthropic, openai, google, local"),
    owner: str = typer.Option(None, help="Owner user or team"),
):
    """Manually register an agent."""
    with _client() as client:
        resp = client.post("/v1/agents/register", json={
            "slug": slug, "kind": kind, "provider": provider,
            "source": "manual", "owner_user": owner,
        })
        resp.raise_for_status()
        agent = resp.json()
    console.print(f"[green]✓[/] Registered [cyan]{slug}[/] (id: {agent['id'][:8]}...)")


# ── run ──


@app.command()
def run(
    cmd: list[str] = typer.Argument(..., help="Command to wrap"),
    slug: str = typer.Option(None, help="Agent slug (auto-detected if omitted)"),
):
    """Wrap an AI CLI with automatic register + heartbeat + report."""
    detected_slug = slug or _detect_slug(cmd)
    session_id = str(uuid4())

    with _client() as client:
        resp = client.post("/v1/agents/register", json={
            "slug": detected_slug, "source": "wrapper",
            "metadata": {"wrapped_cmd": " ".join(cmd)},
        })
        if resp.status_code != 200:
            console.print(f"[yellow]Warning: registration failed, running anyway[/]")
            _exec(cmd)
            return

        agent = resp.json()
        agent_id = agent["id"]

        client.post(f"/v1/agents/{agent_id}/events", json={
            "event_type": "session_start",
            "payload": {"session_id": session_id, "cmd": " ".join(cmd)},
        })

    stop_heartbeat = threading.Event()

    def heartbeat_loop():
        while not stop_heartbeat.is_set():
            try:
                with _client() as hb_client:
                    hb_client.post(f"/v1/agents/{agent_id}/heartbeat", json={
                        "session_id": session_id,
                    })
            except httpx.HTTPError:
                pass
            stop_heartbeat.wait(30)

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    start_time = time.time()
    result = _exec(cmd)
    duration = time.time() - start_time

    stop_heartbeat.set()
    hb_thread.join(timeout=2)

    with _client() as client:
        client.post(f"/v1/agents/{agent_id}/events", json={
            "event_type": "session_end",
            "payload": {
                "session_id": session_id,
                "exit_code": result,
                "duration_s": round(duration, 1),
            },
        })

    sys.exit(result)


def _detect_slug(cmd: list[str]) -> str:
    if not cmd:
        return "unknown"
    base = os.path.basename(cmd[0]).lower()
    slug_map = {
        "claude": "claude-code", "codex": "codex-cli",
        "gemini": "gemini-cli", "grok": "grok-build",
        "ollama": "ollama", "aider": "aider", "cursor": "cursor",
    }
    for key, slug in slug_map.items():
        if key in base:
            return slug
    return base


def _exec(cmd: list[str]) -> int:
    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        console.print(f"[red]Command not found: {cmd[0]}[/]")
        return 127


# ── audit ──


@app.command()
def audit(
    agent_slug: str = typer.Option(None, "--agent", help="Filter by agent slug"),
    limit: int = typer.Option(30, help="Number of events to show"),
):
    """View append-only audit event log."""
    with _client() as client:
        params: dict = {"limit": limit}
        if agent_slug:
            resp = client.get("/v1/agents")
            resp.raise_for_status()
            agent = next((a for a in resp.json() if a["slug"] == agent_slug), None)
            if not agent:
                console.print(f"[red]Agent '{agent_slug}' not found[/]")
                raise typer.Exit(1)
            params["agent_id"] = agent["id"]

        resp = client.get("/v1/audit-events", params=params)
        resp.raise_for_status()
        events = resp.json()

    if not events:
        console.print("[yellow]No audit events found.[/]")
        return

    table = Table(title="Audit Events", show_lines=False)
    table.add_column("Time", width=19)
    table.add_column("Type", style="cyan")
    table.add_column("Actor")
    table.add_column("Hash", width=12)
    table.add_column("Payload")

    for e in events:
        payload_str = json.dumps(e.get("payload", {}))[:60]
        table.add_row(
            e["occurred_at"][:19], e["event_type"],
            e.get("actor") or "—", e["hash_self"][:12],
            payload_str,
        )

    console.print(table)


# ── gaps ──


@app.command()
def gaps():
    """Show governance gaps — unowned, stale, or risky agents."""
    with _client() as client:
        resp = client.get("/v1/agents")
        resp.raise_for_status()
        agents = resp.json()

    if not agents:
        console.print("[yellow]No agents registered. Run 'acpctl scan' first.[/]")
        return

    issues = []
    for a in agents:
        if not a.get("owner_user") and not a.get("owner_team"):
            issues.append(("⚠️", a["slug"], "No owner assigned", "Assign owner or suspend"))
        if a["status"] in ("stale", "unknown"):
            issues.append(("⚠️", a["slug"], f"Status: {a['status']}", "Check if still needed"))
        if a.get("risk_profile") == "low" and a.get("max_permission_level") in ("L3", "L4"):
            issues.append((
                "🔴", a["slug"],
                f"Has {a['max_permission_level']} access but risk_profile=low",
                "Review permission or upgrade risk_profile",
            ))

    compliant = [a for a in agents if not any(i[1] == a["slug"] for i in issues)]

    if issues:
        table = Table(title="Governance Gaps", show_lines=False)
        table.add_column("", width=3)
        table.add_column("Agent", style="cyan")
        table.add_column("Issue")
        table.add_column("Recommendation", style="dim")
        for sev, slug, issue, rec in issues:
            table.add_row(sev, slug, issue, rec)
        console.print(table)

    for a in compliant:
        console.print(f"[green]✅[/] {a['slug']}: policy compliant")

    console.print(f"\n[bold]{len(issues)} issue(s), {len(compliant)} compliant[/]")


if __name__ == "__main__":
    app()
