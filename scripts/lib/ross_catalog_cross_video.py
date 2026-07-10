"""Cross-video symbol inference for Ross catalog clip videos.

Short YouTube clips often omit tickers but match a same-day full recap trade.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _pnl_close(a: float | None, b: float | None, *, tol: float = 0.4) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol


def infer_clip_symbols(entries: list[dict]) -> list[dict]:
    """Fill empty symbol lists on clip rows from same-day recap rows."""
    by_date: dict[date, list[dict]] = {}
    for e in entries:
        td = e.get("trade_date")
        if isinstance(td, date):
            by_date.setdefault(td, []).append(e)

    out: list[dict] = []
    for e in entries:
        row = dict(e)
        syms = row.get("symbols_traded") or []
        if syms:
            out.append(row)
            continue

        td = row.get("trade_date")
        if not isinstance(td, date):
            out.append(row)
            continue

        clip_pnl = row.get("net_pnl_usd")
        title = (row.get("video_title") or "").lower()
        candidates: list[tuple[str, float, str]] = []

        for other in by_date.get(td, []):
            if other is e:
                continue
            other_syms = other.get("symbols_traded") or []
            if not other_syms:
                continue
            other_pnl = other.get("net_pnl_usd")
            other_title = (other.get("video_title") or "").lower()

            # Same-day recap with matching P&L magnitude
            if _pnl_close(clip_pnl, other_pnl):
                for s in other_syms:
                    candidates.append((s, 0.85, f"pnl_match:{other.get('video_id')}"))
                continue

            # Clip about one trade + recap names a single dominant winner
            if clip_pnl and other_pnl and clip_pnl >= 5000 and "one trade" in title:
                if len(other_syms) == 1 and other_pnl >= clip_pnl * 0.7:
                    candidates.append((other_syms[0], 0.9, f"one_trade_clip:{other.get('video_id')}"))

            # Transcript on sibling video names ticker (handled via pre-filled symbols on other row)
            if "squeeze" in title and "breaking news" in other_title and other_syms:
                candidates.append((other_syms[0], 0.8, f"same_theme:{other.get('video_id')}"))

        if not candidates:
            out.append(row)
            continue

        # Best confidence per symbol
        best: dict[str, tuple[float, str]] = {}
        for sym, conf, reason in candidates:
            if sym not in best or conf > best[sym][0]:
                best[sym] = (conf, reason)

        ranked = sorted(best.items(), key=lambda x: -x[1][0])
        inferred = [s for s, _ in ranked[:3]]
        top_sym, (conf, reason) = ranked[0]

        row["symbols_traded"] = inferred
        row["winners"] = [{
            "symbol": top_sym,
            "pnl_usd": clip_pnl,
            "note": f"cross-video inference ({reason})",
        }]
        row["extraction_method"] = row.get("extraction_method", "regex")
        if row["extraction_method"] == "regex":
            row["extraction_method"] = "cross_video"
        row["extraction_confidence"] = max(row.get("extraction_confidence") or 0, conf)
        hrj = dict(row.get("hermes_review_json") or {})
        hrj["cross_video_inference"] = {
            "inferred_symbols": inferred,
            "reason": reason,
            "clip_pnl_usd": clip_pnl,
        }
        row["hermes_review_json"] = hrj
        out.append(row)

    return out


def apply_cross_video_to_catalog(since: date, until: date) -> int:
    """Reload catalog rows in range, infer clips, upsert. Returns rows updated."""
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root / "scripts"))
    from warrior_daily_catalog_extractor import upsert_catalog, _get_conn

    conn, cur = _get_conn()
    cur.execute(
        """
        SELECT trade_date, video_id, video_title, video_publish_date,
               symbols_traded, winners, losers, net_pnl_usd,
               extraction_method, extraction_confidence, hermes_review_json
        FROM ross_daily_catalog
        WHERE trade_date BETWEEN %s AND %s
        ORDER BY trade_date, video_id
        """,
        (since, until),
    )
    entries = []
    for r in cur.fetchall():
        entries.append({
            "trade_date": r["trade_date"],
            "video_id": r["video_id"],
            "video_title": r["video_title"],
            "video_publish_date": r.get("video_publish_date"),
            "symbols_traded": list(r["symbols_traded"] or []),
            "winners": r["winners"] if isinstance(r["winners"], list) else json.loads(r["winners"] or "[]"),
            "losers": r["losers"] if isinstance(r["losers"], list) else json.loads(r["losers"] or "[]"),
            "net_pnl_usd": r["net_pnl_usd"],
            "extraction_method": r["extraction_method"],
            "extraction_confidence": r["extraction_confidence"],
            "hermes_review_json": r["hermes_review_json"] if isinstance(r["hermes_review_json"], dict) else json.loads(r["hermes_review_json"] or "{}"),
        })
    conn.close()

    before = sum(1 for e in entries if not (e.get("symbols_traded") or []))
    updated = infer_clip_symbols(entries)
    after_empty = sum(1 for e in updated if not (e.get("symbols_traded") or []))
    changed = [e for a, e in zip(entries, updated) if (a.get("symbols_traded") or []) != (e.get("symbols_traded") or [])]

    if changed:
        upsert_catalog(changed)

    return len(changed)