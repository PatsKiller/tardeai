#!/usr/bin/env python3
"""Build a bounded Evening Surveillance packet.

The OpenClaw Aegis Evening Surveillance job must consume THIS file — not the
entire Telegram history, watchlist, alert table, prior conversation, or the
retired cio_decisions artifact.

Usage:
    python3 scripts/aegis_evening_packet.py           # write packet + print path
    python3 scripts/aegis_evening_packet.py --prompt  # print the isolated-session prompt
    python3 scripts/aegis_evening_packet.py --json    # print packet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

PACKET_PATH = ROOT / "data" / "runtime" / "aegis_evening_packet.json"
MAX_FINDINGS = 8
MAX_CHARS = 12_000


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _trim(obj, n=800):
    s = json.dumps(obj, default=str)
    if len(s) <= n:
        return obj
    return {"_truncated": True, "chars": len(s), "head": s[:n]}


def _cio_product() -> dict:
    """Current canonical CIO product — never the retired cio_decisions file."""
    candidates = [
        ROOT / "data" / "cio" / "cio_investment_product_latest.json",
        ROOT / "data" / "cio" / "CURRENT" / "cio_investment_product_latest.json",
    ]
    # TRADEAI_CIO_DIR / live CURRENT tree
    cio_dir = os.environ.get("TRADEAI_CIO_DIR")
    if cio_dir:
        candidates.insert(0, Path(cio_dir) / "cio_investment_product_latest.json")
    for p in candidates:
        if p.exists():
            data = _read_json(p) or {}
            if isinstance(data, dict) and data:
                return {
                    "source": "cio_investment_product",
                    "path": str(p),
                    "product_id": data.get("product_id"),
                    "as_of": data.get("as_of") or data.get("generated_at"),
                    "trigger": data.get("trigger"),
                    "what_changed_material": data.get("what_changed_material"),
                    "desk": _trim(data.get("desk") or data.get("memo") or data.get("summary"), 1200),
                    "reentry": _trim(data.get("reentry") or data.get("re_entry"), 800),
                }
    # Fallback: latest persist via library if present
    try:
        from cio_investment_product import load_brief
        brief = load_brief()
        if brief:
            return {
                "source": "cio_investment_product.load_brief",
                "product_id": getattr(brief, "product_id", None) or (brief.get("product_id") if isinstance(brief, dict) else None),
                "brief": _trim(brief if isinstance(brief, dict) else getattr(brief, "__dict__", str(brief)), 1600),
            }
    except Exception:
        pass
    return {"source": "cio_investment_product", "available": False, "note": "no current product on disk"}


def _holdings_protection() -> dict:
    p = ROOT / "data" / "portfolios" / "state" / "holdings.json"
    d = _read_json(p) or {}
    holds = d.get("holdings") or []
    tot = (d.get("portfolio_totals") or {}).get("total_value")
    near_stop = []
    for h in holds:
        if not isinstance(h, dict):
            continue
        px = h.get("price") or h.get("current_price")
        stop = h.get("stop") or h.get("stop_price") or h.get("stop_loss")
        try:
            if px and stop and float(px) > 0:
                dist = abs(float(px) - float(stop)) / float(px)
                if dist <= 0.03:
                    near_stop.append({
                        "symbol": h.get("symbol"),
                        "account": h.get("account"),
                        "price": px,
                        "stop": stop,
                        "distance_pct": round(dist * 100, 2),
                    })
        except (TypeError, ValueError):
            continue
    return {
        "as_of": d.get("as_of") or d.get("generated_at") or d.get("last_repriced"),
        "position_count": len(holds),
        "total_value": tot,
        "accounts": sorted({h.get("account") for h in holds if isinstance(h, dict) and h.get("account")}),
        "near_stop": near_stop[:MAX_FINDINGS],
        "freshness_note": d.get("_freshness_note"),
    }


def _health() -> dict:
    out = {"unresolved_critical": [], "stale": []}
    try:
        from alert_condition_state import today_metrics, unresolved_conditions
        out["condition_metrics"] = today_metrics()
        crit = unresolved_conditions()
        out["unresolved_count"] = len(crit)
        out["unresolved_critical"] = [
            {"key": c["key"], "state": c.get("state")} for c in crit[:MAX_FINDINGS]
        ]
    except Exception as e:
        out["condition_error"] = str(e)[:120]
    # holdings freshness
    hp = ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if hp.exists():
        age_h = (datetime.now().timestamp() - hp.stat().st_mtime) / 3600
        out["holdings_age_hours"] = round(age_h, 1)
        if age_h > 36:
            out["stale"].append(f"holdings.json {age_h:.0f}h old")
    return out


def _advisory() -> dict:
    p = ROOT / "data" / "runtime" / "advisory_latest.json"
    if p.exists():
        return {"source": "advisory_latest", "body": _trim(_read_json(p), 800)}
    return {"source": "advisory", "available": False}


def build_packet() -> dict:
    packet = {
        "schema": "aegis_evening_packet@v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_cio_source": "cio_investment_product",
        "retired_artifacts_forbidden": ["cio_decisions"],
        "command_center": "https://tradeai.jwwhiting.com/v3/",
        "max_findings": MAX_FINDINGS,
        "cio": _cio_product(),
        "holdings_protection": _holdings_protection(),
        "health": _health(),
        "advisory": _advisory(),
        "instructions": [
            "Title: Aegis Evening Scan",
            "Use ONLY this packet. Do not dump Telegram, watchlist, alert_events, or prior chat.",
            "Do not treat cio_decisions as canonical CIO intelligence.",
            "Report at most 8 findings across: protection, CIO/re-entry change, research/news, runtime failure, freshness.",
            "Large diagnostics: point at Command Center, do not load them into context.",
        ],
    }
    raw = json.dumps(packet, default=str)
    packet["packet_chars"] = len(raw)
    if len(raw) > MAX_CHARS:
        packet["cio"] = _trim(packet.get("cio"), 600)
        packet["advisory"] = _trim(packet.get("advisory"), 400)
        packet["truncated"] = True
    return packet


def isolated_prompt(packet_path: Path = PACKET_PATH) -> str:
    return (
        "FRESH SESSION. Do not inherit prior conversation.\n"
        "Read ONLY this bounded packet file and reply with 'Aegis Evening Scan'.\n"
        f"Packet: {packet_path}\n"
        "Rules:\n"
        "- Maximum 8 findings.\n"
        "- Sections: protection / CIO-reentry / research-news / runtime / freshness.\n"
        "- Canonical CIO source is cio_investment_product (never cio_decisions).\n"
        "- Do not fetch Telegram history, the full watchlist, or alert_events.\n"
        "- Point leftover detail at Command Center /v3/.\n"
        "If the packet is missing, say PACKET_MISSING and stop."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    packet = build_packet()
    PACKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    PACKET_PATH.write_text(json.dumps(packet, indent=2, default=str))
    if args.prompt:
        print(isolated_prompt(PACKET_PATH))
        return 0
    if args.json:
        print(json.dumps(packet, indent=2, default=str))
        return 0
    print(f"[aegis-evening] wrote {PACKET_PATH} chars={packet.get('packet_chars')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
