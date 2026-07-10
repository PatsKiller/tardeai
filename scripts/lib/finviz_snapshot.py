"""P5 Finviz snapshot reliability — nearest prime_setups file to scan time."""
from __future__ import annotations

import csv
import glob
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


_TS_RE = re.compile(r"prime_setups_(\d{8})_(\d{6})\.csv$", re.IGNORECASE)


def _parse_snapshot_ts(path: Path) -> datetime | None:
    m = _TS_RE.search(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def list_prime_setup_files(project_root: Path | str, trade_date: date) -> list[tuple[datetime, Path]]:
    root = Path(project_root)
    pattern = str(root / "data" / "raw" / "finviz" / str(trade_date) / "**" / "prime_setups_*.csv")
    out: list[tuple[datetime, Path]] = []
    for fp in glob.glob(pattern, recursive=True):
        p = Path(fp)
        ts = _parse_snapshot_ts(p)
        if ts:
            out.append((ts, p))
    out.sort(key=lambda x: x[0])
    return out


def nearest_prime_setup_file(
    project_root: Path | str,
    trade_date: date,
    reference: datetime | None = None,
) -> Path | None:
    files = list_prime_setup_files(project_root, trade_date)
    if not files:
        return None
    if reference is None:
        return files[-1][1]
    ref = reference.replace(tzinfo=None) if reference.tzinfo else reference
    best = min(files, key=lambda item: abs((item[0] - ref).total_seconds()))
    return best[1]


def _row_match(row: dict, symbol: str) -> bool:
    tick = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
    return tick == symbol.upper()


def lookup_finviz_symbol(
    project_root: Path | str,
    trade_date: date,
    symbol: str,
    *,
    reference: datetime | None = None,
    scan_row: dict | None = None,
) -> dict | None:
    """Find symbol in nearest prime_setups snapshot; fallback scan_row fields."""
    sym = symbol.upper()
    snap_path = nearest_prime_setup_file(project_root, trade_date, reference)
    if snap_path:
        try:
            with open(snap_path, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if _row_match(row, sym):
                        return {
                            "file": snap_path.name,
                            "snapshot_ts": _parse_snapshot_ts(snap_path),
                            "change_pct": row.get("Change") or row.get("Change%"),
                            "gap_pct": row.get("Gap") or row.get("Gap%"),
                            "rvol": row.get("Relative Volume") or row.get("RVOL"),
                            "price": row.get("Price"),
                            "source": "prime_setups",
                        }
        except Exception:
            pass

    files = list_prime_setup_files(project_root, trade_date)
    for _, fp in reversed(files):
        if snap_path and fp == snap_path:
            continue
        try:
            with open(fp, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if _row_match(row, sym):
                        return {
                            "file": fp.name,
                            "snapshot_ts": _parse_snapshot_ts(fp),
                            "change_pct": row.get("Change") or row.get("Change%"),
                            "gap_pct": row.get("Gap") or row.get("Gap%"),
                            "rvol": row.get("Relative Volume") or row.get("RVOL"),
                            "price": row.get("Price"),
                            "source": "prime_setups_fallback",
                        }
        except Exception:
            continue

    if scan_row:
        if any(scan_row.get(k) not in (None, "") for k in ("rvol", "gap_pct", "change_pct", "price", "volume")):
            return {
                "file": None,
                "snapshot_ts": scan_row.get("scanned_at"),
                "change_pct": scan_row.get("change_pct"),
                "gap_pct": scan_row.get("gap_pct"),
                "rvol": scan_row.get("rvol"),
                "price": scan_row.get("price"),
                "volume": scan_row.get("volume"),
                "source": "trade_ai_scans",
            }
    return None


def _list_finviz_csv_files(project_root: Path, trade_date: date) -> list[Path]:
    """All Finviz CSV exports for a day (prime_setups + screener lists)."""
    base = project_root / "data" / "raw" / "finviz" / str(trade_date)
    if not base.exists():
        return []
    return sorted(base.glob("**/*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_field_map(
    project_root: Path | str,
    field: str = "volume",
    *,
    trade_date: date | None = None,
) -> dict[str, float]:
    """Bulk symbol → numeric field from all Finviz CSV exports for the day."""
    root = Path(project_root)
    td = trade_date or date.today()
    files = _list_finviz_csv_files(root, td)
    if not files and td != date.today():
        files = _list_finviz_csv_files(root, date.today())
    if not files:
        files = [p for _, p in list_prime_setup_files(root, td)]
    col_map = {
        "volume": ("Volume", "volume"),
        "rvol": ("Relative Volume", "RVOL", "relative_volume"),
        "price": ("Price", "price"),
    }
    keys = col_map.get(field, (field,))
    out: dict[str, float] = {}
    for fp in files:
        try:
            with open(fp, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    sym = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
                    if not sym:
                        continue
                    raw = None
                    for k in keys:
                        if row.get(k) not in (None, ""):
                            raw = row.get(k)
                            break
                    if raw is None:
                        continue
                    try:
                        val = float(str(raw).replace(",", "").replace("%", "").replace("x", ""))
                        if val > 0:
                            out[sym] = val
                    except ValueError:
                        continue
        except Exception:
            continue
    return out