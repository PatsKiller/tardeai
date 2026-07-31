#!/usr/bin/env python3
"""Install missing FLEET-linked OpenClaw personas (read-only advisory critics).

Adds sentinel, darwin, concierge, risk_agent to ~/.openclaw/openclaw.json with
workspace + SOUL/IDENTITY files scoped to the governed FLEET contract.
No Telegram routing is added unless --bind-telegram is passed.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "config" / "openclaw_fleet_personas"

PERSONAS = (
    {
        "id": "sentinel",
        "name": "Sentinel Integrity Critic",
        "emoji": "🛡️",
        "role": "Decision-integrity reflective critic (FLEET)",
    },
    {
        "id": "darwin",
        "name": "Darwin Fleet Scorer",
        "emoji": "📊",
        "role": "Outcome-join and artifact scorer (FLEET)",
    },
    {
        "id": "concierge",
        "name": "Concierge Operator Interface",
        "emoji": "🎛️",
        "role": "Governed OpenClaw operator interface (FLEET)",
    },
    {
        "id": "risk_agent",
        "name": "Guardian Risk Critic",
        "emoji": "⚠️",
        "role": "Deterministic risk evidence critic (FLEET)",
    },
)


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.name}.bak_fleet_personas_{stamp}")
    shutil.copy2(path, dest)
    return dest


def _ensure_agent_files(home: Path, agent_id: str) -> None:
    template = TEMPLATE_DIR / agent_id
    ws = home / f"workspace-{agent_id}"
    agent_dir = home / "agents" / agent_id / "agent"
    ws.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name in ("SOUL.md", "IDENTITY.md"):
        src = template / name
        dest = agent_dir / name
        if src.is_file():
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        elif not dest.exists():
            dest.write_text(f"# {agent_id}\n\nFLEET advisory persona — NO FINANCIAL AUTHORITY.\n", encoding="utf-8")


def install(home: Path, *, dry_run: bool = False) -> list[str]:
    cfg_path = home / "openclaw.json"
    if not cfg_path.is_file():
        raise SystemExit(f"Missing {cfg_path}")
    cfg = _load_config(cfg_path)
    agents = cfg.setdefault("agents", {})
    lst = agents.setdefault("list", [])
    existing = {row.get("id") for row in lst if isinstance(row, dict)}
    added: list[str] = []
    for persona in PERSONAS:
        agent_id = persona["id"]
        if agent_id in existing:
            continue
        entry = {
            "id": agent_id,
            "name": agent_id,
            "workspace": str(home / f"workspace-{agent_id}"),
            "agentDir": str(home / "agents" / agent_id / "agent"),
            "identity": {"name": persona["name"], "emoji": persona["emoji"]},
            "model": {
                "primary": "claude-cli/claude-sonnet-4-6",
                "fallbacks": ["ollama/qwen3:8b"],
            },
        }
        if dry_run:
            print(f"would add OpenClaw agent {agent_id}")
        else:
            _ensure_agent_files(home, agent_id)
            lst.append(entry)
            added.append(agent_id)
    if added and not dry_run:
        backup = _backup(cfg_path)
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(f"Added personas: {', '.join(added)}")
        print(f"Backup: {backup}")
    elif not added:
        print("No new personas to add.")
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home() / ".openclaw")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(args.home.expanduser(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
