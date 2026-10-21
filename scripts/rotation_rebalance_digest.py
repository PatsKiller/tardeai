#!/usr/bin/env python3
"""rotation_rebalance_digest.py — weekly advisory rotation digest + research-gap seeding (continuous loop).

Fetches the rotation summary, seeds TradeAI/Hermes research directives for the UNDERWEIGHT sleeves + the
named rotate-in candidates (so the discovery engine + watchlist sweep research them and surface candidates
that come back as rotate-in ideas), and sends a Telegram digest.

ADVISORY ONLY: no broker action, no order, no dollar amount is ever placed — the digest reports ranges to
REVIEW only. Hits the local API (no external network, no Grok/xAI API).
"""
import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run (it always sends)). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "rotation-rebalance-digest"
    _dr_would = (
        "fetch the rotation summary from the local Command Center API, seed research directives for "
        "underweight sleeves and rotate-in candidates and send the weekly advisory digest through the "
        "Telegram chokepoint"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="sleeve"))
    raise SystemExit(0)

try:  # cc_auth (2026-10-14): service token for loopback Command Center (:7777) calls
    from lib.cc_client import cc_urlopen as _cc_urlopen
except ImportError:  # pragma: no cover - scripts/ not on sys.path
    import sys as _cc_sys
    from pathlib import Path as _CcPath
    _cc_sys.path.insert(0, str(next(p for p in _CcPath(__file__).resolve().parents if p.name == "scripts")))
    from lib.cc_client import cc_urlopen as _cc_urlopen

import json
import sys
import urllib.request
from pathlib import Path
from lib.rotation_publication import ready

BASE = "http://localhost:7777/api/v2/rotation"
ROOT = Path(__file__).resolve().parent.parent


def _get(path: str) -> dict:
    with _cc_urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read())


def _post(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _cc_urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main() -> int:
    try:
        summ = (_get("/summary").get("data")) or {}
    except Exception:
        summ = {}
    if not isinstance(summ, dict):
        summ = {}
    available = ready(summ)
    publication = summ.get("publication") or {}
    if not isinstance(publication, dict):
        publication = {}
    status = publication.get("status") if publication.get("status") in {"READY", "STALE", "UNAVAILABLE"} else "UNAVAILABLE"
    if not available and status == "READY":
        status = "UNAVAILABLE"
    if not available:
        # Do not turn missing/held evidence into an empty successful digest or
        # seed new research from advice that failed its publication contract.
        summ = {"publication": publication}
    over = summ.get("sector_overweights", []) or []
    under = summ.get("sector_underweights", []) or []
    ideas = summ.get("research_rotation_ideas", []) or []
    degraded = summ.get("degraded_holdings", []) or []
    seeded = _post("/research-gaps").get("created", []) if available and (over or under or ideas) else []

    lines = ["📊 *Rotation Rebalance Digest* — advisory only, no broker action"]
    if not available:
        reasons = ", ".join(publication.get("reasons") or ["missing_publication_evidence"])
        lines.append(f"\n{status}: advisory output withheld ({reasons}).")
    lines.append(f"Source as of: {publication.get('source_as_of') or 'UNAVAILABLE'} · cache generated: {publication.get('cache_generated_at') or 'UNAVAILABLE'}")
    if degraded:
        # Lead with deteriorating holdings — the rotate-OUT signal driven by real deterioration.
        _hard = [d for d in degraded if d.get("deterministic")]
        _soft = [d for d in degraded if not d.get("deterministic")]
        lines.append("\n⚠️ Deteriorating holdings (review rotating out):")
        for d in degraded[:8]:
            _src = "stop math" if d.get("deterministic") else "LLM read"
            _why = d.get("escalation_reason") or d.get("what_changed") or ""
            _val = f" ${d.get('current_value'):,.0f}" if d.get("current_value") else ""
            lines.append(f"  • {d.get('symbol')} [{d.get('account_key') or 'account UNAVAILABLE'}]: {d.get('thesis_status','').upper()} ({_src}){_val}"
                         + (f" — {_why}" if _why else ""))
        lines.append(f"  ({len(_hard)} deterministic stop signals, {len(_soft)} LLM/soft)")
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
            tags = [f"CIO {i['to_cio_view']}"] if i.get("to_cio_view") else []
            if i.get("to_thin_coverage") is True:
                tags.append("thin analyst coverage")
            tag = f" ({'; '.join(tags)})" if tags else ""
            lines.append(f"  • {i.get('from_symbol')} [{i.get('from_account_key') or 'account UNAVAILABLE'}] → {i.get('to_symbol')}{amt}{tag}")
    if available:
        lines.append(f"\nSeeded {len(seeded)} research directive(s) → TradeAI + Hermes will research the gaps + rotate-in names.")
    lines.append("Review at /v3/rotation · advisory only · nothing placed.")
    msg = "\n".join(lines)

    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram
        send_telegram(msg, priority="P2", producer="rotation_rebalance_digest")
    except Exception:
        print(msg)
    print(json.dumps({"overweights": len(over), "underweights": len(under),
                      "ideas": len(ideas), "directives_seeded": len(seeded), "publication_status": status}))
    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())
