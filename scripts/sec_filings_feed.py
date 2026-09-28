#!/usr/bin/env python3
"""sec_filings_feed.py — SEC EDGAR 8-K / 10-Q / 10-K filings → FilingEvent@v1 (Wave 2 item 5).

Free feed (data.sec.gov submissions API, fair-access User-Agent + 0.15 s spacing, one request per
symbol per run). For every tracked symbol that resolves in the identity registry, every relevant
filing inside ``--since-days`` becomes one immutable event row keyed on the issuer + form + accession:

    data/cio/sec_filing_events.jsonl           canonical, append-only, deduped on event_guid

Downstream (same tranche): the GIR projector projects each row to an ``EVENT:<event_guid>`` node
(class MARKET, kind EVENT) with an ``EVENT —AFFECTED_BY→ SEC:<security_guid>`` edge; the material-change
detector (the declared Market owner) turns high-severity filings into ``MaterialChange@v1`` rows of
kind ``sec_filing`` so the persistent wake can select them. Nothing here decides, sizes or orders.

``--dry-run`` is the default (prints what would be appended); ``--apply`` appends and beats the
heartbeat for lane ``sec-filings-feed``. Network errors are recorded per symbol (UNAVAILABLE), never
treated as "no filings".
"""
NO_CONSUMER_REASON = (
    "FilingEvent@v1 rows are consumed by gir_projector (EVENT nodes + AFFECTED_BY edges) and by "
    "material_change_detector.new_filings (kind sec_filing → the persistent wake); lane sec-filings-feed is "
    "declared NEVER_SCHEDULED until the pkg-20260928-wave-2-enforcement-35c4 cron grant appends its crontab line"
)
SCHEDULED_ENTRYPOINT = "cron (after the cron grant): 20 8,12,17,21 * * 1-5 scripts/sec_filings_feed.py --apply — NOT installed yet"

import argparse
import datetime as _dt
import json
import os
import sys
import uuid
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))
sys.path.insert(0, str(PROJ))

SCHEMA = "FilingEvent@v1"
LANE = "sec-filings-feed"
AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE = "sec_edgar"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
TICKER_MAP_TTL_H = 24 * 7
DEFAULT_LIMIT = 150
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def state_root(env: dict) -> Path:
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def feed_path(root: Path) -> Path:
    return root / "data" / "cio" / "sec_filing_events.jsonl"


def event_guid(issuer_guid: str | None, cik: str, form: str, accession: str) -> str:
    """uuid5 over issuer (registry issuer_guid, else the CIK) | FILING_<form> | accession — the same
    filing observed on any run, from any symbol of the issuer, is the same event."""
    issuer = str(issuer_guid or f"cik:{str(cik).lstrip('0')}")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:event:{issuer}|FILING_{str(form).upper()}|{accession}"))


def events_from_filings(symbol: str, filings: list[dict], *, subject_guid: str | None, issuer_guid: str | None,
                        cik: str, since_days: int, now: _dt.datetime | None = None) -> list[dict]:
    """Pure: FilingEvent@v1 rows for one symbol's submissions (uses sec_filing_events.ITEMS / PERIODIC)."""
    try:
        import sec_filing_events as sfe  # type: ignore
    except ImportError:
        from scripts.lib import sec_filing_events as sfe  # type: ignore
    now = now or _now()
    cutoff = (now - _dt.timedelta(days=since_days)).date()
    out: list[dict] = []
    for f in filings:
        form = str(f.get("form") or "").upper()
        try:
            filed = _dt.date.fromisoformat(str(f.get("filing_date") or "")[:10])
        except ValueError:
            continue
        if filed < cutoff:
            continue
        acc = str(f.get("accession_number") or "")
        if not acc:
            continue
        items = [x.strip() for x in str(f.get("items") or "").split(",") if x.strip()]
        labels: list[dict] = []
        if form in ("8-K", "8-K/A"):
            for item in items:
                if item in sfe.ITEMS:
                    ctype, sev, label = sfe.ITEMS[item]
                    labels.append({"item": item, "catalyst_type": ctype, "severity": sev, "label": label})
        elif form in sfe.PERIODIC:
            ctype, sev, label = sfe.PERIODIC[form]
            labels.append({"item": form, "catalyst_type": ctype, "severity": sev, "label": label})
        if not labels:
            continue
        top = max(labels, key=lambda l: SEVERITY_RANK.get(l["severity"], 0))
        out.append({
            "schema": SCHEMA, "event_guid": event_guid(issuer_guid, cik, form, acc),
            "subject_guid": subject_guid, "issuer_guid": issuer_guid, "symbol": symbol.upper(), "cik": str(cik),
            "form": form, "accession": acc, "items": items, "filed_at": filed.isoformat(),
            "catalyst_type": top["catalyst_type"], "severity": top["severity"], "labels": labels,
            "sec_url": f.get("sec_url") or "", "source": SOURCE, "observed_at": now.isoformat(),
            "authority": AUTHORITY, "memory_behavior_influence": 0,
        })
    return out


def load_ticker_map(root: Path, fetcher, *, now: _dt.datetime | None = None) -> dict[str, str]:
    """{TICKER: 10-digit CIK} from the official map, cached under data/runtime for a week."""
    now = now or _now()
    cache = root / "data" / "runtime" / "sec_company_tickers.json"
    try:
        st = cache.stat()
        if (now.timestamp() - st.st_mtime) < TICKER_MAP_TTL_H * 3600:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return {str(v.get("ticker", "")).upper(): str(v["cik_str"]).zfill(10) for v in data.values() if v.get("cik_str")}
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    data = fetcher(TICKER_MAP_URL) or {}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data), encoding="utf-8"); os.replace(tmp, cache)
    except OSError:
        pass
    return {str(v.get("ticker", "")).upper(): str(v["cik_str"]).zfill(10) for v in data.values() if isinstance(v, dict) and v.get("cik_str")}


def universe(root: Path, limit: int) -> list[str]:
    """Held symbols (holdings snapshot) first, then the fundamentals ingest universe. Alpha tickers only."""
    out: list[str] = []
    try:
        h = json.loads((root / "data" / "cio" / "holdings_snapshot_latest.json").read_text(encoding="utf-8"))
        out += [str(r.get("symbol") or "").upper() for r in h.get("holdings") or []]
    except (OSError, json.JSONDecodeError):
        pass
    try:
        from sec_fundamentals_ingest import universe as _fund_universe  # type: ignore
        out += _fund_universe(limit)
    except Exception:  # noqa: BLE001
        pass
    seen, uniq = set(), []
    for s in out:
        if s and s.isalpha() and s not in seen:
            seen.add(s); uniq.append(s)
    return uniq[:limit]


def existing_guids(path: Path) -> set[str]:
    guids: set[str] = set()
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    g = json.loads(line).get("event_guid")
                    if g:
                        guids.add(g)
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass
    return guids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SEC 8-K/10-Q/10-K filings → FilingEvent@v1")
    ap.add_argument("--apply", action="store_true", help="append new rows (default: dry run)")
    ap.add_argument("--symbols", default="", help="comma list (default: holdings + fundamentals universe)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--since-days", type=int, default=7)
    ap.add_argument("--root", help="state root (default: production persistent-state)")
    a = ap.parse_args(argv)
    env = dict(os.environ)
    root = Path(a.root) if a.root else state_root(env)
    now = _now()

    from financial_senses import sec_companyfacts_reader as sec  # type: ignore
    fetcher = sec._default_fetcher
    try:
        import intelligence_client as ic  # type: ignore
        resolve = ic.default_loaders(root, env).resolve_subject
    except Exception:  # noqa: BLE001
        resolve = None

    syms = [x.strip().upper() for x in a.symbols.split(",") if x.strip()] or universe(root, a.limit)
    try:
        cik_map = load_ticker_map(root, fetcher, now=now)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"schema": "FilingsFeedRun@v1", "as_of": now.isoformat(), "error": f"ticker_map:{type(exc).__name__}"}))
        return 2

    path = feed_path(root)
    have = existing_guids(path)
    new_rows: list[dict] = []
    counts = {"symbols": len(syms), "unresolved_identity": 0, "no_cik": 0, "unavailable": 0, "fetched": 0, "seen": 0, "new": 0}
    per_symbol: dict[str, int] = {}
    for sym in syms:
        ent = None
        if resolve:
            try:
                ent = resolve(sym)
            except Exception:  # noqa: BLE001
                ent = None
        sg = (ent or {}).get("security_guid") or (ent or {}).get("guid")
        ig = (ent or {}).get("issuer_guid")
        if not sg:
            counts["unresolved_identity"] += 1
            continue
        cik = cik_map.get(sym)
        if not cik:
            counts["no_cik"] += 1
            continue
        try:
            subs = sec.get_submissions(cik, fetcher)
            counts["fetched"] += 1
        except Exception:  # noqa: BLE001
            counts["unavailable"] += 1
            continue
        try:
            import sec_filing_events as sfe  # type: ignore
        except ImportError:
            from scripts.lib import sec_filing_events as sfe  # type: ignore
        filings = sfe.filings_from_submissions(cik, subs)
        evs = events_from_filings(sym, filings, subject_guid=str(sg), issuer_guid=str(ig) if ig else None, cik=cik,
                                  since_days=a.since_days, now=now)
        counts["seen"] += len(evs)
        fresh = [e for e in evs if e["event_guid"] not in have]
        for e in fresh:
            have.add(e["event_guid"])
        new_rows += fresh
        per_symbol[sym] = len(fresh)
    counts["new"] = len(new_rows)
    summary = {"schema": "FilingsFeedRun@v1", "as_of": now.isoformat(), "mode": "apply" if a.apply else "dry_run",
               "since_days": a.since_days, "counts": counts, "high_severity_new": sum(1 for r in new_rows if r["severity"] == "high"),
               "path": str(path), "authority": AUTHORITY}
    print(json.dumps(summary, indent=1))
    for r in new_rows[:15]:
        print(f"  {r['symbol']:>6} {r['form']:<6} {r['filed_at']} {r['severity']:<6} {r['catalyst_type']:<22} {r['accession']}")
    if not a.apply:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in new_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    latest = root / "data" / "runtime" / "sec_filings_feed_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    tmp = latest.with_suffix(".json.tmp"); tmp.write_text(json.dumps({**summary, "per_symbol_new": per_symbol}, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, latest)
    try:
        import supervisor_heartbeat as hb  # type: ignore
        conn = None
        try:
            import db_adapter  # type: ignore
            conn = db_adapter._get_conn()
            with conn.cursor() as c:
                c.execute("SET app.tenant_id = 'tradeai:tenant:primary'")
        except Exception:  # noqa: BLE001
            conn = None
        print("heartbeat:", hb.beat(LANE, conn=conn, success=True, output_signal=True, work_claimed=len(syms), work_done=len(new_rows),
                                    work_failed=counts["unavailable"], root=root, env=env).get("pg"))
    except Exception as exc:  # noqa: BLE001
        print(f"heartbeat skipped: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
