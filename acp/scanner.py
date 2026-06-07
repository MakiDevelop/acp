"""Agent auto-discovery scanner — finds AI entities without requiring registration."""

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

CATEGORIES = ("agent", "app", "tool", "runtime", "sdk", "extension")


@dataclass
class ScanFinding:
    slug: str
    kind: str  # agent, app, tool, runtime, sdk, extension
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
    findings.extend(scan_mcp_config())
    findings.extend(scan_processes())
    findings.extend(scan_docker())
    findings.extend(scan_env_vars())
    findings.extend(scan_pip_packages())
    findings.extend(scan_npm_packages())
    findings.extend(scan_vscode_extensions())
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

    agents = [
        (home / ".claude", "claude-code", "agent", "anthropic"),
        (home / ".codex", "codex-cli", "agent", "openai"),
        (home / ".gemini", "gemini-cli", "agent", "google"),
        (home / ".grok", "grok-cli", "agent", "xai"),
        (home / ".aider.conf.yml", "aider", "agent", "mixed"),
    ]
    apps = [
        (home / ".cursor", "cursor", "app", "mixed"),
        (home / ".continue", "continue", "app", "mixed"),
        (home / ".github-copilot", "github-copilot", "app", "mixed"),
        (home / "Library/Application Support/Claude", "claude-desktop", "app", "anthropic"),
        (home / "Library/Application Support/com.openai.chat", "chatgpt-desktop", "app", "openai"),
        (home / ".lmstudio", "lm-studio", "app", "local"),
    ]
    runtimes = [
        (home / ".ollama", "ollama", "runtime", "local"),
    ]

    for entries in (agents, apps, runtimes):
        for path, slug, kind, provider in entries:
            if path.exists():
                evidence = {"path": str(path), "exists": True}
                if path.is_dir():
                    try:
                        evidence["file_count"] = sum(1 for _ in path.iterdir())
                    except PermissionError:
                        evidence["file_count"] = "permission_denied"
                findings.append(ScanFinding(
                    slug=slug, kind=kind, provider=provider,
                    scanner_type="config_file", evidence=evidence,
                ))
    return findings


# ── MCP Config Scanner (individual servers as tools) ──


def scan_mcp_config() -> list[ScanFinding]:
    findings = []
    config_paths = [
        Path.home() / ".claude" / ".mcp.json",
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.local.json",
    ]
    seen_servers: set[str] = set()

    for config_path in config_paths:
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text())
            servers = data.get("mcpServers", {})
            for server_name, server_config in servers.items():
                if server_name in seen_servers:
                    continue
                seen_servers.add(server_name)
                cmd = server_config.get("command", "")
                args = server_config.get("args", [])
                provider = _infer_mcp_provider(server_name, cmd, args)
                findings.append(ScanFinding(
                    slug=f"mcp/{server_name}",
                    kind="tool",
                    provider=provider,
                    scanner_type="mcp_config",
                    evidence={
                        "server_name": server_name,
                        "command": cmd,
                        "args": args[:3],
                        "config_file": str(config_path),
                    },
                ))
        except (json.JSONDecodeError, KeyError):
            pass
    return findings


def _infer_mcp_provider(name: str, cmd: str, args: list) -> str | None:
    combined = f"{name} {cmd} {' '.join(str(a) for a in args)}".lower()
    if "google" in combined or "workspace" in combined or "analytics" in combined:
        return "google"
    if "anthropic" in combined or "claude" in combined:
        return "anthropic"
    if "openai" in combined or "codex" in combined:
        return "openai"
    if "gemini" in combined:
        return "google"
    if "playwright" in combined:
        return None
    return None


# ── Process Scanner ──


def scan_processes() -> list[ScanFinding]:
    findings = []
    patterns = [
        (r"ollama\s+serve", "ollama", "runtime", "local"),
        (r"ollama\s+run", "ollama", "runtime", "local"),
        (r"vllm\.entrypoints", "vllm", "runtime", "local"),
        (r"text-generation-launcher", "tgi", "runtime", "huggingface"),
        (r"SkyComputerUseClient", "codex-computer-use", "agent", "openai"),
        (r"Claude\.app.*MacOS/Claude\b", "claude-desktop", "app", "anthropic"),
        (r"com\.openai\.chat", "chatgpt-desktop", "app", "openai"),
        (r"LM Studio", "lm-studio", "app", "local"),
    ]
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            for pattern, slug, kind, provider in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    cmd_part = line.split(None, 10)[-1] if len(line.split()) > 10 else line
                    findings.append(ScanFinding(
                        slug=slug, kind=kind, provider=provider,
                        scanner_type="process",
                        evidence={"command": cmd_part[:120]},
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
        ai_keywords = ["agent", "bot", "llm", "ai", "chat", "erika", "mcp",
                        "ollama", "vllm", "tgi", "openai", "anthropic"]
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name, image = parts[0], parts[1]
            status = parts[2] if len(parts) > 2 else "unknown"
            if any(kw in name.lower() or kw in image.lower() for kw in ai_keywords):
                findings.append(ScanFinding(
                    slug=name, kind="agent", provider=None,
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
        ("MISTRAL_API_KEY", "mistral-api", "mistral"),
        ("COHERE_API_KEY", "cohere-api", "cohere"),
        ("REPLICATE_API_TOKEN", "replicate-api", "replicate"),
        ("HUGGINGFACE_TOKEN", "huggingface-api", "huggingface"),
        ("HF_TOKEN", "huggingface-api", "huggingface"),
        ("TOGETHER_API_KEY", "together-api", "together"),
        ("OLLAMA_HOST", "ollama-custom-host", "local"),
    ]
    for env_var, slug, provider in env_map:
        if os.getenv(env_var):
            findings.append(ScanFinding(
                slug=slug, kind="sdk", provider=provider,
                scanner_type="env_var",
                evidence={"env_var": env_var, "is_set": True},
            ))
    return findings


# ── Pip Package Scanner ──


def scan_pip_packages() -> list[ScanFinding]:
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
            "anthropic": ("anthropic", "anthropic"),
            "openai": ("openai", "openai"),
            "google-generativeai": ("google-genai", "google"),
            "google-genai": ("google-genai", "google"),
            "langchain": ("langchain", "mixed"),
            "langchain-core": ("langchain", "mixed"),
            "crewai": ("crewai", "mixed"),
            "autogen": ("autogen", "mixed"),
            "transformers": ("transformers", "huggingface"),
            "sentence-transformers": ("sentence-transformers", "huggingface"),
            "huggingface-hub": ("huggingface-hub", "huggingface"),
            "torch": ("pytorch", "meta"),
            "tensorflow": ("tensorflow", "google"),
            "jax": ("jax", "google"),
            "cohere": ("cohere", "cohere"),
            "mistralai": ("mistral", "mistral"),
            "groq": ("groq", "groq"),
            "replicate": ("replicate", "replicate"),
            "together": ("together", "together"),
            "llama-index": ("llama-index", "mixed"),
            "dspy": ("dspy", "mixed"),
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


# ── npm Package Scanner ──


def scan_npm_packages() -> list[ScanFinding]:
    findings = []
    if not shutil.which("npm"):
        return findings
    try:
        result = subprocess.run(
            ["npm", "list", "-g", "--depth=0", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        deps = data.get("dependencies", {})
        npm_map = {
            "@anthropic-ai/sdk": ("anthropic-npm", "sdk", "anthropic"),
            "@google/gemini-cli": ("gemini-cli-npm", "agent", "google"),
            "@openai/codex": ("codex-cli-npm", "agent", "openai"),
            "openai": ("openai-npm", "sdk", "openai"),
        }
        for pkg_name, pkg_info in deps.items():
            if pkg_name in npm_map:
                slug, kind, provider = npm_map[pkg_name]
                version = pkg_info.get("version", "?")
                findings.append(ScanFinding(
                    slug=slug, kind=kind, provider=provider,
                    scanner_type="npm_package",
                    evidence={"package": pkg_name, "version": version},
                ))
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return findings


# ── VS Code Extension Scanner ──


def scan_vscode_extensions() -> list[ScanFinding]:
    findings = []
    ext_dirs = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-insiders" / "extensions",
        Path.home() / ".cursor" / "extensions",
    ]
    ext_map = {
        "github.copilot": ("github-copilot", "extension", "github"),
        "github.copilot-chat": ("github-copilot-chat", "extension", "github"),
        "anthropic.claude-code": ("claude-code-ext", "extension", "anthropic"),
        "openai.chatgpt": ("chatgpt-ext", "extension", "openai"),
        "codeium.codeium": ("codeium", "extension", "codeium"),
        "supermaven.supermaven": ("supermaven", "extension", "supermaven"),
        "continue.continue": ("continue-ext", "extension", "mixed"),
        "tabnine.tabnine-vscode": ("tabnine", "extension", "tabnine"),
        "amazonwebservices.amazon-q-vscode": ("amazon-q", "extension", "aws"),
    }
    for ext_dir in ext_dirs:
        if not ext_dir.exists():
            continue
        try:
            for item in ext_dir.iterdir():
                name_lower = item.name.lower()
                for ext_prefix, (slug, kind, provider) in ext_map.items():
                    if name_lower.startswith(ext_prefix.lower()):
                        version = name_lower.replace(ext_prefix.lower() + "-", "").split("-")[0]
                        findings.append(ScanFinding(
                            slug=slug, kind=kind, provider=provider,
                            scanner_type="vscode_extension",
                            evidence={
                                "extension": ext_prefix,
                                "version": version,
                                "path": str(item),
                                "ide": ext_dir.parent.name,
                            },
                        ))
                        break
        except PermissionError:
            pass
    return findings
