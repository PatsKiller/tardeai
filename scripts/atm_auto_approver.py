#!/usr/bin/env python3
"""
atm_auto_approver.py — ATM v1 auto-approval cron.

Evaluates PENDING proposals against ATM gates and, if mode='active',
calls the canonical approve_proposal() + submit_paper() chain.

Cron: */15 9-15 * * 1-5
No hardcoded broker or account names.
"""
import fcntl, json, logging, os, sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

ATM_CYCLE_LOCK = "/tmp/tradeai_atm.lock"
# Per-symbol cooldown so repeat expiry Telegram batches don't fire for the same ticker all afternoon.
_EXPIRY_TG_RECENT: dict[str, float] = {}
_EXPIRY_TG_COOLDOWN_SEC = 24 * 3600

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from db_adapter import get_connection

log = logging.getLogger("atm")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _telegram_both(msg: str):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="atm_auto_approver", subject_key="ops:atm",
                retention_class="operational", severity="urgent",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def _telegram_expiry_batch(expired_lines: list[str]):
    """Notify operator of newly expired proposals — once per symbol per 24h (dedupes parallel cycles)."""
    if not expired_lines:
        return
    import time as _time
    now = _time.time()
    fresh: list[str] = []
    for line in expired_lines:
        sym = (line.split("(")[0].strip() if "(" in line else line.strip()).upper()
        if not sym:
            continue
        if now - _EXPIRY_TG_RECENT.get(sym, 0) < _EXPIRY_TG_COOLDOWN_SEC:
            log.info("  %s: expiry telegram suppressed (already notified within 24h)", sym)
            continue
        fresh.append(line)
        _EXPIRY_TG_RECENT[sym] = now
    if not fresh:
        return
    msg = (f"ATM expired {len(fresh)} proposal(s) this cycle:\n"
           + "\n".join(f"  - {e}" for e in fresh))
    _telegram_both(msg)


def _get_atm_state(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM atm_state WHERE id=1")
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else {"mode": "disabled"}


def _set_atm_mode(conn, new_mode: str, changed_by: str, reason: str = None):
    cur = conn.cursor()
    cur.execute("SELECT mode, config_hash FROM atm_state WHERE id=1")
    old = cur.fetchone()
    old_mode = old[0] if old else "disabled"
    config_hash = old[1] if old else ""
    cur.execute("""
        UPDATE atm_state SET mode=%s, last_state_change_at=NOW(),
               last_state_change_by=%s, pause_reason=%s WHERE id=1
    """, (new_mode, changed_by, reason))
    cur.execute("""
        INSERT INTO atm_state_events (old_mode, new_mode, changed_by, reason, config_hash)
        VALUES (%s, %s, %s, %s, %s)
    """, (old_mode, new_mode, changed_by, reason, config_hash))
    conn.commit()


def _account_automation_mode(conn, account):
    """Per-account automation_mode from the broker/account model (account_automation_policies).
    Returns the mode string, or None when there is no policy row (caller treats None as 'no override',
    preserving current behaviour). Read-only; tolerant of a missing table (returns None)."""
    try:
        cur = conn.cursor()
        cur.execute("""SELECT p.automation_mode FROM account_automation_policies p
            JOIN broker_accounts ba ON ba.id = p.account_id
            WHERE lower(replace(ba.account_key, '_ira', '')) = lower(replace(%s, '_ira', ''))
            LIMIT 1""", (account or "",))
        r = cur.fetchone()
        return r[0] if r else None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _log_decision(conn, proposal_id, symbol, strategy_id, target_account,
                  account_broker, account_mode, decision, rejection_reasons,
                  classifier_health, positions_open_account, positions_open_total,
                  new_today_account, new_today_total, daily_pnl_pct_account,
                  daily_pnl_pct_aggregate, b1_excluded, config_hash, atm_mode,
                  trade_id=None) -> int:
    # Self-heal: the shared db_adapter connection can be dropped during long approval / LLM
    # calls (DB idle timeout). A cached reference then reads 'connection already closed'.
    # db_adapter.get_connection() transparently reconnects the global if it's closed.
    if conn is None or getattr(conn, "closed", 0):
        from db_adapter import get_connection
        conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO atm_decision_log
            (proposal_id, symbol, strategy_id, target_account,
             account_broker, account_mode, decision, rejection_reasons,
             classifier_health, positions_open_account, positions_open_total,
             new_today_account, new_today_total, daily_pnl_pct_account,
             daily_pnl_pct_aggregate, b1_excluded, config_hash, atm_mode, trade_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (proposal_id, symbol, strategy_id, target_account,
          account_broker, account_mode, decision,
          json.dumps(rejection_reasons) if rejection_reasons else None,
          classifier_health, positions_open_account, positions_open_total,
          new_today_account, new_today_total, daily_pnl_pct_account,
          daily_pnl_pct_aggregate, b1_excluded, config_hash, atm_mode, trade_id))
    did = cur.fetchone()[0]
    conn.commit()
    return did


def _count_positions(conn, account_label: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open' AND target_account=%s",
                (account_label,))
    return cur.fetchone()[0] or 0


def _count_new_today(conn, account_label: str) -> int:
    """Count new trades opened today. Excludes closed/phantom/failed."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM paper_trades
        WHERE target_account=%s AND created_at::date = CURRENT_DATE
        AND status IN ('open', 'pending')
    """, (account_label,))
    return cur.fetchone()[0] or 0


def _daily_pnl_pct(conn, account_label: str) -> float:
    """Today's closed P&L as % of account equity (rough estimate)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(pnl), 0) FROM paper_trades
        WHERE target_account=%s AND status='closed' AND closed_at::date = CURRENT_DATE
    """, (account_label,))
    pnl = float(cur.fetchone()[0] or 0)
    # Get approximate equity — use 100K as default for paper, real accounts use holdings
    cur.execute("SELECT equity_source FROM accounts WHERE account_label=%s", (account_label,))
    row = cur.fetchone()
    equity = 100_000  # default for paper
    return round(pnl / equity * 100, 3) if equity else 0


def _in_operating_hours(hours_config: dict) -> bool:
    """Check if current time is within ATM operating hours (ET).

    Uses start_et for earliest evaluation (default: Alpaca premarket 04:00).
    Uses extended_hours_exit_et for latest exit evaluation (default: 19:30).
    New entries blocked after stop_new_entries_et (default: 15:30).
    """
    import pytz
    et = pytz.timezone("US/Eastern")
    now_et = datetime.now(et)
    # Start of ATM window (entries + exits)
    start = hours_config.get("start_et", "04:00")
    # End of ATM window (exits allowed until extended_hours_exit_et)
    exit_end = hours_config.get("extended_hours_exit_et", hours_config.get("stop_new_entries_et", "15:30"))
    h, m = map(int, start.split(":"))
    start_dt = now_et.replace(hour=h, minute=m, second=0, microsecond=0)
    h2, m2 = map(int, exit_end.split(":"))
    stop_dt = now_et.replace(hour=h2, minute=m2, second=0, microsecond=0)
    return start_dt <= now_et <= stop_dt


def _in_new_entry_window(hours_config: dict) -> bool:
    """Check if current time allows NEW entries (stricter than operating hours)."""
    import pytz
    et = pytz.timezone("US/Eastern")
    now_et = datetime.now(et)
    start = hours_config.get("start_et", "04:00")
    stop = hours_config.get("stop_new_entries_et", "15:30")
    h, m = map(int, start.split(":"))
    start_dt = now_et.replace(hour=h, minute=m, second=0, microsecond=0)
    h2, m2 = map(int, stop.split(":"))
    stop_dt = now_et.replace(hour=h2, minute=m2, second=0, microsecond=0)
    return start_dt <= now_et <= stop_dt


def _intraday_window_gate(strategy_id: str) -> dict:
    """Fail-closed intraday-window gate for the ATM fast-path (P0-3).

    Delegates to the shared, import-light resolver. A missing/malformed/unparsable
    window for an intraday strategy BLOCKS auto-approval with
    ``intraday_window_config_invalid`` — it never falls open. Non-intraday strategies
    are unrestricted (``applicable=False``)."""
    from intraday_window import evaluate_intraday_window
    return evaluate_intraday_window(strategy_id)


def resolve_atm_expiry(strategy_id, created_at, expires_at=None, now=None) -> dict:
    """P0-1: deterministic pre-approval expiry decision. Pure/testable (no DB).

    For INTRADAY strategies the authoritative TTL is the strategy's minutes-based
    intraday_execution.proposal_ttl_minutes (single source of truth, via
    proposal_lifecycle.get_expiry_datetime) — NOT the legacy 4-hour rule. A stored
    ``expires_at`` that is earlier is honored. Fail-safe: an intraday proposal whose
    freshness cannot be established (no created_at and no expires_at) is BLOCKED, never
    approved.

    Returns one of:
      {"action": "ok",     "intraday": bool, ...}
      {"action": "expire", "reason": "intraday_ttl_expired",
                           "lifecycle_status": "EXPIRED_INTRADAY", "message": str, ...}
      {"action": "block",  "reason": "intraday_ttl_unknown", "message": str, ...}
    Non-intraday strategies always return action="ok" here (the caller applies the
    legacy fallback rules).
    """
    from datetime import datetime, timezone
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        import proposal_lifecycle as _pl
        intraday = strategy_id in _pl.INTRADAY_STRATEGIES
    except Exception:
        _pl = None
        intraday = strategy_id in ("momentum_scalp", "gap_and_go")
    if not intraday:
        return {"action": "ok", "intraday": False}

    def _aware(dt):
        if dt is None:
            return None
        return dt if getattr(dt, "tzinfo", None) else dt.replace(tzinfo=timezone.utc)

    created_at = _aware(created_at)
    expires_at = _aware(expires_at)
    ttl_min = _pl._intraday_ttl_minutes(strategy_id) if _pl else 30

    # Authoritative expiry = created_at + TTL; honor a stored expires_at if it is earlier.
    eff_expiry = None
    if created_at is not None and _pl is not None:
        eff_expiry = _pl.get_expiry_datetime(strategy_id, created_at)
    elif created_at is not None:
        from datetime import timedelta
        eff_expiry = created_at + timedelta(minutes=ttl_min)
    if expires_at is not None and (eff_expiry is None or expires_at < eff_expiry):
        eff_expiry = expires_at

    if eff_expiry is None:
        return {"action": "block", "reason": "intraday_ttl_unknown", "intraday": True,
                "ttl_minutes": ttl_min,
                "message": (f"{strategy_id}: intraday proposal has no created_at/expires_at — "
                            f"cannot verify {ttl_min}min TTL freshness (fail-safe block)")}

    age_min = (now - created_at).total_seconds() / 60.0 if created_at is not None else None
    if now >= eff_expiry:
        msg = (f"{strategy_id}: intraday scalp proposal "
               + (f"aged {age_min:.0f}min ≥ " if age_min is not None else "past expiry, ")
               + f"{ttl_min}min TTL (expired {eff_expiry.isoformat()})")
        return {"action": "expire", "reason": "intraday_ttl_expired", "intraday": True,
                "lifecycle_status": "EXPIRED_INTRADAY", "ttl_minutes": ttl_min,
                "age_minutes": age_min, "effective_expiry": eff_expiry, "message": msg}

    return {"action": "ok", "intraday": True, "ttl_minutes": ttl_min,
            "age_minutes": age_min, "effective_expiry": eff_expiry}


def _acquire_atm_cycle_lock():
    """Non-blocking flock guard shared by cron (safe_flock) and enrichment immediate triggers."""
    try:
        fd = open(ATM_CYCLE_LOCK, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (IOError, OSError):
        try:
            fd.close()
        except Exception:
            pass
        return None


def _release_atm_cycle_lock(lock_fd):
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    except Exception:
        pass


def _expire_proposal_atomic(cur, pid, expiry_code, expiry_lifecycle, expiry_message) -> bool:
    """Transition PENDING → EXPIRED exactly once. Returns True if this call won the race."""
    cur.execute("""
        UPDATE paper_trade_proposals
        SET atm_expired_at = NOW(), atm_expiry_reason = %s,
            status = 'EXPIRED', lifecycle_status = %s,
            lifecycle_message = %s
        WHERE id = %s AND status = 'PENDING' AND atm_expired_at IS NULL
    """, (expiry_code, expiry_lifecycle, expiry_message, pid))
    return cur.rowcount > 0


def run_cycle():
    """Main ATM evaluation cycle."""
    lock_fd = _acquire_atm_cycle_lock()
    if lock_fd is None:
        log.info("ATM cycle skipped — another instance holds tradeai_atm.lock")
        return
    try:
        _run_cycle_locked()
    finally:
        _release_atm_cycle_lock(lock_fd)


def _run_cycle_locked():
    """Main ATM evaluation cycle (caller holds tradeai_atm.lock)."""
    conn = get_connection()
    if not conn:
        log.error("No DB connection")
        return

    # ── Pre-flight ──
    state = _get_atm_state(conn)
    mode = state.get("mode", "disabled")

    # Always update heartbeat + config_hash
    cur = conn.cursor()
    try:
        from atm_config_manager import load_config as _lc
        _, _ch = _lc()
    except Exception:
        _ch = None
    cur.execute("UPDATE atm_state SET last_evaluated_at = NOW(), config_hash = COALESCE(%s, config_hash) WHERE id = 1", (_ch,))
    conn.commit()

    if mode == "disabled":
        log.info("ATM mode=disabled, exiting")
        return

    if mode == "paused":
        pu = state.get("paused_until")
        if pu and datetime.now(timezone.utc) >= pu:
            log.info("Pause expired, resuming to active")
            _set_atm_mode(conn, "active", "system", "pause_expired")
            _telegram_both("ATM: pause expired, resuming ACTIVE mode")
            mode = "active"
        else:
            log.info(f"ATM mode=paused until {pu}")
            return

    # Load config
    from atm_config_manager import (load_config, get_enabled_accounts,
                                     get_effective_limits, is_bucket2_excluded,
                                     is_same_day_skip, get_strategy_filter,
                                     get_operating_hours, get_kill_switch_thresholds)
    cfg, config_hash = load_config()

    # Operating hours check
    hours = get_operating_hours()
    try:
        if not _in_operating_hours(hours):
            log.info("Outside operating hours")
            return
    except Exception as e:
        log.warning(f"Operating hours check failed (proceeding): {e}")

    # Kill switch checks
    enabled_accounts = get_enabled_accounts()
    if not enabled_accounts:
        log.info("No enabled accounts")
        return

    thresholds = get_kill_switch_thresholds()
    total_pnl_pct = 0
    for acct in enabled_accounts:
        pnl_pct = _daily_pnl_pct(conn, acct)
        total_pnl_pct += pnl_pct
        if pnl_pct <= -thresholds["per_account"]:
            log.warning(f"Per-account kill switch: {acct} at {pnl_pct:.1f}%")
            _telegram_both(f"ATM KILL SWITCH: {acct} daily P&L {pnl_pct:.1f}% — account paused")

    if total_pnl_pct <= -thresholds["aggregate"]:
        log.critical(f"Aggregate kill switch: {total_pnl_pct:.1f}% — pausing ATM")
        _set_atm_mode(conn, "paused", "kill_switch",
                      f"aggregate_daily_pnl_{total_pnl_pct:.1f}pct")
        _telegram_both(f"ATM KILL SWITCH FIRED: aggregate daily P&L {total_pnl_pct:.1f}% — ATM PAUSED")
        return

    # ── Load pending proposals (exclude already-expired) ──
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.symbol, p.strategy_id, p.target_account,
               p.atm_action, p.status, p.proposed_entry, p.proposed_stop,
               p.proposed_target1, p.proposed_shares,
               p.enrichment_status, p.enrichment_last_attempt_at, p.enrichment_failures,
               p.created_at, p.atm_evaluation_count, p.atm_last_failure_reason,
               p.proposed_rr, p.risk_gate_result, p.expires_at, p.lifecycle_status,
               p.discovery_source, p.origin, p.proposed_by
        FROM paper_trade_proposals p
        WHERE p.status = 'PENDING' AND p.atm_expired_at IS NULL
          AND COALESCE(p.proposal_kind, 'entry') = 'entry'
        ORDER BY p.created_at ASC
    """)
    # SAFETY: the entry path bracket-submits (buy + stop + target). proposal_kind='protection' rows
    # are stop modifications, NOT entries — they are handled by the protection pass below and must
    # never reach submit_paper_bracket here.
    cols = [d[0] for d in cur.description]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not proposals:
        log.info(f"ATM cycle: 0 pending entry proposals (mode={mode}) — skipping entry path")
        try:
            from protection_atm_pass import run_protection_pass
            pr = run_protection_pass(conn, mode=mode)
            log.info(f"ATM protection pass (entry-idle): auto_applied={pr['auto_applied']} "
                     f"operator_pending={pr['operator_pending']} advisory={pr['skipped_action']} failed={pr['failed']}")
        except Exception as e:
            log.warning(f"ATM protection pass error: {e}")
        return

    log.info(f"ATM cycle: {len(proposals)} pending proposals (mode={mode})")

    strategy_filter = get_strategy_filter()
    from atm_classifier_health import get_health

    # Account info cache
    cur.execute("SELECT account_label, broker, mode FROM accounts")
    account_info = {r[0]: {"broker": r[1], "mode": r[2]} for r in cur.fetchall()}

    approved_count = 0
    rejected_count = 0
    expired_this_cycle = []  # for batched Telegram

    for p in proposals:
        pid = p["id"]
        sym = p["symbol"]
        sid = p["strategy_id"] or "unknown"
        target = p["target_account"]
        reasons = []   # init before any branch appends to it — the no-target branch below referenced it
                       # before it was set (was only assigned after this block), crashing the whole cycle.
        if not target:
            reasons.append({"gate": "account_resolution_missing", "detail": "proposal has no target_account"})
            _log_decision(conn, pid, sym, sid, "UNRESOLVED", "unknown", "unknown",
                         "deferred", reasons, 0, 0, 0, 0, 0, 0, 0,
                         False, config_hash, mode)
            log.info(f"  {sym}: deferred (no target_account on proposal)")
            continue
        decision = None
        b1_flag = False

        acct = account_info.get(target, {})
        acct_broker = acct.get("broker", "unknown")
        acct_mode = acct.get("mode", "unknown")

        # ── 0: Per-account automation_mode gate (broker/account model) ──
        # ADDITIVE safety layer: it can only PREVENT auto-approval, never bypass the live-trading
        # interlock and never change the submission endpoint (the account adapter + ALPACA_MODE still
        # govern paper-vs-live). No policy row → no override (current behaviour preserved).
        _amode = _account_automation_mode(conn, target)
        if _amode in ("DISABLED", "MANUAL_REVIEW", "PAUSED_ENTRIES", "EMERGENCY_STOP"):
            log.info(f"  {sym}: HELD — account {target} automation_mode={_amode} (no auto-approve; left PENDING for manual review)")
            continue
        if _amode == "AUTO_LIVE" and acct_mode == "live":
            # Real-money live submission must pass the live-trading gate; never auto-arm live here.
            _live_ok = False
            try:
                from live_trading_interlock import assert_writable, InterlockRefused, _conn as _il_conn
                _ic = _il_conn()
                try:
                    assert_writable(_ic, target, action="AUTO_LIVE auto-submit")
                    _live_ok = True
                except InterlockRefused:
                    _live_ok = False
                finally:
                    _ic.close()
            except Exception:
                _live_ok = False  # fail-closed
            if not _live_ok:
                log.info(f"  {sym}: HELD — AUTO_LIVE on live account {target} blocked by live-trading interlock")
                continue
        # AUTO_PAPER, AUTO_LIVE on a paper account (paper endpoint — no real money), or no policy → proceed.

        # ── 1: Proposal expiry check (P0-1) ──
        # INTRADAY strategies expire on their authoritative minutes-based TTL
        # (intraday_execution.proposal_ttl_minutes — single source of truth). The legacy
        # 4-hour rule is a FALLBACK only for non-intraday / legacy proposals.
        expiry_code = None
        expiry_lifecycle = "EXPIRED"
        expiry_message = None
        expiry_gate = "atm_expired"
        proposal_age_hours = 0
        try:
            _created = p.get("created_at")
            if _created:
                if hasattr(_created, 'tzinfo') and _created.tzinfo:
                    proposal_age_hours = (datetime.now(timezone.utc) - _created).total_seconds() / 3600
                else:
                    proposal_age_hours = (datetime.utcnow() - _created).total_seconds() / 3600
        except Exception:
            pass

        eval_count = p.get("atm_evaluation_count") or 0
        last_fail = p.get("atm_last_failure_reason") or ""

        _exp = resolve_atm_expiry(sid, p.get("created_at"), p.get("expires_at"))
        if _exp["action"] == "block":
            # Fail-safe: intraday proposal whose freshness can't be established — never approve,
            # but do NOT permanently expire (await created_at/expires_at on a later cycle).
            _log_decision(conn, pid, sym, sid, target,
                          acct.get("broker", "unknown"), acct.get("mode", "unknown"),
                          "deferred",
                          [{"gate": _exp["reason"], "detail": _exp["message"]}],
                          0, 0, 0, 0, 0, 0, 0, False, config_hash, mode)
            log.info(f"  {sym}: deferred — {_exp['message']}")
            continue
        if _exp["action"] == "expire":
            # Authoritative intraday TTL expiry — independent of the 4-hour rule.
            expiry_code = _exp["reason"]                     # 'intraday_ttl_expired'
            expiry_lifecycle = _exp["lifecycle_status"]      # 'EXPIRED_INTRADAY'
            expiry_message = _exp["message"]
            expiry_gate = "intraday_ttl_expired"
        elif not _exp.get("intraday"):
            # NON-INTRADAY fallback: honor stored expires_at first, then legacy 4h / failure rules.
            _exp_at = p.get("expires_at")
            if _exp_at is not None:
                try:
                    _ea = _exp_at if getattr(_exp_at, "tzinfo", None) else _exp_at.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) >= _ea:
                        expiry_code = f"expires_at_reached ({_ea.isoformat()})"
                except Exception:
                    pass
            if not expiry_code and proposal_age_hours > 4:
                expiry_code = f"age_exceeded_4h ({proposal_age_hours:.1f}h)"
            elif not expiry_code and eval_count >= 5 and "approve_proposal_failed" in last_fail:
                expiry_code = f"persistent_approval_failure ({eval_count} attempts)"
            elif not expiry_code and (p.get("enrichment_status") == "FAILED"
                                      and (p.get("enrichment_failures") or 0) >= 3):
                expiry_code = "enrichment_failed_3x"
        # NOTE: for an intraday proposal with action=="ok" we deliberately do NOT apply the
        # 4-hour rule — its only expiry authority is the minutes-based TTL above.

        if expiry_code:
            if expiry_message is None:
                expiry_message = f"ATM expired: {expiry_code}"
            if not _expire_proposal_atomic(cur, pid, expiry_code, expiry_lifecycle, expiry_message):
                log.info(f"  {sym}: expiry skipped — already expired by another cycle")
                continue
            conn.commit()
            _log_decision(conn, pid, sym, sid, target,
                          acct.get("broker", "unknown"), acct.get("mode", "unknown"),
                          "rejected",
                          [{"gate": expiry_gate, "detail": expiry_message}],
                          0, 0, 0, 0, 0, 0, 0, False, config_hash, mode)
            expired_this_cycle.append(f"{sym} ({expiry_code})")
            log.info(f"  {sym}: EXPIRED — {expiry_code}")
            continue

        pos_open = _count_positions(conn, target)
        pos_total = sum(_count_positions(conn, a) for a in enabled_accounts)
        new_today = _count_new_today(conn, target)
        new_total = sum(_count_new_today(conn, a) for a in enabled_accounts)
        pnl_acct = _daily_pnl_pct(conn, target)
        health = get_health(sid)

        # ── 2a-pre: Enrichment freshness check ──
        _enrich_status = p.get("enrichment_status")
        _enrich_failures = p.get("enrichment_failures") or 0
        if _enrich_status == "FAILED" and _enrich_failures >= 3:
            reasons.append({"gate": "enrichment_failed_3x"})
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         "deferred", reasons, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            log.info(f"  {sym}: deferred (enrichment failed 3x)")
            continue
        if _enrich_status not in ("COMPLETE",):
            # Source-neutral fast-track: curated pipelines (pullback/MACD, watchlist) with complete
            # levels on paper, OR legacy fresh+APPROVED+R:R≥2. No origin/discovery filter on SELECT.
            from atm_proposal_source_policy import atm_enrichment_bypass
            _rr = float(p.get("proposed_rr") or 0) if p.get("proposed_rr") else 0
            _rg = p.get("risk_gate_result") or ""
            _fast_track, _ft_reason = atm_enrichment_bypass(
                p, acct_mode=acct_mode, proposal_age_hours=proposal_age_hours,
            )

            if _fast_track:
                _src = p.get("discovery_source") or p.get("origin") or "auto"
                log.info(f"  {sym}: FAST-TRACK ({_ft_reason}) — source={_src}, R:R={_rr:.1f}, "
                         f"risk={_rg}, age={proposal_age_hours:.1f}h (skipping enrichment)")
            else:
                reasons.append({"gate": "not_yet_enriched", "detail": f"status={_enrich_status}"})
                _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                             "deferred", reasons, health, pos_open, pos_total,
                             new_today, new_total, pnl_acct, total_pnl_pct,
                             b1_flag, config_hash, mode)
                log.info(f"  {sym}: deferred (not yet enriched, status={_enrich_status})")
                continue

        # ── 2a: Per-proposal override ──
        atm_action = p.get("atm_action")
        if atm_action == "force_skip":
            decision = "force_skipped"
        elif atm_action == "force_reject":
            decision = "force_rejected"
            cur.execute("UPDATE paper_trade_proposals SET status='REJECTED' WHERE id=%s", (pid,))
            conn.commit()
        elif atm_action == "force_approve":
            # Skip ATM-specific gates (2c-2e) but still run hard gates via approve_proposal
            pass  # Fall through to approval below

        if decision:
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         decision, reasons, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            log.info(f"  {sym}: {decision}")
            continue

        # ── 2b: Target account check ──
        if target not in enabled_accounts:
            reasons.append({"gate": "account_disabled", "detail": f"{target} not in enabled accounts"})
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         "deferred", reasons, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            log.info(f"  {sym}: deferred (account {target} disabled)")
            continue

        # ── 2c: B-1 + same-day filters ──
        if is_bucket2_excluded(sid):
            b1_flag = True
            reasons.append({"gate": "bucket2_b1_observation_active"})
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         "deferred", reasons, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            log.info(f"  {sym}: deferred (B-1 bucket2 exclusion)")
            continue

        if is_same_day_skip(sid):
            # Same-day strategies (momentum_scalp, gap_and_go) proceed through normal
            # ATM gates. The cadence skip was removed because ATM should auto-trade
            # all approved strategies. If timing is critical, the enrichment pipeline
            # should trigger ATM evaluation immediately on ENTRY_ZONE_VALID.
            log.info(f"  {sym}: same-day strategy {sid} — proceeding through normal ATM gates")

        # ── 2d: Intraday trading window (scalp fast-path: only act inside the strategy's window,
        # e.g. momentum_scalp 6am-noon ET). Outside the window — OR on any window-config parse
        # failure — the scalp must not auto-trade (fail closed, P0-3). ──
        _wg = _intraday_window_gate(sid)
        if _wg.get("blocked"):
            reasons.append({"gate": _wg.get("code") or "outside_intraday_window",
                            "detail": _wg.get("reason") or f"{sid} intraday window"})

        # ── 2e: ATM-specific gates (skipped for force_approve) ──
        if atm_action != "force_approve":
            limits = get_effective_limits(target)

            # Classifier health
            min_health = strategy_filter.get("min_classifier_health", 0.5)
            if health < min_health:
                reasons.append({"gate": "classifier_health",
                                "detail": f"{health:.3f} < {min_health}"})

            # Whitelist/blacklist
            wl = strategy_filter.get("whitelist", [])
            bl = strategy_filter.get("blacklist", [])
            if wl and sid not in wl:
                reasons.append({"gate": "not_in_whitelist"})
            if bl and sid in bl:
                reasons.append({"gate": "in_blacklist"})

            # Position limits
            if pos_open >= limits.get("max_concurrent", 10):
                reasons.append({"gate": "max_concurrent",
                                "detail": f"{pos_open} >= {limits['max_concurrent']}"})
            if new_today >= limits.get("max_new_per_day", 6):
                reasons.append({"gate": "max_new_per_day",
                                "detail": f"{new_today} >= {limits['max_new_per_day']}"})

            if reasons:
                decision = "rejected" if mode == "active" else "dry_run_rejected"
                _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                             decision, reasons, health, pos_open, pos_total,
                             new_today, new_total, pnl_acct, total_pnl_pct,
                             b1_flag, config_hash, mode)
                # Actually reject the proposal so it stops re-alerting
                if mode == "active":
                    _reason_text = ", ".join(r["gate"] for r in reasons)
                    cur.execute("""UPDATE paper_trade_proposals
                        SET status='REJECTED', rejection_reason=%s, rejected_at=NOW(), updated_at=NOW()
                        WHERE id=%s AND status='PENDING'""",
                        [f"atm_gate: {_reason_text}"[:200], pid])
                    conn.commit()
                rejected_count += 1
                log.info(f"  {sym}: {decision} ({[r['gate'] for r in reasons]})")
                continue

        # ── 2e-bis: Authoritative trade plan (no R:R-only gambling geometry) ──
        try:
            import broker_trade_plan_gate as btpg
            import remediate_proposal_trade_plans as rtpr
            tp_gate = btpg.assess_proposal_trade_plan(pid, conn=conn)
            if not tp_gate.get("allowed"):
                rtpr.remediate_symbol(conn, sym, proposal_ids=[pid])
                tp_gate = btpg.assess_proposal_trade_plan(pid, conn=conn)
            if not tp_gate.get("allowed"):
                v0 = (tp_gate.get("violations") or ["no authoritative trade plan"])[0]
                reasons.append({"gate": "trade_plan_blocked", "detail": str(v0)[:160]})
                _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                             "deferred", reasons, health, pos_open, pos_total,
                             new_today, new_total, pnl_acct, total_pnl_pct,
                             b1_flag, config_hash, mode)
                log.info(f"  {sym}: deferred (trade plan blocked — {v0[:80]})")
                continue
        except Exception as _tp_e:
            log.warning(f"  {sym}: trade plan gate check failed (non-fatal): {_tp_e}")

        # ── 2e-ter: Finviz technical gate (align ATM with Proposals technical grade) ──
        # Curated paper-lane proposals (pullback_macd, watchlist) already passed screener/bridge
        # quality — skip Finviz on paper accounts so ATM burn-in isn't blocked by lagging scores.
        _skip_finviz = False
        if acct_mode == "paper":
            try:
                from atm_proposal_source_policy import is_curated_proposal
                _skip_finviz = is_curated_proposal(p)
            except Exception:
                _skip_finviz = False
        if _skip_finviz:
            log.info(f"  {sym}: skipping Finviz technical gate (curated paper-lane source)")
        else:
            try:
                from atm_technical_gate import atm_technical_allowed
                _lp = None
                try:
                    _lp = float(p.get("proposed_entry") or 0) or None
                except Exception:
                    pass
                _ok, _tg_reason, _tg_meta = atm_technical_allowed(
                    pid, sym, conn=conn, live_price=_lp,
                )
                if not _ok:
                    _detail = (
                        f"{_tg_meta.get('technical_grade')} score={_tg_meta.get('technical_score')} "
                        f"({_tg_reason})"
                    )
                    reasons.append({"gate": "finviz_technical", "detail": _detail[:160]})
                    _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                                 "deferred", reasons, health, pos_open, pos_total,
                                 new_today, new_total, pnl_acct, total_pnl_pct,
                                 b1_flag, config_hash, mode)
                    log.info(f"  {sym}: deferred (Finviz technical — {_detail[:80]})")
                    continue
            except Exception as _ft_e:
                log.warning(f"  {sym}: Finviz technical gate check failed (non-fatal): {_ft_e}")

        # ── 2f: Decision ──
        if mode == "dry_run":
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         "dry_run_approved", None, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            log.info(f"  {sym}: dry_run_approved (would approve)")
            continue

        # mode == 'active' — actually approve
        try:
            from paper_trade_logger import approve_proposal
            result = approve_proposal(pid)
            # approve_proposal can run long (LLM / broker) and the shared DB connection may be
            # dropped by the server mid-cycle. Re-acquire a live conn+cursor before logging the
            # decision / committing, so we never write on a stale 'connection already closed'.
            conn = get_connection()
            cur = conn.cursor()

            if not result.get("success"):
                fail_reason = result.get("message", "unknown")[:200]
                reasons.append({"gate": "approve_proposal_failed",
                                "detail": fail_reason})
                _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                             "rejected", reasons, health, pos_open, pos_total,
                             new_today, new_total, pnl_acct, total_pnl_pct,
                             b1_flag, config_hash, mode)
                # Track evaluation count for expiry detection
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET atm_evaluation_count = atm_evaluation_count + 1,
                        atm_last_evaluation_at = NOW(),
                        atm_last_failure_reason = %s
                    WHERE id = %s
                """, (f"approve_proposal_failed: {fail_reason[:150]}", pid))
                conn.commit()
                rejected_count += 1
                log.warning(f"  {sym}: REJECTED by hard gates ({fail_reason[:80]})")
                continue

            # Submit to broker
            trade_id = result.get("paper_trade_id")
            broker_status = "not_attempted"
            sub_result = {}
            try:
                from proposal_paper_submitter import submit_paper
                from session13_db import get_conn as _sub_conn
                sub_conn = _sub_conn()
                if sub_conn:
                    sub_result = submit_paper(sub_conn, pid, dry_run=False) or {}
                    sub_conn.close()
                    broker_status = sub_result.get("status", "unknown")
            except Exception as se:
                broker_status = f"error: {se}"
                log.error(f"  {sym}: broker submit failed: {se}")

            _broker_ok = broker_status in ("submitted", "simulation", "dry_run")
            if not _broker_ok:
                fail_detail = (
                    sub_result.get("block_detail")
                    or sub_result.get("reason")
                    or sub_result.get("error")
                    or (sub_result.get("blockers") or [None])[0]
                    or broker_status
                )
                if isinstance(fail_detail, list):
                    fail_detail = "; ".join(str(x) for x in fail_detail)
                fail_detail = str(fail_detail)[:200]
                reasons.append({"gate": "broker_submit_failed", "detail": fail_detail})
                _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                             "rejected", reasons, health, pos_open, pos_total,
                             new_today, new_total, pnl_acct, total_pnl_pct,
                             b1_flag, config_hash, mode, trade_id)
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET atm_evaluation_count = atm_evaluation_count + 1,
                        atm_last_evaluation_at = NOW(),
                        atm_last_failure_reason = %s
                    WHERE id = %s
                """, (f"cancelled_broker_submit: {fail_detail[:150]}", pid))
                conn.commit()
                rejected_count += 1
                log.warning(f"  {sym}: CANCELLED — proposal #{pid} trade #{trade_id} "
                            f"broker={broker_status}: {fail_detail} (operator notified by submitter)")
                continue

            # Stamp ATM provenance on the trade
            decision_id = _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                                        "force_approved" if atm_action == "force_approve" else "approved",
                                        None, health, pos_open, pos_total,
                                        new_today, new_total, pnl_acct, total_pnl_pct,
                                        b1_flag, config_hash, mode, trade_id)

            if trade_id:
                cur.execute("""
                    UPDATE paper_trades SET atm_decision_id=%s, atm_config_hash=%s,
                           atm_during_b1=%s WHERE id=%s
                """, (decision_id, config_hash,
                      cfg.get("b1_tracking", {}).get("enabled", False), trade_id))
                conn.commit()

            approved_count += 1
            shares = result.get("shares", p.get("proposed_shares", 0))
            entry = result.get("entry", p.get("proposed_entry", 0))
            log.info(f"  {sym}: APPROVED — trade #{trade_id}, broker={broker_status}")

            _telegram_both(
                f"ATM auto-approved: {sym} ({sid.replace('_', ' ')}) "
                f"qty={shares} entry=${entry:.2f} -> {target} "
                f"({acct_broker}/{acct_mode}) broker={broker_status}"
            )

        except Exception as e:
            log.error(f"  {sym}: approval error: {e}")
            reasons.append({"gate": "exception", "detail": str(e)[:200]})
            _log_decision(conn, pid, sym, sid, target, acct_broker, acct_mode,
                         "rejected", reasons, health, pos_open, pos_total,
                         new_today, new_total, pnl_acct, total_pnl_pct,
                         b1_flag, config_hash, mode)
            rejected_count += 1

    # Batched Telegram for expired proposals (per-symbol 24h dedup)
    if expired_this_cycle:
        _telegram_expiry_batch(expired_this_cycle)

    expired_count = len(expired_this_cycle)
    deferred_count = len(proposals) - approved_count - rejected_count - expired_count
    log.info(f"ATM cycle complete: {approved_count} approved, {rejected_count} rejected, "
             f"{expired_count} expired, {deferred_count} deferred")

    # Protection adjustments are governed by the SAME ATM cycle: paper positions auto-apply the
    # guarded stop-up actions; real positions stay PROPOSED for operator approval (+2FA). Nothing
    # is applied without a paper_protection_adjustment_proposals record.
    try:
        from protection_atm_pass import run_protection_pass
        pr = run_protection_pass(conn, mode=mode)
        log.info(f"ATM protection pass: auto_applied={pr['auto_applied']} "
                 f"operator_pending={pr['operator_pending']} advisory={pr['skipped_action']} failed={pr['failed']}")
    except Exception as e:
        log.warning(f"ATM protection pass error: {e}")


if __name__ == "__main__":
    run_cycle()
