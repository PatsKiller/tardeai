"""Account state — absent is not zero (One Source of Truth, Phase 6).

THE DEFECT (measured 2026-09-13). Two accounts rendered $0 for two different
reasons and nothing distinguished them:

  moomoo_taxable_live    trade-ai-lab-moomoo-opend.service is FAILED (exit 78 /
                         EX_CONFIG: MOOMOO_OPEND_LOGIN_ACCOUNT missing from the
                         Bitwarden env render). The read sync writes nothing, so
                         the account reads zero.
  fidelity_rollover_ira  no retail API exists; the value is a manual statement
                         entry dated 2026-07-16 (~$566K pre-rollover).

Totals silently included or excluded both with no label. The registry
(`config/data_source_authority.json`, domain `holdings_accounts`) already
declares the answer: `no_coverage: per_account_state_never_zero` with the
states LIVE · STALE · SERVICE_DOWN · NO_API_MANUAL. This module is the one
implementation of that classification.

WHAT THIS MODULE CHANGES — labelling only. It adds `state`, `state_reason`,
`state_as_of` (plus provenance) to each `account_summaries[...]` entry and
projects a display value that carries the LAST KNOWN value with its date instead
of a bare $0. It never edits a share count, a total_value, a position, an order
or a stop. `MBI_BEHAVIOR = 0` (AGENTS.md §0).

DATA-DRIVEN. The account registry (`assets/portfolio_accounts.yaml`) declares
per account:

    sync_kind:          api | manual            (default: api)
    service_unit:       systemd user unit the sync depends on (optional)
    service_receipt:    JSON receipt written by that unit's health probe
                        (optional; relative to the project root)
    sync_window_hours:  freshness window (default: the domain's 24h)
    manual_as_of:       last manual statement / entry date (manual accounts)

No account id is named in code (repo rule: broker/account-agnostic).

WHERE SERVICE FAILURE IS DETECTED. In the PRODUCER only (portfolio_loader). The
order of evidence is:

  1. the sync's own last-run receipt   data/runtime/sync_receipts/<account>.json
  2. the service health receipt        (registry `service_receipt`, e.g. the
                                        opend_health.py probe output)
  3. `systemctl --user is-failed <unit>` — only when 1 and 2 are missing or
                                        older than RECEIPT_MAX_AGE_HOURS, and
                                        only when the caller passes
                                        allow_shell=True (the loader does; the
                                        repricer and every API handler do not).

An API handler never shells out. The read path (`project_account_states`) only
reads what the producer wrote.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CONTRACT_VERSION = "AccountState@v1"

STATE_LIVE = "LIVE"
STATE_STALE = "STALE"
STATE_SERVICE_DOWN = "SERVICE_DOWN"
STATE_NO_API_MANUAL = "NO_API_MANUAL"
ACCOUNT_STATES = (STATE_LIVE, STATE_STALE, STATE_SERVICE_DOWN, STATE_NO_API_MANUAL)

#: What a reader reports when the producer has not classified the account yet
#: (pre-Phase-6 holdings.json). It is NOT one of the four states on purpose: an
#: unclassified account must never pass for a LIVE one.
STATE_UNCLASSIFIED = "UNCLASSIFIED"

SYNC_KIND_API = "api"
SYNC_KIND_MANUAL = "manual"

#: Domain default from config/data_source_authority.json holdings_accounts.stale_after_hours.
DEFAULT_SYNC_WINDOW_HOURS = 24.0
#: A receipt older than this no longer speaks for the service.
RECEIPT_MAX_AGE_HOURS = 2.0

SYNC_RECEIPT_DIR = Path("data") / "runtime" / "sync_receipts"

# BSD sysexits, so a failed unit's exit status reads as a cause, not a number.
_SYSEXITS = {
    64: "EX_USAGE", 65: "EX_DATAERR", 66: "EX_NOINPUT", 67: "EX_NOUSER", 68: "EX_NOHOST",
    69: "EX_UNAVAILABLE", 70: "EX_SOFTWARE", 71: "EX_OSERR", 72: "EX_OSFILE",
    73: "EX_CANTCREAT", 74: "EX_IOERR", 75: "EX_TEMPFAIL", 76: "EX_PROTOCOL",
    77: "EX_NOPERM", 78: "EX_CONFIG",
}


# ── time helpers ──────────────────────────────────────────────────────────────

def _utc(dt: Optional[datetime]) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_time(value: Any) -> Optional[datetime]:
    """ISO date / datetime → aware UTC datetime, or None. Never raises."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # "2026-09-04 10:05:00 ET" (repricer stamp) — drop a trailing zone word.
    parts = s.split(" ")
    if len(parts) >= 2 and parts[-1].isalpha():
        s = " ".join(parts[:-1])
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return _utc(dt)


def age_hours(value: Any, now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_time(value)
    if dt is None:
        return None
    return round((_utc(now) - dt).total_seconds() / 3600.0, 2)


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ── the pure classifier ───────────────────────────────────────────────────────

def classify_account_state(
    *,
    sync_kind: str = SYNC_KIND_API,
    last_sync_at: Any = None,
    now: Optional[datetime] = None,
    window_hours: Any = None,
    service_failed: Optional[bool] = None,
    service_detail: str = "",
    service_unit: str = "",
    last_run_error: str = "",
    manual_as_of: Any = None,
) -> dict[str, Any]:
    """Classify one account. Pure: no I/O, no clock unless `now` is omitted.

    Precedence (most specific claim wins):
      NO_API_MANUAL   the registry says there is no API. state_as_of = manual_as_of.
      SERVICE_DOWN    the sync's service is failed, or its last run errored.
                      state_as_of = the last successful sync (may be None).
      LIVE            an API sync landed inside the window.
      STALE           a sync exists but is older than the window — or no sync
                      has ever landed (a never-synced API account is not LIVE).
    """
    now_utc = _utc(now)
    kind = (str(sync_kind or SYNC_KIND_API)).strip().lower()
    win = _num(window_hours)
    if win is None or win <= 0:
        win = DEFAULT_SYNC_WINDOW_HOURS
    sync_dt = parse_time(last_sync_at)
    sync_iso = sync_dt.isoformat() if sync_dt else None
    sync_age = round((now_utc - sync_dt).total_seconds() / 3600.0, 2) if sync_dt else None

    base = {
        "contract_version": CONTRACT_VERSION,
        "sync_kind": kind,
        "sync_window_hours": win,
        "last_sync_at": sync_iso,
        "last_sync_age_hours": sync_age,
        "service_unit": service_unit or None,
        "classified_at": now_utc.isoformat(),
    }

    if kind == SYNC_KIND_MANUAL:
        m_dt = parse_time(manual_as_of)
        reason = "no API for this custodian; value is a manual statement entry"
        reason += f" dated {m_dt.date().isoformat()}" if m_dt else " with NO manual_as_of recorded"
        return {**base, "state": STATE_NO_API_MANUAL, "state_reason": reason,
                "state_as_of": m_dt.isoformat() if m_dt else None,
                "manual_as_of": m_dt.date().isoformat() if m_dt else None}

    if service_failed is True or (last_run_error or "").strip():
        bits = []
        if service_failed is True:
            bits.append(f"service {service_unit or '?'} failed" + (f": {service_detail}" if service_detail else ""))
        if (last_run_error or "").strip():
            bits.append(f"last sync run errored: {str(last_run_error).strip()[:200]}")
        bits.append(f"last successful sync {sync_iso}" if sync_iso else "no successful sync on record")
        return {**base, "state": STATE_SERVICE_DOWN, "state_reason": "; ".join(bits),
                "state_as_of": sync_iso}

    if sync_dt is None:
        return {**base, "state": STATE_STALE,
                "state_reason": ("never synced: no broker_position_as_of on any row, no sync "
                                 "receipt, no sync clock on the summary (valuation restamps "
                                 "do not count)"),
                "state_as_of": None}

    if sync_age is not None and sync_age <= win:
        return {**base, "state": STATE_LIVE,
                "state_reason": f"synced {sync_age:.1f}h ago (window {win:g}h)",
                "state_as_of": sync_iso}

    return {**base, "state": STATE_STALE,
            "state_reason": f"last sync {sync_age:.1f}h ago exceeds window {win:g}h",
            "state_as_of": sync_iso}


# ── evidence readers (producer side) ──────────────────────────────────────────

def _read_json(path: Path) -> dict[str, Any]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def read_sync_receipt(project_root: Path, account_key: str) -> dict[str, Any]:
    """The sync's own last-run receipt: {ok, at, error, ...} or {} when absent."""
    return _read_json(Path(project_root) / SYNC_RECEIPT_DIR / f"{account_key}.json")


def write_sync_receipt(project_root: Path, account_key: str, *, ok: bool, error: str = "",
                       extra: Optional[dict[str, Any]] = None) -> Path:
    """Called by a read-only sync at the end of its run. Small, atomic, no history."""
    path = Path(project_root) / SYNC_RECEIPT_DIR / f"{account_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"account": account_key, "ok": bool(ok), "at": datetime.now(timezone.utc).isoformat(),
           "error": (error or "")[:400] or None}
    if extra:
        rec.update(extra)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


def interpret_service_receipt(receipt: dict[str, Any], *, now: Optional[datetime] = None,
                              max_age_hours: float = RECEIPT_MAX_AGE_HOURS) -> dict[str, Any]:
    """Read a health-probe receipt (opend_health.py shape) into {failed, detail, fresh}.

    `failed` is None when the receipt is absent or too old to speak for the
    service — the caller then decides whether it may ask systemctl.
    """
    if not receipt:
        return {"failed": None, "detail": "no service receipt", "fresh": False, "source": "receipt"}
    checked = receipt.get("checked_at") or receipt.get("at")
    age = age_hours(checked, now)
    if age is None or age > max_age_hours:
        return {"failed": None, "detail": f"service receipt stale ({age}h)", "fresh": False,
                "source": "receipt", "checked_at": checked}
    unit = receipt.get("unit") if isinstance(receipt.get("unit"), dict) else {}
    unit_state = str(unit.get("state") or "").strip().lower()
    ok = receipt.get("ok")
    if unit_state == "failed":
        detail = f"unit state failed (receipt {checked})"
        return {"failed": True, "detail": detail, "fresh": True, "source": "receipt", "checked_at": checked}
    if ok is False:
        q = receipt.get("quote") if isinstance(receipt.get("quote"), dict) else {}
        port = receipt.get("port") if isinstance(receipt.get("port"), dict) else {}
        why = q.get("detail") or ("port closed" if port.get("open") is False else "probe not ok")
        return {"failed": True, "detail": f"data plane down: {why} (receipt {checked})",
                "fresh": True, "source": "receipt", "checked_at": checked}
    if ok is True or unit_state == "active":
        return {"failed": False, "detail": f"service ok (receipt {checked})", "fresh": True,
                "source": "receipt", "checked_at": checked}
    return {"failed": None, "detail": f"receipt inconclusive (unit={unit_state or '?'})",
            "fresh": True, "source": "receipt", "checked_at": checked}


def _systemctl_env() -> dict[str, str]:
    env = dict(os.environ)
    try:
        uid = os.getuid()
    except AttributeError:  # pragma: no cover — non-POSIX
        return env
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def _run_systemctl(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                       timeout=10, env=_systemctl_env())
    return r.returncode, (r.stdout or "").strip()


def probe_service_unit(unit: str, *, runner=None) -> dict[str, Any]:
    """`systemctl --user is-failed <unit>` — PRODUCER ONLY. Never call from a handler.

    `runner(args) -> (returncode, stdout)` is injectable so tests never shell out.
    Returns {failed: True|False|None, detail, source: "systemctl"}.
    """
    run = runner or _run_systemctl
    try:
        rc, out = run(["is-failed", unit])
    except Exception as e:  # noqa: BLE001 — a probe error is a finding, not a crash
        return {"failed": None, "detail": f"systemctl unavailable: {type(e).__name__}", "source": "systemctl"}
    state = out.strip().lower()
    if state == "failed":
        detail = "unit failed"
        try:
            _, show = run(["show", unit, "-p", "Result", "-p", "ExecMainStatus"])
            props = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
            result = props.get("Result", "").strip()
            status = props.get("ExecMainStatus", "").strip()
            if result:
                detail += f" (Result={result}"
                if status:
                    detail += f", ExecMainStatus={status}"
                    try:
                        name = _SYSEXITS.get(int(status))
                        if name:
                            detail += f" {name}"
                    except ValueError:
                        pass
                detail += ")"
        except Exception:  # noqa: BLE001
            pass
        return {"failed": True, "detail": detail, "source": "systemctl"}
    if state in ("active", "activating", "reloading"):
        return {"failed": False, "detail": f"unit {state}", "source": "systemctl"}
    if state in ("inactive", "deactivating"):
        # Not failed, but not serving either: for a sync that depends on it that
        # is a down service. Say which.
        return {"failed": True, "detail": f"unit {state} (not running)", "source": "systemctl"}
    return {"failed": None, "detail": f"unit state unknown ({state or 'no output'})", "source": "systemctl"}


# ── deriving the sync clock from the store ────────────────────────────────────

#: The ONE row-level sync stamp. Broker syncs (schwab_position_sync,
#: alpaca_live_read_sync, moomoo_live_read_sync) write it when they observe the
#: broker's book. `as_of` / `updated_at` are NOT sync clocks: portfolio_loader.
#: reprice_holdings restamps both to "now" on every repriced row, so reading them
#: would make every repriced account LIVE forever — the exact lie this module
#: exists to end.
_ROW_SYNC_CLOCKS = ("broker_position_as_of",)
_SUMMARY_SYNC_CLOCKS = ("synced_at", "last_sync_at", "last_import", "as_of", "reported_total_as_of")


def derive_last_sync(rows: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[Optional[str], str]:
    """The NEWEST broker observation stamp among the account's position rows,
    else the summary's own sync clocks. Rows first: they are rebuilt by every
    broker sync; account_summaries.as_of is an abandoned mirror
    (portfolio_aggregate_contract). Valuation restamps are deliberately ignored.
    """
    best: Optional[datetime] = None
    best_src = ""
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        for k in _ROW_SYNC_CLOCKS:
            dt = parse_time(r.get(k))
            if dt and (best is None or dt > best):
                best, best_src = dt, f"holdings.{k}"
    if best is not None:
        return best.isoformat(), best_src
    for k in _SUMMARY_SYNC_CLOCKS:
        dt = parse_time((summary or {}).get(k))
        if dt:
            return dt.isoformat(), f"account_summaries.{k}"
    return None, ""


# ── producer entry point ──────────────────────────────────────────────────────

def annotate_account_states(
    account_summaries: dict[str, Any],
    holdings: list[dict[str, Any]],
    accounts_cfg: dict[str, Any],
    *,
    project_root: Path,
    now: Optional[datetime] = None,
    allow_shell: bool = False,
    default_window_hours: float = DEFAULT_SYNC_WINDOW_HOURS,
    systemctl_runner=None,
) -> dict[str, dict[str, Any]]:
    """Stamp state / state_reason / state_as_of onto every account_summaries entry.

    Mutates `account_summaries` in place (labels only — total_value,
    holdings_count and every other field are left exactly as found) and returns
    {account: state_block}. Never raises: an account whose evidence cannot be
    read keeps its previous state block, so a producer crash can never wipe a
    label.

    `allow_shell=True` is for portfolio_loader only. The repricer refreshes the
    classification from receipts and row clocks and passes False.
    """
    now_utc = _utc(now)
    root = Path(project_root)
    rows_by_acct: dict[str, list[dict[str, Any]]] = {}
    for h in holdings or []:
        if isinstance(h, dict):
            a = str(h.get("account") or h.get("account_id") or "").strip()
            if a:
                rows_by_acct.setdefault(a, []).append(h)

    out: dict[str, dict[str, Any]] = {}
    for acct_key, summary in (account_summaries or {}).items():
        if not isinstance(summary, dict):
            continue
        try:
            block = _classify_one(acct_key, summary, rows_by_acct.get(acct_key, []),
                                  (accounts_cfg or {}).get(acct_key) or {},
                                  root=root, now=now_utc, allow_shell=allow_shell,
                                  default_window_hours=default_window_hours,
                                  systemctl_runner=systemctl_runner)
        except Exception as e:  # noqa: BLE001
            prev = summary.get("account_state") if isinstance(summary.get("account_state"), dict) else {}
            block = dict(prev) if prev else {"state": STATE_UNCLASSIFIED}
            block["state_reason"] = f"classification error: {type(e).__name__}: {str(e)[:120]}"
            block["classified_at"] = now_utc.isoformat()
        summary["state"] = block["state"]
        summary["state_reason"] = block.get("state_reason")
        summary["state_as_of"] = block.get("state_as_of")
        summary["account_state"] = block
        out[acct_key] = block
    return out


def _classify_one(acct_key: str, summary: dict[str, Any], rows: list[dict[str, Any]],
                  cfg: dict[str, Any], *, root: Path, now: datetime, allow_shell: bool,
                  default_window_hours: float, systemctl_runner) -> dict[str, Any]:
    sync_kind = str(cfg.get("sync_kind") or SYNC_KIND_API).strip().lower()
    service_unit = str(cfg.get("service_unit") or "").strip()
    window = _num(cfg.get("sync_window_hours")) or default_window_hours
    manual_as_of = cfg.get("manual_as_of") or summary.get("manual_as_of") \
        or summary.get("reported_total_as_of") or summary.get("as_of")

    last_sync, sync_src = derive_last_sync(rows, summary)

    evidence: dict[str, Any] = {"last_sync_source": sync_src or None}
    service_failed: Optional[bool] = None
    service_detail = ""
    last_run_error = ""

    if sync_kind != SYNC_KIND_MANUAL:
        # 1) the sync's own receipt
        rec = read_sync_receipt(root, acct_key)
        if rec:
            evidence["sync_receipt"] = {"ok": rec.get("ok"), "at": rec.get("at"), "error": rec.get("error")}
            if rec.get("ok") is False:
                last_run_error = str(rec.get("error") or "sync run reported ok=false")
            elif rec.get("ok") is True and parse_time(rec.get("at")):
                # A successful run receipt is a sync clock in its own right.
                rec_dt = parse_time(rec.get("at"))
                cur_dt = parse_time(last_sync)
                if rec_dt and (cur_dt is None or rec_dt > cur_dt):
                    last_sync, sync_src = rec_dt.isoformat(), "sync_receipt.at"
                    evidence["last_sync_source"] = sync_src
        # 2) the service health receipt
        if service_unit:
            receipt_rel = str(cfg.get("service_receipt") or "").strip()
            if receipt_rel:
                verdict = interpret_service_receipt(_read_json(root / receipt_rel), now=now)
                evidence["service_receipt"] = {k: verdict.get(k) for k in ("failed", "detail", "fresh", "checked_at")}
                if verdict.get("failed") is not None:
                    service_failed, service_detail = verdict["failed"], verdict["detail"]
            # 3) systemctl — producer only, only when the receipts could not say
            if service_failed is None and allow_shell:
                probe = probe_service_unit(service_unit, runner=systemctl_runner)
                evidence["systemctl"] = {"failed": probe.get("failed"), "detail": probe.get("detail")}
                if probe.get("failed") is not None:
                    service_failed, service_detail = probe["failed"], probe["detail"]
            elif service_failed is None:
                evidence["systemctl"] = {"failed": None, "detail": "not probed (allow_shell=False)"}
            else:
                evidence["systemctl"] = {"failed": None, "detail": "not probed (receipt decided)"}

    block = classify_account_state(
        sync_kind=sync_kind, last_sync_at=last_sync, now=now, window_hours=window,
        service_failed=service_failed, service_detail=service_detail, service_unit=service_unit,
        last_run_error=last_run_error, manual_as_of=manual_as_of,
    )
    block["evidence"] = evidence

    # Registry facts a reader needs beside the label — passthrough, never invented.
    for k in ("closed", "closed_at", "rolled_to", "read_only", "active"):
        if k in cfg:
            block[f"registry_{k}"] = cfg[k]

    # ── last known value: the number a reader shows instead of $0 ─────────────
    cur = _num(summary.get("total_value"))
    prev = summary.get("account_state") if isinstance(summary.get("account_state"), dict) else {}
    if cur is not None and abs(cur) > 0 and block["state"] == STATE_LIVE:
        block["last_known_value"] = round(cur, 2)
        block["last_known_value_as_of"] = block.get("state_as_of") or now.isoformat()
        block["last_known_value_source"] = "account_summaries.total_value"
    elif cur is not None and abs(cur) > 0 and block["state"] in (STATE_STALE, STATE_NO_API_MANUAL):
        block["last_known_value"] = round(cur, 2)
        block["last_known_value_as_of"] = block.get("state_as_of") or last_sync
        block["last_known_value_source"] = "account_summaries.total_value"
    elif cur is not None and abs(cur) > 0:
        # SERVICE_DOWN with a carried value (e.g. the CASH row the sync preserved)
        block["last_known_value"] = round(cur, 2)
        block["last_known_value_as_of"] = last_sync
        block["last_known_value_source"] = "account_summaries.total_value (carried through outage)"
    elif prev.get("last_known_value") is not None:
        block["last_known_value"] = prev.get("last_known_value")
        block["last_known_value_as_of"] = prev.get("last_known_value_as_of")
        block["last_known_value_source"] = f"carried: {prev.get('last_known_value_source') or 'previous state block'}"
    elif _num(summary.get("reported_total_value")):
        block["last_known_value"] = round(_num(summary.get("reported_total_value")), 2)
        block["last_known_value_as_of"] = parse_time(summary.get("reported_total_as_of")).isoformat() \
            if parse_time(summary.get("reported_total_as_of")) else None
        block["last_known_value_source"] = "account_summaries.reported_total_value"
    else:
        block["last_known_value"] = None
        block["last_known_value_as_of"] = None
        block["last_known_value_source"] = None
    return block


# ── read-path projection (handlers and the snapshot) ─────────────────────────

def project_account_state(summary: dict[str, Any]) -> dict[str, Any]:
    """Render ONE account_summaries entry for a hub. Reads only what the producer
    wrote; never shells, never invents a state.

    `display_value` is the number a header may show for the account: the live
    total for LIVE; the last known value (with its date) for anything else. A
    non-LIVE account whose last known value is unknown renders None — never 0.
    `counted_in_total` is what the portfolio total actually carries for it.
    """
    block = summary.get("account_state") if isinstance(summary.get("account_state"), dict) else {}
    state = str(summary.get("state") or block.get("state") or STATE_UNCLASSIFIED)
    total = _num(summary.get("total_value"))
    counted = round(total, 2) if total is not None else 0.0
    last_known = block.get("last_known_value")
    last_known_as_of = block.get("last_known_value_as_of")

    if state == STATE_LIVE:
        display, display_as_of, basis = counted, block.get("state_as_of"), "live_total"
    elif state == STATE_UNCLASSIFIED:
        # Pre-Phase-6 shape: nothing distinguishes absent from zero. Render the
        # raw total and SAY it is unclassified — the reader's assertion catches it.
        display, display_as_of, basis = counted, None, "unclassified_total"
    elif last_known is not None:
        display, display_as_of, basis = last_known, last_known_as_of, "last_known_value"
    elif abs(counted) > 0:
        display, display_as_of, basis = counted, block.get("state_as_of"), "carried_total"
    else:
        display, display_as_of, basis = None, None, "unknown"

    return {
        "state": state,
        "state_reason": summary.get("state_reason") or block.get("state_reason"),
        "state_as_of": summary.get("state_as_of") or block.get("state_as_of"),
        "sync_kind": block.get("sync_kind"),
        "service_unit": block.get("service_unit"),
        "manual_as_of": block.get("manual_as_of"),
        "last_known_value": last_known,
        "last_known_value_as_of": last_known_as_of,
        "display_value": display,
        "display_value_as_of": display_as_of,
        "display_basis": basis,
        "counted_in_total": counted,
        "classified_at": block.get("classified_at"),
    }


def project_account_states(holdings_doc: dict[str, Any]) -> dict[str, Any]:
    """Project a whole holdings.json into {accounts: {...}, excluded_accounts: [...],
    stale_accounts: [...], unclassified_accounts: [...]}.

    excluded_accounts — accounts whose current value is NOT a live sync
    (SERVICE_DOWN, NO_API_MANUAL): the header total either carries a $0 or a
    carried number for them, and says so here with the last known value.
    stale_accounts — API accounts counted at a value older than their window.
    """
    summaries = holdings_doc.get("account_summaries") if isinstance(holdings_doc, dict) else {}
    accounts: dict[str, Any] = {}
    excluded: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for acct, summary in sorted((summaries or {}).items()):
        if not isinstance(summary, dict):
            continue
        p = project_account_state(summary)
        accounts[acct] = p
        entry = {"account": acct, "state": p["state"], "last_value": p["last_known_value"],
                 "as_of": p["last_known_value_as_of"] or p["state_as_of"],
                 "counted_in_total": p["counted_in_total"], "reason": p["state_reason"]}
        if p["state"] in (STATE_SERVICE_DOWN, STATE_NO_API_MANUAL):
            excluded.append(entry)
        elif p["state"] == STATE_STALE:
            stale.append(entry)
        elif p["state"] == STATE_UNCLASSIFIED:
            unclassified.append(acct)
    return {
        "contract_version": CONTRACT_VERSION,
        "accounts": accounts,
        "excluded_accounts": excluded,
        "stale_accounts": stale,
        "unclassified_accounts": unclassified,
        "excluded_last_value_total": round(sum(_num(e["last_value"]) or 0.0 for e in excluded), 2),
    }


def assert_never_zero_for_non_live(projection: dict[str, Any]) -> None:
    """The Phase 6 invariant, as an assertion a test or a gate can run.

    A non-LIVE account must render a labelled state and must not render a bare
    $0 (display_value == 0 with no last-known value). An UNCLASSIFIED account
    fails outright: that is the pre-fix shape.
    """
    for acct, p in (projection.get("accounts") or {}).items():
        state = p.get("state")
        assert state in ACCOUNT_STATES, f"{acct}: state {state!r} is not one of {ACCOUNT_STATES}"
        if state != STATE_LIVE:
            dv = p.get("display_value")
            assert not (dv == 0 and p.get("display_basis") != "last_known_value"), (
                f"{acct}: non-LIVE account renders a bare $0 (state={state})")
            assert p.get("state_reason"), f"{acct}: non-LIVE account without a state_reason"
