#!/usr/bin/env python3
"""
Generate daily operator alert digest from SIEM normalized events.
Writes markdown digest to data/system_events/daily/.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def generate_digest(period="today"):
    """Generate operator digest from normalized events."""
    from normalize_tradeai_alerts import normalize

    days = 1 if period == "today" else 7
    events, rollup = normalize(days=days, dry_run=True)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Operator Alert Digest — {today}",
        f"",
        f"Period: {period} ({days} day{'s' if days > 1 else ''})",
        f"Total events: {rollup['total_raw']}",
        f"Immediate (P0/P1): {rollup['immediate_alerts']}",
        f"Digest-only: {rollup['digest_only']}",
        f"Noise reduction: {rollup['severity'].get('SUPPRESSED', 0)} suppressed",
        f"",
    ]

    # Section 1: Needs action now
    p0p1 = [e for e in events if e["severity"] in ("P0", "P1") and not e.get("suppressed", e.get("suppression_status") == "SUPPRESS_TO_DIGEST")]
    lines.append("## 1. Needs Action Now")
    if p0p1:
        for e in p0p1[:10]:
            lines.append(f"- **{e['severity']}** [{e['event_type']}] {e.get('raw_message_excerpt', e.get('message', ''))[:100]}")
    else:
        lines.append("- None")
    lines.append("")

    # Section 2: Morning review
    stops = [e for e in events if e["event_type"] == "STOP_TRIGGERED"]
    lines.append("## 2. Morning Review (Stops)")
    if stops:
        for e in stops[:5]:
            lines.append(f"- {e.get('raw_message_excerpt', e.get('message', ''))[:100]} (×{e.get('repeat_count', 1)})")
    else:
        lines.append("- No stop alerts")
    lines.append("")

    # Section 3: Suppressed duplicates
    top_dup = sorted(rollup.get("top_dedupe", []), key=lambda x: -x["count"])[:5]
    lines.append("## 3. Suppressed Duplicates")
    for d in top_dup:
        lines.append(f"- {d['key']}: {d['count']}×")
    lines.append("")

    # Section 4: Still unresolved
    lines.append("## 4. Still Unresolved")
    unresolved = [e for e in events if e.get("resolved_status") == "unknown" and e["severity"] in ("P1", "P2")]
    lines.append(f"- {len(unresolved)} events with unknown resolution status")
    lines.append("")

    # Section 5: Data quality
    dq = [e for e in events if e["event_type"] == "DATA_QUALITY"]
    lines.append("## 5. Data Quality Issues")
    if dq:
        for e in dq[:5]:
            lines.append(f"- {e.get('raw_message_excerpt', e.get('message', ''))[:100]}")
    else:
        lines.append("- None")
    lines.append("")

    # Section 6: Summary
    lines.append("## 6. Summary")
    lines.append(f"- Severity breakdown: {rollup['severity']}")
    lines.append(f"- Dedupe groups: {rollup['dedupe_groups']}")
    lines.append("")

    digest_text = "\n".join(lines)

    # Write
    out_dir = PROJECT_ROOT / "data" / "system_events" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}_operator_digest.md"
    out_path.write_text(digest_text)
    print(f"Digest written: {out_path}")
    return digest_text


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="today", choices=["today", "week"])
    args = ap.parse_args()
    print(generate_digest(args.period))
