# Source Export: scripts/check_llm_fleet_alerts.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/check_llm_fleet_alerts.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `6ee6434f5ea74233b0fd782848e6aae4a1a384143a442260f6d7c0fc5f7b84cb` |
| **File Size** | 3474 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""check_llm_fleet_alerts.py — Evaluate fleet status against alert rules. Read-only."""
import argparse, json, sys, yaml, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"

def _get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except: return None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rules", default=str(PROJ / "config" / "llm_fleet_alert_rules.yaml"))
    p.add_argument("--since-hours", type=int, default=24)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    rules = yaml.safe_load(Path(args.rules).read_text())
    expected = set(rules.get("expected_resident_models", {}).get("outside_deep_window", []))
    transient = set(rules.get("expected_resident_models", {}).get("transient_allowed", []))
    thresholds = rules.get("thresholds", {})

    # Get current state
    ps = _get(f"{OLLAMA}/api/ps") or {}
    resident = {m.get("name", ""): round(m.get("size_vram", 0) / 1e9, 2) for m in ps.get("models", [])}
    resident_names = set(resident.keys())
    vram_total = sum(resident.values())

    alerts = []
    status = "OK"

    # Check missing
    for exp in expected:
        if not any(exp in n for n in resident_names):
            alerts.append({"level": "WARN", "rule": "missing_expected", "detail": f"{exp} not resident"})

    # Check unexpected
    for name in resident_names:
        base = name.split(":")[0]
        if name not in expected and not any(t.split(":")[0] in base for t in transient) and name not in expected:
            normalized = any(e.split(":")[0] in name for e in expected)
            if not normalized:
                alerts.append({"level": "WARN", "rule": "unexpected_resident", "detail": name})

    # VRAM
    free = 16.0 - vram_total
    if free < thresholds.get("min_free_vram_gb_warn", 1.0):
        alerts.append({"level": "WARN", "rule": "low_vram", "detail": f"free={free:.1f}GB"})

    if alerts:
        status = "WARN"

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status, "alert_count": len(alerts), "alerts": alerts,
        "resident": list(resident_names), "vram_gb": round(vram_total, 2),
        "free_vram_gb": round(free, 2),
    }

    if args.verbose:
        print(f"Fleet alerts: {status} ({len(alerts)} alerts)")
        print(f"Resident: {list(resident_names)}")
        print(f"VRAM: {vram_total:.1f}GB used, {free:.1f}GB free")
        for a in alerts:
            print(f"  [{a['level']}] {a['rule']}: {a['detail']}")
        if not alerts:
            print("  No alerts triggered.")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result, indent=2, default=str))
    if args.output_md:
        lines = ["# Fleet Alert Check", f"\n**Status:** {status}", f"**Alerts:** {len(alerts)}",
                 f"**VRAM:** {vram_total:.1f}GB used, {free:.1f}GB free\n"]
        if alerts:
            lines.extend([f"- [{a['level']}] {a['rule']}: {a['detail']}" for a in alerts])
        else:
            lines.append("No alerts triggered.\n")
        Path(args.output_md).write_text("\n".join(lines))

if __name__ == "__main__":
    main()
```
