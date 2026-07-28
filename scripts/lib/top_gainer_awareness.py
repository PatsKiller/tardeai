"""Tag Finviz leaders for operator awareness (never tradeable GO).

Two upstream sources, unioned by load_top_gainers():
  1. prime_setups CSV — hard-filtered (RVOL>5x, gap>10%, $2-20, float<50M). Rich
     fields (rvol/gap/float) but routinely returns 0-1 rows on a 15-gainer day.
  2. market_movers snapshot — the SAME raw Finviz ta_topgainers screen the Home
     board renders, unfiltered. Thin fields (price/change/volume only) but it is
     the only source that sees names outside the scalp filter (2026-07-28: 10 of
     Home's 15 top gainers reached no other surface).

The TOP GAINER marker is ORTHOGONAL to awareness_status. awareness_status is a
single-valued lane (SQUEEZE > MICRO_FLOAT > LOW_PRICE > HIGH_RVOL > TOP_GAINER >
SOCIAL_AWARENESS); a row that is both a squeeze and a top gainer used to lose the
gainer fact entirely because the squeeze tagger runs first and owns the field.
row["top_gainer"] is set regardless of lane so the pill can render alongside.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

MARKET_MOVERS_SNAPSHOT = ("data", "runtime", "market_movers_latest.json")

# Scanner verdicts that mean "the engine passed this on its own evidence". Awareness
# tagging is additive and must not revoke tradeability for these.
ACTIONABLE_DECISIONS = frozenset({"GO", "ENTER", "TAKE"})


def _pct_num(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_latest_prime_setups_csv(project_root: Path) -> Path | None:
    base = project_root / "data" / "raw" / "finviz"
    if not base.exists():
        return None
    candidates = sorted(base.glob("**/prime_setups_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def load_finviz_top_gainers(project_root: Path, *, limit: int = 10, min_change_pct: float = 10.0) -> list[dict]:
    """Parse the newest prime_setups export; return top symbols by Change %."""
    path = _find_latest_prime_setups_csv(project_root)
    if not path:
        return []
    try:
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8", errors="replace"))))
    except Exception:
        return []

    parsed: list[dict] = []
    for row in rows:
        sym = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
        if not sym or not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        chg = _pct_num(row.get("Change") or row.get("change_percent") or row.get("Change%"))
        if chg is None or chg < min_change_pct:
            continue
        gap = _pct_num(row.get("Gap") or row.get("gap_percent") or row.get("Gap%"))
        rvol = _pct_num(row.get("Relative Volume") or row.get("relative_volume") or row.get("RVOL"))
        price = _pct_num(row.get("Price") or row.get("price"))
        float_raw = row.get("Shares Float") or row.get("float_m") or row.get("Float")
        float_m = _pct_num(float_raw)
        if float_m is not None and float_m > 500:
            float_m = round(float_m / 1_000_000, 2)
        parsed.append({
            "symbol": sym,
            "change_pct": chg,
            "change_pct_display": f"+{chg:.1f}%",
            "gap_pct": gap,
            "rvol": rvol,
            "price": price,
            "float_m": float_m,
            "sector": (row.get("Sector") or "").strip(),
            "industry": (row.get("Industry") or "").strip(),
            "company": (row.get("Company") or "").strip(),
            "source_file": str(path.relative_to(project_root)),
            "source": "prime_setups",
        })

    parsed.sort(key=lambda r: r["change_pct"], reverse=True)
    return parsed[:limit]


def _capture_is_stale(captured_at: str) -> bool:
    """True when the snapshot was captured on an earlier ET session date than today."""
    if not captured_at:
        return True
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        cap = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        return cap.astimezone(et).date() < datetime.now(et).date()
    except Exception:
        return True


def load_market_movers_top_gainers(
    project_root: Path, *, limit: int = 15, min_change_pct: float = 10.0
) -> list[dict]:
    """Parse the market_movers snapshot's raw ta_topgainers screen (the Home board feed).

    Unfiltered, so it carries the sub-$2 / >$20 / large-float names prime_setups
    drops. rvol/gap/float are absent upstream — left None, never faked."""
    snap = project_root.joinpath(*MARKET_MOVERS_SNAPSHOT)
    try:
        data = json.loads(snap.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    captured_at = str(data.get("captured_at") or "")
    stale = _capture_is_stale(captured_at)
    rows = ((data.get("signals") or {}).get("top_gainers") or {}).get("rows") or []

    parsed: list[dict] = []
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym or not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        chg = _pct_num(row.get("change_pct"))
        if chg is None or chg < min_change_pct:
            continue
        parsed.append({
            "symbol": sym,
            "change_pct": chg,
            "change_pct_display": f"+{chg:.1f}%",
            "gap_pct": None,
            "rvol": None,
            "price": _pct_num(row.get("last")),
            "float_m": None,
            "volume": _pct_num(row.get("volume")),
            "sector": (row.get("sector") or "").strip(),
            "industry": "",
            "company": (row.get("company") or "").strip(),
            "source_file": str(snap.relative_to(project_root)),
            "source": "market_movers",
            "captured_at": captured_at,
            "stale": stale,
        })

    parsed.sort(key=lambda r: r["change_pct"], reverse=True)
    return parsed[:limit]


def load_top_gainers(
    project_root: Path, *, limit: int = 30, min_change_pct: float = 10.0
) -> list[dict]:
    """Union of both Finviz gainer sources, deduped by symbol, sorted by Change % desc.

    prime_setups wins on conflict — it carries rvol/gap/float that market_movers
    lacks — but market_movers change_pct is preferred when the prime row is missing
    it. Ranks are assigned after the merge (1-based)."""
    merged: dict[str, dict] = {}

    for g in load_market_movers_top_gainers(project_root, limit=limit, min_change_pct=min_change_pct):
        merged[g["symbol"]] = g

    for g in load_finviz_top_gainers(project_root, limit=limit, min_change_pct=min_change_pct):
        prior = merged.get(g["symbol"])
        if prior:
            g = {**prior, **{k: v for k, v in g.items() if v not in (None, "")}}
            g["source"] = "prime_setups+market_movers"
        merged[g["symbol"]] = g

    out = sorted(merged.values(), key=lambda r: r["change_pct"], reverse=True)[:limit]
    for i, g in enumerate(out, 1):
        g["rank"] = i
    return out


def _mark_top_gainer(row: dict, g: dict) -> None:
    """Set the lane-independent TOP GAINER marker. Never touches awareness_status."""
    row["top_gainer"] = True
    row["top_gainer_pct"] = g["change_pct"]
    row["top_gainer_rank"] = g.get("rank")
    row["top_gainer_source"] = g.get("source") or "prime_setups"
    row["top_gainer_pill"] = f"TOP GAINER · {g['change_pct_display']}"
    if g.get("captured_at"):
        row["top_gainer_captured_at"] = g["captured_at"]
    if g.get("stale"):
        row["top_gainer_stale"] = True


def attach_top_gainer_awareness(tickers: list[dict], project_root: Path, *, limit: int = 10) -> list[str]:
    """Tag (or inject) awareness rows for Finviz top gainers. Returns symbol list."""
    gainers = load_top_gainers(project_root, limit=limit)
    if not gainers:
        return []

    by_sym = {str(t.get("symbol", "")).upper(): t for t in tickers}
    tagged: list[str] = []

    for g in gainers:
        sym = g["symbol"]
        tagged.append(sym)
        row = by_sym.get(sym)
        pill = f"TOP GAINER · {g['change_pct_display']}"
        subtitle = "Leading Finviz gainer — awareness only, not momentum-scalp GO"

        if row:
            # Lane-independent: a squeeze/runner/social row is STILL a top gainer.
            _mark_top_gainer(row, g)
            if row.get("awareness_status") == "SOCIAL_AWARENESS" or row.get("setup_class") == "social_awareness_only":
                for key, val in (
                    ("price", g.get("price")),
                    ("rvol", g.get("rvol")),
                    ("change_pct", f"{g['change_pct']:.2f}" if g.get("change_pct") is not None else ""),
                    ("gap_pct", f"{g['gap_pct']:.2f}" if g.get("gap_pct") is not None else ""),
                    ("float_m", f"{g['float_m']:.2f}" if g.get("float_m") is not None else ""),
                    ("sector", g.get("sector")),
                    ("industry", g.get("industry")),
                ):
                    if val not in (None, "", 0, "0", "0.0") and not row.get(key):
                        row[key] = val
                continue
            if row.get("awareness_status") == "SQUEEZE" or row.get("decision") == "MANUAL_REVIEW":
                # Keep the squeeze lane and its pill intact — the gainer fact now
                # travels on row["top_gainer"], so it no longer has to fight for
                # operator_pill and silently lose (INLF, 2026-07-28).
                row["awareness_status"] = "SQUEEZE"
                if not row.get("operator_pill"):
                    row["operator_pill"] = f"TOP GAINER · {g['change_pct_display']} · SQUEEZE"
            elif not row.get("awareness_status"):
                # Only claim the lane when nothing else has. Overwriting here used to
                # DOWNGRADE a scored runner (LVWR/POLA sat in HIGH_RVOL with a RUNNER
                # pill and were relabelled TOP_GAINER, 2026-07-28) — harmless while
                # prime_setups matched ~nothing, wrong now that the raw movers board
                # feeds a dozen already-scored names per run.
                row["awareness_status"] = "TOP_GAINER"
                if not row.get("operator_pill"):
                    row["operator_pill"] = pill
            row["operator_subtitle"] = row.get("operator_subtitle") or (
                row.get("disqualification_reason") or subtitle
            )
            row["operator_color_token"] = row.get("operator_color_token") or (
                "squeeze" if row.get("awareness_status") == "SQUEEZE" else "topGainer"
            )
            # Awareness metadata must never revoke tradeability the scanner granted on
            # its own evidence. Appearing on the raw Finviz gainers screen is not a
            # disqualification — force the flags only on rows the engine did not pass.
            if str(row.get("decision") or "").upper() not in ACTIONABLE_DECISIONS:
                row["not_tradeable"] = True
                row["not_validation_ready"] = True
            if row.get("disqualified") and row.get("disqualification_reason"):
                row["operator_tooltip_hints"] = [str(row["disqualification_reason"])[:120]]
            for key, val in (
                ("price", g.get("price")),
                ("rvol", g.get("rvol")),
                ("change_pct", f"{g['change_pct']:.2f}" if g.get("change_pct") is not None else ""),
                ("gap_pct", f"{g['gap_pct']:.2f}" if g.get("gap_pct") is not None else ""),
                ("float_m", f"{g['float_m']:.2f}" if g.get("float_m") is not None else ""),
                ("sector", g.get("sector")),
                ("industry", g.get("industry")),
            ):
                if val not in (None, "", 0, "0", "0.0") and not row.get(key):
                    row[key] = val
            continue

        src = g.get("source") or "prime_setups"
        detail = {
            "prime_setups": "Finviz prime_setups",
            "market_movers": "Finviz market movers (Home board)",
        }.get(src, "Finviz prime_setups + market movers")
        injected = {
            "symbol": sym,
            "score": 0,
            "grade": "AWARE",
            "decision": "AWARE",
            "rvol": float(g.get("rvol") or 0),
            "price": float(g.get("price") or 0),
            "volume": float(g.get("volume") or 0),
            "change_pct": f"{g['change_pct']:.2f}",
            "gap_pct": f"{g['gap_pct']:.2f}" if g.get("gap_pct") is not None else "",
            "float_m": f"{g['float_m']:.2f}" if g.get("float_m") is not None else "",
            "catalyst": g.get("company") or "Finviz top gainer",
            "catalyst_verified": False,
            "disqualified": False,
            "sector": g.get("sector") or "",
            "industry": g.get("industry") or "",
            "source": "screener",
            "source_detail": detail,
            "awareness_status": "TOP_GAINER",
            "operator_pill": pill,
            "operator_subtitle": subtitle if src == "prime_setups" else (
                "Leading Finviz gainer (Home movers board) — awareness only, outside "
                "the momentum-scalp filter; rvol/gap/float not carried by this source"
            ),
            "operator_color_token": "topGainer",
            "not_tradeable": True,
            "not_validation_ready": True,
        }
        _mark_top_gainer(injected, g)
        tickers.append(injected)
        by_sym[sym] = tickers[-1]

    return tagged