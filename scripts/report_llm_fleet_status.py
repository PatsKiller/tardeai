#!/usr/bin/env python3
"""report_llm_fleet_status.py — Unified read-only LLM fleet status report."""
import argparse, json, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"

EXPECTED_RESIDENT = {"qwen3:14b", "gemma3:4b", "nomic-embed-text:latest"}
TRANSIENT_ALLOWED = {"qwen3-embedding:8b", "gemma3-overnight:latest", "gemma3-overnight"}

ROLES = {
    "qwen3:14b": "STANDARD/REALTIME",
    "gemma3:4b": "MEDIA/PROSE",
    "nomic-embed-text:latest": "PRODUCTION EMBEDDING",
    "qwen3-embedding:8b": "HYBRID OFFLINE (transient)",
    "gemma3-overnight:latest": "DEEP REASONING (transient)",
}

def _get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [fleet] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser(description="LLM fleet status report")
    p.add_argument("--since-hours", type=int, default=24)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Model list
    models_data = _get(f"{OLLAMA}/api/tags") or {}
    installed = {m["name"]: {"size_gb": round(m.get("size", 0) / 1e9, 1)}
                 for m in models_data.get("models", [])}

    # Resident
    ps_data = _get(f"{OLLAMA}/api/ps") or {}
    resident = {}
    for m in ps_data.get("models", []):
        name = m.get("name", "")
        resident[name] = {
            "vram_gb": round(m.get("size_vram", 0) / 1e9, 2),
            "total_gb": round(m.get("size", 0) / 1e9, 2),
        }

    # GPU
    gpu = _get("http://localhost:7777/api/v2/gpu-status") or {}

    # Safety
    env_lines = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() in ("ALPACA_MODE", "LLM_DISABLE_LIVE_EXECUTION"):
                env_lines[k.strip()] = v.strip()

    # Phase policies
    p2h = {}
    try:
        sys.path.insert(0, str(PROJ / "scripts"))
        from phase2g_hybrid_canary_policy import load_policy as p2_load
        p2h = p2_load(str(PROJ / "config" / "phase2h_bounded_hybrid_rag_policy.yaml"))
    except Exception: pass

    p3 = {}
    try:
        from phase3_media_prose_routing_policy import load_policy as p3_load
        p3 = p3_load()
    except Exception: pass

    # Checks
    resident_names = set(resident.keys())
    missing = EXPECTED_RESIDENT - resident_names
    unexpected = resident_names - EXPECTED_RESIDENT - TRANSIENT_ALLOWED
    vram_used = gpu.get("vram_used_gb", sum(r.get("vram_gb", 0) for r in resident.values()))

    status = "OK"
    warnings = []
    if missing:
        status = "WARN"
        warnings.append(f"Missing expected: {missing}")
    if unexpected:
        status = "WARN"
        warnings.append(f"Unexpected resident: {unexpected}")
    if vram_used > 15.5:
        status = "WARN"
        warnings.append(f"VRAM high: {vram_used}GB")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status, "warnings": warnings,
        "installed": installed, "resident": resident,
        "expected_resident": list(EXPECTED_RESIDENT),
        "missing_expected": list(missing),
        "unexpected_resident": list(unexpected),
        "vram_used_gb": round(vram_used, 2),
        "roles": ROLES,
        "safety": env_lines,
        "phase2h": {"enabled": p2h.get("enabled"), "global_promotion": p2h.get("global_promotion_approved")},
        "phase3": {"enabled": p3.get("enabled"), "candidate": p3.get("candidate_model")},
        "rollback": {
            "phase2h": "./scripts/rollback_phase2g_canary.sh --disable",
            "phase3": "./scripts/rollback_phase3_media_prose_routing.sh --disable",
        },
    }

    if args.verbose:
        log(f"Fleet status: {status}")
        log(f"Resident: {list(resident.keys())}")
        log(f"Missing: {list(missing) or 'none'}")
        log(f"VRAM: {vram_used:.1f}GB")
        for r_name, r_role in ROLES.items():
            in_res = "✓" if r_name in resident_names or any(r_name.split(":")[0] in n for n in resident_names) else "—"
            log(f"  {in_res} {r_role}: {r_name}")
        for w in warnings:
            log(f"  WARN: {w}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        lines = ["# LLM Fleet Status", f"\n**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 f"**Status:** {status}", f"\n## Resident Models\n"]
        for name, info in resident.items():
            role = ROLES.get(name, "unknown")
            lines.append(f"- {name} ({role}) — {info.get('vram_gb', '?')}GB VRAM")
        if missing: lines.append(f"\n**Missing:** {', '.join(missing)}")
        if warnings: lines.extend([f"\n## Warnings\n"] + [f"- {w}" for w in warnings])
        lines.append(f"\n## VRAM\n\nUsed: {vram_used:.1f}GB\n")
        Path(args.output_md).write_text("\n".join(lines))

if __name__ == "__main__":
    main()
