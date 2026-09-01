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
import time
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
    """Resolve secrets: Bitwarden SM tmpfs → os.environ → disk .env (never logs values)."""
    try:
        import sys as _sys
        _sec = Path(__file__).resolve().parent / "secrets"
        if str(_sec) not in _sys.path:
            _sys.path.insert(0, str(_sec))
        from resolve_secret import resolve_secret
        return resolve_secret(name, default)
    except Exception:
        # Last-resort fallback if resolver import fails (should be rare)
        val = os.getenv(name, "").strip()
        if val:
            return val
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        return default


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


_RATE_LIMITED_SCREENERS: list = []
_DQ_TELEGRAM_LAST: dict = {"ts": 0.0, "key": ""}
_DQ_TELEGRAM_COOLDOWN_SEC = 3600  # one DATA QUALITY Telegram per distinct issue / hour


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
    # Finviz often exports Rel Volume as 0 pre-market while Volume + Avg Volume are populated.
    # Backfill TOS-style RVOL (volume / avg_volume) before the quality gate so scoring isn't degraded
    # and we don't spam false "all-zero relative_volume" Telegram alerts.
    if "volume" in df.columns and "avg_volume" in df.columns:
        if "relative_volume" not in df.columns:
            df["relative_volume"] = 0.0
        _vol = df["volume"].fillna(0)
        _avg = df["avg_volume"].fillna(0)
        _rv = df["relative_volume"].fillna(0)
        _mask = (_rv == 0) & (_avg > 0) & (_vol > 0)
        if _mask.any():
            df.loc[_mask, "relative_volume"] = (_vol[_mask] / _avg[_mask]).round(2)
    # Data quality gate: warn if critical scoring columns are missing or all-zero
    # Skip check if DataFrame is empty (no matching stocks at this time — normal pre-market)
    _required = ["relative_volume", "gap_percent", "float_shares"]
    if len(df) > 0:
        _missing = [c for c in _required if c not in df.columns]
        # ETFs/funds legitimately have no float — exclude them from the float_shares all-zero check so
        # fund/index screeners (core_index_etfs, bond/income) stop tripping false Telegram alerts.
        _eq = df
        if "industry" in df.columns:
            _eq = df[~df["industry"].astype(str).str.contains("Exchange Traded Fund", case=False, na=False)]
        def _allzero(c):
            frame = _eq if c == "float_shares" else df
            return c in frame.columns and len(frame) > 0 and frame[c].sum() == 0
        _zero = [c for c in _required if _allzero(c)]
        if _missing or _zero:
            if _RATE_LIMITED_SCREENERS:
                _msg = (f"⚠️ TRADE AI DATA QUALITY ALERT\nFinviz RATE-LIMITED (429) this run: {_RATE_LIMITED_SCREENERS}\n"
                        f"Degraded columns: missing {_missing}, all-zero {_zero}\n→ Partial run; next scheduled run should recover.")
            else:
                _msg = f"⚠️ TRADE AI DATA QUALITY ALERT\nMissing: {_missing}\nAll-zero: {_zero}\n→ Scoring degraded. Check screeners.yaml uses v=152"
            print(f"  [finviz] ⚠️  DATA QUALITY: missing columns {_missing}, all-zero columns {_zero}"
                  + (f" (RATE-LIMITED: {_RATE_LIMITED_SCREENERS})" if _RATE_LIMITED_SCREENERS else ""))
            print(f"  [finviz]    → " + ("partial run due to Finviz 429s; next run should recover"
                  if _RATE_LIMITED_SCREENERS else "Scoring will be degraded. Check screeners.yaml uses v=152 (not v=111)"))
            try:
                _dq_key = f"m:{_missing}|z:{_zero}|rl:{bool(_RATE_LIMITED_SCREENERS)}"
                _now = time.time()
                if (_now - _DQ_TELEGRAM_LAST["ts"] >= _DQ_TELEGRAM_COOLDOWN_SEC
                        or _DQ_TELEGRAM_LAST["key"] != _dq_key):
                    from telegram_alert import send_telegram
                    if send_telegram(_msg):
                        _DQ_TELEGRAM_LAST.update({"ts": _now, "key": _dq_key})
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

def make_session(*, use_cookie: bool = True) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": optional_env("FINVIZ_USER_AGENT", "Mozilla/5.0"),
        "Accept": "text/csv,*/*",
    })
    if use_cookie:
        cookie = optional_env("FINVIZ_COOKIE")
        if cookie:
            session.headers["Cookie"] = cookie
    return session


def _append_auth_token(url: str, token: str) -> str:
    if not token or "auth=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}auth={token}"


def _csv_ok(resp: requests.Response | None) -> bool:
    return bool(resp and resp.status_code == 200 and "Ticker" in (resp.text or "")[:300])


def _login_page(resp: requests.Response | None) -> bool:
    body_l = ((resp.text if resp else "") or "")[:800].lower()
    return "login" in body_l or "sign in" in body_l


def finviz_export_url(url: str) -> str:
    """Convert screener URL to export URL. Ensure Elite v=152."""
    if "export" in url:
        return url
    if "screener.ashx" in url:
        url = url.replace("screener.ashx", "export")
    # Ensure Elite v=152 with custom columns
    if "elite.finviz.com" not in url:
        url = url.replace("https://finviz.com/", "https://elite.finviz.com/")
    for old_v in ["v=111", "v=121", "v=131", "v=141", "v=151"]:
        if old_v in url:
            url = url.replace(old_v, "v=152")
    if "&c=" not in url:
        url += "&c=0,1,2,3,4,5,6,7,25,61,63,64,65,66,67"
    return url


# Fallback version chain for download resilience
_FINVIZ_VERSION_FALLBACKS = ["v=152", "v=151", "v=141", "v=111"]


def _fetch_screener_export(
    export_url: str,
    name: str,
    *,
    use_cookie: bool,
    token: str,
) -> tuple[requests.Response | None, str, bool, bool]:
    """Try version fallbacks for one auth mode. Returns (resp, used_version, csv_ok, rate_limited)."""
    import time

    session = make_session(use_cookie=use_cookie)
    resp: requests.Response | None = None
    used_version = "v=152"
    csv_ok = False
    rate_limited = False
    auth_label = "cookie" if use_cookie else "token"
    for version in _FINVIZ_VERSION_FALLBACKS:
        try_url = export_url.replace("v=152", version) if version != "v=152" else export_url
        if not use_cookie and token:
            try_url = _append_auth_token(try_url, token)
        for attempt in range(3):
            try:
                from finviz_throttle import acquire as _fv_acquire
                _fv_acquire()
            except Exception:
                pass
            resp = session.get(try_url, timeout=60)
            if resp.status_code == 429:
                rate_limited = True
                wait = (10, 30, 60)[attempt]
                try:
                    from finviz_throttle import cooldown as _fv_cd
                    _fv_cd(float(resp.headers.get("Retry-After") or wait))
                except Exception:
                    pass
                print(
                    f"  [finviz] 429 on {name} ({auth_label}, {version}) "
                    f"— backing off {wait}s (attempt {attempt+1}/3)"
                )
                time.sleep(wait)
                continue
            rate_limited = False
            break
        if rate_limited:
            print(f"  [finviz] {name}: persistent rate-limit ({auth_label}) — skipping this screener this run")
            return None, used_version, False, True
        if _csv_ok(resp):
            used_version = version
            csv_ok = True
            return resp, used_version, True, False
        if version != "v=111":
            print(
                f"  [finviz] {name}: {auth_label} {version} failed "
                f"(HTTP {resp.status_code if resp else '?'}) → trying next version"
            )
    return resp, used_version, False, False


def download_screener_csvs(
    screeners: Dict[str, Dict[str, Any]],
    raw_dir: Path,
) -> List[Dict[str, Any]]:
    cookie = optional_env("FINVIZ_COOKIE")
    token = optional_env("FINVIZ_API_TOKEN")
    if not cookie and not token:
        raise RuntimeError("FINVIZ_COOKIE or FINVIZ_API_TOKEN is required for live Finviz downloads.")
    import time
    _RATE_LIMITED_SCREENERS.clear()   # per-run reset (long-lived processes reuse this module)
    rows: List[Dict[str, Any]] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i, (name, entry) in enumerate(screeners.items()):
        export_url = finviz_export_url(entry["finviz_url"])
        if i > 0:
            try:
                from finviz_throttle import acquire as _fv_acquire
                _fv_acquire()
            except Exception:
                time.sleep(3.5)
        resp = None
        used_version = "v=152"
        csv_ok = False
        rate_limited = False
        auth_used = "none"

        if cookie:
            resp, used_version, csv_ok, rate_limited = _fetch_screener_export(
                export_url, name, use_cookie=True, token=token,
            )
            auth_used = "cookie"
        if not csv_ok and not rate_limited and token and (not cookie or _login_page(resp) or not _csv_ok(resp)):
            if cookie and _login_page(resp):
                print(f"  [finviz] {name}: cookie auth returned login page — retrying with FINVIZ_API_TOKEN")
            elif not cookie:
                print(f"  [finviz] {name}: no FINVIZ_COOKIE — using FINVIZ_API_TOKEN")
            else:
                print(f"  [finviz] {name}: cookie auth failed — retrying with FINVIZ_API_TOKEN")
            resp, used_version, csv_ok, rate_limited = _fetch_screener_export(
                export_url, name, use_cookie=False, token=token,
            )
            if csv_ok:
                auth_used = "token"

        if rate_limited:
            _RATE_LIMITED_SCREENERS.append(name)
            continue
        if not resp or resp.status_code != 200:
            raise RuntimeError(f"Finviz download failed for {name} after all version fallbacks")
        if not csv_ok:
            if auth_used == "cookie" and _login_page(resp) and not token:
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
            print(f"  [finviz] {name}: no CSV header after version fallbacks (HTTP {resp.status_code}) "
                  f"— transient/rate-limit, skipping (not cookie expiry)")
            _RATE_LIMITED_SCREENERS.append(name)
            continue
        if used_version != "v=152":
            print(f"  [finviz] {name}: fell back to {used_version} (Elite v=152 unavailable)")
        content = resp.text

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
