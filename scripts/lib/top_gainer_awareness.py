"""Tag Finviz prime-setup leaders for operator awareness (never tradeable GO)."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path


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
        })

    parsed.sort(key=lambda r: r["change_pct"], reverse=True)
    return parsed[:limit]


def attach_top_gainer_awareness(tickers: list[dict], project_root: Path, *, limit: int = 10) -> list[str]:
    """Tag (or inject) awareness rows for Finviz top gainers. Returns symbol list."""
    gainers = load_finviz_top_gainers(project_root, limit=limit)
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
                row["awareness_status"] = "SQUEEZE"
                if not row.get("operator_pill") or "TOP GAINER" in str(row.get("operator_pill")):
                    row["operator_pill"] = f"TOP GAINER · {g['change_pct_display']} · SQUEEZE"
            else:
                row["awareness_status"] = "TOP_GAINER"
                if not row.get("operator_pill"):
                    row["operator_pill"] = pill
            row["operator_subtitle"] = row.get("operator_subtitle") or (
                row.get("disqualification_reason") or subtitle
            )
            row["operator_color_token"] = row.get("operator_color_token") or (
                "squeeze" if row.get("awareness_status") == "SQUEEZE" else "topGainer"
            )
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

        tickers.append({
            "symbol": sym,
            "score": 0,
            "grade": "AWARE",
            "decision": "AWARE",
            "rvol": float(g.get("rvol") or 0),
            "price": float(g.get("price") or 0),
            "change_pct": f"{g['change_pct']:.2f}",
            "gap_pct": f"{g['gap_pct']:.2f}" if g.get("gap_pct") is not None else "",
            "float_m": f"{g['float_m']:.2f}" if g.get("float_m") is not None else "",
            "catalyst": g.get("company") or "Finviz top gainer",
            "catalyst_verified": False,
            "disqualified": False,
            "sector": g.get("sector") or "",
            "industry": g.get("industry") or "",
            "source": "screener",
            "source_detail": "Finviz prime_setups",
            "awareness_status": "TOP_GAINER",
            "operator_pill": pill,
            "operator_subtitle": subtitle,
            "operator_color_token": "topGainer",
            "not_tradeable": True,
            "not_validation_ready": True,
        })
        by_sym[sym] = tickers[-1]

    return tagged