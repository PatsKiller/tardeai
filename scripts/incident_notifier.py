#!/usr/bin/env python3
"""incident_notifier.py — the human end of the incident fan-in (N8N maturity B2, 2026-10-09).

`scripts/n8n_incident_fanin.py` computes the open incidents every 5 minutes (measured 2026-10-09 20:05Z:
116 open, 2 P1, 25 P2) and writes them to the coordination ledger, but nothing told the operator. This
host-side consumer reads the fan-in receipt and the ledger and sends:

  * P1  — at once: every P1 not already notified in the dedupe window, in one message per run.
  * P2  — in one batched message at most every TRADEAI_INCIDENT_NOTIFIER_P2_BATCH_MIN minutes (30).
  * recovery — one message when incidents that were notified are no longer open.

Dedupe is per incident key (source|item, day-independent) for TRADEAI_INCIDENT_NOTIFIER_DEDUPE_HOURS (24):
an incident still open after the window is reminded once more; a worse severity re-notifies at once.
At most TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP messages per UTC day (24); a capped message is recorded as
CAPPED on the receipt and its incidents stay un-notified, so the next day sends them. P3 never sends.

Delivery: the SYSTEM ops family only, through `scripts/lib/autonomy_watchdog/telegram_system.send_system`
(ops bot, ops chat, SYSTEM_TELEGRAM_ENABLED, SYSTEM_TELEGRAM_INTERDICT; the transport confirms the claim
from the calling module, so this script cannot name a family, a token, a chat or a CIO bot). That module
records every send in its own ledger and in the comms hub via telegram_alert.record_operator_message.

    python3 scripts/incident_notifier.py --dry-run     # plan + transport gate preview; sends and records nothing
    python3 scripts/incident_notifier.py --live

Receipt: $TRADEAI_STATE_ROOT/data/runtime/incident_notifier_last.json (IncidentNotification@v1), history in
incident_notifications.jsonl beside it; dry-run writes incident_notifier_dry_run_last.json only.
Dedupe state: incident_notifier_state.json (live only; atomic writes).

AUTHORITY: OPERATOR_NOTIFY_SYSTEM_OPS. Reads receipts and the ledger read-only; no restart, no remediation.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.atomic_json_store import append_jsonl, atomic_write_json  # noqa: E402
from scripts.lib.n8n_pilot_observations import served_sha, state_root  # noqa: E402
from scripts.n8n_incident_fanin import LANE as FANIN_LANE  # noqa: E402
from scripts.n8n_incident_fanin import RECEIPT_REL as FANIN_RECEIPT_REL  # noqa: E402

SCHEMA = "IncidentNotification@v1"
STATE_SCHEMA = "IncidentNotifierState@v1"
AUTHORITY = "OPERATOR_NOTIFY_SYSTEM_OPS"
NO_CONSUMER_REASON = (
    "operator-facing sender (SYSTEM ops family); the receipt is evidence for the run ledger. Not scheduled: "
    "AGENTS.md 3.0.0 §23.3 keeps senders out of config/n8n_run_allowlist.json, so the incident-notifier lane "
    "waits on an operator decision (see the PR body)."
)
RECEIPT_REL = "data/runtime/incident_notifier_last.json"
DRY_RUN_RECEIPT_REL = "data/runtime/incident_notifier_dry_run_last.json"
HISTORY_REL = "data/runtime/incident_notifications.jsonl"
STATE_REL = "data/runtime/incident_notifier_state.json"
LOCK_REL = "data/runtime/incident_notifier.lock"

# Defaults; each is overridable by the env var of the same name (see config_from_env).
DEFAULT_DAILY_CAP = 24
DEFAULT_P2_BATCH_MIN = 30
DEFAULT_DEDUPE_HOURS = 24
DEFAULT_MAX_FANIN_AGE_MIN = 30   # fan-in runs */5; six missed runs and the input is stale
DEFAULT_MAX_LINES = 15           # incident lines per message; the rest is "+N more"
ENV = {
    "daily_cap": ("TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP", DEFAULT_DAILY_CAP),
    "p2_batch_min": ("TRADEAI_INCIDENT_NOTIFIER_P2_BATCH_MIN", DEFAULT_P2_BATCH_MIN),
    "dedupe_hours": ("TRADEAI_INCIDENT_NOTIFIER_DEDUPE_HOURS", DEFAULT_DEDUPE_HOURS),
    "max_fanin_age_min": ("TRADEAI_INCIDENT_NOTIFIER_MAX_FANIN_AGE_MIN", DEFAULT_MAX_FANIN_AGE_MIN),
    "max_lines": ("TRADEAI_INCIDENT_NOTIFIER_MAX_LINES", DEFAULT_MAX_LINES),
}
NOTIFY_SEVERITIES = ("P1", "P2")
SEV_RANK = {"P1": 1, "P2": 2, "P3": 3}
RECOVERY_CONSUMER = "recovery-observer"   # the fan-in's own consumer_ack for a finding that disappeared
IDENTITY_PREFIX = "incident-notifier:"

Sender = Callable[..., dict]      # send_system(text, *, identity, kind) -> record
Previewer = Callable[..., dict]   # preview_send(text, *, identity, kind) -> plan


def config_from_env(env: Optional[dict] = None) -> dict[str, int]:
    env = os.environ if env is None else env
    out: dict[str, int] = {}
    for name, (var, default) in ENV.items():
        try:
            val = int(str(env.get(var, "")).strip() or default)
        except ValueError:
            val = default
        out[name] = val if val >= 0 else default
    return out


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _load(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def incident_key(source: str, item: str) -> str:
    """Day-independent key (the fan-in's idempotency_key changes every UTC day; a 24 h window must not)."""
    return "inc-" + hashlib.sha256(f"{source}|{item}".encode("utf-8")).hexdigest()[:20]


def read_fanin(root: Path, now: datetime, cfg: dict[str, int]) -> dict[str, Any]:
    """The fan-in receipt as {status, as_of, age_min, open, by_severity, incidents}; status OK only when usable."""
    path = root / FANIN_RECEIPT_REL
    doc = _load(path)
    out: dict[str, Any] = {"path": FANIN_RECEIPT_REL, "status": "MISSING", "incidents": []}
    if doc is None:
        return out
    as_of = _parse_ts(doc.get("as_of"))
    age_min = None if as_of is None else round((now - as_of).total_seconds() / 60, 1)
    out.update({"as_of": doc.get("as_of"), "age_min": age_min, "mode": doc.get("mode"), "open": doc.get("open"),
                "by_severity": doc.get("by_severity") or {}, "schema": doc.get("schema")})
    if doc.get("schema") != "N8nIncidentFanin@v1" or doc.get("mode") != "apply":
        out["status"] = "NOT_APPLY_RECEIPT"
        return out
    if age_min is None or age_min > cfg["max_fanin_age_min"]:
        out["status"] = "STALE"
        return out
    out["status"] = "OK"
    out["incidents"] = [r for r in doc.get("incidents") or [] if isinstance(r, dict)]
    return out


def read_ledger_acks(path: Optional[Path] = None, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Events on the fan-in lane CONSUMED by someone other than the recovery observer (an operator ack).

    Read-only, through the Command Center projection; no ledger means no acks, and the receipt says so."""
    try:
        from scripts.lib.n8n_coordination_projection import project
        proj = project(path, lane_id=FANIN_LANE, state="CONSUMED", limit=500, now=now)
    except Exception as exc:  # noqa: BLE001 — a broken ledger read is a note, never a crash of the notifier
        return {"status": f"unavailable:{type(exc).__name__}", "acked_event_ids": []}
    acked = sorted({str(it.get("event_id")) for it in proj.get("items") or []
                    if it.get("event_id") and str(it.get("consumer") or "") not in {"", RECOVERY_CONSUMER}})
    return {"status": str(proj.get("status")), "acked_event_ids": acked}


def open_incidents(fanin: dict[str, Any], acked_event_ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    """P1/P2 rows keyed by incident_key, minus acknowledged ones. Returns (open, acked_keys)."""
    out: dict[str, dict] = {}
    acked: list[str] = []
    for r in fanin.get("incidents") or []:
        sev = str(r.get("severity") or "")
        if sev not in NOTIFY_SEVERITIES:
            continue
        key = incident_key(str(r.get("source")), str(r.get("item")))
        if r.get("state") == "CONSUMED" or str(r.get("event_id") or "") in acked_event_ids:
            acked.append(key)
            continue
        prev = out.get(key)
        if prev is None or SEV_RANK[sev] < SEV_RANK[prev["severity"]]:
            out[key] = {"key": key, "source": str(r.get("source")), "item": str(r.get("item")), "severity": sev,
                        "detail": str(r.get("detail") or "")[:160], "detected_at": r.get("detected_at"),
                        "event_id": r.get("event_id")}
    return out, sorted(set(acked))


def load_state(path: Path) -> dict[str, Any]:
    doc = _load(path) or {}
    if doc.get("schema") != STATE_SCHEMA:
        doc = {}
    return {"schema": STATE_SCHEMA, "notified": dict(doc.get("notified") or {}),
            "last_p2_batch_at": doc.get("last_p2_batch_at"), "sends_by_day": dict(doc.get("sends_by_day") or {})}


def _due(key: str, inc: dict, state: dict, now: datetime, dedupe_h: int) -> bool:
    prior = state["notified"].get(key)
    if not prior:
        return True
    if SEV_RANK.get(inc["severity"], 9) < SEV_RANK.get(str(prior.get("severity")), 9):
        return True   # escalated (P2 -> P1): tell the operator now
    last = _parse_ts(prior.get("last_notified_at"))
    return last is None or (now - last) >= timedelta(hours=dedupe_h)


DETAIL_MAX = 100


def _line(inc: dict) -> str:
    """One plain line. A structured detail (a dumped dict or list) is dropped: raw JSON never reaches the
    operator (AGENTS.md §9.1), and the evidence stays one click away on the fan-in receipt."""
    d = str(inc.get("detail") or "").strip()
    if d.startswith(("{", "[")):
        d = ""
    detail = f" — {d[:DETAIL_MAX]}" if d else ""
    return f"• {inc['source']} {inc['item']}{detail}"


def _body(header: str, incs: list[dict], footer: str, max_lines: int) -> str:
    lines = [_line(i) for i in incs[:max_lines]]
    if len(incs) > max_lines:
        lines.append(f"• +{len(incs) - max_lines} more (Command Center → coordination events, lane {FANIN_LANE})")
    return "\n".join([header, *lines, footer])


def _identity(kind: str, keys: list[str], now: datetime) -> str:
    digest = hashlib.sha256("|".join(sorted(keys)).encode("utf-8")).hexdigest()[:12]
    return f"{IDENTITY_PREFIX}{kind}:{now.strftime('%Y%m%dT%H%M')}:{digest}"


def plan_messages(open_now: dict[str, dict], state: dict, now: datetime, cfg: dict[str, int],
                  fanin: dict[str, Any], acked: Optional[set[str]] = None) -> tuple[list[dict], dict[str, Any]]:
    """Pure: which messages this run sends, in priority order (P1, recovery, P2 batch). No I/O."""
    by_sev = fanin.get("by_severity") or {}
    footer = (f"Fan-in as of {str(fanin.get('as_of') or '')[:16]}Z · open P1 {by_sev.get('P1', 0)} · "
              f"P2 {by_sev.get('P2', 0)} · P3 {by_sev.get('P3', 0)} (P3 never sends)")
    msgs: list[dict] = []
    p1 = sorted((i for k, i in open_now.items() if i["severity"] == "P1" and _due(k, i, state, now, cfg["dedupe_hours"])),
                key=lambda i: (i["source"], i["item"]))
    if p1:
        msgs.append({"kind": "p1", "severity": "P1", "incident_keys": [i["key"] for i in p1], "incidents": p1,
                     "text": _body(f"TRADE AI SYSTEM INCIDENT — P1 ({len(p1)})", p1, footer, cfg["max_lines"])})
    acked = acked or set()
    cleared = sorted(k for k in state["notified"] if k not in open_now and k not in acked)   # acked != recovered
    if cleared:
        rec = [{"key": k, "source": state["notified"][k].get("source"), "item": state["notified"][k].get("item"),
                "severity": state["notified"][k].get("severity"), "detail": ""} for k in cleared]
        msgs.append({"kind": "recovery", "severity": "RECOVERY", "incident_keys": cleared, "incidents": rec,
                     "text": _body(f"TRADE AI SYSTEM RECOVERED — {len(rec)} incident(s) no longer open at P1/P2", rec, footer,
                                   cfg["max_lines"])})
    p2 = sorted((i for k, i in open_now.items() if i["severity"] == "P2" and _due(k, i, state, now, cfg["dedupe_hours"])),
                key=lambda i: (i["source"], i["item"]))
    batch: dict[str, Any] = {"pending": len(p2), "window_min": cfg["p2_batch_min"], "next_batch_at": None}
    if p2:
        last = _parse_ts(state.get("last_p2_batch_at"))
        if last is not None and (now - last) < timedelta(minutes=cfg["p2_batch_min"]):
            batch["next_batch_at"] = (last + timedelta(minutes=cfg["p2_batch_min"])).isoformat()
            batch["deferred"] = True
        else:
            msgs.append({"kind": "p2_batch", "severity": "P2", "incident_keys": [i["key"] for i in p2], "incidents": p2,
                         "text": _body(f"TRADE AI SYSTEM INCIDENTS — P2 batch ({len(p2)})", p2, footer, cfg["max_lines"])})
    for m in msgs:
        m["identity"] = _identity(m["kind"], m["incident_keys"], now)
    return msgs, batch


def _default_sender() -> Sender:
    from scripts.lib.autonomy_watchdog.telegram_system import send_system
    return send_system


def _default_previewer() -> Previewer:
    from scripts.lib.autonomy_watchdog.telegram_system import preview_send
    return preview_send


def apply_result(state: dict, msg: dict, now: datetime) -> None:
    """Record a delivered message in the dedupe state (live mode only)."""
    iso = now.isoformat()
    if msg["kind"] == "recovery":
        for k in msg["incident_keys"]:
            state["notified"].pop(k, None)
        return
    for inc in msg["incidents"]:
        prior = state["notified"].get(inc["key"]) or {}
        state["notified"][inc["key"]] = {"source": inc["source"], "item": inc["item"], "severity": inc["severity"],
                                         "first_notified_at": prior.get("first_notified_at") or iso,
                                         "last_notified_at": iso, "identity": msg["identity"]}
    if msg["kind"] == "p2_batch":
        state["last_p2_batch_at"] = iso


def run(*, live: bool, root: Optional[Path] = None, now: Optional[datetime] = None, env: Optional[dict] = None,
        sender: Optional[Sender] = None, previewer: Optional[Previewer] = None,
        ledger_path: Optional[Path] = None) -> dict[str, Any]:
    root = root or state_root(env)
    now = now or datetime.now(timezone.utc)
    cfg = config_from_env(env)
    fanin = read_fanin(root, now, cfg)
    ledger = read_ledger_acks(ledger_path, now=now) if fanin["status"] == "OK" else {"status": "not_read", "acked_event_ids": []}
    state = load_state(root / STATE_REL)
    day = now.strftime("%Y-%m-%d")
    state["sends_by_day"] = {d: n for d, n in state["sends_by_day"].items() if d >= (now - timedelta(days=7)).strftime("%Y-%m-%d")}
    used = int(state["sends_by_day"].get(day, 0))
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "mode": "live" if live else "dry-run",
        "served_sha": served_sha(env), "family": "TRADE_AI_SYSTEM", "config": cfg,
        "fanin": {k: v for k, v in fanin.items() if k != "incidents"}, "ledger_source": {"status": ledger["status"],
                                                                                        "acked": len(ledger["acked_event_ids"])},
        "messages": [], "p2_batch": None, "acked_keys": [], "open_notifiable": 0, "ok": True,
    }
    if fanin["status"] != "OK":
        receipt["status"] = f"NO_INPUT:{fanin['status']}"   # never declare recovery or alert from a stale/missing input
        receipt["cap"] = {"day": day, "used": used, "limit": cfg["daily_cap"]}
        return receipt
    open_now, acked = open_incidents(fanin, set(ledger["acked_event_ids"]))
    receipt["acked_keys"] = acked
    receipt["open_notifiable"] = len(open_now)
    msgs, batch = plan_messages(open_now, state, now, cfg, fanin, set(acked))
    receipt["p2_batch"] = batch
    send = sender if sender is not None else (_default_sender() if live else None)
    preview = previewer if previewer is not None else (None if live else _default_previewer())
    failed = False
    for m in msgs:
        row = {k: m[k] for k in ("kind", "severity", "identity", "incident_keys")}
        row["lines"] = m["text"].count("\n") + 1
        row["text"] = m["text"]
        if used >= cfg["daily_cap"]:
            row["status"] = "CAPPED"          # incidents stay un-notified; tomorrow's budget sends them
        elif not live:
            try:
                plan = preview(m["text"], identity=m["identity"], kind=f"incident_{m['kind']}")  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 — a preview never fails the dry run
                plan = {"would_send": False, "reason": f"preview_failed:{type(exc).__name__}"}
            row["status"] = "DRY_RUN"
            row["preview"] = {k: plan.get(k) for k in ("would_send", "reason", "transport_gate") if k in plan}
            used += 1                         # the plan counts against the cap exactly as a live run would
        else:
            try:
                res = send(m["text"], identity=m["identity"], kind=f"incident_{m['kind']}")  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 — recorded on the receipt, exit 1
                res = {"ok": False, "reason": f"exception:{type(exc).__name__}"}
            row["send"] = {k: res.get(k) for k in ("ok", "message_id", "reason", "suppressed", "deduped", "status_code")
                           if k in res}
            if res.get("ok"):
                row["status"] = "SUPPRESSED" if res.get("suppressed") else "SENT"
                used += 1
                apply_result(state, m, now)
            else:
                row["status"] = "FAILED"
                failed = True
        receipt["messages"].append(row)
    state["sends_by_day"][day] = used if live else state["sends_by_day"].get(day, 0)
    receipt["cap"] = {"day": day, "used": used, "limit": cfg["daily_cap"],
                      "capped": sum(1 for r in receipt["messages"] if r["status"] == "CAPPED")}
    receipt["status"] = "FAILED" if failed else "OK"
    receipt["ok"] = not failed
    if live:
        atomic_write_json(root / STATE_REL, {**state, "as_of": now.isoformat()}, indent=1)
    return receipt


def write_receipt(root: Path, receipt: dict[str, Any]) -> Path:
    if receipt["mode"] == "live":
        p = atomic_write_json(root / RECEIPT_REL, receipt, indent=1)
        append_jsonl(root / HISTORY_REL, {k: v for k, v in receipt.items() if k != "messages"}
                     | {"messages": [{k: v for k, v in m.items() if k != "text"} for m in receipt["messages"]]})
        return p
    return atomic_write_json(root / DRY_RUN_RECEIPT_REL, receipt, indent=1)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="print what would be sent; send and record nothing")
    g.add_argument("--live", action="store_true", help="send through the SYSTEM ops family and record dedupe state")
    args = ap.parse_args(argv)
    root = state_root()
    lock_path = root / LOCK_REL
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"schema": SCHEMA, "status": "LOCKED", "note": "another incident_notifier run holds the lock"}))
            return 75
        receipt = run(live=bool(args.live), root=root)
        write_receipt(root, receipt)
    summary = {"mode": receipt["mode"], "status": receipt["status"], "fanin": receipt["fanin"].get("status"),
               "open_notifiable": receipt["open_notifiable"], "cap": receipt["cap"], "p2_batch": receipt["p2_batch"],
               "messages": [{"kind": m["kind"], "status": m["status"], "incidents": len(m["incident_keys"]),
                             **({"preview": m["preview"]} if "preview" in m else {})} for m in receipt["messages"]]}
    print(json.dumps(summary, default=str))
    if not args.live:
        for m in receipt["messages"]:
            print(f"\n--- would send ({m['kind']}, {m['status']}) ---\n{m['text']}")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
