#!/usr/bin/env python3
# phase3_lookthrough_fetcher.py
# Automated monthly refresh of fund look-through data.
# Sources: yfinance, ARK daily CSV, SEC EDGAR, Vanguard API.
# Falls back to last known good data + Telegram alert if stale.

from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

STALE_DAYS = 90          # alert threshold
TOP_N = 25               # top N holdings to capture
SLEEP_BETWEEN = 1.5      # seconds between API calls

# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _load_env(root: Path):
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env", override=False)
    except Exception:
        pass


def _telegram_alert(msg: str, root: Path):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    text = f"📊 Portfolio Look-Through Alert\n{msg}"
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        ok = bool(send_telegram(text))
        try:
            project_root = str(root)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="phase3_lookthrough_fetcher",
                subject_key="ops:lookthrough",
                retention_class="operational", severity="warning",
                sanitized_body=text[:500], short_summary=text[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if ok:
            print(f"  [telegram] sent: {msg[:60]}")
        else:
            print(f"  [telegram] send_telegram returned False: {msg[:60]}")
    except Exception as e:
        # ALARM-DELIVERY-DECLARED: best-effort advisory notify after chokepoint migration; never blocks caller
        print(f"  [telegram] failed: {e}")


def _days_old(date_str: str) -> int:
    try:
        d = date.fromisoformat(date_str)
        return (date.today() - d).days
    except Exception:
        return 9999


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _fetch_yfinance(ticker: str) -> dict:
    """
    Fetch sector weights + top 25 holdings from yfinance.
    Returns {sector_weights: {}, top_holdings: [], fetched_date, source}.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        # Sector weights — stored as list of dicts in yfinance
        sector_weights = {}
        raw_sectors = info.get("sectorWeightings", []) or []
        if isinstance(raw_sectors, list):
            for item in raw_sectors:
                if isinstance(item, dict):
                    for sector, weight in item.items():
                        # yfinance returns as decimal (0.258 = 25.8%)
                        sector_weights[sector] = round(float(weight) * 100, 2)
        elif isinstance(raw_sectors, dict):
            for sector, weight in raw_sectors.items():
                sector_weights[sector] = round(float(weight) * 100, 2)

        # Top holdings
        top_holdings = []
        raw_holdings = info.get("holdings", []) or []
        for h in raw_holdings[:TOP_N]:
            if isinstance(h, dict):
                sym = h.get("symbol") or h.get("ticker") or ""
                name = h.get("holdingName") or h.get("name") or ""
                pct = float(h.get("holdingPercent", 0) or 0) * 100
                if sym or name:
                    top_holdings.append({
                        "ticker": sym,
                        "name": name,
                        "pct": round(pct, 2)
                    })

        # Normalize sector names to match portfolio standard
        sector_weights = _normalize_sectors(sector_weights)

        return {
            "sector_weights": sector_weights,
            "top_holdings": top_holdings,
            "fetched_date": date.today().isoformat(),
            "data_source": f"yfinance_{ticker}",
        }
    except Exception as e:
        print(f"  [yfinance] {ticker} failed: {e}")
        return {}


def _normalize_sectors(raw: dict) -> dict:
    """Map yfinance sector names to portfolio standard names."""
    mapping = {
        "realestate": "Real Estate",
        "real estate": "Real Estate",
        "technology": "Technology",
        "information technology": "Technology",
        "communicationservices": "Communication Services",
        "communication services": "Communication Services",
        "consumer cyclical": "Consumer Cyclical",
        "consumercyclical": "Consumer Cyclical",
        "consumer discretionary": "Consumer Cyclical",
        "financial services": "Financial Services",
        "financials": "Financial Services",
        "healthcare": "Healthcare",
        "health care": "Healthcare",
        "consumer defensive": "Consumer Defensive",
        "consumer staples": "Consumer Defensive",
        "consumerdefensive": "Consumer Defensive",
        "industrials": "Industrials",
        "energy": "Energy",
        "utilities": "Utilities",
        "basic materials": "Basic Materials",
        "materials": "Basic Materials",
        "fixed income": "Fixed Income",
    }
    normalized = {}
    for k, v in raw.items():
        key = k.lower().strip()
        standard = mapping.get(key, k)
        normalized[standard] = normalized.get(standard, 0) + v
    return normalized


# ── ARK daily CSV fetch ───────────────────────────────────────────────────────

def _fetch_ark(ark_symbol: str) -> dict:
    """
    Fetch ARK fund holdings from their public daily CSV.
    ARK publishes at: https://ark-funds.com/wp-content/uploads/funds-etf-csv/{SYMBOL}_holdings.csv
    """
    try:
        import urllib.request, csv, io
        url = f"https://ark-funds.com/wp-content/uploads/funds-etf-csv/{ark_symbol}_holdings.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        text = resp.read().decode("utf-8", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        top_holdings = []
        sector_tally = {}

        for i, row in enumerate(reader):
            ticker = (row.get("ticker") or row.get("TICKER") or "").strip()
            name = (row.get("company") or row.get("COMPANY") or "").strip()
            weight = row.get("weight(%)") or row.get("WEIGHT (%)") or row.get("weight") or "0"
            try:
                pct = float(str(weight).replace("%", "").strip())
            except Exception:
                pct = 0.0

            if i < TOP_N and (ticker or name):
                top_holdings.append({
                    "ticker": ticker,
                    "name": name,
                    "pct": round(pct, 2)
                })

        # ARK doesn't publish sector weights directly — derive from known sectors
        # Return top holdings and let sector resolver handle it
        return {
            "top_holdings": top_holdings,
            "sector_weights": {},  # fetcher will use existing seed
            "fetched_date": date.today().isoformat(),
            "data_source": f"ark_daily_csv_{ark_symbol}",
        }
    except Exception as e:
        print(f"  [ark_csv] {ark_symbol} failed: {e}")
        return {}


# ── SEC EDGAR fetch ───────────────────────────────────────────────────────────

def _fetch_sec_edgar(cik: str, fund_name: str) -> dict:
    """
    Fetch most recent N-CSR or N-CSRS filing from SEC EDGAR.
    Attempts to extract sector weights from filing text.
    """
    try:
        import urllib.request, json as _json
        # Get most recent filing list
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "portfolio-intelligence admin@local.com"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = _json.loads(resp.read())

        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        # Find most recent N-CSR or N-CSRS
        for form, fdate, acc in zip(forms, dates, accessions):
            if form in ("N-CSR", "N-CSRS", "N-CSRS/A"):
                print(f"  [sec_edgar] found {form} dated {fdate} for {fund_name}")
                # Note: full parsing would require fetching the document
                # Return metadata only — sector parsing is complex
                return {
                    "fetched_date": date.today().isoformat(),
                    "data_source": f"sec_edgar_{form}_{fdate}",
                    "sec_filing_date": fdate,
                    "sec_form": form,
                    "sec_accession": acc,
                    "sector_weights": {},  # keep existing seed
                    "top_holdings": [],
                }
        print(f"  [sec_edgar] no N-CSR found for CIK {cik}")
        return {}
    except Exception as e:
        print(f"  [sec_edgar] {fund_name} CIK {cik} failed: {e}")
        return {}


# ── Main refresh loop ─────────────────────────────────────────────────────────

def refresh_all(project_root: Path, force: bool = False) -> dict:
    _load_env(project_root)
    state_dir = project_root / "data" / "portfolios" / "state"
    log_dir = project_root / "logs" / "phase3"
    log_dir.mkdir(parents=True, exist_ok=True)

    lookthrough_path = state_dir / "fund_lookthrough.json"
    data = _safe_json(lookthrough_path, {})
    if not data:
        print("ERROR: fund_lookthrough.json not found or empty")
        return {}

    meta = data.get("_meta", {})
    results = {"refreshed": [], "skipped": [], "stale_alerts": [], "failed": []}

    for symbol, entry in data.items():
        if symbol == "_meta":
            continue

        fetched_date = entry.get("fetched_date", "2000-01-01")
        age = _days_old(fetched_date)
        auto_fetchable = entry.get("auto_fetchable", False)
        fetch_method = entry.get("fetch_method", "none")
        next_refresh = entry.get("next_refresh", "2000-01-01")

        # Skip if not yet due and not forced
        if not force and date.today().isoformat() < next_refresh:
            print(f"  SKIP {symbol}: not due until {next_refresh}")
            results["skipped"].append(symbol)
            continue

        print(f"\n  Refreshing {symbol} [{fetch_method}] age={age}d ...")

        fetched = {}

        if fetch_method == "yfinance_direct":
            fetched = _fetch_yfinance(symbol)
            time.sleep(SLEEP_BETWEEN)

        elif fetch_method == "yfinance_proxy":
            proxy = entry.get("proxy_ticker", "")
            if proxy:
                fetched = _fetch_yfinance(proxy)
                time.sleep(SLEEP_BETWEEN)

        elif fetch_method == "sp500_proxy":
            fetched = _fetch_yfinance("SPY")
            time.sleep(SLEEP_BETWEEN)

        elif fetch_method == "ark_csv":
            ark_sym = entry.get("ark_fund_symbol", symbol)
            fetched = _fetch_ark(ark_sym)
            time.sleep(SLEEP_BETWEEN)

        elif fetch_method == "sec_edgar":
            cik = entry.get("sec_cik", "")
            if cik:
                fetched = _fetch_sec_edgar(cik, entry.get("fund_name", symbol))
            time.sleep(SLEEP_BETWEEN)

        elif fetch_method == "telegram_alert_if_stale":
            if age > STALE_DAYS:
                msg = (f"⚠️ {symbol} ({entry.get('fund_name','')}) sector data is "
                       f"{age} days old. Cannot auto-fetch. Please update manually in "
                       f"data/portfolios/state/fund_lookthrough.json")
                _telegram_alert(msg, project_root)
                results["stale_alerts"].append({"symbol": symbol, "age_days": age})
            results["skipped"].append(symbol)
            continue

        elif fetch_method == "none":
            results["skipped"].append(symbol)
            continue

        # Merge fetched data into entry
        if fetched:
            # Update sector weights only if we got real data
            if fetched.get("sector_weights"):
                entry["sector_weights"] = fetched["sector_weights"]

            # Update top holdings only if we got real data
            if fetched.get("top_holdings"):
                entry["top_holdings"] = fetched["top_holdings"][:TOP_N]

            entry["fetched_date"] = fetched.get("fetched_date", date.today().isoformat())
            entry["data_source"] = fetched.get("data_source", entry.get("data_source", ""))

            # Set next refresh to first of next month
            next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
            entry["next_refresh"] = next_month.isoformat()

            data[symbol] = entry
            results["refreshed"].append(symbol)
            print(f"  ✓ {symbol}: {len(entry.get('sector_weights',{}))} sectors, "
                  f"{len(entry.get('top_holdings',[]))} holdings")
        else:
            results["failed"].append(symbol)
            print(f"  ✗ {symbol}: fetch failed, keeping existing data")

            # Alert if stale despite failure
            if age > STALE_DAYS:
                msg = (f"⚠️ {symbol} ({entry.get('fund_name','')}) auto-fetch failed "
                       f"and data is {age} days old. Manual update needed.")
                _telegram_alert(msg, project_root)
                results["stale_alerts"].append({"symbol": symbol, "age_days": age})

    # Save updated lookthrough data
    data["_meta"] = meta
    data["_meta"]["last_run"] = datetime.now().isoformat()
    data["_meta"]["last_run_results"] = results
    lookthrough_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # Save run log
    log_path = log_dir / f"lookthrough_refresh_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    log_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print(f"\n[phase3_lookthrough] Done.")
    print(f"  Refreshed : {len(results['refreshed'])} — {results['refreshed']}")
    print(f"  Skipped   : {len(results['skipped'])}")
    print(f"  Failed    : {len(results['failed'])} — {results['failed']}")
    print(f"  Stale alerts: {len(results['stale_alerts'])}")
    print(f"  Written: {lookthrough_path}")
    return results


def main():
    ap = argparse.ArgumentParser(description="Phase 3 fund look-through fetcher")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--force", action="store_true", help="Force refresh all funds regardless of next_refresh date")
    ap.add_argument("--symbol", help="Refresh only this symbol")
    args = ap.parse_args()
    project_root = Path(args.project_root)

    if args.symbol:
        # Single symbol refresh
        state_dir = project_root / "data" / "portfolios" / "state"
        _load_env(project_root)
        lookthrough_path = state_dir / "fund_lookthrough.json"
        data = _safe_json(lookthrough_path, {})
        sym = args.symbol.upper()
        if sym not in data:
            print(f"ERROR: {sym} not found in fund_lookthrough.json")
            sys.exit(1)
        # Force refresh this one
        data[sym]["next_refresh"] = "2000-01-01"
        lookthrough_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    refresh_all(project_root, force=args.force)


if __name__ == "__main__":
    main()
