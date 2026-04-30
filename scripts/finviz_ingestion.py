"""finviz_ingestion.py — Finviz Elite CSV download and lineage tracking.

Fixes vs v10.0:
  - pick_active_screeners() now resolves union_of entries recursively so
    watchlist_refresh_seed (and any future derived-union screener) is no
    longer silently dropped.
  - include_groups=False added to groupby().apply() for pandas >= 2.2
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
import yaml


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def parse_num(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text or text == "-":
        return 0.0
    if text.endswith("%"):
        text = text[:-1]
    mult = 1.0
    suffix = text[-1:].upper() if text[-1:].isalpha() else ""
    if suffix == "B":
        mult = 1e9; text = text[:-1]
    elif suffix == "M":
        mult = 1e6; text = text[:-1]
    elif suffix == "K":
        mult = 1e3; text = text[:-1]
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    try:
        return float(cleaned) * mult
    except Exception:
        return 0.0


def normalize_finviz_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "Ticker": "symbol", "Company": "company", "Sector": "sector",
        "Industry": "industry", "Country": "country",
        "Price": "price", "Change": "change_percent",
        "Gap": "gap_percent", "Gap %": "gap_percent",
        "Volume": "volume", "Rel Volume": "relative_volume",
        "Relative Volume": "relative_volume", "Avg Volume": "avg_volume",
        "Average Volume": "avg_volume",
        "Market Cap": "market_cap", "Float": "float_shares",
        "Shs Float": "float_shares", "Shares Float": "float_shares",
        "ATR": "atr",
        "Premarket Price": "premarket_price",
        "Premarket Change": "premarket_change_percent",
        "Premarket Volume": "premarket_volume",
    }
    df = df.rename(columns=rename_map)
    numeric_cols = [
        "price", "change_percent", "gap_percent", "volume",
        "relative_volume", "avg_volume", "market_cap", "float_shares", "atr",
        "premarket_price", "premarket_change_percent", "premarket_volume",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].map(parse_num)
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    # Data quality gate: warn if critical scoring columns are missing or all-zero
    # Skip check if DataFrame is empty (no matching stocks at this time — normal pre-market)
    _required = ["relative_volume", "gap_percent", "float_shares"]
    if len(df) > 0:
        _missing = [c for c in _required if c not in df.columns]
        _zero = [c for c in _required if c in df.columns and df[c].sum() == 0]
        if _missing or _zero:
            _msg = f"⚠️ TRADE AI DATA QUALITY ALERT\nMissing: {_missing}\nAll-zero: {_zero}\n→ Scoring degraded. Check screeners.yaml uses v=152"
            print(f"  [finviz] ⚠️  DATA QUALITY: missing columns {_missing}, all-zero columns {_zero}")
            print(f"  [finviz]    → Scoring will be degraded. Check screeners.yaml uses v=152 (not v=111)")
            try:
                from telegram_alert import send_telegram
                send_telegram(_msg)
            except Exception:
                pass
    else:
        print(f"  [finviz] No matching stocks — this is normal pre-market / low-activity")
    return df


# ──────────────────────────────────────────────────────────────────────
# Screener selection — FIX: resolve union_of entries
# ──────────────────────────────────────────────────────────────────────

def pick_active_screeners(
    cfg: Dict[str, Any],
    run_label: str,
) -> Dict[str, Dict[str, Any]]:
    """Return the set of screeners that have a finviz_url for this run window.

    Handles derived-union screeners (those with union_of instead of
    finviz_url) by expanding them to their constituent screeners.
    """
    screeners: Dict[str, Any] = cfg.get("screeners", {})
    active_names: List[str] = (
        cfg.get("run_windows", {})
        .get(run_label, {})
        .get("active_screeners", [])
    )

    chosen: Dict[str, Dict[str, Any]] = {}

    def _resolve(name: str, depth: int = 0) -> None:
        """Recursively expand union_of entries."""
        if depth > 10:
            return  # guard against circular references
        entry = screeners.get(name)
        if not entry:
            return
        if entry.get("finviz_url"):
            chosen[name] = entry
        elif entry.get("union_of"):
            for child_name in entry["union_of"]:
                _resolve(child_name, depth + 1)
        # else: skip (no URL, no union — truly empty)

    for name in active_names:
        _resolve(name)

    return chosen


# ──────────────────────────────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": optional_env("FINVIZ_USER_AGENT", "Mozilla/5.0"),
        "Accept": "text/csv,*/*",
    })
    cookie = optional_env("FINVIZ_COOKIE")
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def finviz_export_url(url: str) -> str:
    if "export" in url:
        return url
    if "screener.ashx" in url:
        return url.replace("screener.ashx", "export")
    raise ValueError(f"Unsupported Finviz URL: {url}")


def download_screener_csvs(
    screeners: Dict[str, Dict[str, Any]],
    raw_dir: Path,
) -> List[Dict[str, Any]]:
    if not optional_env("FINVIZ_COOKIE"):
        raise RuntimeError("FINVIZ_COOKIE is required for live Finviz downloads.")
    import time
    session = make_session()
    rows: List[Dict[str, Any]] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i, (name, entry) in enumerate(screeners.items()):
        export_url = finviz_export_url(entry["finviz_url"])
        # Delay between requests to avoid Finviz 429 rate-limit
        # First request fires immediately; subsequent ones wait 1.5 seconds
        if i > 0:
            time.sleep(1.5)
        # Retry up to 3 times on 429
        for attempt in range(3):
            resp = session.get(export_url, timeout=60)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)   # 5s, 10s, 15s
                print(f"  [finviz] 429 on {name} — waiting {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError(f"Finviz 429 rate limit persisted after 3 retries for screener: {name}")
        # Guardrail: detect expired cookie (login page returned instead of CSV)
        content = resp.text
        if "login" in content.lower()[:500] or "sign in" in content.lower()[:500] or "Ticker" not in content[:200]:
            _msg = (f"🔴 *FINVIZ COOKIE EXPIRED*\n"
                    f"Screener `{name}` returned login page instead of CSV.\n\n"
                    f"To fix, reply:\n`update FINVIZ_COOKIE YOUR_NEW_COOKIE_VALUE`\n\n"
                    f"Get cookie from browser → elite.finviz.com → DevTools → Application → Cookies")
            print(f"  [finviz] ❌ Cookie expired! Login page returned for {name}")
            try:
                from telegram_alert import send_telegram
                send_telegram(_msg)
            except Exception:
                pass
            raise RuntimeError(f"Finviz cookie expired — login page returned for screener: {name}")

        path = raw_dir / f"{name}_{stamp}.csv"
        path.write_text(content, encoding="utf-8")
        rows.append({
            "name": name,
            "path": path,
            "meta": entry,
            "finviz_url": export_url,
        })
    return rows


# ──────────────────────────────────────────────────────────────────────
# Merge + lineage tracking
# ──────────────────────────────────────────────────────────────────────

def combine_and_track(
    downloads: List[Dict[str, Any]],
    run_label: str,
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    now = datetime.now().isoformat(timespec="seconds")

    for item in downloads:
        try:
            df = pd.read_csv(item["path"])
            df = normalize_finviz_columns(df)
            if df.empty:
                continue
            name = item["name"]
            meta = item["meta"]
            strategy_class = meta.get("strategy_class", "day_scalp")
            day_flag = str(strategy_class).lower() == "day_scalp"
            df["primary_source_list"] = name
            df["source_lists"] = name
            df["source_count"] = 1
            df["screener_name"] = name
            df["screener_group"] = meta.get("group", "unknown")
            df["run_window"] = run_label
            df["finviz_url_used"] = item["finviz_url"]
            df["ingestion_timestamp"] = now
            df["strategy_class"] = strategy_class
            df["day_scalping_flag"] = day_flag
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    if "symbol" not in merged.columns:
        return merged

    def _combine(group: pd.DataFrame) -> pd.Series:
        first = group.iloc[0].copy()
        source_lists = sorted({
            str(x) for x in group["source_lists"].dropna().tolist() if str(x)
        })
        strategy_classes = sorted({
            str(x) for x in group["strategy_class"].dropna().tolist() if str(x)
        })
        first["primary_source_list"] = source_lists[0] if source_lists else first.get("primary_source_list", "")
        first["source_lists"] = "|".join(source_lists)
        first["source_count"] = len(source_lists)
        first["strategy_class"] = "|".join(strategy_classes)
        first["day_scalping_flag"] = bool(group["day_scalping_flag"].fillna(False).any())
        return first

    merged = merged.groupby("symbol", as_index=False).apply(
        _combine, include_groups=False
    )
    if isinstance(merged.index, pd.MultiIndex):
        merged = merged.reset_index(drop=True)
    return merged


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def load_live_candidates(
    project_root: Path,
    run_label: str,
    date_str: str,
    output_dir: Path,
) -> Dict[str, Any]:
    cfg = load_yaml(project_root / "assets" / "screeners.yaml")
    active = pick_active_screeners(cfg, run_label)
    if not active:
        raise RuntimeError(f"No screener URLs resolved for run_label={run_label!r}.")

    raw_dir   = ensure_dir(project_root / cfg["storage"]["raw_dir"]    / date_str / run_label)
    merged_dir = ensure_dir(project_root / cfg["storage"]["merged_dir"] / date_str)
    logs_dir  = ensure_dir(project_root / cfg["storage"]["logs_dir"])

    downloads = download_screener_csvs(active, raw_dir)
    merged    = combine_and_track(downloads, run_label)

    merged_path = merged_dir / f"merged_{run_label}.csv"
    merged.to_csv(merged_path, index=False)

    summary = {
        "date": date_str,
        "run_label": run_label,
        "screeners_used": list(active.keys()),
        "downloaded_files": [str(x["path"]) for x in downloads],
        "rows_merged": int(len(merged)),
        "merged_path": str(merged_path),
    }
    summary_path = logs_dir / f"ingestion_summary_{date_str}_{run_label}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "downloads": downloads,
        "merged_path": str(merged_path),
        "summary_path": str(summary_path),
        "dataframe": merged,
    }
