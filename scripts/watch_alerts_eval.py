#!/usr/bin/env python3
"""Watch Desk operator-alert evaluation pass.

Deterministic conditions over data that already exists. Fires into alert_events
with daily dedupe and sends ONE batched Telegram per pass under the shared daily
cap. Re-Entry exit detail, rotation-back composite monitors, closed-session
resistance intelligence, and the shared Watch/Journal/Re-Entry context are
refreshed in this same RTH lane.

Advisory only: no proposal, approval, broker order, or 2FA path is reachable.
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run (it always sends)). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "watch-alerts-eval"
    _dr_would = (
        "evaluate the Watch Desk operator-alert conditions, write deduped alert_events, refresh the re-entry "
        "/ rotation-back / resistance context and send one batched Telegram under the daily cap"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="watch_condition"))
    raise SystemExit(0)

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CFG_PATH = ROOT / "config" / "watch_alerts.json"


def _emit_watch_alert_payload(alert: dict, message: str | None = None) -> None:
    """Flag-gated DecisionPayload@v1 when a watch alert fires. Fail-soft. Never raises."""
    try:
        try:
            from lib.agent_decision_payload import emit_watch_alert_payload
        except ImportError:
            from scripts.lib.agent_decision_payload import emit_watch_alert_payload
        emit_watch_alert_payload(alert, message=message)
    except Exception:
        pass


def _cfg():
    try:
        return json.loads(CFG_PATH.read_text())
    except Exception:
        return {"daily_cap": 12}


def _quote_is_current(fetched_at) -> bool:
    """Market-session-aware freshness via watch_canonical_quote.derive_freshness.

    A row without fetched_at is unknown-age and keeps the prior behaviour; a
    row WITH a stale fetched_at for its session is skipped."""
    if not fetched_at:
        return True
    try:
        try:
            from scripts.lib.watch_canonical_quote import derive_freshness
        except ImportError:
            from lib.watch_canonical_quote import derive_freshness  # type: ignore
    except Exception:
        return True  # library absent: keep prior behaviour, do not silently drop alerts
    state, _ = derive_freshness(fetched_at)
    return state not in ("STALE", "DATA_UNAVAILABLE")


def _price_quotes(ex, symbols: list[str]) -> dict[str, dict]:
    """Current prices for a batch of symbols, through the one shared price helper.

    Operator price rule (2026-11-07): Finviz cache when it is younger than the configured limit, else the
    fresher broker / market_quotes row — never a stored DB print older than that. The previous path read
    market_quotes directly, which served PFE 27.56 from 16:45 ET while Finviz at 23:30 ET said 29.39
    (data-truth audit 2026-11-07). One batch call per pass, not one read per alert.

    A helper failure returns {} and is logged: price alerts then do not fire this pass, which is the safe
    direction (an alert on an unverified price is worse than no alert), and the log names the cause.
    """
    if not symbols:
        return {}
    # "" is the safe state and it is not silent: the handler logs the cause.
    # nosemgrep: tq-py-broad-except-returns-default -- logged, and no alert beats an alert on an unread price
    try:
        try:
            from lib.data_broker.market_quote import get_price_batch
        except ImportError:
            from scripts.lib.data_broker.market_quote import get_price_batch  # type: ignore -- package import when scripts/ is not on sys.path
        return get_price_batch(ex, symbols, max_age_hours=12, finviz_first=True) or {}
    except Exception as exc:  # noqa: BLE001 -- never crash the lane; never fire on an unread price
        _log(f"price batch unavailable ({type(exc).__name__}: {str(exc)[:80]}); price alerts skipped this pass")
        return {}


def _log(msg: str) -> None:
    try:
        print(msg)
    except Exception:
        pass


def _evaluate_single_condition_alerts(ex, alerts, today: str) -> tuple[list[str], list[int]]:
    lines: list[str] = []
    fired_ids: list[int] = []
    # One batch for every price-cross alert, through the shared Finviz-first helper (see _price_quotes).
    price_symbols = sorted({
        (a.get("symbol") or "").upper() for a in alerts
        if a.get("condition_type") in ("price_cross_above", "price_cross_below")
        and (a.get("symbol") or "").strip()
    })
    quotes = _price_quotes(ex, price_symbols)
    for alert in alerts:
        uid = f"watch_alert:{alert['id']}:{today}"
        if ex("SELECT 1 FROM alert_events WHERE alert_uid=%s LIMIT 1", (uid,), fetch="one"):
            continue
        if alert.get("last_fired_at") and not alert.get("recurring"):
            continue
        if alert.get("recurring") and alert.get("last_fired_at"):
            cooldown = int(alert.get("cooldown_days") or 5)
            days = (dt.datetime.now(dt.timezone.utc) - alert["last_fired_at"]).days
            if days < cooldown * 1.4:  # trading-day approximation
                continue
        symbol = (alert.get("symbol") or "").upper()
        condition = alert["condition_type"]
        threshold = alert.get("threshold")
        hit, current = False, None
        if condition in ("price_cross_above", "price_cross_below") and symbol and threshold is not None:
            quote = quotes.get(symbol) or {}
            current = quote.get("price")
            # A price alert must not fire (or stay silent) on a stale print; a quote with no current
            # price, or one stale for its session, is skipped this pass and named in the log.
            if current is None:
                _log(f"skip alert {alert['id']} {symbol}: no current quote ({quote.get('source') or 'helper returned none'})")
                continue
            if not _quote_is_current(quote.get("as_of")):
                _log(f"skip alert {alert['id']} {symbol}: quote {quote.get('as_of')} from {quote.get('source')} is stale for its session")
                continue
            hit = current is not None and (
                current >= float(threshold) if condition.endswith("above") else current <= float(threshold)
            )
        elif condition in ("rsi_above", "rsi_below") and symbol and threshold is not None:
            row = ex(
                """SELECT rsi FROM watchlist_items
                   WHERE upper(symbol)=%s AND rsi IS NOT NULL
                   ORDER BY first_seen_at DESC LIMIT 1""",
                (symbol,), fetch="one",
            )
            current = float(row["rsi"]) if row and row.get("rsi") is not None else None
            hit = current is not None and (
                current >= float(threshold) if condition.endswith("above") else current <= float(threshold)
            )
        elif condition == "directive_hit" and alert.get("directive_id"):
            row = ex(
                """SELECT count(*) AS n FROM watch_directive_hits
                   WHERE directive_id=%s
                     AND surfaced_at > COALESCE(%s, now() - interval '1 day')""",
                (alert["directive_id"], alert.get("last_fired_at")), fetch="one",
            )
            current = (row or {}).get("n") or 0
            hit = current > 0
        if not hit:
            continue
        message = (
            f"🔔 {symbol or ('directive #' + str(alert.get('directive_id')))} · "
            f"{condition.replace('_', ' ')} {threshold if threshold is not None else ''} · "
            f"now {current} · open Pullback/Watchlist card"
        )
        ex(
            """INSERT INTO alert_events
               (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
               VALUES (%s,'watch_alert',%s,'info','watch_alerts_eval',%s,NOW())
               ON CONFLICT (alert_uid) DO NOTHING""",
            (uid, symbol or None, message), fetch=None,
        )
        ex(
            "UPDATE watch_alerts SET last_fired_at=NOW(), active=%s WHERE id=%s",
            (bool(alert.get("recurring")), alert["id"]), fetch=None,
        )
        lines.append(message)
        fired_ids.append(alert["id"])
        _emit_watch_alert_payload(alert, message=message)
    return lines, fired_ids


def _recovery_snapshot(ex, case: dict, technical_by_symbol: dict | None = None) -> dict | None:
    """The market fields the recovery state machine needs, from their registered sources.

    The close and its OWN timestamp come from the quote ledger (``market_quotes``); the technical input that
    carries R4 — SMA20 — comes from the registered technical projection (``recovery_state.technical_inputs``). The quote
    table has no sma20 column and its only writer cannot write one, so searching that row for the level is how
    R4 stayed permanently false. An absent projection leaves R4 unfired; the engine says so rather than guessing.
    """
    symbol = str(case.get("symbol") or "").upper().strip()
    if not symbol:
        return None
    try:
        row = ex("SELECT * FROM market_quotes WHERE upper(symbol)=%s ORDER BY fetched_at DESC LIMIT 1",
                 (symbol,), fetch="one")
    except Exception:
        return None
    try:
        from lib import recovery_state as _R
    except ImportError:
        from scripts.lib import recovery_state as _R  # type: ignore
    if technical_by_symbol is None:
        # A caller that has no batch (a single-case probe): one projection read, still the registered source.
        technical_by_symbol = _R.technical_inputs([symbol])
    technical = technical_by_symbol.get(symbol) if isinstance(technical_by_symbol, dict) else None
    return _R.quote_snapshot(row, technical)


def _recovery_state_pass(ex) -> dict:
    """One pass of the recovery state machine (piece B). Reports absence honestly; never a silent skip."""
    try:
        from lib import recovery_state as R
    except ImportError:
        try:
            from scripts.lib import recovery_state as R
        except ImportError:
            return {"store": "module_absent", "considered": 0, "changed": 0}
    try:
        _engine_db = __import__("db_adapter")._get_conn()  # the CaseStore takes a connection
    except Exception:
        _engine_db = None
    store = R.store_accessor(_engine_db, None)
    if store is None:
        return {"store": "absent", "considered": 0, "changed": 0}
    # ONE read-only listing just for the symbols: the technical projection is then a single batch call.
    try:
        rows = store.list_open(limit=200) if hasattr(store, "list_open") else store.list()
    except Exception:
        rows = []
    technical_by_symbol = R.technical_inputs(R.technical_symbols(rows))
    return R.run_pass(store, lambda c: _recovery_snapshot(ex, c, technical_by_symbol), dry_run=False)


def _run_pass(stats: dict) -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        stats["error"] = "USE_DB off"
        return 2

    today = dt.date.today().isoformat()
    cap = int(_cfg().get("daily_cap") or 12)
    sent_today = (
        ex(
            """SELECT count(*) AS n FROM alert_events
               WHERE alert_type='watch_alert' AND created_at::date=CURRENT_DATE""",
            fetch="one",
        ) or {}
    ).get("n") or 0

    alerts = ex("SELECT * FROM watch_alerts WHERE active", fetch="all") or []
    lines, fired_ids = _evaluate_single_condition_alerts(ex, alerts, today)

    exit_count = 0
    exit_payload = None
    try:
        from lib.reentry_exit_cache import refresh_exit_cache
        exit_payload = refresh_exit_cache(ex)
        exit_count = int((exit_payload.get("counts") or {}).get("exits_found") or 0)
    except Exception as error:
        print(f"[watch-alerts] re-entry exit-cache refresh error: {str(error)[:200]}")

    resistance_count = 0
    resistance_payload = None
    try:
        from lib.reentry_resistance import refresh_resistance_cache
        resistance_payload = refresh_resistance_cache(ex)
        resistance_count = int(resistance_payload.get("symbol_count") or 0)
    except Exception as error:
        print(f"[watch-alerts] re-entry resistance refresh error: {str(error)[:200]}")

    shared_context_count = 0
    try:
        from lib.reentry_shared_context import refresh_shared_symbol_context
        shared_context = refresh_shared_symbol_context(
            ex,
            exit_payload=exit_payload,
            resistance_payload=resistance_payload,
        )
        shared_context_count = int(shared_context.get("symbol_count") or 0)
    except Exception as error:
        print(f"[watch-alerts] shared Watch/Journal/Re-Entry context refresh error: {str(error)[:200]}")

    # Re-Entry v4: the six mandatory return-to-growth gates are recomputed from
    # primary DB evidence on every scheduled pass. The helper persists the same
    # alert_events evidence and returns lines for this shared Telegram batch.
    try:
        from lib.reentry_rotation_alerts import evaluate_armed_rotation_alerts
        composite = evaluate_armed_rotation_alerts(ex, today=today)
    except Exception as error:
        composite = {"lines": [], "fired": [], "error": str(error)[:200]}
        print(f"[watch-alerts] re-entry composite evaluator error: {composite['error']}")
    lines.extend(composite.get("lines") or [])

    if lines:
        room = max(0, cap - sent_today)
        shown = lines[:room]
        message = "🔔 Watch alerts\n" + "\n".join(shown)
        if len(lines) > len(shown):
            message += f"\n…and {len(lines) - len(shown)} more (daily cap {cap}; in next digest)"
        try:
            from telegram_alert import send_telegram
            send_telegram(message, priority="P1", producer="watch_alerts_eval")  # armed price triggers: time-critical, self-capped
        except Exception:
            pass

    try:
        recovery = _recovery_state_pass(ex)
    except Exception as error:  # noqa: BLE001 — a recovery pass failure never stops the alert lane
        recovery = {"store": "error", "considered": 0, "changed": 0, "error": str(error)[:200]}
        print(f"[watch-alerts] recovery state machine error: {recovery['error']}")

    stats.update(armed=len(alerts), fired=len(fired_ids), composites=len(composite.get("fired") or []),
                 recovery_store=recovery.get("store"))
    print(
        f"[watch-alerts] {len(alerts)} single-condition armed · "
        f"{len(fired_ids)} fired: {fired_ids} · "
        f"{len(composite.get('fired') or [])} re-entry composites fired: "
        f"{composite.get('fired') or []} · "
        f"{exit_count} full exit rows refreshed · "
        f"{resistance_count} resistance rows refreshed · "
        f"{shared_context_count} shared context rows refreshed · "
        f"recovery store {recovery.get('store')}: {recovery.get('considered', 0)} cases, "
        f"{recovery.get('changed', 0)} state changes"
    )
    return 0


def main() -> int:
    """WV-07 (LQ-20261107-2622): one pass plus a run record, so a silent stop is visible as an aged receipt."""
    started = dt.datetime.now(dt.timezone.utc)
    stats: dict = {}
    try:
        rc = _run_pass(stats)
    except Exception as error:  # noqa: BLE001 - recorded on the receipt, then re-raised
        stats["error"] = str(error)[:200]
        _write_run_record(started, 1, stats)
        raise
    _write_run_record(started, rc, stats)
    return rc


def _write_run_record(started, rc: int, stats: dict) -> None:
    try:
        from lib.lane_last_receipt import write_lane_receipt
        write_lane_receipt(
            "watch-alerts-eval", ok=rc == 0, exit_code=rc, started_at=started,
            script="scripts/watch_alerts_eval.py", error=stats.get("error"),
            summary={k: v for k, v in stats.items() if k != "error"},
            produced_count=int(stats.get("fired") or 0) + int(stats.get("composites") or 0),
            attempted_count=int(stats.get("armed") or 0),
            empty_reason=None if rc != 0 or stats.get("fired") or stats.get("composites") else "no_alert_fired")
    except Exception as error:  # noqa: BLE001 - a receipt failure never stops the alert lane
        print(f"[watch-alerts] run record not written: {str(error)[:200]}")
    _append_runs_record(rc, stats)


def _append_runs_record(rc: int, stats: dict) -> None:
    """Append this pass to the durable runs record (one jsonl line per pass).

    The lane receipt is overwritten every pass, so it cannot answer "when did a run last succeed" or "how many runs
    in 24 h". The Watch Alerts tab reads ``lib/watch_alerts_record.read_record`` (Watch v002, LQ-20261107-2993c-v2);
    without this line that read is a permanent UNKNOWN, not a stale value. Guarded twice: a writer module that is
    missing OR fails at import (the v002 lib folds after this lane) is named once per pass and never fails the run,
    and a record write failure never stops an alert pass.

    A pass that never acquired the pass lock is NOT a run (F1, REVIEW-LQ-20261107-3011-runs-record-cc-deepseek-8):
    its rc is 0, and the reader certifies from the newest rc == 0 line, so appending it would turn the certified
    armed count UNKNOWN and advance ``last_ok_at`` past a pass that evaluated nothing. The receipt beside it
    already carries ``empty_reason: lock_skipped``, which is where the skip stays visible. On this tree (release-3
    source d12fe7ec3) no pass lock exists yet, so nothing sets the key; the guard is inert until the 3011-v4 pass
    (or an equivalent) lands, and it is pinned by test_lock_skipped_pass_is_not_a_run.
    """
    if stats.get("lock_skipped"):
        return
    try:
        from lib.watch_alerts_record import append_run
    except ImportError:
        print("[watch-alerts] runs record writer absent (lib/watch_alerts_record); no liveness line this pass")
        return
    except Exception as error:  # noqa: BLE001 - F2: a writer that fails at import must never stop the alert lane
        print(f"[watch-alerts] runs record writer failed to import: {str(error)[:200]}")
        return
    try:
        wrote = append_run(
            armed=stats.get("armed"),  # None = the alerts read failed: UNKNOWN, never "armed 0"
            fired=stats.get("fired") or 0,
            composites=stats.get("composites") or 0,
            rc=rc,
            error=stats.get("error"),
        )
    except Exception as error:  # noqa: BLE001 - a record failure never stops an alert pass
        print(f"[watch-alerts] runs record not written: {str(error)[:200]}")
        return
    # N1: append_run never raises; it returns False when the write is refused. Say so instead of leaving only an
    # unexplained UNKNOWN on the Alerts tab.
    if wrote is False:
        print("[watch-alerts] runs record refused: the writer returned False; the tab will read UNKNOWN")


if __name__ == "__main__":
    raise SystemExit(main())
