"""Ops Controls: manual "Run lane now" for every allowlisted n8n lane (LQ-20261107-611).

The operator asked for a way to test any n8n lane between its slots without n8n's credential. This module adds
five Ops Controls kinds (direction is static per kind, so dry and live are separate kinds):

    n8n_lane_run.dry          SAFE   one lane, dry_run         (one confirm)
    n8n_lane_run.live         RISKY  one lane, live            (step-up + typed phrase)
    n8n_lane_run_all.dry      SAFE   every lane with a dry_run_arg, one request
    n8n_lane_run_all.live     RISKY  every lane that is live-listed AND safe to re-run off-slot, one request
    n8n_lane_run.cancel       SAFE   cancel the runs of one batch that the executor has not started

The host applier executes an approved request by signing ``coordination/run`` to the loopback gateway as the
DEDICATED caller ``operator-manual`` (its own HMAC key, TRADEAI_N8N_GATEWAY_HMAC_KEY_OPERATOR, scope run+read),
exactly as ``scripts/n8n_run_relay.py run()`` builds it. n8n's key and bearer are never read here and no key is
ever loaded in the web process: ``plan`` is read-only and the web process only ever calls ``plan``/``lanes_view``.
The executor (scripts/n8n_run_executor.py) drains the rows; locks, receipts and the effect-key gate behave exactly
as for an n8n fire. Nothing here spawns a lane, touches a broker, or sends anything.

Run-all LIVE eligibility is DERIVED from config fields (``live_exclusions``); there is no hand list:
    config/n8n_run_allowlist.json   live_arg, market_gate, llm_route, offpeak_gate, command, lock
    config/n8n_effect_keys.json     effects (send / llm), idempotent_today, a staged spec at all
    the relay live list             the same refusal codes as scripts/n8n_run_relay.py:521-523
    the broker token scan           scripts.pipelines.pipeline_manifest.forbidden_command_tokens
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

KIND_DRY = "n8n_lane_run.dry"
KIND_LIVE = "n8n_lane_run.live"
KIND_ALL_DRY = "n8n_lane_run_all.dry"
KIND_ALL_LIVE = "n8n_lane_run_all.live"
KIND_CANCEL = "n8n_lane_run.cancel"
KINDS = (KIND_DRY, KIND_LIVE, KIND_ALL_DRY, KIND_ALL_LIVE, KIND_CANCEL)
MODE_OF = {KIND_DRY: "dry_run", KIND_LIVE: "live", KIND_ALL_DRY: "dry_run", KIND_ALL_LIVE: "live"}

CALLER_ID = "operator-manual"
REQUESTED_BY_PREFIX = "operator-manual:"
RUN_ID_PREFIX = "opm-"
KEY_ENV_DEFAULT = "TRADEAI_N8N_GATEWAY_HMAC_KEY_OPERATOR"
GATEWAY_URL_DEFAULT = "http://127.0.0.1:18091"
BATCH_COOLDOWN_S = 600
MAX_BATCH = 200
CLAIM_LIFE_S = 120
ALLOWLIST_REL = "config/n8n_run_allowlist.json"
EFFECT_KEYS_REL = "config/n8n_effect_keys.json"
REQUEST_ID_RE = re.compile(r"^opsreq_[0-9a-f]{20}$")
LANE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")
#: argv tokens that deliver to an operator surface (text, email, Telegram, a brief --deliver)
SEND_TOKEN_RE = re.compile(r"(deliver|telegram|whatsapp|sms|email|mailgun|smtp|notify|--send\b|send[_-]?(brief|alert|digest))", re.I)

Transport = Callable[[str, dict], "tuple[int, dict]"]


class LaneRunError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 409):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


def _err(code: str, detail: str = "", status: int = 409):
    # the core's OpsError is the error type callers already map to HTTP; import lazily (the core imports this module)
    from scripts.lib.ops_controls_core import OpsError

    return OpsError(code, detail, status)


# ── configuration ──────────────────────────────────────────────────────────────────────────────────────────────


def section(cfg: Mapping[str, Any]) -> dict:
    return dict(cfg.get("n8n_lane_run") or {})


def load_allowlist(code_root: Path) -> dict[str, dict]:
    doc = json.loads((Path(code_root) / ALLOWLIST_REL).read_text(encoding="utf-8"))
    return {e["lane_id"]: e for e in doc.get("lanes") or [] if isinstance(e, dict) and e.get("lane_id")}


def load_effects(code_root: Path) -> dict[str, dict]:
    doc = json.loads((Path(code_root) / EFFECT_KEYS_REL).read_text(encoding="utf-8"))
    return {k: v for k, v in (doc.get("lanes") or {}).items() if isinstance(v, dict)}


def live_set(hosts: Any) -> tuple[frozenset[str], bool]:
    """(lanes on the EFFECTIVE relay live list, missing). ``missing`` mirrors the relay's relay_live_lanes_missing
    refusal: n8n_relay_live_lanes.resolve() returned no list.

    LQ-611 review (cc-opus-2, LQ-652 #2): this used to parse the legacy TRADEAI_N8N_RELAY_LIVE_LANES key out of the host
    file, which the relay only uses as a fallback. The relay's list is the rendered registry list minus the Ops
    Controls pauses and the host-file pauses, so the legacy key accepted a lane the relay will not run, refused lanes it
    does, and ignored the operator's own pause toggle. Only the two lane-id keys of the host file are read, by name,
    plus the state root (the same environ the Ops Controls tab builds in ops_controls_api.effective_live_list)."""
    import os

    from scripts.lib import n8n_relay_live_lanes as RLL
    from scripts.lib import ops_controls_api as API
    from scripts.lib import ops_controls_core as C

    try:
        environ = dict(API._host_lane_keys(hosts.live_list_path.read_text(encoding="utf-8")))
    except OSError:
        environ = {}
    state_root = (hosts.cfg.get("live_list") or {}).get("state_root") or os.environ.get("TRADEAI_STATE_ROOT")
    if state_root:
        environ["TRADEAI_STATE_ROOT"] = str(C.expand(state_root))
    try:
        lanes = RLL.resolve(environ, Path(hosts.code_root))["lanes"]
    except Exception:  # noqa: BLE001 - an unreadable list is "missing", never "empty and fine"
        return frozenset(), True
    if lanes is None:
        return frozenset(), True
    return frozenset(lanes), False


def market_is_open_today(hosts: Any) -> Optional[bool]:
    """True/False when a trading-day check is available, None when it is not (live run-all then fails closed)."""
    fn = getattr(hosts, "market_open", None)
    if callable(fn):
        return fn()
    try:
        from scripts.market_session import is_trading_day  # the same check scripts/market_day_gate.sh uses

        return bool(is_trading_day())
    except Exception:  # noqa: BLE001 - unknown is a distinct answer
        return None


# ── eligibility (derived, never listed by hand) ────────────────────────────────────────────────────────────────


def _argv_text(entry: Mapping[str, Any]) -> str:
    cmd = entry.get("command")
    base = " ".join(str(x) for x in cmd) if isinstance(cmd, list) else str(cmd or "")
    live = " ".join(str(x) for x in (entry.get("live_arg") or []))
    return f"{base} {live}".strip()


def _broker_tokens(text: str) -> list[str]:
    try:
        from scripts.pipelines.pipeline_manifest import forbidden_command_tokens

        return sorted(set(forbidden_command_tokens(text)))
    except Exception:  # noqa: BLE001 - the scan is advisory display on the cron path; here it only EXCLUDES
        return []


# LQ-611 review #1: lanes that remove files or sweep state. Excluded from Run-all LIVE whatever their declaration says.
DELETE_LANE_RE = re.compile(r"hygiene|--standing|\bpurge\b|\bprune\b|\bdelete\b|\bcleanup\b|\bretention\b|\brotate\b|\barchive\b|[-_]rotate|[-_]archive", re.I)


def idempotent(spec: Optional[Mapping[str, Any]]) -> bool:
    """No spec = no verdict here: ``live_exclusions`` separately fails closed on an undeclared lane. A spec's ``idempotent_today`` must start with
    ``yes`` or ``guarded`` (the config's own vocabulary); ``no``, ``partial`` or no statement is not idempotent."""
    if spec is None:
        return True
    verdict = str(spec.get("idempotent_today") or "").strip().lower()
    return verdict.startswith("yes") or verdict.startswith("guarded")


def dry_availability(entry: Mapping[str, Any]) -> Optional[str]:
    """None when a dry run exists, else the reason it does not. ``dry_run_arg: []`` is a real dry run (no flag)."""
    if entry.get("dry_run_arg") is None:
        return "no_dry_run_arg: the allowlist entry has no dry-run mode"
    return None


def live_refusal(entry: Mapping[str, Any], spec: Optional[Mapping[str, Any]], live: frozenset, missing: bool) -> Optional[str]:
    """None when a manual live run can be queued and executed, else ``code: reason`` (single-lane rules)."""
    lane = entry["lane_id"]
    if entry.get("live_arg") is None:
        return "no_live_mode: the allowlist entry has no live mode"
    if missing:
        return "relay_live_lanes_missing: the relay live list is unreadable; live fails closed"
    if lane not in live:
        return "relay_live_not_enabled: the lane is not on the relay live list (Ops Controls > n8n live list)"
    if spec is not None:
        # scripts/n8n_run_executor.py begin(): an effect-keyed lane's live run needs a d:/e:/g: slot key, a p: key or a
        # parent retry. An operator run id (opm-...) is none of them, so the executor would refuse it after queueing.
        return ("effect_slot_unknown: the lane has a staged effect key (config/n8n_effect_keys.json); the executor "
                "refuses a live run whose id is not a scheduled slot key")
    return None


def live_exclusions(entry: Mapping[str, Any], spec: Optional[Mapping[str, Any]], live: frozenset, missing: bool,
                    market_open: Optional[bool]) -> list[str]:
    """Every reason a lane is left out of Run-all LIVE, each ``code: reason``. Empty = included."""
    out: list[str] = []
    refusal = live_refusal(entry, spec, live, missing)
    if refusal:
        out.append(refusal)
    text = _argv_text(entry)
    effects = [str(x) for x in (spec or {}).get("effects") or []]
    if "send" in effects or SEND_TOKEN_RE.search(text):
        out.append("sends_to_operator_surface: the lane sends (effects/argv name a text, email, Telegram or delivery)")
    if "llm" in effects or entry.get("llm_route") is not None or entry.get("offpeak_gate") is not None:
        out.append("spends_llm_money: the lane makes a model call (llm_route/off-peak gate/effects); it follows its "
                   "off-peak and cap policy, not a manual fire")
    if entry.get("market_gate"):
        if market_open is None:
            out.append("market_unknown: market_gate lane and the trading-day check is unavailable")
        elif not market_open:
            out.append("market_closed: market_gate lane and today is not a trading day")
    broker = _broker_tokens(text)
    if broker:
        out.append("touches_broker_or_orders: " + ", ".join(broker[:6]))
    if DELETE_LANE_RE.search(f"{entry.get('lane_id', '')} {text}"):
        out.append("deletes_or_hygiene: the lane's id/argv names a hygiene, cleanup, purge or --standing sweep; "
                   "a delete lane runs only on its own slot and policy, never from Run-all")
    if spec is None and entry.get("manual_rerun_safe") is not True:
        out.append("no_effect_declaration: the lane has no staged effect key and its allowlist entry does not declare "
                   "manual_rerun_safe: true; an undeclared lane is not assumed safe to re-run (fails closed)")
    if not idempotent(spec):
        out.append("not_idempotent: effect key says " + repr(str((spec or {}).get("idempotent_today") or "no statement")[:80]))
    return out


# ── ledger reads (read-only) ───────────────────────────────────────────────────────────────────────────────────


def _ro(path: Path) -> sqlite3.Connection:
    from scripts.lib.ops_controls_n8n_outcomes import connect_ro

    return connect_ro(path)


def _iso_et(v: Any) -> Optional[str]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo

        return d.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    except (ValueError, TypeError):
        return str(v)[:32]


def _receipt(row: Mapping[str, Any]) -> dict:
    """The public face of one runs row: what the operator needs to read an outcome, no env, no argv."""
    try:
        rec = json.loads(row.get("receipt_json") or "{}")
    except ValueError:
        rec = {}
    before, after = rec.get("output_signal_mtime_before"), rec.get("output_signal_mtime_after")
    advanced = None
    if isinstance(after, (int, float)):
        advanced = after > (before if isinstance(before, (int, float)) else 0)
    return {
        "run_id": row.get("run_id"), "lane_id": row.get("lane_id"), "mode": row.get("mode"), "state": row.get("state"),
        "reason": (str(rec.get("reason"))[:200] if rec.get("reason") else None),
        "flock_held": rec.get("reason") == "flock_held" or row.get("state") == "RUN_SKIPPED_LOCK",
        "exit_code": row.get("exit_code"), "duration_s": row.get("duration_s"),
        "requested_at": _iso_et(row.get("requested_at")), "started_at": _iso_et(row.get("started_at")),
        "finished_at": _iso_et(row.get("finished_at")),
        "output_signal_advanced": advanced, "output_signal_mtime_after": after if isinstance(after, (int, float)) else None,
    }


def _last_receipts(path: Path, lanes: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        c = _ro(path)
    except (OSError, sqlite3.Error):
        return out
    try:
        c.row_factory = sqlite3.Row
        for lane in lanes:
            r = c.execute(
                "SELECT * FROM runs WHERE lane_id=? AND state IN ('RUN_DONE','RUN_FAILED','RUN_TIMEOUT',"
                "'RUN_SKIPPED_LOCK','RUN_REFUSED') ORDER BY requested_at DESC LIMIT 1", (lane,)).fetchone()
            if r is not None:
                out[lane] = _receipt(dict(r))
    except sqlite3.Error:
        pass
    finally:
        c.close()
    return out


def batch_rows(path: Path, batch_id: str) -> list[dict]:
    """Every runs row of one request (single or batch), oldest first. Read-only; empty when the ledger is absent."""
    if not REQUEST_ID_RE.fullmatch(batch_id or ""):
        raise _err("PARAMS_INVALID", "batch_id must be an Ops Controls request id", 400)
    try:
        c = _ro(path)
    except (OSError, sqlite3.Error):
        return []
    try:
        c.row_factory = sqlite3.Row
        like = f"{RUN_ID_PREFIX}{batch_id}"
        rows = c.execute(
            "SELECT * FROM runs WHERE caller_id=? AND (run_id=? OR (run_id>=? AND run_id<?)) "
            "ORDER BY run_id LIMIT ?", (CALLER_ID, like, like + "-", like + ".", MAX_BATCH + 1)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        c.close()


def batch_progress(path: Path, batch_id: str) -> dict:
    rows = [_receipt(r) for r in batch_rows(path, batch_id)]
    counts = {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0}
    for r in rows:
        s = r["state"]
        if s == "REQUESTED":
            counts["queued"] += 1
        elif s == "RUNNING":
            counts["running"] += 1
        elif s == "RUN_DONE":
            counts["done"] += 1
        elif s == "RUN_REFUSED" and r.get("reason") == "cancelled_by_operator":
            counts["cancelled"] += 1
        else:
            counts["failed"] += 1
    finished = counts["queued"] == 0 and counts["running"] == 0
    return {"batch_id": batch_id, "total": len(rows), "counts": counts, "finished": finished and bool(rows), "runs": rows}


def _recent_batches(path: Path, mode: str, now: datetime, exclude_request: str) -> list[str]:
    """run_ids of operator batch members of ``mode`` requested inside the cooldown window, other than this request's."""
    try:
        c = _ro(path)
    except (OSError, sqlite3.Error):
        return []
    try:
        since = (now - timedelta(seconds=BATCH_COOLDOWN_S)).astimezone(timezone.utc).isoformat()
        rows = c.execute(
            "SELECT run_id FROM runs WHERE caller_id=? AND mode=? AND requested_at>=? AND run_id GLOB ? LIMIT 5",
            (CALLER_ID, mode, since, f"{RUN_ID_PREFIX}*-[0-9][0-9][0-9]")).fetchall()
        return [r[0] for r in rows if not r[0].startswith(f"{RUN_ID_PREFIX}{exclude_request}-")]
    except sqlite3.Error:
        return []
    finally:
        c.close()


# ── the lanes view (GET /api/v2/ops/controls/lanes) ─────────────────────────────────────────────────────────────


def lanes_view(hosts: Any, now: Optional[datetime] = None) -> dict:
    now = now or hosts.clock()
    allow = load_allowlist(hosts.code_root)
    effects = load_effects(hosts.code_root)
    live, missing = live_set(hosts)
    market = market_is_open_today(hosts)
    last = _last_receipts(hosts.n8n_ledger_path, sorted(allow))
    reg = {r.get("lane_id"): r for r in (hosts.lane_registry().get("lanes") or [])}
    rows = []
    for lane in sorted(allow):
        e, spec = allow[lane], effects.get(lane)
        dry_no = dry_availability(e)
        live_no = live_refusal(e, spec, live, missing)
        excl = live_exclusions(e, spec, live, missing, market)
        sched = ((reg.get(lane) or {}).get("scheduler") or {})
        sig = e.get("output_signal")
        rows.append({
            "lane_id": lane,
            "family": lane.split("-")[0] if "-" in lane else lane,
            "schedule": sched.get("expression") or (spec or {}).get("schedule"),
            "dry": {"available": dry_no is None, "reason": dry_no},
            "live": {"available": live_no is None, "reason": live_no, "live_listed": lane in live},
            "run_all_live": {"included": not excl, "excluded_because": excl},
            "run_all_dry": {"included": dry_no is None},
            "output_signal": sig if isinstance(sig, (str, dict)) else None,
            "last_receipt": last.get(lane),
        })
    inc_live = [r["lane_id"] for r in rows if r["run_all_live"]["included"]]
    inc_dry = [r["lane_id"] for r in rows if r["run_all_dry"]["included"]]
    return {
        "schema": "OpsControlsLanes@v1", "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "live_list_missing": missing, "market_open_today": market, "lanes": rows,
        "run_all": {"dry_count": len(inc_dry), "live_count": len(inc_live),
                    "live_excluded": [{"lane_id": r["lane_id"], "reasons": r["run_all_live"]["excluded_because"]}
                                      for r in rows if not r["run_all_live"]["included"]],
                    "cooldown_s": BATCH_COOLDOWN_S},
        "note": "Undo is not supported: a queued run is a request to the executor, not a state change that can be reversed. "
                "A run that has not started can be cancelled; one that is running cannot.",
    }


# ── phrase / plan / apply ───────────────────────────────────────────────────────────────────────────────────────


def phrase(kind: str, params: Mapping[str, Any], today: str) -> Optional[str]:
    if kind == KIND_LIVE:
        return f"RUN LIVE {params['lane_id']} {today}"
    if kind == KIND_ALL_LIVE:
        return f"RUN ALL LIVE {today}"
    return None


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _members(hosts: Any, mode: str) -> tuple[list[str], list[dict]]:
    allow, effects = load_allowlist(hosts.code_root), load_effects(hosts.code_root)
    live, missing = live_set(hosts)
    market = market_is_open_today(hosts)
    inc, exc = [], []
    for lane in sorted(allow):
        e, spec = allow[lane], effects.get(lane)
        reasons = ([dry_availability(e)] if dry_availability(e) else []) if mode == "dry_run" else \
            live_exclusions(e, spec, live, missing, market)
        (exc if reasons else inc).append({"lane_id": lane, "reasons": reasons} if reasons else lane)
    return inc, exc  # type: ignore[return-value]


def plan(kind: str, params: Mapping[str, Any], hosts: Any, store: Any, *, request_id: str, actor: str = ""):
    """Validate and preview. Read-only: reads config, the live list and the ledger; signs and sends nothing."""
    from scripts.lib.ops_controls_core import Plan

    p = dict(params)
    now = hosts.clock()
    if kind == KIND_CANCEL:
        bid = str(p.get("batch_id") or "")
        rows = [r for r in batch_rows(hosts.n8n_ledger_path, bid) if r.get("state") == "REQUESTED"]
        if not rows:
            raise _err("NOTHING_TO_CANCEL", "no queued (not yet started) run belongs to that request", 409)
        ids = [r["run_id"] for r in rows]
        return Plan(kind, {"batch_id": bid}, f"cancel {len(ids)} queued run(s) of {bid}", {"queued": ids}, {"queued": []},
                    _digest(ids), diff=[f"- {r['lane_id']} ({r['mode']})" for r in rows],
                    warnings=["a run the executor has already started is not touched"],
                    undo=None, undo_reason="a cancelled run cannot be revived; request it again",
                    payload={"run_ids": ids})
    mode = MODE_OF[kind]
    if p.get("mode", mode) != mode:
        raise _err("PARAMS_INVALID", f"mode must be {mode} for {kind}", 400)
    allow = load_allowlist(hosts.code_root)
    if kind in (KIND_DRY, KIND_LIVE):
        lane = p.get("lane_id")
        if not isinstance(lane, str) or not LANE_ID_RE.fullmatch(lane):
            raise _err("PARAMS_INVALID", "lane_id invalid", 400)
        if lane not in allow:
            raise _err("LANE_NOT_ALLOWLISTED", f"{lane} is not in {ALLOWLIST_REL}", 400)
        e, spec = allow[lane], load_effects(hosts.code_root).get(lane)
        if mode == "dry_run":
            why = dry_availability(e)
            if why:
                raise _err(why.split(":")[0].upper(), why, 409)
        else:
            live, missing = live_set(hosts)
            why = live_refusal(e, spec, live, missing)
            if why:
                raise _err(why.split(":")[0].upper(), why, 409)
        run_id = f"{RUN_ID_PREFIX}{request_id}"
        runs = [{"lane_id": lane, "mode": mode, "run_id": run_id}]
        return Plan(kind, {"lane_id": lane, "mode": mode},
                    f"queue one {'LIVE' if mode == 'live' else 'dry'} run of {lane} (the executor decides when it starts)",
                    {"lane_id": lane}, {"queued": [run_id]}, _digest([lane, mode]), diff=[f"+ {mode} {lane}"],
                    warnings=(["LIVE: the lane writes what its --apply/--write mode writes"] if mode == "live" else []),
                    undo=None, undo_reason="not supported: a queued run is a request, not a reversible state change",
                    phrase=None, payload={"runs": runs})
    # run-all
    inc, exc = _members(hosts, mode)
    if not inc:
        raise _err("NOTHING_TO_RUN", "no lane is eligible for this run-all", 409)
    if len(inc) > MAX_BATCH:
        raise _err("BATCH_TOO_LARGE", f"{len(inc)} lanes exceeds {MAX_BATCH}", 409)
    recent = _recent_batches(hosts.n8n_ledger_path, mode, now, request_id)
    if recent:
        raise _err("BATCH_COOLDOWN", f"a run-all of this mode was queued in the last {BATCH_COOLDOWN_S // 60} minutes", 409)
    runs = [{"lane_id": lane, "mode": mode, "run_id": f"{RUN_ID_PREFIX}{request_id}-{i:03d}"}
            for i, lane in enumerate(inc)]
    return Plan(kind, {"mode": mode},
                f"queue {len(inc)} {'LIVE' if mode == 'live' else 'dry'} runs, one per eligible lane, into the executor queue "
                f"({len(exc)} left out)",
                {"eligible": len(inc), "excluded": len(exc)}, {"queued": len(inc)}, _digest([r["lane_id"] for r in runs]),
                diff=[f"+ {r['mode']} {r['lane_id']}" for r in runs] + [f"! skip {x['lane_id']}: {x['reasons'][0]}" for x in exc[:40]],
                warnings=["not parallel: the executor's worker cap and per-lane locks decide the order",
                          f"a second run-all of this mode within {BATCH_COOLDOWN_S // 60} minutes is refused"]
                + (["LIVE: every listed lane runs its live mode"] if mode == "live" else []),
                undo=None, undo_reason="not supported: queued runs can be cancelled before they start, not undone",
                payload={"runs": runs, "excluded": exc})


def build_run_payload(*, key: bytes, lane_id: str, mode: str, run_id: str, request_id: str, now: float,
                      nonce: Optional[str] = None, project: str = "trade-ai") -> dict:
    """The exact ``coordination/run`` envelope (same shape scripts/n8n_run_relay.py run() signs), as caller
    ``operator-manual``. No secret appears in it: the signature is an HMAC over the claim."""
    from scripts.lib.n8n_coordination_gateway import SCOPE_RUN, sign_claim

    claim = {"v": 1, "caller_id": CALLER_ID, "project": project, "iat": now, "exp": now + CLAIM_LIFE_S,
             "nonce": nonce or secrets.token_urlsafe(12), "scope": SCOPE_RUN}
    return {
        "route": "coordination/run", "operation": "run", "claim": claim, "signature": sign_claim(claim, key),
        "lane_id": lane_id, "mode": mode, "idempotency_key": run_id,
        "requested_by": f"{REQUESTED_BY_PREFIX}{request_id}",
    }


def http_transport(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - loopback gateway URL from config
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except (UnicodeDecodeError, ValueError):
            return exc.code, {"state": "REFUSED", "reason": "gateway_http_error"}


def operator_key(hosts: Any) -> Optional[bytes]:
    """The operator-manual HMAC key, from the applier's environment only (or an injected test key)."""
    k = getattr(hosts, "operator_key", None)
    if k is not None:
        return k
    import os

    raw = os.environ.get(section(hosts.cfg).get("key_env") or KEY_ENV_DEFAULT, "")
    return raw.encode("utf-8") if len(raw) >= 32 else None


def apply(kind: str, plan_: Any, hosts: Any, store: Any, *, request_id: str, actor: str) -> dict[str, Any]:
    res: dict[str, Any] = {"kind": kind, "summary": plan_.summary, "undo": None, "undo_reason": plan_.undo_reason}
    if kind == KIND_CANCEL:
        from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

        ledger = CoordinationLedger(hosts.n8n_ledger_path)
        rs = LedgerRunStore(ledger)
        now = hosts.clock().timestamp()
        cancelled = [rid for rid in plan_.payload["run_ids"]
                     if rs.cancel_requested(rid, caller_id=CALLER_ID, reason="cancelled_by_operator", now=now)]
        res["cancelled"] = cancelled
        res["verify"] = {"requested": len(plan_.payload["run_ids"]), "cancelled": len(cancelled)}
        res["outcome"] = "APPLIED" if cancelled else "FAILED"
        res["detail"] = (f"{len(plan_.payload['run_ids']) - len(cancelled)} had already started" if len(cancelled) != len(plan_.payload["run_ids"]) else None)
        return res
    key = operator_key(hosts)
    if key is None:
        raise _err("OPERATOR_KEY_MISSING",
                   f"{section(hosts.cfg).get('key_env') or KEY_ENV_DEFAULT} is not in the applier environment "
                   "(docs/ops/OPS_CONTROLS.md, manual lane run)", 503)
    cfg = section(hosts.cfg)
    url = (cfg.get("gateway_url") or GATEWAY_URL_DEFAULT).rstrip("/") + "/v1/coordination"
    transport = getattr(hosts, "gateway_transport", None) or http_transport
    queued: list[dict] = []
    for r in plan_.payload["runs"]:
        payload = build_run_payload(key=key, lane_id=r["lane_id"], mode=r["mode"], run_id=r["run_id"],
                                    request_id=request_id, now=hosts.clock().timestamp())
        try:
            status, reply = transport(url, payload)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            queued.append({**r, "state": "UNREACHABLE", "reason": type(exc).__name__})
            break  # the gateway is down; do not hammer it for every remaining lane
        ident_ok = all(reply.get(k) in (None, v) for k, v in (("lane_id", r["lane_id"]), ("mode", r["mode"]), ("run_id", r["run_id"])))
        state = reply.get("state") if ident_ok else "REFUSED"
        queued.append({**r, "state": state, "reason": reply.get("reason") if ident_ok else "identity_mismatch",
                       "duplicate": bool(reply.get("duplicate")), "http": status})
    # a replayed apply (applier restarted mid-batch) gets duplicate:true rows back in whatever state they reached
    ok = [q for q in queued if q["state"] == "REQUESTED" or (q.get("duplicate") and q["state"] not in (None, "REFUSED"))]
    res["runs"] = queued
    res["batch_id"] = request_id
    res["verify"] = {"requested": len(plan_.payload["runs"]), "queued": len(ok),
                     "refused": [{"lane_id": q["lane_id"], "reason": q.get("reason")} for q in queued if q not in ok]}
    res["outcome"] = "APPLIED" if len(ok) == len(plan_.payload["runs"]) else "FAILED"
    if res["outcome"] == "FAILED":
        res["detail"] = f"{len(ok)} of {len(plan_.payload['runs'])} queued; the rest were refused (see verify.refused)"
    return res
