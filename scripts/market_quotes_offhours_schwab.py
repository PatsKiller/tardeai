#!/usr/bin/env python3
"""Schwab off-hours market-data quotes for the Market Risk Engine: index futures, indices, extended-hours prices.

OFF BY DEFAULT (``schwab.enabled: false`` in config/market_risk_offhours_quotes.yaml). It depends on AGENTS.md 28.2.0
(PR #2407, PROPOSED, not ratified), which would let host lanes read broker MARKET DATA. Until the operator ratifies
28.2.0, grants the §7A row (schwab provider supplies quotes) and activates the lane in session (§25.10.2), every live
invocation stops at ``disabled`` before any Schwab module is imported.

What it reads: GET ``/marketdata/v1/quotes`` only (the host in ``schwab.marketdata_base_url``; any other URL is
refused), with the access token from the Schwab token manager's public read API (``get_access_token``). It does not
import ``schwab_transport`` (the module that also carries the order surface), never touches an account, order, stop,
2FA or auth-flow endpoint, and never reads a credential file itself. ``config/schwab_access_mode.yaml`` must allow
reads. Rows go to ``market_quotes`` as source ``schwab`` through the one writer
(scripts/lib/writers/market_quotes_writer.py).

    python3 scripts/market_quotes_offhours_schwab.py --probe                 # availability, no Schwab call
    python3 scripts/market_quotes_offhours_schwab.py --dry-run --fixture F   # parse a recorded payload; no DB, no net
    python3 scripts/market_quotes_offhours_schwab.py --apply                 # live (only when enabled)

A dry run is fixtures-only: without ``--fixture`` it refuses rather than call Schwab.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import offhours_quotes as oq  # noqa: E402

QUOTES_PATH = "quotes"


def marketdata_url(cfg: dict) -> str:
    """The one URL this lane may GET. Refuses anything that is not the Schwab market-data host path."""
    base = str((cfg.get("schwab") or {}).get("marketdata_base_url") or "")
    if not base.startswith("https://api.schwabapi.com/marketdata/v1/"):
        raise ValueError(f"refused: {base!r} is not the Schwab market-data API")
    return base + QUOTES_PATH


def live_fetch(symbols: list[str], cfg: dict) -> dict:
    """Live Schwab quotes. Only reached with schwab.enabled true and --apply; never in a dry run or a test."""
    from lib import schwab_access_mode as sam

    if not sam.reads_allowed():
        sam.log_skip("market_quotes_offhours_schwab")
        return {"_status": sam.PAUSED_STATUS, "_detail": f"schwab_access_mode={sam.mode()}"}
    import requests
    import schwab_token_manager as tm  # public read API only: canonical_token_key, get_access_token

    url = marketdata_url(cfg)
    key = tm.canonical_token_key()
    token = tm.get_access_token(key) if key else None
    if not token:
        return {"_status": "no_token", "_detail": "token manager returned no access token (fail closed)"}
    out: dict = {}
    size = int((cfg.get("schwab") or {}).get("batch_size", 100))
    for i in range(0, len(symbols), size):
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                         params={"symbols": ",".join(symbols[i:i + size]), "fields": "quote,extended,regular",
                                 "indicative": "false"}, timeout=20)
        if r.status_code != 200:
            if tm.is_auth_failure(r.text):
                tm.record_auth_failure(r.text[:200], source="market_quotes_offhours_schwab")
            print(f"  [schwab-offhours] HTTP {r.status_code} on batch {i}")
            continue
        body = r.json()
        if isinstance(body, dict):
            out.update(body)
    return out


def probe(cfg: dict) -> dict:
    """Availability without calling Schwab: switch, policy dependency, window, URL rail, modules present."""
    now = datetime.now(timezone.utc)
    ok, why = oq.schwab_window(now, cfg)
    s = cfg.get("schwab") or {}
    try:
        url, url_ok = marketdata_url(cfg), True
    except ValueError as exc:
        url, url_ok = str(exc), False
    universe, prov = oq.resolve_universe(cfg)
    return {"schema": "OffHoursQuoteProbe@v1", "provider": "schwab", "enabled": bool(s.get("enabled")),
            "requires_policy": s.get("requires_policy"), "window_now": why, "in_window_now": ok,
            "marketdata_url": url, "url_rail_ok": url_ok,
            "token_manager_present": importlib.util.find_spec("schwab_token_manager") is not None,
            "symbols": oq.schwab_symbols(cfg, universe), "universe_missing_refs": prov["missing_refs"],
            "live_call_made": False}


def _write(rows: list[dict]):
    from db_adapter import _get_conn
    from lib.writers.market_quotes_writer import write_market_quotes

    conn = _get_conn()
    try:
        rc = write_market_quotes(conn.cursor(), rows, source="schwab")
        conn.commit()
        return rc
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--fixture", help="recorded /marketdata/v1/quotes payload (dry run)")
    ap.add_argument("--now", help="ISO time with offset, pins the clock (dry run)")
    ap.add_argument("--force-window", action="store_true", help="ignore the ET window (dry run only)")
    ap.add_argument("--config", help="alternate config path")
    a = ap.parse_args(argv)
    cfg = oq.load_config(a.config)
    if a.probe:
        print(json.dumps(probe(cfg), indent=1))
        return 0
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    if a.dry_run:
        if not a.fixture:
            print(json.dumps({"status": "refused", "detail": "dry run is fixtures-only: pass --fixture"}))
            return 2
        doc = json.loads(Path(a.fixture).read_text(encoding="utf-8"))
        dry_cfg = {**cfg, "schwab": {**cfg["schwab"], "enabled": True}}  # parse path only; no Schwab, no DB
        r = oq.run("schwab", cfg=dry_cfg, now=now, fetch=lambda _s: doc.get("quotes", doc), write=None,
                   dry_run=True, force_window=a.force_window)
        r["config_enabled"] = bool(cfg["schwab"].get("enabled"))
        print(json.dumps(r, default=str, indent=1))
        return 0
    r = oq.run("schwab", cfg=cfg, now=now, fetch=lambda syms: live_fetch(syms, cfg), write=_write, dry_run=False)
    print(json.dumps(r, default=str, indent=1))
    return 0 if r.get("status") in ("ok", "disabled", "outside_window", "schwab_paused") else 1


if __name__ == "__main__":
    raise SystemExit(main())
