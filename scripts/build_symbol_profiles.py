#!/usr/bin/env python3
"""build_symbol_profiles.py — one-sentence company profiles + sector for watch-grade symbols.

Feeds the unified card layer (operator 2026-06-12): every watchlist / open-trades / portfolio card
shows what the company DOES, its sector, and sector-relative performance. Source: yfinance
longBusinessSummary (first sentence, display-sized) + sector/industry. Proxy-mapped fund codes get
their asset-class label. Refresh: only missing or >30d-old rows (profiles barely change).

  python3 scripts/build_symbol_profiles.py [--symbols X,Y] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ONE write module per store (AGENTS.md §7A). This file is the registry's writer_target for
# symbol_identity; the SQL itself lives in lib/writers/symbol_profiles_writer.py and is
# re-exported here so every producer can `from build_symbol_profiles import upsert_profile`.
from lib.writers.symbol_profiles_writer import (  # noqa: E402,F401  (re-export)
    EARNINGS_NONE,
    EARNINGS_SCHEDULED,
    EARNINGS_UNKNOWN,
    LANES,
    WriteReceipt,
    earnings_state_for,
    resolve_subject_guid,
    upsert_profile,
    write_earnings,
    write_symbol_profiles,
)


# ETFs have no sector in yfinance .info — give the card a real sector so it shows sector + vs-sector.
# Mirrors open_trades_intelligence._ETF_SECTOR (reference data, kept in sync).
_ETF_SECTOR = {
    "XLK": "Technology",
    "XLF": "Financial",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLP": "Consumer Defensive",
    "XLY": "Consumer Cyclical",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "BND": "Fixed Income",
    "AGG": "Fixed Income",
    "TLT": "Fixed Income",
    "BNDX": "Fixed Income",
    "LQD": "Fixed Income",
    "JEPI": "Income / Covered Call",
    "JEPQ": "Income / Covered Call",
    "SCHD": "Dividend Equity",
    "DGRO": "Dividend Equity",
    "VYM": "Dividend Equity",
    "DIV": "Dividend Equity",
    "SCHG": "Growth Equity",
    "SPY": "Broad Equity",
    "VOO": "Broad Equity",
    "VTI": "Broad Equity",
    "QQQ": "Broad Equity",
    "IWM": "Broad Equity",
    "ARKG": "Healthcare",
    "ARKK": "Innovation",
    "ARKQ": "Innovation",
    "ARKW": "Innovation",
    "ARKF": "Innovation",
}

# Open-end mutual funds have no single GICS sector in yfinance either — give them an asset-class label
# so the card's sector slot isn't blank (Morningstar-style category, not a GICS sector → no vs-sector).
_FUND_SECTOR = {
    "FCNTX": "Large-Cap Growth Fund",
    "TILCX": "Large-Cap Growth Fund",
    "AMANX": "Equity Income Fund",
    "VFTNX": "Large-Cap Equity Fund (ESG)",
    "ABSZX": "Small/Mid-Cap Equity Fund",
}


def _two_line_summary(text, maxlen=300):
    """First TWO sentences of the business summary — a ~two-line 'what the company does' blurb."""
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    s = " ".join(parts[:2]).strip() if parts else ""
    if not s:
        return None
    return (s[: maxlen - 1] + "…") if len(s) > maxlen else s


def _finviz_map(symbols, root="."):
    """Batch Finviz sector/industry/company for plain tickers — the fallback when yfinance is
    rate-limited (it provides no business summary, so we synthesize a one-liner from company+industry)."""
    plain = [s for s in symbols if re.fullmatch(r"[A-Z]{1,5}", s)]
    if not plain:
        return {}
    try:
        import finviz_enrichment as fe

        return fe.enrich_tickers(plain, project_root=root) or {}
    except Exception as e:
        print(f"  [finviz fallback] error: {str(e)[:80]}")
        return {}


def _profile_lane() -> dict:
    """profile_lane in config/opportunity_conviction.yaml (CIO-ranked coverage + stub retry). {} when absent."""
    try:
        import yaml

        cfg = yaml.safe_load((PROJECT_ROOT / "config" / "opportunity_conviction.yaml").read_text(encoding="utf-8"))
        return (cfg or {}).get("profile_lane") or {}
    except Exception:
        return {}


def _cio_ranked(top_n: int) -> list[str]:
    """The CIO projection's top_n ranked symbols, best rank first. [] when the projection is unreadable."""
    if top_n <= 0:
        return []
    try:
        from lib.cio_opportunity_store import CIOOpportunityStore

        items = CIOOpportunityStore().read_projection().get("items") or {}
        ranked = sorted(
            (a["rank"], s.upper())
            for s, a in items.items()
            if isinstance(a, dict) and a.get("rank") and a["rank"] <= top_n
        )
        return [s for _, s in ranked if re.fullmatch(r"[A-Z]{1,5}", s)]
    except Exception:
        return []


def run(symbols=None, force=False, watchlist_top=0, dry_run=False):
    """Profile the stale watch-grade universe. Returns the summary dict it prints.

    dry_run: compute the universe and the stale list from the DB (SELECTs only) and report what a
    real run would fetch and upsert, then return BEFORE yfinance/Finviz are imported or called and
    before any upsert/commit is reachable (AGENTS.md §6).
    """
    from db_adapter import _get_conn
    import watch_universe as wu
    from holding_proxies import HOLDING_PROXY_MAP

    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    cur = conn.cursor()
    uni = set(s.upper() for s in symbols) if symbols else (wu.symbols(cur) | set(HOLDING_PROXY_MAP))
    # operator 2026-06-18: also cover the top watchlist names so their cards get sector/description
    # (the unified card layer was blank for AI-discovered names — only watch_universe was profiled).
    if watchlist_top and not symbols:
        cur.execute(
            """SELECT symbol FROM watchlist_items WHERE status<>'removed' AND symbol ~ '^[A-Z]{1,5}$'
                       ORDER BY hermes_rank ASC NULLS LAST LIMIT %s""",
            (watchlist_top,),
        )
        uni |= {r[0].upper() for r in cur.fetchall()}
    lane = _profile_lane() if not symbols else {}
    ranked = _cio_ranked(int(lane.get("top_n") or 0)) if lane.get("enabled") else []
    uni |= set(ranked)
    uni = sorted(uni)
    if not force:
        # A Finviz-synthesized one-liner ("Ceva Inc — Semiconductors.") is written when yfinance comes back empty;
        # it is a stand-in, not a description, so it is retried after stub_retry_days instead of counting as fresh
        # for 30 days (operator 2026-10-08: the opportunity modal said nothing about what the company does — 1,074
        # profiles were stubs that had never been retried). Retries are capped per run, CIO top-ranked first.
        cur.execute(
            """SELECT symbol FROM symbol_profiles
                       WHERE updated_at > now() - interval '30 days' AND description_1s IS NOT NULL
                         AND (COALESCE(source, '') <> 'finviz'
                              OR updated_at > now() - make_interval(days => %s))""",
            (int(lane.get("stub_retry_days") or 30),),
        )
        fresh = {r[0] for r in cur.fetchall()}
        stale = [s for s in uni if s not in fresh]
        cap = int(lane.get("stub_retry_max") or 0)
        if cap:
            cur.execute("SELECT symbol FROM symbol_profiles WHERE COALESCE(source, '') = 'finviz'")
            stubs = {r[0] for r in cur.fetchall()}
            order = {s: i for i, s in enumerate(ranked)}
            retry = sorted((s for s in stale if s in stubs), key=lambda s: (order.get(s, len(order)), s))[:cap]
            stale = [s for s in stale if s not in stubs] + retry
        uni = sorted(stale)
    if not uni:
        out = {"status": "fresh", "updated": 0, "checked": 0}
        if dry_run:
            out["mode"] = "dry_run"
        conn.rollback()  # end the read transaction (nothing was written)
        out["output"] = _output(produced=0, attempted=0, skipped={}, empty_reason="no_stale_symbols")
        print(json.dumps(out))
        return out
    if dry_run:
        proxies = [s for s in uni if s in HOLDING_PROXY_MAP and not re.fullmatch(r"[A-Z]{1,5}", s)]
        fetch = [s for s in uni if s not in proxies]
        out = {
            "mode": "dry_run",
            "checked": len(uni),
            "would_upsert_proxy_labels": len(proxies),
            "would_fetch": len(fetch),
            "sample": fetch[:25],
            "would_write": {"table": "symbol_profiles", "max_rows": len(uni)},
            # A dry run produces nothing by definition; attempted_count is what a real run would try.
            "output": _output(produced=0, attempted=len(uni), skipped={}, empty_reason="dry_run"),
        }
        conn.rollback()  # end the read transaction; nothing was written
        print(json.dumps(out))
        return out
    # ── Real run: no transaction may stay open across a network call ─────────────────────────────────
    # 2026-10-15 lane repair. Every failure in logs/symbol_profiles*.log since 09-20 is the first upsert after the
    # Finviz batch: psycopg2.OperationalError "SSL connection has been closed unexpectedly", or LockNotAvailable.
    # db_adapter sets idle_in_transaction_session_timeout = 120s (the role sets 2min); the SELECTs above opened a
    # transaction that stayed open through _finviz_map (6 views x hundreds of tickers) and the per-symbol yfinance
    # calls, so the server killed the session before the first write. The one long transaction also held every
    # upserted row lock until the final commit, so a concurrent profile writer hit lock_timeout (3s).
    # Now: the read transaction ends here, before any provider call; each symbol's upsert is its own short
    # transaction; a dropped connection is rebuilt; a lock timeout is retried once, then skipped with a reason.
    conn.rollback()
    import yfinance as yf

    fvz = _finviz_map(uni)  # batch Finviz once (sector/industry/company)
    retry_sleep = float(lane.get("db_lock_retry_sleep_s") or _DB_LOCK_RETRY_SLEEP_S)
    updated = missed = fvz_used = rejected = 0
    skipped: dict[str, int] = {}
    for sym in uni:
        if sym in HOLDING_PROXY_MAP and not re.fullmatch(r"[A-Z]{1,5}", sym):
            etf, label = HOLDING_PROXY_MAP[sym]
            # proxy_label owns description + sector only; an existing industry is left alone.
            fields = {"description_1s": f"Retirement-plan fund — {label} (tracked via {etf} proxy).", "sector": label}
            source = "proxy_label"
        else:
            try:
                info = yf.Ticker(sym).info or {}
            except Exception:
                info = {}
            desc = _two_line_summary(info.get("longBusinessSummary"))
            sector = info.get("sector") or _ETF_SECTOR.get(sym) or _FUND_SECTOR.get(sym) or None
            industry = info.get("industry") or (
                "Exchange Traded Fund" if sym in _ETF_SECTOR else "Mutual Fund" if sym in _FUND_SECTOR else None
            )
            source = "yfinance"
            # ── Finviz fallback (yfinance rate-limited / empty): sector + industry + a synthesized one-liner ──
            if not (desc or sector):
                fd = fvz.get(sym) or {}
                f_sector, f_industry, f_company = fd.get("sector"), fd.get("industry"), fd.get("company")
                if f_sector or f_industry:
                    sector = sector or f_sector
                    industry = industry or f_industry
                    if not desc:
                        bits = [b for b in (f_company, f_industry) if b]
                        desc = " — ".join(bits) + "." if bits else None
                    source = "finviz"
                    fvz_used += 1
            if not (desc or sector):
                missed += 1
                skipped["provider_no_profile"] = skipped.get("provider_no_profile", 0) + 1
                continue
            fields = {"description_1s": desc, "sector": sector, "industry": industry}
        rcpt, db_skip = _upsert_one(sym, fields, source, retry_sleep)
        if db_skip:
            skipped[db_skip] = skipped.get(db_skip, 0) + 1
            continue
        updated += rcpt.rows_written
        rejected += rcpt.rows_rejected
        if rcpt.rows_rejected:
            skipped["writer_rejected"] = skipped.get("writer_rejected", 0) + rcpt.rows_rejected
    out = {
        "checked": len(uni),
        "updated": updated,
        "finviz_fallback": fvz_used,
        "no_profile": missed,
        "rejected": rejected,
        "db_skipped": sum(v for k, v in skipped.items() if k.startswith("db_")),
        "output": _output(produced=updated, attempted=len(uni), skipped=skipped,
                          empty_reason=None if updated else "all_skipped"),
    }
    print(json.dumps(out))
    return out


_DB_LOCK_RETRY_SLEEP_S = 2.0


def _db_errors() -> tuple:
    """psycopg2's error classes, or () when psycopg2 is absent (then nothing is caught here)."""
    try:
        import psycopg2

        return (psycopg2.OperationalError, psycopg2.InterfaceError), getattr(
            getattr(psycopg2, "errors", None), "LockNotAvailable", None)
    except Exception:  # noqa: BLE001
        return (), None


def _upsert_one(sym, fields, source, retry_sleep):
    """One symbol = one short transaction on a live connection. Returns (receipt, None) or (None, skip_reason).

    A lock timeout is retried once after ``retry_sleep`` seconds; a dropped connection (OperationalError /
    InterfaceError) is rebuilt through db_adapter and retried once. A second failure skips the symbol with a typed
    reason instead of killing the whole drain. Any other exception propagates (honest failure, failed receipt)."""
    import time

    from db_adapter import _get_conn

    errors, lock_cls = _db_errors()
    reason = None
    for attempt in range(2):
        conn = _get_conn()  # pings an idle connection and rebuilds a dead one (db_adapter)
        if conn is None:
            reason = "db_unavailable"
            break
        try:
            rcpt = upsert_profile(conn.cursor(), sym, fields, source=source)
            conn.commit()
            return rcpt, None
        except errors as exc:  # type: ignore[misc]
            is_lock = lock_cls is not None and isinstance(exc, lock_cls)
            reason = "db_lock_timeout" if is_lock else "db_connection_lost"
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 -- a dead connection cannot roll back
                pass
            if not is_lock:
                try:
                    from db_adapter import close_thread_conn

                    close_thread_conn()
                except Exception:  # noqa: BLE001
                    pass
            if attempt == 0:
                time.sleep(retry_sleep if is_lock else 0)
    print(f"  {sym}: skipped ({reason})")
    return None, reason


def _output(**kw):
    from lib.lane_output import output_block

    return output_block(unit="symbol_profiles rows upserted", **kw)


def receipt_name(symbols, watchlist_top) -> str | None:
    """Which lane receipt a real run writes. An ad-hoc --symbols run is not a scheduled lane."""
    if symbols:
        return None
    return "build_symbol_profiles_watchlist" if watchlist_top else "build_symbol_profiles"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--symbols")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--watchlist-top", type=int, default=0, help="also profile the top-N watchlist names by hermes_rank"
    )
    ap.add_argument("--dry-run", action="store_true", help="compute the stale universe and report; no fetch, no write")
    a = ap.parse_args(argv)
    symbols = a.symbols.split(",") if a.symbols else None
    if a.dry_run:
        if a.watchlist_top:
            # Keep the already-reviewed watchlist lane's data preview unchanged.
            run(symbols=symbols, force=a.force, watchlist_top=a.watchlist_top, dry_run=True)
            return 0
        print(f"DRY-RUN build-symbol-profiles-at-0-19: would refresh profiles for "
              f"{a.symbols or 'watch-grade universe'} (force={a.force}, watchlist_top={a.watchlist_top}) "
              "via yfinance/Finviz and symbol_profiles; inputs NOT_MEASURED")
        # The offline preview (refactor shard 05: no env, no DB, no provider) cannot count the stale universe;
        # the measured read-only preview is `--watchlist-top N --dry-run`.
        from lib.lane_output import emit, output_block

        emit(OWN_LANE, "dry_run", output_block(unit="symbol_profiles rows upserted", produced=0, attempted=0,
                                               empty_reason="dry_run_offline"))
        return 0
    name = receipt_name(symbols, a.watchlist_top)
    started_at = _now_iso()
    try:
        out = run(symbols=symbols, force=a.force, watchlist_top=a.watchlist_top)
    except Exception as exc:
        if name:
            _receipt(name, ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    out = out or {}
    if name:
        _receipt(name, ok=True, started_at=started_at, summary=out)
        from lib.lane_output import emit

        emit(OWN_LANE if name == "build_symbol_profiles" else name, "live", _output_of(out), started_at=started_at)
    # Honest exit (refactor contract §2): 1 when nothing landed although there was work, or a write was lost.
    return 0 if _work_landed(out) else 1


OWN_LANE = "build-symbol-profiles-at-0-19"


def _output_of(summary) -> dict:
    """The LaneOutput@v1 block of a run summary (rebuilt from the legacy counts when a caller returned none)."""
    block = (summary or {}).get("output")
    if isinstance(block, dict) and "produced_count" in block:
        return block
    produced = int((summary or {}).get("updated") or 0)
    attempted = int((summary or {}).get("checked") or 0)
    skipped = {"provider_no_profile": int((summary or {}).get("no_profile") or 0),
               "writer_rejected": int((summary or {}).get("rejected") or 0)}
    return _output(produced=produced, attempted=attempted, skipped=skipped,
                   empty_reason=None if produced else ("no_stale_symbols" if not attempted else "all_skipped"))


def _work_landed(summary) -> bool:
    """False when there was work but nothing was written, or a DB write was skipped / rejected.

    A provider with no profile for a symbol (yfinance 404 for VIX, ABB, ... every week) is a typed skip, not a
    failure: before 2026-10-15 it kept the weekly lane's ok_at from ever advancing (09-20: 17 of 28 had none)."""
    block = _output_of(summary)
    reasons = block.get("skipped_reasons") or {}
    if block["attempted_count"] and not block["produced_count"]:
        return False
    return not any(reasons.get(k) for k in ("writer_rejected", "db_lock_timeout", "db_connection_lost",
                                            "db_unavailable"))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _receipt(name, **kw):
    from lib.lane_last_receipt import write_lane_receipt, write_receipt

    write_receipt(name, **kw)
    if name == "build_symbol_profiles":
        own = dict(kw)
        # Partial provider misses are typed skips; a lost or rejected write, or nothing written although there was
        # work, keeps the legacy CLI's receipt but cannot advance success.
        own["ok"] = own["ok"] and _work_landed(own.get("summary") or {})
        write_lane_receipt(OWN_LANE, exit_code=0 if own["ok"] else 1, output=_receipt_output(own), **own)


def _receipt_output(own: dict) -> dict:
    """LaneRunReceipt@v2 output fields for the n8n lane receipt (expected_output unit: symbol_profiles rows
    upserted), from the run's LaneOutput@v1 block. Nothing stale (profiles are fresh for 30 days) is the closed-enum
    ``nothing_due``; a crash is ``dependency_unavailable``."""
    if "summary" not in own:
        return {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}}
    block = _output_of(own.get("summary") or {})
    produced, attempted = block["produced_count"], block["attempted_count"]
    return {"produced_count": produced, "attempted_count": max(attempted, produced),
            "skipped_reasons": dict(block.get("skipped_reasons") or {}),
            "empty_reason": "nothing_due" if not produced and not attempted else None}


if __name__ == "__main__":
    raise SystemExit(main())
