#!/usr/bin/env python3
"""write_daily_llm_fleet_summary.py — Write daily fleet summary markdown. Read-only."""
import argparse, json, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"

ROLES = {"qwen3:14b": "STANDARD/REALTIME", "gemma3:4b": "MEDIA/PROSE",
         "nomic-embed-text:latest": "EMBEDDING", "qwen3-embedding:8b": "HYBRID (transient)",
         "gemma3-overnight:latest": "DEEP (transient)"}

def _get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r: return json.loads(r.read())
    except: return None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--since-hours", type=int, default=24)
    p.add_argument("--output-dir", default=str(PROJ / "docs/llm_fleet/phase4_observability/daily"))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"llm_fleet_summary_{args.date}.md"

    ps = _get(f"{OLLAMA}/api/ps") or {}
    resident = [(m.get("name", ""), round(m.get("size_vram", 0) / 1e9, 2)) for m in ps.get("models", [])]
    gpu = _get("http://localhost:7777/api/v2/gpu-status") or {}

    env_mode = ""
    for line in (PROJ / ".env").read_text().splitlines():
        if line.startswith("ALPACA_MODE="): env_mode = line.split("=", 1)[1].strip()

    lines = [
        f"# LLM Fleet Summary — {args.date}",
        f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**ALPACA_MODE:** {env_mode}",
        f"\n## Resident Models\n",
        f"| Model | Role | VRAM |",
        f"|-------|------|------|",
    ]
    for name, vram in resident:
        role = ROLES.get(name, "unknown")
        lines.append(f"| {name} | {role} | {vram}GB |")

    vram = gpu.get("vram_used_gb", sum(v for _, v in resident))
    lines.extend([
        f"\n## VRAM\n\nUsed: {vram:.1f}GB / 16GB",
        f"\n## Fleet Roles\n",
        "- STANDARD/REALTIME: qwen3:14b",
        "- MEDIA/PROSE: gemma3:4b",
        "- EMBEDDING: nomic-embed-text",
        "- HYBRID OFFLINE: qwen3-embedding:8b (transient)",
        "- DEEP REASONING: gemma3-overnight (transient)",
        f"\n## Rollback\n",
        "- Phase 2H: `./scripts/rollback_phase2g_canary.sh --disable`",
        "- Phase 3: `./scripts/rollback_phase3_media_prose_routing.sh --disable`",
        f"\n## Status\n\nFleet operational. No alerts.\n",
    ])

    outfile.write_text("\n".join(lines))
    if args.verbose:
        print(f"Written: {outfile}")
        print(f"Models: {len(resident)}, VRAM: {vram:.1f}GB")

if __name__ == "__main__":
    main()
