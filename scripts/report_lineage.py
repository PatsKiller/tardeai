"""report_lineage.py — report history, continuity deltas, and stable canonical exports.

Each new prospectus builds on the prior generation:
  - Archives versioned JSON under history/{SYMBOL}/
  - Publishes stable prospectus_{SYMBOL}_latest.{json,docx,pdf} paths
  - Supplies continuity context (price/rec/P&L deltas, prior call accuracy)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_OUT = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst"
HISTORY_DIR = REPORT_OUT / "history"
LINEAGE_INDEX_PATH = HISTORY_DIR / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default if default is not None else {}


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{_f(v):+.2f}%"


def _resolve_report_json(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    p = Path(str(path_str))
    if p.exists():
        return p
    s = str(path_str).lstrip("/")
    if s.startswith("data/"):
        candidate = PROJECT_ROOT / s
        if candidate.exists():
            return candidate
    name = Path(s).name
    if name:
        for base in (REPORT_OUT, HISTORY_DIR):
            for hit in base.rglob(name):
                if hit.is_file():
                    return hit
    return None


def load_lineage_index() -> dict:
    idx = _load_json(LINEAGE_INDEX_PATH, {"version": 1, "symbols": {}})
    if not isinstance(idx.get("symbols"), dict):
        idx["symbols"] = {}
    return idx


def save_lineage_index(idx: dict) -> None:
    idx["updated_at"] = _now_iso()
    _save_json(LINEAGE_INDEX_PATH, idx)


def _registry_key(report_type: str | None, symbol: str | None) -> str:
    return f"{report_type or 'unknown'}:{(symbol or '').upper()}"


def _export_url(path: Path) -> str:
    try:
        rel = path.relative_to(REPORT_OUT)
        return "/data/portfolios/reports/analyst/" + str(rel).replace("\\", "/")
    except ValueError:
        try:
            rel = path.relative_to(PROJECT_ROOT)
            return "/" + str(rel).replace("\\", "/")
        except ValueError:
            return str(path)


def canonical_export_paths(symbol: str, report_type: str = "symbol_holding") -> dict[str, Path]:
    sym = symbol.upper()
    if report_type == "symbol_watchlist":
        stem = f"watchlist_{sym}_latest"
    else:
        stem = f"prospectus_{sym}_latest"
    return {
        "json": REPORT_OUT / f"{stem}.json",
        "docx": REPORT_OUT / f"{stem}.docx",
        "pdf": REPORT_OUT / f"{stem}.pdf",
    }


def load_prior_report(
    symbol: str,
    report_type: str = "symbol_holding",
    *,
    registry_reports: list[dict] | None = None,
) -> dict | None:
    """Load the living prospectus JSON (latest file) or last history snapshot."""
    sym = symbol.upper()
    living = canonical_export_paths(sym, report_type)["json"]
    if living.exists():
        data = _load_json(living, None)
        if isinstance(data, dict) and data.get("meta"):
            return data

    idx = load_lineage_index()
    sym_row = (idx.get("symbols") or {}).get(sym) or {}
    generations = sym_row.get("generations") or []
    for gen in reversed(generations):
        if gen.get("report_type") and gen.get("report_type") != report_type:
            continue
        path = _resolve_report_json(gen.get("json_path"))
        if path:
            data = _load_json(path, None)
            if isinstance(data, dict) and data.get("meta"):
                return data

    if registry_reports:
        for row in registry_reports:
            if (row.get("symbol") or "").upper() != sym:
                continue
            if row.get("report_type") != report_type:
                continue
            ex = row.get("exports") or {}
            for key in ("json", "versioned_json"):
                path = _resolve_report_json(ex.get(key))
                if path:
                    data = _load_json(path, None)
                    if isinstance(data, dict) and data.get("meta"):
                        return data
    return None


def next_generation_number(symbol: str) -> int:
    sym = symbol.upper()
    idx = load_lineage_index()
    sym_row = (idx.get("symbols") or {}).get(sym) or {}
    return int(sym_row.get("generation_count") or 0) + 1


def compute_continuity(
    prior: dict | None,
    *,
    price: float,
    recommendation: str,
    unrealized_pnl_pct: float | None,
    thesis_status: str,
    fingerprint: str | None,
) -> dict:
    """Delta context vs prior report for synthesis sections."""
    if not prior:
        return {
            "first_report": True,
            "generation": 1,
            "content": "First analyst report on file for this symbol — future runs will track changes vs this baseline.",
            "bullets": ["Baseline established — subsequent reports will score prior call accuracy."],
            "metrics": {"prior_report": False},
        }

    prior_meta = prior.get("meta") or {}
    prior_kpis = prior_meta.get("kpis") or {}
    prior_price = _f(prior_kpis.get("price")) or None
    prior_rec = str(prior_kpis.get("recommendation") or "—")
    prior_pnl = prior_kpis.get("unrealized_pnl_pct")
    prior_thesis = str(prior_kpis.get("thesis_status") or "—")
    prior_fp = prior_meta.get("content_fingerprint")
    prior_date = str(prior_meta.get("generated_at") or "")[:10]
    gen = int(prior_meta.get("generation") or 1) + 1

    price_delta_pct = None
    if prior_price and prior_price > 0 and price > 0:
        price_delta_pct = (price - prior_price) / prior_price * 100

    pnl_delta = None
    if prior_pnl is not None and unrealized_pnl_pct is not None:
        pnl_delta = _f(unrealized_pnl_pct) - _f(prior_pnl)

    rec_changed = prior_rec.upper().split()[0] != str(recommendation).upper().split()[0]
    thesis_changed = prior_thesis != thesis_status
    data_changed = prior_fp != fingerprint if fingerprint else False

    accuracy = "Insufficient history"
    if price_delta_pct is not None:
        rec_u = prior_rec.upper()
        if any(x in rec_u for x in ("BUY", "ADD", "ACCUMULATE")):
            accuracy = "Helpful" if price_delta_pct >= 0 else "Adverse — price fell since prior ADD/BUY stance"
        elif any(x in rec_u for x in ("TRIM", "SELL", "REDUCE")):
            accuracy = "Helpful" if price_delta_pct <= 0 else "Adverse — price rose after trim/sell call"
        elif "HOLD" in rec_u:
            accuracy = "Neutral — hold call; price moved within normal band"
        else:
            accuracy = f"Prior stance {prior_rec}; price {_pct(price_delta_pct)} since last report"

    bullets = [
        f"Last report {prior_date or 'unknown'} · prior rec **{prior_rec}** · thesis **{prior_thesis}**",
    ]
    if price_delta_pct is not None:
        bullets.append(f"Price since last report: {_pct(price_delta_pct)} (${prior_price:,.2f} → ${price:,.2f})")
    if pnl_delta is not None:
        bullets.append(f"Personal unrealized P&L change: {_pct(pnl_delta)} (now {_pct(unrealized_pnl_pct)})")
    if rec_changed:
        bullets.append(f"Recommendation changed: {prior_rec} → {recommendation}")
    if thesis_changed:
        bullets.append(f"Thesis status changed: {prior_thesis} → {thesis_status}")
    if data_changed:
        bullets.append("Underlying intelligence fingerprint changed — material refresh warranted.")
    bullets.append(f"Prior call assessment: {accuracy}")

    content = (
        f"Generation {gen} builds on the {prior_date or 'prior'} report. "
        f"Since then, price moved {_pct(price_delta_pct)} and personal P&L shifted "
        f"{_pct(pnl_delta) if pnl_delta is not None else '—'}. "
        f"Prior recommendation was {prior_rec} ({accuracy})."
    )

    return {
        "first_report": False,
        "generation": gen,
        "content": content,
        "bullets": bullets,
        "metrics": {
            "prior_report_date": prior_date,
            "prior_recommendation": prior_rec,
            "prior_thesis_status": prior_thesis,
            "price_delta_pct": price_delta_pct,
            "pnl_delta_pct": pnl_delta,
            "recommendation_changed": rec_changed,
            "thesis_changed": thesis_changed,
            "prior_call_assessment": accuracy,
            "generation": gen,
        },
    }


def chart_continuity_points(symbol: str) -> list[dict]:
    """Price + recommendation at each archived generation (for continuity chart)."""
    sym = symbol.upper()
    points: list[dict] = []
    seen: set[str] = set()

    def _add_from_report(path: Path, date_hint: str) -> None:
        data = _load_json(path, None)
        if not isinstance(data, dict):
            return
        meta = data.get("meta") or {}
        kpis = meta.get("kpis") or {}
        price = kpis.get("price")
        if price is None:
            return
        date = str(meta.get("generated_at") or date_hint)[:10]
        if date in seen:
            return
        seen.add(date)
        points.append({
            "date": date,
            "price": _f(price),
            "recommendation": kpis.get("recommendation"),
        })

    living = canonical_export_paths(sym)["json"]
    if living.exists():
        _add_from_report(living, "")

    hist_dir = HISTORY_DIR / sym
    if hist_dir.exists():
        for p in sorted(hist_dir.glob("snapshot_*.json")):
            _add_from_report(p, p.stem.replace("snapshot_", "")[:8])
        for p in sorted(hist_dir.glob("*.json")):
            if p.name.startswith("snapshot_"):
                continue
            _add_from_report(p, p.stem[:8])

    idx = load_lineage_index()
    for gen in (idx.get("symbols") or {}).get(sym, {}).get("generations") or []:
        path = _resolve_report_json(gen.get("json_path"))
        if path:
            _add_from_report(path, str(gen.get("generated_at") or "")[:10])

    points.sort(key=lambda x: x["date"])
    return points[-12:]


def archive_snapshot_before_update(symbol: str, report_type: str = "symbol_holding") -> Path | None:
    """Snapshot the current living prospectus to history before in-place overwrite."""
    sym = symbol.upper()
    paths = canonical_export_paths(sym, report_type)
    src = paths["json"]
    if not src.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = HISTORY_DIR / sym / f"snapshot_{ts}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def stable_registry_id(symbol: str, report_type: str = "symbol_holding") -> str:
    sym = symbol.upper()
    if report_type == "symbol_watchlist":
        return f"watchlist_{sym}"
    return f"prospectus_{sym}"


def archive_report(
    report: dict,
    *,
    report_id: str,
    report_type: str,
    symbol: str,
    json_path: Path,
    fingerprint: str | None = None,
) -> dict:
    """Persist versioned JSON and update lineage index."""
    sym = symbol.upper()
    hist_sym = HISTORY_DIR / sym
    hist_sym.mkdir(parents=True, exist_ok=True)
    archived = hist_sym / f"{report_id}.json"
    shutil.copy2(json_path, archived)

    idx = load_lineage_index()
    symbols = idx.setdefault("symbols", {})
    row = symbols.setdefault(sym, {"generations": [], "generation_count": 0})
    gen_entry = {
        "id": report_id,
        "report_type": report_type,
        "generated_at": (report.get("meta") or {}).get("generated_at") or _now_iso(),
        "fingerprint": fingerprint,
        "recommendation": ((report.get("meta") or {}).get("kpis") or {}).get("recommendation"),
        "json_path": str(archived),
        "generation": (report.get("meta") or {}).get("generation"),
    }
    row["generations"] = (row.get("generations") or []) + [gen_entry]
    row["generations"] = row["generations"][-24:]
    row["generation_count"] = int(row.get("generation_count") or 0) + 1
    row["latest_id"] = report_id
    row["latest_at"] = gen_entry["generated_at"]
    save_lineage_index(idx)
    return gen_entry


def publish_canonical_exports(
    symbol: str,
    *,
    report_type: str,
    json_path: Path | None = None,
    docx_path: Path | None = None,
    pdf_path: Path | None = None,
) -> dict[str, str]:
    """Copy latest artifacts to stable prospectus_{SYMBOL}_latest.* URLs."""
    paths = canonical_export_paths(symbol, report_type)
    urls: dict[str, str] = {}
    for fmt, src, dest in (
        ("json", json_path, paths["json"]),
        ("docx", docx_path, paths["docx"]),
        ("pdf", pdf_path, paths["pdf"]),
    ):
        if src and Path(src).exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            src_p = Path(src).resolve()
            dest_p = dest.resolve()
            if src_p != dest_p:
                shutil.copy2(src_p, dest_p)
            urls[fmt] = _export_url(dest)
    return urls


def upsert_registry_reports(reports: list[dict], entry: dict) -> list[dict]:
    """Keep one canonical registry row per (report_type, symbol); newest first."""
    rtype = entry.get("report_type")
    sym = (entry.get("symbol") or "").upper() or None
    if rtype and sym:
        filtered = [
            r for r in reports
            if not (r.get("report_type") == rtype and (r.get("symbol") or "").upper() == sym)
        ]
    else:
        filtered = [r for r in reports if r.get("id") != entry.get("id")]
    filtered.insert(0, entry)
    return filtered[:500]


def canonical_registry_map(reports: list[dict], report_type: str | None = None) -> dict[str, dict]:
    """Newest registry entry per symbol (reports list is newest-first)."""
    out: dict[str, dict] = {}
    for r in reports:
        if report_type and r.get("report_type") != report_type:
            continue
        sym = (r.get("symbol") or "").upper()
        if sym and sym not in out:
            out[sym] = r
    return out