"""Broker Access & Sync — Command Center read model (operator 2026-10-16: one place for broker access and sync).

Brings together what was scattered across CLI output, Telegram and logs. READ-ONLY, and nothing here calls a broker:

- Schwab access mode   ``lib/schwab_access_mode.status()`` (config/schwab_access_mode.yaml: forbidden/read_only/normal)
- trading lock         ``lib/trading_lock.status()`` (pure read of the lock files) + today's refusals from its audit
- Schwab token state   ``broker_oauth_tokens`` METADATA columns only (expiry, degraded, last_error; ``has_token`` is
                       computed in SQL as ``refresh_token_enc IS NOT NULL`` so no token value ever leaves the DB) and
                       the last successful ``reauth`` row of ``broker_oauth_token_audit`` (the true 7-day clock, the
                       same anchor as ``/api/v2/brokers/schwab/token-health`` and ``schwab_auto_reauth.py --status``),
                       plus the auto-reauth state file ``data/runtime/schwab_auto_reauth_state.json``. No decrypt, no
                       live probe.
- sync freshness       the position store's per-account classification (``account_summaries[*].account_state``,
                       written by portfolio_loader via ``lib/account_state``), ``schwab_sync_history``, the newest
                       ``schwab_api`` row in ``trade_transactions``, the Alpaca fail-streak file, the moomoo sync
                       receipt + OpenD health receipt, ``snaptrade_sync_state.json``, ``positions_sync_runs`` (with
                       ``positions_sync.freshness`` — the exact ``--check-fresh`` semantics), and the operator's latest
                       ``sync_all_*_apply.log`` (step names, rc and a fixed signal vocabulary; raw output is never
                       returned).
- stop health          ``data/runtime/stop_health_last.json`` + open ``alert_events`` rows from ``stop_health``.

Every broker row carries one state from ``STATES`` and a reason. An empty or unreadable source is never "OK": it is
DEGRADED with "no evidence". ``db_query`` is injected (``callable(sql, params=None, fetch="all")``); without it the DB
sections say so. Output ``BrokerAccess@v1``, cached per process for ``CACHE_TTL_S``. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCHEMA = "BrokerAccess@v1"
CACHE_TTL_S = 45.0
PROJECT_ROOT = Path(__file__).resolve().parents[3]

OK, STALE, DEGRADED, PAUSED, NEEDS_REAUTH = "OK", "STALE", "DEGRADED", "PAUSED", "NEEDS_REAUTH"
STATES = (OK, STALE, DEGRADED, PAUSED, NEEDS_REAUTH)
#: Worst-first, for the overall roll-up.
SEVERITY = {NEEDS_REAUTH: 4, DEGRADED: 3, PAUSED: 2, STALE: 1, OK: 0}

#: Schwab refresh tokens have a FIXED 7-day lifetime from the browser login (schwab_auto_reauth.py docstring).
TRUE_LOGIN_LIFETIME_DAYS = 7.0
#: Fallbacks only; the live values are read (not imported) from scripts/schwab_auto_reauth.py.
AUTO_REAUTH_DEFAULTS = {"REAUTH_AT_DAYS": 6.0, "ALLOWED_HOURS": [8, 22], "MAX_PER_DAY": 4, "MIN_GAP_MIN": 120}
#: A receipt-backed sync (moomoo receipt, Alpaca streak file) older than this is STALE.
RECEIPT_STALE_HOURS = 24.0
#: The newest Schwab API transaction older than this is STALE (weekends + a holiday fit inside).
TRANSACTIONS_STALE_DAYS = 5.0
STOP_ALERT_LOOKBACK_DAYS = 7
MAX_TEXT = 200
#: The trading-lock audit is append-only; today's refusals sit at its end.
AUDIT_TAIL_BYTES = 2 * 1024 * 1024

RUNTIME_REL = Path("data") / "runtime"
OPERATOR_SYNC_LOG_DIR_ENV = "TRADEAI_OPERATOR_SYNC_LOG_DIR"
OPERATOR_SYNC_LOG_DIR = Path.home() / "n8n-maturity-verification"
SYNC_COMMAND = "bash ~/n8n-maturity-verification/sync_all_readonly.sh"
SYNC_COMMAND_FUTURE = "scripts/ops/broker_read_sync.sh"
RUN_SYNC_DISABLED_REASON = "requires broker-read grant + ratified amendment"
REAUTH_PAGE = "/v3/system/schwab-reauth"

LINKS = [
    {"label": "Schwab Reauth", "href": REAUTH_PAGE},
    {"label": "Stop health / Risk", "href": "/v3/risk?drawer=stops"},
    {"label": "Coordination › What n8n did today", "href": "/v3/coordination?tab=today"},
]

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()

# ── redaction ─────────────────────────────────────────────────────────────────────────────────────
_REDACT = [
    (re.compile(r"(?i)\b(access_token|refresh_token|id_token|client_secret|secret|password|apikey|api_key|"
                r"authorization|bearer)\b(\s*[:=]\s*|\s+)\S+"), r"\1=[redacted]"),
    (re.compile(r"(?i)([?&]code=)[^&\s\"']+"), r"\1[redacted]"),
    (re.compile(r"\b\d{6,}\b"), "[number]"),  # account numbers / hashes never reach the page
]


def scrub(text: Any, limit: int = MAX_TEXT) -> Optional[str]:
    if text is None:
        return None
    s = " ".join(str(text).split())
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    return s[:limit]


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────
def default_state_root() -> Path:
    try:
        from lib.canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _parse(ts: Any) -> Optional[datetime]:
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if hasattr(ts, "year") and not isinstance(ts, datetime):  # a date
        return datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(ts: Any) -> Optional[str]:
    dt = _parse(ts)
    return dt.isoformat() if dt else None


def _age_h(ts: Any, now: datetime) -> Optional[float]:
    dt = _parse(ts)
    return None if dt is None else round((now - dt).total_seconds() / 3600.0, 2)


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _q(db_query: Optional[Callable], sql: str, params: Any = None) -> Optional[list]:
    """Rows, [] for an empty answer, None when the DB could not be asked."""
    if db_query is None:
        return None
    try:
        rows = db_query(sql, params)
    except Exception:  # noqa: BLE001
        return None
    if rows is None:
        return None
    return list(rows) if isinstance(rows, (list, tuple)) else [rows]


def _row(state: str, reason: str, **extra) -> dict:
    assert state in STATES, state
    return {"state": state, "reason": reason, **extra}


def _worst(states: list[str]) -> str:
    return max(states, key=lambda s: SEVERITY.get(s, 3)) if states else DEGRADED


def _auth_failure(text: Any) -> bool:
    if not text:
        return False
    try:
        from lib import schwab_access_mode as sam  # type: ignore
        return bool(sam._AUTH_FAILURE_RE.search(str(text)))
    except Exception:  # noqa: BLE001
        return bool(re.search(r"\b(401|403)\b|unauthori[sz]ed|reauth|re-auth|no schwab login token|degraded",
                              str(text), re.I))


def _sync_cfg() -> dict:
    try:
        import positions_sync as ps  # type: ignore
        return ps.load_sync_config()
    except Exception:  # noqa: BLE001
        return {"required_accounts": [], "optional_accounts": [], "stale_after_minutes_market": 30,
                "stale_after_hours_closed": 72}


def _schwab_accounts(cfg: dict) -> list[str]:
    accts = [a for a in (cfg.get("required_accounts") or []) + (cfg.get("optional_accounts") or [])
             if str(a).startswith("schwab")]
    return sorted(dict.fromkeys(accts))


# ── access mode + trading lock ────────────────────────────────────────────────────────────────────
def access_mode() -> dict:
    try:
        from lib import schwab_access_mode as sam  # type: ignore
        st = sam.status()
    except Exception as exc:  # noqa: BLE001 — an unreadable switch is reported, never guessed as normal
        return {"mode": "unknown", "paused": False, "reads_allowed": None, "since": None, "reason": None,
                "source": None, "error": scrub(f"{type(exc).__name__}: {exc}")}
    return {k: st.get(k) for k in ("mode", "paused", "reads_allowed", "since", "reason", "source", "error")}


def trading_lock_view(now: datetime) -> dict:
    out: dict[str, Any] = {"locked": True, "reason": None, "refusals_today": 0, "last_refusal": None}
    try:
        from lib import trading_lock as tl  # type: ignore
        st = tl.status()
        out.update(locked=bool(st.get("locked", True)), reason=scrub(st.get("reason")),
                   unlocked_until=st.get("unlocked_until"), brokers=st.get("brokers"))
        audit = Path(tl.audit_path())
    except Exception as exc:  # noqa: BLE001 — fail secure: an unreadable lock reads LOCKED
        out["reason"] = scrub(f"lock state unreadable ({type(exc).__name__}) — treated as LOCKED")
        return out
    try:
        et_now = now.astimezone(ET)
        midnight = datetime(et_now.year, et_now.month, et_now.day, tzinfo=ET).astimezone(timezone.utc)
        rows = []
        for raw in _tail_lines(audit, AUDIT_TAIL_BYTES):
            ts = _parse(raw.get("ts"))
            if ts and ts >= midnight and raw.get("event") == "refused":
                rows.append(raw)
        out["refusals_today"] = len(rows)
        if rows:
            last = rows[-1]
            out["last_refusal"] = {"at": last.get("ts"), "broker": last.get("broker"), "action": last.get("action"),
                                   "caller": scrub(last.get("caller"), 120)}
    except Exception:  # noqa: BLE001
        pass
    return out


def _tail_lines(path: Path, max_bytes: int) -> list[dict]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return []
    rows = []
    for raw in data.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


# ── auto-reauth schedule constants (parsed, never imported: the script loads env + browser bits) ─────
def auto_reauth_constants(path: Optional[Path] = None) -> dict:
    out = dict(AUTO_REAUTH_DEFAULTS)
    p = path or (PROJECT_ROOT / "scripts" / "schwab_auto_reauth.py")
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in out:
                    try:
                        v = ast.literal_eval(node.value)
                        out[name] = list(v) if isinstance(v, tuple) else v
                    except ValueError:
                        pass
        out["source"] = "scripts/schwab_auto_reauth.py"
    except (OSError, SyntaxError):
        out["source"] = "defaults"
    return out


# ── Schwab tokens ─────────────────────────────────────────────────────────────────────────────────
TOKEN_SQL = ("SELECT account_key, refresh_expires_at, next_reauth_due_at, access_expires_at, degraded, last_error, "
             "updated_at, (refresh_token_enc IS NOT NULL) AS has_token FROM broker_oauth_tokens "
             "WHERE broker='schwab' AND environment='live' ORDER BY account_key")
LOGIN_SQL = ("SELECT account_key, max(created_at) AS last_login FROM broker_oauth_token_audit "
             "WHERE broker='schwab' AND event='reauth' AND status='ok' GROUP BY account_key")
AUDIT_ERR_SQL = ("SELECT DISTINCT ON (account_key) account_key, event, status, detail, created_at "
                 "FROM broker_oauth_token_audit WHERE broker='schwab' AND COALESCE(status,'') <> 'ok' "
                 "ORDER BY account_key, created_at DESC")


def schwab_tokens(db_query: Optional[Callable], accounts: list[str], access: dict, state_root: Path,
                  now: datetime) -> dict:
    paused = bool(access.get("paused"))
    toks = _q(db_query, TOKEN_SQL)
    logins = _q(db_query, LOGIN_SQL)
    errs = _q(db_query, AUDIT_ERR_SQL)
    consts = auto_reauth_constants()
    state_file = _read_json(state_root / RUNTIME_REL / "schwab_auto_reauth_state.json") or {}
    login_by = {r.get("account_key"): r.get("last_login") for r in (logins or [])}
    err_by = {r.get("account_key"): r for r in (errs or [])}
    tok_by = {r.get("account_key"): r for r in (toks or [])}
    # one browser login covers every Schwab account; the newest one is the operator's real clock
    newest_login = max((_parse(v) for v in login_by.values() if _parse(v)), default=None)
    rows = []
    for acct in sorted(set(accounts) | set(tok_by)):
        t = tok_by.get(acct)
        last_login = _parse(login_by.get(acct)) or newest_login
        true_exp = last_login + timedelta(days=TRUE_LOGIN_LIFETIME_DAYS) if last_login else None
        due_at = last_login + timedelta(days=float(consts["REAUTH_AT_DAYS"])) if last_login else None
        days_left = round((true_exp - now).total_seconds() / 86400, 2) if true_exp else None
        last_error = scrub((t or {}).get("last_error"))
        audit_err = err_by.get(acct)
        if toks is None:
            cond, why = DEGRADED, "token store unreadable (no DB answer) — state unknown, not assumed healthy"
        elif t is None:
            cond, why = NEEDS_REAUTH, "no token on file — a browser login is required"
        elif not t.get("has_token"):
            cond, why = NEEDS_REAUTH, "token row has no refresh token — a browser login is required"
        elif t.get("degraded"):
            cond, why = NEEDS_REAUTH, f"token marked degraded{': ' + last_error if last_error else ''}"
        elif days_left is not None and days_left <= 0:
            cond, why = NEEDS_REAUTH, "7-day login expired"
        elif _parse(t.get("refresh_expires_at")) and _parse(t.get("refresh_expires_at")) <= now:
            cond, why = NEEDS_REAUTH, "refresh token expired"
        elif _auth_failure(last_error):
            cond, why = NEEDS_REAUTH, f"last error looks like an auth failure: {last_error}"
        elif days_left is not None and days_left <= 1.0:
            cond, why = NEEDS_REAUTH, f"renewal window: {days_left:.1f} days to true expiry"
        elif last_login is None:
            cond, why = DEGRADED, "no successful reauth on record — the true 7-day clock is unknown"
        else:
            cond, why = OK, f"{days_left:.1f} days to true expiry"
        state, reason = cond, why
        if paused:
            state, reason = PAUSED, f"Schwab access paused ({access.get('mode')}); token: {why}"
        rows.append({
            "account_key": acct, "state": state, "reason": reason, "token_condition": cond,
            "has_token": bool(t and t.get("has_token")), "degraded": bool(t and t.get("degraded")),
            "last_login": _iso(last_login), "login_source": "audit:account" if login_by.get(acct) else
            ("audit:newest_any_account" if newest_login else None),
            "true_expiry": _iso(true_exp), "proactive_due_at": _iso(due_at), "days_left": days_left,
            "refresh_expires_at": _iso((t or {}).get("refresh_expires_at")),
            "access_expires_at": _iso((t or {}).get("access_expires_at")),
            "updated_at": _iso((t or {}).get("updated_at")),
            "last_error": last_error,
            "last_failed_event": ({"event": audit_err.get("event"), "status": audit_err.get("status"),
                                   "at": _iso(audit_err.get("created_at")), "detail": scrub(audit_err.get("detail"))}
                                  if audit_err else None),
        })
    auto = {
        "reauth_at_days": consts["REAUTH_AT_DAYS"], "allowed_hours_local": consts["ALLOWED_HOURS"],
        "max_per_day": consts["MAX_PER_DAY"], "min_gap_min": consts["MIN_GAP_MIN"], "constants_source": consts["source"],
        "mode": "notify-only (manual login); browser automation is opt-in",
        "last_attempt_at": _iso(state_file.get("last_attempt_at")), "last_result": state_file.get("last_result"),
        "last_state": state_file.get("last_state"), "last_error": scrub(state_file.get("last_error")),
        "attempts_day": state_file.get("attempts_day"), "attempts_count": state_file.get("attempts_count"),
        "proactive_due_at": _iso(newest_login + timedelta(days=float(consts["REAUTH_AT_DAYS"]))) if newest_login else None,
        "due_now": (any(r["token_condition"] == NEEDS_REAUTH for r in rows) or
                    bool(newest_login and now >= newest_login + timedelta(days=float(consts["REAUTH_AT_DAYS"])))),
        "status_command": "python3 scripts/schwab_auto_reauth.py --status",
    }
    return {"accounts": rows, "db": "ok" if toks is not None else "unavailable", "auto_reauth": auto}


# ── operator sync log ─────────────────────────────────────────────────────────────────────────────
_SIGNALS = [
    ("no account mapping", re.compile(r"no account mapping", re.I)),
    ("needs re-auth", re.compile(r"no schwab login token|re-?auth required|token degraded|\b401\b|unauthori[sz]ed",
                                 re.I)),
    ("degraded no-op", re.compile(r"degraded_noop", re.I)),
    ("paused", re.compile(r"schwab_paused|access mode=forbidden", re.I)),
    ("stop data unavailable", re.compile(r"stop data unavailable", re.I)),
    ("stale", re.compile(r'"stale":\s*true', re.I)),
    ("fresh", re.compile(r'"stale":\s*false', re.I)),
    ("wrote", re.compile(r'"wrote":\s*true', re.I)),
    ("error", re.compile(r'"ok":\s*false|traceback|\berror:', re.I)),
]


def latest_sync_log(log_dir: Optional[Path] = None) -> Optional[Path]:
    d = Path(log_dir or os.environ.get(OPERATOR_SYNC_LOG_DIR_ENV) or OPERATOR_SYNC_LOG_DIR)
    files = sorted(glob.glob(str(d / "sync_all_*_apply.log")))
    return Path(files[-1]) if files else None


def parse_sync_log(path: Optional[Path]) -> dict:
    """Step names, rc and a fixed signal vocabulary. Raw output is never returned."""
    if path is None:
        return {"present": False, "path": None, "steps": [], "note": "no sync_all_*_apply.log found"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"present": False, "path": path.name, "steps": [], "note": f"unreadable ({type(exc).__name__})"}
    m = re.search(r"sync_all_(\d{8}T\d{6}Z)_", path.name)
    ran_at = None
    if m:
        try:
            ran_at = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            ran_at = None
    head = text.splitlines()[0] if text else ""
    hm = re.search(r"mode=(\S+).*?schwab_access=(\S+).*?release=(\S+)", head)
    steps: list[dict] = []
    cur: Optional[dict] = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("=== "):
            cur = {"name": scrub(line[4:].strip(), 80), "rc": None}
            body = []
            continue
        rc = re.match(r"\s+rc=(\d+)\s*$", line)
        if rc and cur is not None:
            blob = "\n".join(body)
            cur["rc"] = int(rc.group(1))
            cur["signals"] = [name for name, rx in _SIGNALS if rx.search(blob)]
            steps.append(cur)
            cur = None
            continue
        if cur is not None:
            body.append(line)
    return {"present": True, "path": path.name, "ran_at": ran_at,
            "mode": hm.group(1) if hm else None, "schwab_access": hm.group(2) if hm else None,
            "release": hm.group(3) if hm else None, "steps": steps,
            "failed_steps": [s["name"] for s in steps if s.get("rc") not in (0, None)]}


def _log_step(log: dict, *needles: str) -> Optional[dict]:
    for s in log.get("steps") or []:
        n = str(s.get("name") or "").lower()
        if all(k in n for k in needles):
            return s
    return None


# ── per-broker rows ───────────────────────────────────────────────────────────────────────────────
def _holdings_doc(holdings_path: Optional[Path]) -> dict:
    try:
        from lib import portfolio_positions as pp  # type: ignore
        doc = pp.load_store(holdings_path) if holdings_path else pp.load_store()
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _acct_state(holdings: dict, acct: str) -> Optional[dict]:
    s = (holdings.get("account_summaries") or {}).get(acct)
    if not isinstance(s, dict):
        return None
    st = s.get("account_state") if isinstance(s.get("account_state"), dict) else {}
    return {"account": acct, "state": st.get("state") or s.get("state"),
            "reason": scrub(st.get("state_reason") or s.get("state_reason")),
            "last_sync_at": _iso(st.get("last_sync_at") or s.get("state_as_of")),
            "classified_at": _iso(st.get("classified_at")), "retired": bool(s.get("retired")),
            "retired_reason": scrub(s.get("retired_reason"), 120) if s.get("retired") else None}


def _from_account_states(states: list[dict]) -> tuple[str, str]:
    """Map lib/account_state vocabulary (LIVE/STALE/SERVICE_DOWN/...) onto ours."""
    if not states:
        return DEGRADED, "no account classification in the position store — no evidence"
    raw = {s["account"]: str(s.get("state") or "UNCLASSIFIED") for s in states}
    down = [a for a, v in raw.items() if v == "SERVICE_DOWN"]
    stale = [a for a, v in raw.items() if v == "STALE"]
    odd = [a for a, v in raw.items() if v not in ("LIVE", "STALE", "SERVICE_DOWN")]
    if down:
        return DEGRADED, f"service down: {', '.join(down)}"
    if odd:
        return DEGRADED, f"unclassified: {', '.join(odd)}"
    if stale:
        ages = [s.get("reason") for s in states if s["account"] in stale]
        return STALE, f"stale: {', '.join(stale)} ({ages[0]})"
    return OK, "; ".join(f"{s['account']}: {s.get('reason')}" for s in states)


def _needs_reauth(tokens: dict, step: Optional[dict], log: dict) -> list[str]:
    """Accounts whose token needs a login, from the token store; else the operator sync log's own evidence."""
    needs = [t["account_key"] for t in tokens.get("accounts", []) if t.get("token_condition") == NEEDS_REAUTH]
    if not needs and tokens.get("db") != "ok" and step and "needs re-auth" in (step.get("signals") or []):
        needs = [f"operator sync log {log.get('ran_at') or ''}".strip()]
    return needs


def schwab_positions_row(holdings: dict, accounts: list[str], access: dict, tokens: dict,
                         db_query: Optional[Callable], log: dict) -> dict:
    states = [x for x in (_acct_state(holdings, a) for a in _holdings_aliases(holdings, accounts)) if x]
    hist = _q(db_query, "SELECT DISTINCT ON (account_key) account_key, status, reason, position_count, "
                        "wrote_holdings, created_at FROM schwab_sync_history ORDER BY account_key, created_at DESC")
    last_runs = [{"account_key": h.get("account_key"), "status": h.get("status"), "reason": scrub(h.get("reason")),
                  "positions": h.get("position_count"), "wrote": h.get("wrote_holdings"),
                  "at": _iso(h.get("created_at"))} for h in (hist or [])]
    base_state, base_reason = _from_account_states(states)
    step = _log_step(log, "schwab", "positions")
    needs = _needs_reauth(tokens, step, log)
    flags = []
    if needs:
        flags.append(NEEDS_REAUTH)
    if access.get("paused"):
        state, reason = PAUSED, (f"Schwab access mode {access.get('mode')} since {access.get('since') or '?'}"
                                 f" ({access.get('reason') or 'operator pause'}); positions are cached — {base_reason}")
    elif needs:
        state, reason = NEEDS_REAUTH, f"login needed for {', '.join(needs)}; positions — {base_reason}"
    elif last_runs and all(r["status"] not in ("ok",) for r in last_runs if r.get("status")):
        state, reason = DEGRADED, f"latest Schwab syncs did not write: {last_runs[0]['status']} {last_runs[0]['reason'] or ''}"
    else:
        state, reason = base_state, base_reason
    return _row(state, reason, id="schwab_positions", broker="schwab", label="Schwab positions",
                flags=flags, accounts=states, last_runs=last_runs,
                last_success_at=max((s["last_sync_at"] for s in states if s.get("last_sync_at")), default=None),
                operator_log_step=step)


def _holdings_aliases(holdings: dict, accounts: list[str]) -> list[str]:
    """The store keys Schwab accounts by its own names (e.g. schwab_roth for schwab_roth_ira)."""
    keys = list((holdings.get("account_summaries") or {}).keys())
    out = []
    for a in accounts:
        if a in keys:
            out.append(a)
            continue
        alt = [k for k in keys if k.startswith("schwab") and (a.startswith(k) or k.startswith(a))]
        out.extend(alt[:1])
    return out


def schwab_transactions_row(access: dict, tokens: dict, db_query: Optional[Callable], log: dict,
                            now: datetime) -> dict:
    rows = _q(db_query, "SELECT account, max(trade_date) AS last_trade_date, count(*) AS n FROM trade_transactions "
                        "WHERE import_source = 'schwab_api' GROUP BY account ORDER BY account")
    per = [{"account": r.get("account"), "last_trade_date": _iso(r.get("last_trade_date")), "rows": r.get("n")}
           for r in (rows or [])]
    newest = max((_parse(p["last_trade_date"]) for p in per if p.get("last_trade_date")), default=None)
    step = _log_step(log, "schwab", "transactions")
    needs = _needs_reauth(tokens, step, log)
    if access.get("paused"):
        state, reason = PAUSED, f"Schwab access mode {access.get('mode')}; no transaction ingest while paused"
    elif needs:
        state, reason = NEEDS_REAUTH, f"login needed for {', '.join(needs)}"
    elif rows is None:
        state, reason = DEGRADED, "trade_transactions unreadable (no DB answer) — no evidence"
    elif newest is None:
        state, reason = DEGRADED, "no schwab_api transactions on file — no evidence"
    elif (now - newest).total_seconds() > TRANSACTIONS_STALE_DAYS * 86400:
        state, reason = STALE, f"newest Schwab API transaction is {newest.date().isoformat()}"
    else:
        state, reason = OK, f"newest Schwab API transaction {newest.date().isoformat()}"
    flags = [NEEDS_REAUTH] if needs else []
    return _row(state, reason, id="schwab_transactions", broker="schwab", label="Schwab transactions", flags=flags,
                accounts=per, last_success_at=_iso(newest), operator_log_step=step,
                note="last_success_at is the newest ingested trade date, not the ingest run time")


def alpaca_row(holdings: dict, cfg: dict, state_root: Path, log: dict, now: datetime) -> dict:
    accts = [a for a in (cfg.get("optional_accounts") or []) if str(a).startswith("alpaca")]
    states = [x for x in (_acct_state(holdings, a) for a in accts) if x]
    streak_path = state_root / RUNTIME_REL / "alpaca_live_read_fail_streak.json"
    streak = _read_json(streak_path)
    streaks = {a: int((streak or {}).get(a) or 0) for a in accts} if isinstance(streak, dict) else {}
    step = _log_step(log, "alpaca")
    state, reason = _from_account_states(states)
    bad = {a: n for a, n in streaks.items() if n > 0}
    if bad:
        state, reason = DEGRADED, "read failures in a row: " + ", ".join(f"{a} ×{n}" for a, n in bad.items())
    return _row(state, reason, id="alpaca_live", broker="alpaca", label="Alpaca live read", flags=[],
                accounts=states, fail_streak=streaks, fail_streak_file_updated_at=_mtime_iso(streak_path),
                last_success_at=max((s["last_sync_at"] for s in states if s.get("last_sync_at")), default=None),
                operator_log_step=step)


def moomoo_row(holdings: dict, cfg: dict, state_root: Path, log: dict, now: datetime) -> dict:
    accts = [a for a in (cfg.get("optional_accounts") or []) if str(a).startswith("moomoo")]
    rt = state_root / RUNTIME_REL
    receipts = []
    for a in accts:
        r = _read_json(rt / "sync_receipts" / f"{a}.json")
        if isinstance(r, dict):
            receipts.append({"account": a, "ok": r.get("ok"), "at": _iso(r.get("at")), "error": scrub(r.get("error")),
                             "rows": r.get("n_rows"), "wrote": r.get("wrote")})
    health = _read_json(rt / "moomoo_opend_health.json")
    opend = ({"ok": health.get("ok"), "checked_at": _iso(health.get("checked_at")),
              "unit_active": (health.get("unit") or {}).get("active"),
              "quote_ok": (health.get("quote") or {}).get("ok"), "fail_streak": health.get("fail_streak")}
             if isinstance(health, dict) else None)
    states = [x for x in (_acct_state(holdings, a) for a in accts) if x]
    step = _log_step(log, "moomoo")
    if not receipts:
        state, reason = DEGRADED, "no moomoo sync receipt — no evidence"
    elif any(r["ok"] is False for r in receipts):
        bad = [r for r in receipts if r["ok"] is False][0]
        state, reason = DEGRADED, f"last sync failed: {bad.get('error') or 'error'}"
    elif any((_age_h(r["at"], now) or 1e9) > RECEIPT_STALE_HOURS for r in receipts):
        state, reason = STALE, f"last sync receipt older than {RECEIPT_STALE_HOURS:g}h"
    elif opend and opend.get("ok") is False:
        state, reason = DEGRADED, "OpenD health probe failing"
    else:
        r = receipts[0]
        state, reason = OK, f"synced {_age_h(r['at'], now)}h ago ({r.get('rows')} rows)"
    retired = [s for s in states if s.get("retired")]
    return _row(state, reason, id="moomoo", broker="moomoo", label="moomoo", flags=[], receipts=receipts,
                opend=opend, accounts=states,
                last_success_at=max((r["at"] for r in receipts if r.get("ok") and r.get("at")), default=None),
                operator_log_step=step,
                note=(f"position store marks {', '.join(s['account'] for s in retired)} retired: "
                      f"{retired[0].get('retired_reason')}") if retired else None)


def snaptrade_row(state_root: Path, log: dict) -> dict:
    st_path = state_root / RUNTIME_REL / "snaptrade_sync_state.json"
    st = _read_json(st_path)
    mapping = PROJECT_ROOT / "config" / "snaptrade_accounts.json"
    mapped = mapping.is_file()
    step = _log_step(log, "snaptrade")
    sig = set((step or {}).get("signals") or [])
    if "no account mapping" in sig or not mapped:
        state, reason = DEGRADED, "no account mapping (config/snaptrade_accounts.json) — SnapTrade sync cannot run"
    elif step and step.get("rc") not in (0, None):
        state, reason = DEGRADED, f"last operator sync step exited rc={step.get('rc')}"
    elif st is None:
        state, reason = DEGRADED, "no SnapTrade sync state — no evidence"
    else:
        state, reason = OK, "SnapTrade sync state present"
    return _row(state, reason, id="snaptrade", broker="snaptrade", label="SnapTrade", flags=[],
                mapping_file_present=mapped, state_file_updated_at=_mtime_iso(st_path),
                missing_accounts=len((st or {}).get("missing") or {}) if isinstance(st, dict) else None,
                last_success_at=None, operator_log_step=step)


def positions_store_row(cfg: dict, db_query: Optional[Callable], log: dict, now: datetime) -> dict:
    last = _q(db_query, "SELECT max(finished_at) AS last_complete FROM positions_sync_runs "
                        "WHERE status = 'complete' AND promoted")
    latest = _q(db_query, "SELECT run_id, started_at, finished_at, status, promoted, accounts_ok, accounts_failed "
                          "FROM positions_sync_runs ORDER BY run_id DESC LIMIT 1")
    step = _log_step(log, "positions store")
    if last is None:
        return _row(DEGRADED, "positions_sync_runs unreadable (no DB answer) — no evidence", id="positions_store",
                    broker="all", label="Positions store", flags=[], freshness=None, latest_run=None,
                    last_success_at=None, operator_log_step=step)
    last_complete = _parse((last[0] if last else {}).get("last_complete"))
    try:
        import positions_sync as ps  # type: ignore
        fresh = ps.freshness(last_complete, cfg, now)
    except Exception:  # noqa: BLE001
        limit = float(cfg.get("stale_after_hours_closed") or 72) * 3600
        age = None if last_complete is None else (now - last_complete).total_seconds()
        fresh = {"last_complete": _iso(last_complete), "age_s": age, "limit_s": limit,
                 "stale": age is None or age > limit}
    lr = latest[0] if latest else None
    latest_run = None
    if lr:
        failed = lr.get("accounts_failed")
        if isinstance(failed, str):
            try:
                failed = json.loads(failed)
            except ValueError:
                failed = {}
        latest_run = {"run_id": lr.get("run_id"), "status": lr.get("status"), "promoted": lr.get("promoted"),
                      "started_at": _iso(lr.get("started_at")), "finished_at": _iso(lr.get("finished_at")),
                      "accounts_ok": list(lr.get("accounts_ok") or []),
                      "accounts_failed": {k: scrub(v, 120) for k, v in (failed or {}).items()}}
    if fresh.get("stale"):
        state, reason = STALE, ("no complete promoted run on record" if last_complete is None else
                                f"last complete promoted run {round((fresh.get('age_s') or 0) / 3600, 1)}h ago "
                                f"(limit {round((fresh.get('limit_s') or 0) / 3600, 1)}h)")
    elif latest_run and latest_run["status"] in ("partial", "failed"):
        state, reason = DEGRADED, (f"fresh by --check-fresh, but the latest run #{latest_run['run_id']} is "
                                   f"{latest_run['status']} (failed: {', '.join(latest_run['accounts_failed']) or '?'})")
    elif step and step.get("rc") not in (0, None):
        state, reason = DEGRADED, (f"fresh by --check-fresh, but the operator sync step '{step.get('name')}' "
                                   f"exited rc={step.get('rc')}")
    else:
        state, reason = OK, f"last complete promoted run {round((fresh.get('age_s') or 0) / 3600, 1)}h ago"
    fresh = {**fresh, "last_complete": _iso(fresh.get("last_complete"))}
    return _row(state, reason, id="positions_store", broker="all", label="Positions store", flags=[],
                freshness=fresh, latest_run=latest_run, last_success_at=fresh.get("last_complete"),
                operator_log_step=step, semantics="positions_sync.py --check-fresh")


# ── stop health ───────────────────────────────────────────────────────────────────────────────────
def stop_health(state_root: Path, db_query: Optional[Callable], now: datetime) -> dict:
    hb = _read_json(state_root / RUNTIME_REL / "stop_health_last.json")
    alerts = _q(db_query, "SELECT id, created_at, symbol, severity, raw_text, lifecycle_state FROM alert_events "
                          "WHERE source_script = 'stop_health' "
                          "AND COALESCE(lifecycle_state,'active') NOT IN ('resolved','acknowledged') "
                          "AND created_at > now() - make_interval(days => %s) ORDER BY created_at DESC LIMIT 25",
                (STOP_ALERT_LOOKBACK_DAYS,))
    open_alerts = [{"id": a.get("id"), "at": _iso(a.get("created_at")), "symbol": a.get("symbol"),
                    "severity": a.get("severity"), "message": scrub(a.get("raw_text"), 160),
                    "lifecycle_state": a.get("lifecycle_state") or "active"} for a in (alerts or [])]
    if not isinstance(hb, dict):
        return _row(DEGRADED, "no stop_health_last.json — no evidence that the stop check ran", headline=None,
                    finished_at=None, open_alerts=open_alerts, open_alert_count=len(open_alerts),
                    alerts_db="ok" if alerts is not None else "unavailable")
    ss = hb.get("schwab_stops") if isinstance(hb.get("schwab_stops"), dict) else {}
    status = str(hb.get("status") or "").lower()
    age = _age_h(hb.get("finished_at"), now)
    if status == "degraded" or str(ss.get("status") or "").upper() == "UNAVAILABLE":
        headline = "DEGRADED: Schwab stop data unavailable"
        state = PAUSED if ss.get("paused") else DEGRADED
        reason = f"{headline} — {scrub(ss.get('reason'), 160) or 'no reason recorded'}"
    elif status == "ok":
        headline = f"OK: {hb.get('stops', 0)} stops checked, {hb.get('alert_count', 0)} alerts"
        state, reason = (STALE, f"last check {age}h ago") if (age or 0) > RECEIPT_STALE_HOURS * 3 else (OK, headline)
        if state == OK and (hb.get("stops") or 0) == 0:
            state, reason = DEGRADED, "check ran but saw zero stops — not reported as healthy"
    else:
        headline = f"{status.upper() or 'UNKNOWN'}: stop check did not complete"
        state, reason = DEGRADED, headline
    return _row(state, reason, headline=headline, finished_at=_iso(hb.get("finished_at")), age_hours=age,
                ok_at=_iso(hb.get("ok_at")), stops=hb.get("stops"), by_health=hb.get("by_health"),
                alert_count=hb.get("alert_count"), incident_recovery_ok=hb.get("incident_recovery_ok"),
                failed_accounts=ss.get("failed_accounts") or [], open_alerts=open_alerts,
                open_alert_count=len(open_alerts), alerts_db="ok" if alerts is not None else "unavailable")


# ── re-login + operator command (static guidance, no action) ──────────────────────────────────────
def relogin_steps(access: dict) -> dict:
    return {
        "warning": ("Schwab access is paused by the operator — re-login only when you intend to lift the pause"
                    if access.get("paused") else None),
        "telegram": {
            "label": "Telegram route",
            "steps": [
                {"text": "Request a fresh login link (sends it to Telegram and email):",
                 "command": "python3 scripts/schwab_auto_reauth.py --now"},
                {"text": "Open the link on your phone and finish Schwab login + 2FA."},
                {"text": "Schwab redirects to a 127.0.0.1?code=… page that will not load. Copy that whole URL."},
                {"text": "Paste the copied 127.0.0.1?code=… URL into the Telegram bot chat."},
                {"text": "Check the result:", "command": "python3 scripts/schwab_auto_reauth.py --status"},
            ],
        },
        "command_center": {
            "label": "Command Center route",
            "href": REAUTH_PAGE,
            "steps": [{"text": "Open the Schwab Reauth page, request the authorize URL, log in, paste the "
                               "127.0.0.1?code=… URL back into the page."}],
            "note": ("The CC route currently requires step-up; TOTP step-up is being added to that page. "
                     "If it is blocked, use the Telegram route."),
        },
    }


def sync_command() -> dict:
    return {
        "run_by": "operator",
        "dry_run": SYNC_COMMAND,
        "apply": f"{SYNC_COMMAND} --apply",
        "future_path": SYNC_COMMAND_FUTURE,
        "future_note": "moving into the repo behind a proposed AGENTS amendment",
        "run_action": {"enabled": False, "reason": RUN_SYNC_DISABLED_REASON},
        "scope": "read-only broker reads; writes only our own stores; never places, changes or cancels orders",
    }


# ── assembly + cache ──────────────────────────────────────────────────────────────────────────────
def build(state_root: Optional[Path] = None, db_query: Optional[Callable] = None, now: Optional[datetime] = None,
          *, holdings_path: Optional[Path] = None, sync_log_dir: Optional[Path] = None) -> dict:
    root = Path(state_root or default_state_root())
    now = now or datetime.now(timezone.utc)
    cfg = _sync_cfg()
    access = access_mode()
    lock = trading_lock_view(now)
    accounts = _schwab_accounts(cfg)
    tokens = schwab_tokens(db_query, accounts, access, root, now)
    log = parse_sync_log(latest_sync_log(sync_log_dir))
    holdings = _holdings_doc(holdings_path)
    brokers = [
        schwab_positions_row(holdings, accounts, access, tokens, db_query, log),
        schwab_transactions_row(access, tokens, db_query, log, now),
        alpaca_row(holdings, cfg, root, log, now),
        moomoo_row(holdings, cfg, root, log, now),
        snaptrade_row(root, log),
        positions_store_row(cfg, db_query, log, now),
    ]
    stops = stop_health(root, db_query, now)
    overall = _worst([b["state"] for b in brokers] + [t["state"] for t in tokens["accounts"]] + [stops["state"]])
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "overall": overall,
        "states": list(STATES),
        "access": access,
        "trading_lock": lock,
        "schwab_tokens": tokens,
        "brokers": brokers,
        "stop_health": stops,
        "operator_sync_log": log,
        "relogin": relogin_steps(access),
        "sync_command": sync_command(),
        "links": LINKS,
        "read_only": True,
        "note": "Read-only. No broker call, no credential read, no token value. Sources are receipts, logs and DB "
                "metadata; an empty source reads DEGRADED, never OK.",
    }


def get_broker_access(state_root: Optional[Path] = None, db_query: Optional[Callable] = None,
                      now: Optional[datetime] = None, ttl_s: float = CACHE_TTL_S, **kw) -> dict:
    key = str(state_root or "")
    t = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and ttl_s > 0 and t - hit[0] < ttl_s:
            return {**hit[1], "cache": "HIT"}
    doc = build(state_root, db_query, now, **kw)
    with _LOCK:
        _CACHE[key] = (t, doc)
    return {**doc, "cache": "MISS"}
