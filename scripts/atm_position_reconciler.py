#!/usr/bin/env python3
"""
atm_position_reconciler.py v2.0


Recurring audit job for ATM paper-trade position reconciliation.


Default behavior is audit-only:
- compares DB-open paper_trades with journal/broker-open positions
- writes structured audit rows and JSON reports
- never places, cancels, replaces, or modifies broker orders
- never updates paper_trades unless a future explicit remediation mode is added


Install target:
  scripts/atm_position_reconciler.py


Designed by ChatGPT Chief Architect for Trade AI ATM lifecycle hardening.
"""


from __future__ import annotations


import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Load .env from project root
_project_root = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
except ImportError:
    pass
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
except Exception:  # pragma: no cover
    psycopg2 = None


UTC = dt.timezone.utc
DEFAULT_BASE_URL = os.environ.get("TRADE_AI_API_BASE", "http://127.0.0.1:7777")
DEFAULT_REPORT_DIR = Path("logs/atm_position_reconciliation")
PAPER_TRADE_OPEN_SQL = """
SELECT
    id AS paper_trade_id,
    '' AS lifecycle_id,
    symbol,
    strategy_id,
    '' AS strategy_family,
    account,
    '' AS broker,
    '' AS broker_order_id,
    '' AS alpaca_order_id,
    '' AS status,
    entry_time,
    entry_price,
    shares,
    exit_time,
    exit_price,
    exit_reason,
    stop_loss,
    target_1 AS target_price,
    NULL AS stop_hit_at,
    NULL AS target_hit_at,
    NULL AS closed_at,
    NULL AS updated_at,
    created_at
FROM paper_trades
WHERE exit_time IS NULL
  AND (exit_reason IS NULL OR exit_reason = '')
ORDER BY symbol, id;
"""


RUN_INSERT_SQL = """
INSERT INTO atm_position_reconciliation_runs
(run_id, started_at, completed_at, mode, journal_source, db_open_count, journal_open_count,
 matched_count, mismatch_count, duplicate_count, mirror_account_count, missing_identifier_count,
 status, payload)
VALUES
(%(run_id)s, %(started_at)s, %(completed_at)s, %(mode)s, %(journal_source)s, %(db_open_count)s,
 %(journal_open_count)s, %(matched_count)s, %(mismatch_count)s, %(duplicate_count)s,
 %(mirror_account_count)s, %(missing_identifier_count)s, %(status)s, %(payload)s);
"""


ITEM_INSERT_SQL = """
INSERT INTO atm_position_reconciliation_items
(run_id, paper_trade_id, lifecycle_id, symbol, strategy_id, account, broker_order_id,
 journal_match_key, classification, severity, reason, recommended_action, payload)
VALUES
(%(run_id)s, %(paper_trade_id)s, %(lifecycle_id)s, %(symbol)s, %(strategy_id)s, %(account)s,
 %(broker_order_id)s, %(journal_match_key)s, %(classification)s, %(severity)s, %(reason)s,
 %(recommended_action)s, %(payload)s);
"""


SQLITE_RUN_INSERT_SQL = RUN_INSERT_SQL.replace("%(run_id)s", ":run_id").replace("%(started_at)s", ":started_at").replace("%(completed_at)s", ":completed_at").replace("%(mode)s", ":mode").replace("%(journal_source)s", ":journal_source").replace("%(db_open_count)s", ":db_open_count").replace("%(journal_open_count)s", ":journal_open_count").replace("%(matched_count)s", ":matched_count").replace("%(mismatch_count)s", ":mismatch_count").replace("%(duplicate_count)s", ":duplicate_count").replace("%(mirror_account_count)s", ":mirror_account_count").replace("%(missing_identifier_count)s", ":missing_identifier_count").replace("%(status)s", ":status").replace("%(payload)s", ":payload")
SQLITE_ITEM_INSERT_SQL = ITEM_INSERT_SQL.replace("%(run_id)s", ":run_id").replace("%(paper_trade_id)s", ":paper_trade_id").replace("%(lifecycle_id)s", ":lifecycle_id").replace("%(symbol)s", ":symbol").replace("%(strategy_id)s", ":strategy_id").replace("%(account)s", ":account").replace("%(broker_order_id)s", ":broker_order_id").replace("%(journal_match_key)s", ":journal_match_key").replace("%(classification)s", ":classification").replace("%(severity)s", ":severity").replace("%(reason)s", ":reason").replace("%(recommended_action)s", ":recommended_action").replace("%(payload)s", ":payload")




@dataclass
class PositionRecord:
    source: str
    symbol: str
    account: str = ""
    strategy_id: str = ""
    paper_trade_id: Optional[int] = None
    lifecycle_id: str = ""
    broker_order_id: str = ""
    alpaca_order_id: str = ""
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    shares: Optional[float] = None
    status: str = ""
    exit_time: str = ""
    exit_price: Optional[float] = None
    exit_reason: str = ""
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    raw: Dict[str, Any] = None  # type: ignore


    def __post_init__(self) -> None:
        if self.raw is None:
            self.raw = {}
        self.symbol = normalize_symbol(self.symbol)
        self.account = str(self.account or "").upper()
        self.strategy_id = str(self.strategy_id or "")
        self.broker_order_id = str(self.broker_order_id or self.alpaca_order_id or "")




@dataclass
class ReconciliationItem:
    paper_trade_id: Optional[int]
    lifecycle_id: str
    symbol: str
    strategy_id: str
    account: str
    broker_order_id: str
    journal_match_key: str
    classification: str
    severity: str
    reason: str
    recommended_action: str
    payload: Dict[str, Any]




def now_iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat()




def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()




def to_float(value: Any) -> Optional[float]:
    if value in (None, "", "—"):
        return None
    try:
        return float(value)
    except Exception:
        return None




def to_int(value: Any) -> Optional[int]:
    if value in (None, "", "—"):
        return None
    try:
        return int(value)
    except Exception:
        return None




def stable_run_id() -> str:
    seed = f"{now_iso()}:{os.getpid()}:{time.time_ns()}"
    return "atmrecon_" + hashlib.sha1(seed.encode()).hexdigest()[:16]




def get_nested_arrays(payload: Any) -> List[List[Dict[str, Any]]]:
    """Return candidate arrays that may contain journal open trades."""
    arrays: List[List[Dict[str, Any]]] = []
    if not isinstance(payload, dict):
        return arrays
    candidates = [
        payload.get("open_trades"),
        payload.get("open_positions"),
        payload.get("openPositions"),
        payload.get("open"),
        payload.get("positions"),
        (payload.get("data") or {}).get("open_trades") if isinstance(payload.get("data"), dict) else None,
        (payload.get("data") or {}).get("open_positions") if isinstance(payload.get("data"), dict) else None,
        (payload.get("journal") or {}).get("open_trades") if isinstance(payload.get("journal"), dict) else None,
        (payload.get("journal") or {}).get("open_positions") if isinstance(payload.get("journal"), dict) else None,
        (payload.get("tradeai_automated") or {}).get("open_trades") if isinstance(payload.get("tradeai_automated"), dict) else None,
        (payload.get("tradeai_automated") or {}).get("open_positions") if isinstance(payload.get("tradeai_automated"), dict) else None,
    ]
    for item in candidates:
        if isinstance(item, list):
            arrays.append([x for x in item if isinstance(x, dict)])
    return arrays




def record_from_db(row: Dict[str, Any]) -> PositionRecord:
    return PositionRecord(
        source="paper_trades",
        symbol=row.get("symbol"),
        account=row.get("account") or row.get("broker") or "",
        strategy_id=row.get("strategy_id") or "",
        paper_trade_id=to_int(row.get("paper_trade_id")),
        lifecycle_id=str(row.get("lifecycle_id") or ""),
        broker_order_id=str(row.get("broker_order_id") or ""),
        alpaca_order_id=str(row.get("alpaca_order_id") or ""),
        entry_price=to_float(row.get("entry_price")),
        current_price=None,
        shares=to_float(row.get("shares")),
        status=str(row.get("status") or ""),
        exit_time=str(row.get("exit_time") or ""),
        exit_price=to_float(row.get("exit_price")),
        exit_reason=str(row.get("exit_reason") or ""),
        stop_loss=to_float(row.get("stop_loss")),
        target_price=to_float(row.get("target_price")),
        raw=row,
    )




def record_from_journal(row: Dict[str, Any]) -> PositionRecord:
    return PositionRecord(
        source="journal_open",
        symbol=row.get("symbol") or row.get("ticker"),
        account=row.get("account") or row.get("broker") or row.get("account_name") or os.environ.get("DEFAULT_PAPER_ACCOUNT"),
        strategy_id=row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "",
        paper_trade_id=to_int(row.get("paper_trade_id") or row.get("trade_id") or row.get("id")),
        lifecycle_id=str(row.get("lifecycle_id") or ""),
        broker_order_id=str(row.get("broker_order_id") or row.get("alpaca_order_id") or row.get("order_id") or ""),
        alpaca_order_id=str(row.get("alpaca_order_id") or ""),
        entry_price=to_float(row.get("entry_price") or row.get("entry")),
        current_price=to_float(row.get("current_price") or row.get("mark_price") or row.get("now")),
        shares=to_float(row.get("shares") or row.get("qty") or row.get("quantity")),
        status=str(row.get("status") or "open"),
        stop_loss=to_float(row.get("stop_loss") or row.get("stop") or row.get("db_stop")),
        target_price=to_float(row.get("target_price") or row.get("target")),
        raw=row,
    )




def deterministic_keys(p: PositionRecord) -> List[str]:
    keys: List[str] = []
    if p.broker_order_id:
        keys.append(f"order:{p.broker_order_id}")
    if p.alpaca_order_id:
        keys.append(f"order:{p.alpaca_order_id}")
    if p.paper_trade_id is not None:
        keys.append(f"paper:{p.paper_trade_id}")
    if p.lifecycle_id:
        keys.append(f"life:{p.lifecycle_id}")
    if p.symbol and p.shares is not None and p.entry_price is not None:
        keys.append(f"sig:{p.symbol}|{round(p.shares, 4)}|{round(p.entry_price, 4)}")
    if p.symbol and p.account and p.shares is not None and p.entry_price is not None:
        keys.append(f"acctsig:{p.symbol}|{p.account}|{round(p.shares, 4)}|{round(p.entry_price, 4)}")
    return keys




def exit_like_evidence(p: PositionRecord) -> bool:
    text = " ".join([p.status, p.exit_reason, str(p.raw.get("verdict") or ""), str(p.raw.get("reason") or "")]).lower()
    if p.exit_price is not None or p.exit_reason or p.raw.get("closed_at"):
        return True
    return any(term in text for term in ["closed", "stop_hit", "stop hit", "target_hit", "target hit", "broker close", "manual stale close", "cancel"])




def classify_db_position(db: PositionRecord, journal_index: Dict[str, PositionRecord], dup_counts: Dict[str, int]) -> ReconciliationItem:
    matched_key = ""
    for key in deterministic_keys(db):
        if key in journal_index:
            matched_key = key
            break


    duplicate_key = f"{db.symbol}|{db.account}|{db.shares}|{db.entry_price}"
    is_duplicate = dup_counts.get(duplicate_key, 0) > 1
    is_mirror = db.account.startswith("TOS") or db.account in {"TOS_PAPER", "THINKORSWIM_PAPER"}
    missing_id = not (db.broker_order_id or db.alpaca_order_id or db.paper_trade_id or db.lifecycle_id)


    if matched_key:
        classification = "matched_open"
        severity = "ok"
        reason = "DB-open row matches journal/broker-open position."
        action = "No action."
    elif exit_like_evidence(db):
        classification = "closed_evidence_missing_exit_time"
        severity = "high"
        reason = "DB row is still open but has exit-like evidence. It likely needs controlled backfill after review."
        action = "Review exit evidence and backfill exit_time/exit_reason only with operator-approved remediation."
    elif is_mirror:
        classification = "mirror_account_no_adapter"
        severity = "medium"
        reason = "Non-Alpaca mirror account row cannot be reconciled by Alpaca adapter. It requires source-specific reconciliation or mirror cleanup policy."
        action = "Do not trade. Route to broker/mirror reconciliation review."
    elif is_duplicate:
        classification = "duplicate_candidate"
        severity = "high"
        reason = "Multiple DB-open rows share symbol/account/shares/entry signature."
        action = "Review for duplicate/orphan and reconcile DB state after confirmation."
    elif missing_id:
        classification = "missing_identifier"
        severity = "high"
        reason = "DB-open row lacks identifiers for deterministic broker/journal reconciliation."
        action = "Add missing link metadata or manually reconcile."
    else:
        classification = "unmatched_db_open"
        severity = "high"
        reason = "DB-open row is missing from journal/broker-open positions."
        action = "Investigate before it appears as actionable. If broker/journal confirms closed, backfill DB close state."


    return ReconciliationItem(
        paper_trade_id=db.paper_trade_id,
        lifecycle_id=db.lifecycle_id,
        symbol=db.symbol,
        strategy_id=db.strategy_id,
        account=db.account,
        broker_order_id=db.broker_order_id or db.alpaca_order_id,
        journal_match_key=matched_key,
        classification=classification,
        severity=severity,
        reason=reason,
        recommended_action=action,
        payload={"db_record": asdict(db)},
    )




def http_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))




def fetch_journal_open_positions(base_url: str, endpoint: str) -> Tuple[str, List[PositionRecord], Dict[str, Any]]:
    url = endpoint if endpoint.startswith("http") else base_url.rstrip("/") + endpoint
    payload = http_json(url)
    arrays = get_nested_arrays(payload)
    rows = arrays[0] if arrays else []
    records = [record_from_journal(r) for r in rows]
    records = [r for r in records if r.symbol]
    return url, records, payload




def db_connect(args: argparse.Namespace):
    db_url = args.database_url or os.environ.get("DATABASE_URL") or os.environ.get("TRADE_AI_DATABASE_URL")
    # Construct from DB_* env vars if no DATABASE_URL
    if not db_url and os.environ.get("DB_PASSWORD"):
        _h = os.environ.get("DB_HOST", "localhost")
        _p = os.environ.get("DB_PORT", "5432")
        _u = os.environ.get("DB_USER", "trade_ai")
        _pw = os.environ.get("DB_PASSWORD", "")
        _d = os.environ.get("DB_NAME", "trade_ai")
        db_url = f"postgresql://{_u}:{_pw}@{_h}:{_p}/{_d}"
    sqlite_path = args.sqlite_path or os.environ.get("TRADE_AI_SQLITE_PATH")
    if db_url:
        if psycopg2 is None:
            raise RuntimeError("DATABASE_URL is set but psycopg2 is not installed.")
        return "postgres", psycopg2.connect(db_url)
    if sqlite_path:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        return "sqlite", conn
    # Common project fallback; Claude may adjust after repo inspection.
    for candidate in ["data/trade_ai.db", "data/portfolio.db", "trade_ai.db"]:
        if Path(candidate).exists():
            conn = sqlite3.connect(candidate)
            conn.row_factory = sqlite3.Row
            return "sqlite", conn
    raise RuntimeError("No DB configured. Set DATABASE_URL, TRADE_AI_DATABASE_URL, or TRADE_AI_SQLITE_PATH.")




def fetch_db_open_positions(kind: str, conn) -> List[PositionRecord]:
    if kind == "postgres":
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:  # type: ignore
            cur.execute(PAPER_TRADE_OPEN_SQL)
            rows = [dict(r) for r in cur.fetchall()]
    else:
        cur = conn.execute(PAPER_TRADE_OPEN_SQL)
        rows = [dict(r) for r in cur.fetchall()]
    return [record_from_db(r) for r in rows]




def write_audit(kind: str, conn, run: Dict[str, Any], items: List[ReconciliationItem]) -> None:
    run_row = dict(run)
    run_row["payload"] = json.dumps(run_row.get("payload", {}), sort_keys=True, default=str)
    if kind == "postgres":
        with conn.cursor() as cur:
            cur.execute(RUN_INSERT_SQL, run_row)
            for item in items:
                row = asdict(item)
                row["run_id"] = run["run_id"]
                row["payload"] = json.dumps(row["payload"], sort_keys=True, default=str)
                cur.execute(ITEM_INSERT_SQL, row)
        conn.commit()
    else:
        conn.execute(SQLITE_RUN_INSERT_SQL, run_row)
        for item in items:
            row = asdict(item)
            row["run_id"] = run["run_id"]
            row["payload"] = json.dumps(row["payload"], sort_keys=True, default=str)
            conn.execute(SQLITE_ITEM_INSERT_SQL, row)
        conn.commit()




def write_reports(report_dir: Path, report: Dict[str, Any], items: List[ReconciliationItem], json_out: Optional[str]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    target = Path(json_out) if json_out else report_dir / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    dated = report_dir / f"reconciliation_{report['run_id']}.json"
    dated.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")


    csv_path = report_dir / f"reconciliation_{report['run_id']}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "paper_trade_id", "lifecycle_id", "symbol", "strategy_id", "account", "broker_order_id",
            "journal_match_key", "classification", "severity", "reason", "recommended_action"
        ])
        writer.writeheader()
        for item in items:
            row = asdict(item)
            row.pop("payload", None)
            writer.writerow(row)




def build_journal_index(records: List[PositionRecord]) -> Dict[str, PositionRecord]:
    idx: Dict[str, PositionRecord] = {}
    for rec in records:
        for key in deterministic_keys(rec):
            idx.setdefault(key, rec)
    return idx




def duplicate_counts(records: List[PositionRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in records:
        key = f"{r.symbol}|{r.account}|{r.shares}|{r.entry_price}"
        counts[key] = counts.get(key, 0) + 1
    return counts




def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ATM paper-trade position reconciliation audit")
    p.add_argument("--audit-only", action="store_true", default=True, help="Audit only; never update paper_trades or place orders. Default true.")
    p.add_argument("--write-audit", action="store_true", help="Write run/items to reconciliation audit tables.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Trade AI local API base URL")
    p.add_argument("--journal-endpoint", default="/api/v2/automated-journal", help="Endpoint containing open_trades/open_positions")
    p.add_argument("--database-url", default=None, help="Postgres DATABASE_URL override")
    p.add_argument("--sqlite-path", default=None, help="SQLite DB path override")
    p.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Report output directory")
    p.add_argument("--json-out", default=None, help="Optional JSON output path")
    p.add_argument("--fail-on-mismatch", action="store_true", help="Exit 2 when mismatches are detected")
    return p.parse_args(argv)




def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    started_at = now_iso()
    run_id = stable_run_id()
    safety = {
        "audit_only": True,
        "orders_placed": "NONE",
        "positions_modified": "NONE",
        "paper_trades_updated": "NONE",
        "alpaca_mode": os.environ.get("ALPACA_MODE", "unknown"),
        "llm_disable_live_execution": os.environ.get("LLM_DISABLE_LIVE_EXECUTION", "unknown"),
    }


    kind, conn = db_connect(args)
    db_open = fetch_db_open_positions(kind, conn)
    journal_source, journal_open, journal_payload = fetch_journal_open_positions(args.base_url, args.journal_endpoint)


    jidx = build_journal_index(journal_open)
    dups = duplicate_counts(db_open)
    items = [classify_db_position(row, jidx, dups) for row in db_open]


    matched = [i for i in items if i.classification == "matched_open"]
    mismatches = [i for i in items if i.classification != "matched_open"]
    duplicates = [i for i in items if i.classification == "duplicate_candidate"]
    mirrors = [i for i in items if i.classification == "mirror_account_no_adapter"]
    missing_ids = [i for i in items if i.classification == "missing_identifier"]


    completed_at = now_iso()
    status = "healthy" if not mismatches else "mismatch_detected"
    run_row = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "mode": "audit_only",
        "journal_source": journal_source,
        "db_open_count": len(db_open),
        "journal_open_count": len(journal_open),
        "matched_count": len(matched),
        "mismatch_count": len(mismatches),
        "duplicate_count": len(duplicates),
        "mirror_account_count": len(mirrors),
        "missing_identifier_count": len(missing_ids),
        "status": status,
        "payload": {"safety": safety},
    }


    report = {
        **run_row,
        "safety": safety,
        "journal_open_positions": [asdict(x) for x in journal_open],
        "db_open_positions": [asdict(x) for x in db_open],
        "items": [asdict(x) for x in items],
    }


    if args.write_audit:
        write_audit(kind, conn, run_row, items)


    write_reports(Path(args.report_dir), report, items, args.json_out)


    print(json.dumps({
        "run_id": run_id,
        "status": status,
        "db_open_count": len(db_open),
        "journal_open_count": len(journal_open),
        "matched_count": len(matched),
        "mismatch_count": len(mismatches),
        "safety": safety,
    }, indent=2))


    if args.fail_on_mismatch and mismatches:
        return 2
    return 0




if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))