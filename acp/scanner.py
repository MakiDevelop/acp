"""Agent auto-discovery scanner — finds AI agents without requiring registration."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path


@dataclass
class ScanFinding:
    slug: str
    kind: str
    provider: str | None
    scanner_type: str
    evidence: dict = field(default_factory=dict)


def host_fingerprint() -> str:
    node = platform.node()
    machine = platform.machine()
    system = platform.system()
    return sha256(f"{node}:{machine}:{system}".encode()).hexdigest()[:16]


def scan_all() -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    findings.extend(scan_config_files())
    findings.extend(scan_processes())
    findings.extend(scan_docker())
    findings.extend(scan_env_vars())
    findings.extend(scan_mcp_config())
    findings.extend(scan_packages())
    return _deduplicate(findings)


def _deduplicate(findings: list[ScanFinding]) -> list[ScanFinding]:
    seen: dict[str, ScanFinding] = {}
    for f in findings:
        key = f"{f.slug}:{f.kind}"
        if key not in seen:
            seen[key] = f
        else:
            seen[key].evidence.update(f.evidence)
    return list(seen.values())


# ── Config File Scanner ──


def scan_config_files() -> list[ScanFinding]:
    findings = []
    home = Path.home()
    configs = [
        (home / ".claude", "claude-code", "cli", "anthropic"),
        (home / ".codex", "codex-cli", "cli", "openai"),
        (home / ".gemini", "gemini-cli", "cli", "google"),
        (home / ".cursor", "cursor", "desktop", "mixed"),
        (home / ".continue", "continue", "desktop", "mixed"),
        (home / ".grok", "grok-cli", "cli", "xai"),
        (home / ".aider.conf.yml", "aider", "cli", "mixed"),
        (home / ".github-copilot", "github-copilot", "desktop", "mixed"),
    ]
    for path, slug, kind, provider in configs:
        if path.exists():
            evidence = {"path": str(path), "exists": True}
            if path.is_dir():
                evidence["file_count"] = len(list(path.iterdir()))
            findings.append(ScanFinding(
                slug=slug, kind=kind, provider=provider,
                scanner_type="config_file", evidence=evidence,
            ))
    return findings


# ── Process Scanner ──


def scan_processes() -> list[ScanFinding]:
    findings = []
    patterns = [
        (r"ollama\s+serve", "ollama", "service", "local"),
        (r"mcp-server", "mcp-server", "mcp_server", None),
        (r"uvicorn.*erika", "erika-bot", "service", None),
        (r"node.*claude", "claude-desktop", "desktop", "anthropic"),
    ]
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            for pattern, slug, kind, provider in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(ScanFinding(
                        slug=slug, kind=kind, provider=provider,
                        scanner_type="process",
                        evidence={"process_line": line.strip()[:200]},
                    ))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return findings


# ── Docker Scanner ──


def scan_docker() -> list[ScanFinding]:
    findings = []
    if not shutil.which("docker"):
        return findings
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                name, image = parts[0], parts[1]
                status = parts[2] if len(parts) > 2 else "unknown"
                ai_keywords = ["agent", "bot", "llm", "ai", "chat", "erika", "mcp"]
                if any(kw in name.lower() or kw in image.lower() for kw in ai_keywords):
                    findings.append(ScanFinding(
                        slug=name, kind="service", provider=None,
                        scanner_type="docker",
                        evidence={"container": name, "image": image, "status": status},
                    ))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return findings


# ── Environment Variable Scanner ──


def scan_env_vars() -> list[ScanFinding]:
    findings = []
    env_map = [
        ("ANTHROPIC_API_KEY", "anthropic-api", "anthropic"),
        ("OPENAI_API_KEY", "openai-api", "openai"),
        ("GOOGLE_API_KEY", "google-api", "google"),
        ("GEMINI_API_KEY", "gemini-api", "google"),
        ("XAI_API_KEY", "xai-api", "xai"),
        ("GROQ_API_KEY", "groq-api", "groq"),
        ("OLLAMA_HOST", "ollama-local", "local"),
    ]
    for env_var, slug, provider in env_map:
        if os.getenv(env_var):
            findings.append(ScanFinding(
                slug=slug, kind="api_key", provider=provider,
                scanner_type="env_var",
                evidence={"env_var": env_var, "is_set": True},
            ))
    return findings


# ── MCP Config Scanner ──


def scan_mcp_config() -> list[ScanFinding]:
    findings = []
    config_paths = [
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.local.json",
    ]
    for config_path in config_paths:
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text())
            servers = data.get("mcpServers", {})
            for server_name, server_config in servers.items():
                cmd = server_config.get("command", "")
                findings.append(ScanFinding(
                    slug=f"mcp-{server_name}", kind="mcp_server", provider=None,
                    scanner_type="mcp_config",
                    evidence={
                        "server_name": server_name,
                        "command": cmd,
                        "config_file": str(config_path),
                    },
                ))
        except (json.JSONDecodeError, KeyError):
            pass
    return findings


# ── Package Scanner ──


def scan_packages() -> list[ScanFinding]:
    findings = []
    if not shutil.which("pip"):
        return findings
    try:
        result = subprocess.run(
            ["pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=15,
        )
        packages = json.loads(result.stdout)
        sdk_map = {
            "anthropic": ("anthropic-sdk", "anthropic"),
            "openai": ("openai-sdk", "openai"),
            "google-generativeai": ("google-genai-sdk", "google"),
            "google-genai": ("google-genai-sdk", "google"),
            "langchain": ("langchain", "mixed"),
            "crewai": ("crewai", "mixed"),
            "autogen": ("autogen", "mixed"),
        }
        for pkg in packages:
            name = pkg["name"].lower()
            if name in sdk_map:
                slug, provider = sdk_map[name]
                findings.append(ScanFinding(
                    slug=slug, kind="sdk", provider=provider,
                    scanner_type="package",
                    evidence={"package": pkg["name"], "version": pkg["version"]},
                ))
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return findings
