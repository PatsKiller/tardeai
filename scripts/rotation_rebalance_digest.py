#!/usr/bin/env python3
"""rotation_rebalance_digest.py — weekly advisory rotation digest + research-gap seeding (continuous loop).

Fetches the rotation summary, seeds TradeAI/Hermes research directives for the UNDERWEIGHT sleeves + the
named rotate-in candidates (so the discovery engine + watchlist sweep research them and surface candidates
that come back as rotate-in ideas), and sends a Telegram digest.

ADVISORY ONLY: no broker action, no order, no dollar amount is ever placed — the digest reports ranges to
REVIEW only. Hits the local API (no external network, no Grok/xAI API).
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://localhost:7777/api/v2/rotation"
ROOT = Path(__file__).resolve().parent.parent


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read())


def _post(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main() -> int:
    summ = (_get("/summary").get("data")) or {}
    over = summ.get("sector_overweights", []) or []
    under = summ.get("sector_underweights", []) or []
    ideas = summ.get("research_rotation_ideas", []) or []
    seeded = _post("/research-gaps").get("created", []) if (over or under or ideas) else []

    lines = ["📊 *Rotation Rebalance Digest* — advisory only, no broker action"]
    if over:
        lines.append("\nOverweight sleeves (review trimming toward target):")
        for o in over[:5]:
            lines.append(f"  • {o['theme']}: {o['pct']}% vs {o['target']}% target — over ~${o['excess_dollars']:,}")
    if under:
        lines.append("\nUnderweight sleeves (now being researched):")
        for u in under:
            lines.append(f"  • {u['theme']}: {u['pct']}% vs {u['floor']}% floor")
    if ideas:
        lines.append("\nAdvisory rebalance ideas (review only — confirm sizing/tax yourself):")
        for i in ideas[:5]:
            rng = i.get("review_amount_range") or {}
            amt = f" (~${rng.get('low'):,}-${rng.get('high'):,})" if rng.get("low") else ""
            lines.append(f"  • {i.get('from_symbol')} → {i.get('to_symbol')}{amt}")
    lines.append(f"\nSeeded {len(seeded)} research directive(s) → TradeAI + Hermes will research the gaps + rotate-in names.")
    lines.append("Review at /v3/rotation · advisory only · nothing placed.")
    msg = "\n".join(lines)

    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        print(msg)
    print(json.dumps({"overweights": len(over), "underweights": len(under),
                      "ideas": len(ideas), "directives_seeded": len(seeded)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
