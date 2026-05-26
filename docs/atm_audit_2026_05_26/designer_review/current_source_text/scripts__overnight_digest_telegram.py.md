# Source Export: scripts/overnight_digest_telegram.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/overnight_digest_telegram.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `016329add5fb60f0601983be86bb9f19e9fe42239b82067ecf51be710c4ae088` |
| **File Size** | 5296 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""overnight_digest_telegram.py — Send overnight intelligence digest via Telegram.

Scheduled at 6:00 AM ET daily. Summarizes the overnight LLM window results
and sends a compact briefing to Telegram.

Usage:
    .venv/bin/python scripts/overnight_digest_telegram.py
    .venv/bin/python scripts/overnight_digest_telegram.py --dry-run

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

API_BASE = os.getenv("API_BASE_URL", "http://localhost:7777")


def fetch_dashboard():
    """Fetch the overnight dashboard data from the API."""
    url = f"{API_BASE}/api/v2/overnight-dashboard"
    resp = urlopen(url, timeout=30)
    data = json.loads(resp.read())
    if data.get("ok"):
        return data.get("data", {})
    return {}


def compose_message(d: dict) -> str:
    """Build a compact Telegram message from dashboard data."""
    w = d.get("window", {})
    lines = []

    # Header
    from datetime import datetime
    date_str = datetime.now().strftime("%B %d")
    lines.append(f"🌙 *OVERNIGHT BRIEF — {date_str}*")

    # Window stats
    start = w.get("window_start", "")
    end = w.get("window_end", "")
    start_t = start[11:16] if start and len(start) > 16 else "?"
    end_t = end[11:16] if end and len(end) > 16 else "?"
    done = w.get("done_count") or 0
    failed = w.get("failed_count") or 0
    avg = w.get("avg_sec") or 0
    lines.append(f"Window: {start_t} → {end_t} ET")
    lines.append(f"Jobs: {done} done, {failed} failed, avg {avg}s")
    lines.append("")

    # Risk synthesis
    rs = d.get("risk_synthesis", {})
    narrative = rs.get("narrative", "")
    if narrative:
        clean = narrative.replace("```json", "").replace("```", "").strip()
        lines.append(f"📊 *Morning brief:* {clean[:200]}{'...' if len(clean) > 200 else ''}")
        lines.append("")

    # Recovery verdicts
    rv = d.get("recovery_verdicts", [])
    if rv:
        reenter = [r["symbol"] for r in rv if r.get("reentry_signal", "").upper() in ("RE_ENTER", "BUY", "REENTER")]
        watch = [r["symbol"] for r in rv if r.get("verdict", "").upper() in ("NEEDS_MORE_DATA", "WAIT_FOR_CATALYST", "HOLD")]
        if reenter:
            lines.append(f"🔄 Re-enter signals: {', '.join(reenter)}")
        if watch:
            lines.append(f"👀 Watch: {', '.join(watch[:5])}")
        lines.append(f"Recovery: {len(rv)} symbols reviewed")
        lines.append("")

    # Trade reviews
    tr = d.get("trade_reviews", [])
    if tr:
        lines.append(f"📝 Trade lessons: {len(tr)} reviewed")
        for t in tr[:3]:
            grade = t.get("grade", "?")
            lesson = (t.get("key_lesson") or t.get("outcome") or "")[:60]
            lines.append(f"  {t['symbol']} ({grade}): {lesson}")
        lines.append("")

    # New proposals
    np = d.get("new_proposals", [])
    if np:
        top = np[0]
        lines.append(f"💼 New proposals: {len(np)} ({top['symbol']} top, {top.get('grade', '?')} grade)")
        lines.append("")

    # Covered calls
    cc = d.get("covered_calls", [])
    if cc:
        syms = [c["symbol"] for c in cc[:3]]
        lines.append(f"📞 Covered calls scored: {', '.join(syms)}")
        lines.append("")

    # Failed jobs
    fj = d.get("failed_jobs", [])
    if fj:
        lines.append(f"⚠️ Failed: {len(fj)} ({', '.join(set(f['job_type'].replace('_', ' ') for f in fj[:3]))})")
        lines.append("")

    # Calibration summary
    cal = d.get("gemma3_calibration", [])
    if cal:
        total_correct = sum(c.get("correct", 0) for c in cal)
        total_graded = sum(c.get("correct", 0) + c.get("hallucinated", 0) + c.get("partial", 0) for c in cal)
        if total_graded > 0:
            lines.append(f"🎯 Gemma3 accuracy: {total_correct}/{total_graded} ({round(total_correct/total_graded*100)}%)")
            lines.append("")

    # Link
    lines.append(f"Full: https://ms01-openclaw.tail163d14.ts.net/v2/overnight")

    return "\n".join(lines)


def send(message: str, dry_run: bool = False):
    """Send the message via Telegram."""
    if dry_run:
        print("=== DRY RUN ===")
        print(message)
        print(f"=== {len(message)} chars ===")
        return

    from telegram_alert import send_telegram
    send_telegram(message)
    print(f"Sent overnight digest ({len(message)} chars)")


def main():
    parser = argparse.ArgumentParser(description="Send overnight LLM digest via Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending")
    args = parser.parse_args()

    # Load .env
    env_path = PROJ / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    data = fetch_dashboard()
    if not data:
        print("No overnight data available — skipping digest")
        return

    msg = compose_message(data)
    send(msg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```
