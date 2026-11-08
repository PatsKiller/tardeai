#!/usr/bin/env python3
"""market-event-brief: the delivery lane of the Market Event Re-entry desk (SPEC_MARKET_EVENT_REENTRY_20261107, WP4).

Reads ``GET /api/v2/market-event/active`` (``MarketEvent@v1``, section 4.4 of the spec) and renders it three ways:

* email   - the full brief (market gate, top N by rank, gates, next tranche $ per account, what changed since the last brief);
* Telegram - the same, compact;
* Fi text  - only on an episode opening or closing and on a name turning READY (alert class ``market_event``, <=160
  characters, one text per event id, the shared 10-per-hour cap). It goes through ``scripts/lib/critical_texts.send_critical_text``;
  this file never addresses a phone, a gateway or a credential.

Advisory only. Nothing here sizes, orders, stops or writes to a broker (MBI_BEHAVIOR = 0); the numbers it prints are the
engine's proposed plan, and the CIO stays the single verdict owner per account. Deterministic: no model call.

Idempotent per slot: a slot that already delivered is skipped, and each text's event id is recorded, so a retry or a second
scheduler cannot send twice. Default mode is a dry-run render (prints, sends nothing, writes no state); ``--deliver`` (alias ``--send``) delivers.

Usage:
  python3 scripts/market_event_brief.py --input tests/fixtures/market_event_brief_sample.json --slot 2026-11-08T20:00 --render-to /tmp/brief.md
  python3 scripts/market_event_brief.py --deliver         # the lane's live argument (the allowlist spells it without the word 'send')
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "market-event-brief"
POLICY_REL = "config/market_event_brief_policy.json"
STATE_REL = "data/runtime/market_event_brief_state.json"
RECEIPT_REL = f"data/runtime/{LANE_ID}_last.json"
SCHEMA = "MarketEventBrief@v1"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TERMINAL = "CLOSED"


# --------------------------------------------------------------------------- inputs
def load_policy(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads((Path(path) if path else PROJECT_ROOT / POLICY_REL).read_text(encoding="utf-8"))


def _state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    from lib.persistent_state_root import good_persistent_root
    return good_persistent_root()


def fetch_active(policy: dict[str, Any]) -> dict[str, Any]:
    """The live payload from the loopback Command Center. Raises on any failure: a brief never renders from nothing."""
    import requests
    try:
        from lib.cc_client import cc_headers
    except ImportError:  # pragma: no cover
        from scripts.lib.cc_client import cc_headers
    url = policy["api_base"].rstrip("/") + policy["api_path"]
    resp = requests.get(url, headers=cc_headers(url), timeout=20)
    resp.raise_for_status()
    return unwrap(resp.json())


def unwrap(body: Any) -> dict[str, Any]:
    """The v2 dispatcher serves {"ok": true, "data": <MarketEvent@v1>}; the brief reads the inner document."""
    if isinstance(body, dict) and body.get("schema") is None and isinstance(body.get("data"), dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------- slots and state
def slot_for(now: datetime, policy: dict[str, Any]) -> Optional[str]:
    """The scheduled slot ``now`` belongs to (``YYYY-MM-DDTHH:MM`` ET), or None when no slot is within the grace window."""
    et = now.astimezone(ZoneInfo(policy["timezone"]))
    grace = timedelta(minutes=int(policy["slot_grace_minutes"]))
    best: Optional[datetime] = None
    for day_offset in (0, -1):
        day = (et + timedelta(days=day_offset)).date()
        for hhmm in policy["slots"].get(DAYS[day.weekday()], []):
            h, m = (int(x) for x in hhmm.split(":"))
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=et.tzinfo)
            if at <= et < at + grace and (best is None or at > best):
                best = at
    return best.strftime("%Y-%m-%dT%H:%M") if best else None


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    for key, default in (("slots", {}), ("texts", {}), ("last", {})):
        if not isinstance(doc.get(key), dict):
            doc[key] = default
    return doc


def save_state(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- reading the payload
def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _fmt(value: Any, spec: str, dash: str = "-") -> str:
    n = _num(value)
    return dash if n is None else format(n, spec)


def _tranche_no(cand: dict[str, Any]) -> Optional[int]:
    plan = cand.get("plan") if isinstance(cand.get("plan"), dict) else {}
    n = plan.get("tranche") or plan.get("next_tranche")
    try:
        return int(n) if n is not None else None
    except (TypeError, ValueError):
        return None


def _plan_rows(cand: dict[str, Any]) -> list[dict[str, Any]]:
    plan = cand.get("plan") if isinstance(cand.get("plan"), dict) else {}
    rows = plan.get("accounts")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _evidence(cand: dict[str, Any], key: str) -> Any:
    if key in cand:
        return cand[key]
    ev = cand.get("reason_evidence")
    return ev.get(key) if isinstance(ev, dict) else None


def _gate_text(cand: dict[str, Any]) -> str:
    gates = cand.get("gate_checks") if isinstance(cand.get("gate_checks"), dict) else cand.get("gates")
    if not isinstance(gates, dict) or not gates:
        return "-"
    return " ".join(f"{k}{'+' if v is True or (isinstance(v, dict) and v.get('pass')) else '-'}" for k, v in sorted(gates.items()))


def ranked(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [c for c in (payload.get("candidates") or []) if isinstance(c, dict) and c.get("symbol")]
    return sorted(rows, key=lambda c: (_num(c.get("rank")) is None, _num(c.get("rank")) or 0, str(c.get("symbol"))))


def snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """What the next brief compares against: episode state, gate tier and each name's state and tranche."""
    ep = payload.get("episode") or {}
    gate = payload.get("market_gate") or {}
    return {
        "episode_id": ep.get("episode_id"),
        "episode_state": ep.get("state"),
        "tier": gate.get("tier"),
        "names": {c["symbol"]: {"state": c.get("state"), "rank": c.get("rank"), "tranche": _tranche_no(c)} for c in ranked(payload)},
    }


def changes_since(prev: dict[str, Any], now_snap: dict[str, Any]) -> list[str]:
    if not prev or prev.get("episode_id") != now_snap.get("episode_id"):
        return ["First brief of this episode."]
    out: list[str] = []
    if prev.get("episode_state") != now_snap.get("episode_state"):
        out.append(f"Episode {prev.get('episode_state')} -> {now_snap.get('episode_state')}.")
    if prev.get("tier") != now_snap.get("tier"):
        out.append(f"Market tier {prev.get('tier')} -> {now_snap.get('tier')}.")
    before, after = prev.get("names") or {}, now_snap.get("names") or {}
    for sym in sorted(after):
        old, new = before.get(sym), after[sym]
        if old is None:
            out.append(f"{sym} joined the list (rank {new.get('rank')}, {new.get('state')}).")
        elif old.get("state") != new.get("state"):
            out.append(f"{sym} {old.get('state')} -> {new.get('state')}.")
        elif new.get("state") == "READY" and old.get("tranche") != new.get("tranche"):
            out.append(f"{sym} tranche {old.get('tranche')} -> {new.get('tranche')}.")
    out += [f"{sym} left the list." for sym in sorted(set(before) - set(after))]
    return out or ["No change since the last brief."]


# --------------------------------------------------------------------------- rendering
def _event_name(ep: dict[str, Any], default: str) -> str:
    """The episode's name as the Home banner shows it (``market_event_api.consumer_view`` ``episode.name``: the
    MRE shock verdict for a market-scope episode, LQ-20261107-513); the raw kind only when a payload lacks it."""
    name = ep.get("name")
    return str(name) if name else str(ep.get("kind") or default).replace("_", " ")


def _headline(payload: dict[str, Any]) -> str:
    ep, gate, cands = payload.get("episode") or {}, payload.get("market_gate") or {}, ranked(payload)
    ready = sum(1 for c in cands if c.get("state") == "READY")
    return (f"{_event_name(ep, 'episode')} {ep.get('state')} - tier {gate.get('tier') or '?'}"
            f" - {len(cands)} candidates - {ready} ready")


def next_tranche_by_account(payload: dict[str, Any]) -> dict[str, float]:
    """Sum of the next-tranche dollars the engine proposes per account label, READY names only."""
    totals: dict[str, float] = {}
    for c in ranked(payload):
        if c.get("state") != "READY":
            continue
        for row in _plan_rows(c):
            usd, label = _num(row.get("tranche_usd") if "tranche_usd" in row else row.get("usd")), str(row.get("account_label") or "")
            if label and usd is not None:
                totals[label] = totals.get(label, 0.0) + usd
    return totals


def render_email(payload: dict[str, Any], *, slot: str, changes: list[str], top_n: int, stale: bool) -> tuple[str, str]:
    cands = ranked(payload)
    gate = payload.get("market_gate") or {}
    subject = f"Market event brief {slot} ET - {_headline(payload)}"
    L = [f"MARKET EVENT BRIEF - {slot} ET", _headline(payload), "Advisory only. No order has been placed or changed; the CIO owns each verdict.", ""]
    if stale:
        L += ["WARNING: the engine payload is stale. Treat every number below as old.", ""]
    L.append("MARKET GATE")
    L.append(f"  tier {gate.get('tier') or '?'}, score {_fmt(gate.get('score'), '.0f')}; passing: "
             + (", ".join(k for k, v in sorted((gate.get('checks') or {}).items()) if v is True or (isinstance(v, dict) and v.get('pass'))) or "none reported"))
    L += ["", "WHAT CHANGED", *[f"  - {c}" for c in changes], "", f"TOP {min(top_n, len(cands))} BY RANK"]
    for c in cands[:top_n]:
        flag = "  [FELL FOR A REASON - operator star needed]" if c.get("fell_for_reason") else ""
        L.append(f"  #{c.get('rank')} {c['symbol']} {c.get('state')}  drawdown {_fmt(c.get('drawdown_pct'), '.1f')}%  fwd P/E "
                 f"{_fmt(_evidence(c, 'forward_pe'), '.1f')}  quality {_fmt(c.get('quality_score'), '.0f')}  gates {_gate_text(c)}{flag}")
        for row in _plan_rows(c):
            L.append(f"      {row.get('account_label')}: tranche {_tranche_no(c) or '?'} ${_fmt(row.get('tranche_usd', row.get('usd')), ',.0f')}"
                     f"  {_fmt(row.get('shares'), '.0f')} sh  entry {row.get('entry_zone') or '-'}  invalidation {_fmt(row.get('invalidation'), '.2f')}")
    L += ["", "NEXT TRANCHE $ (READY names)"]
    totals = next_tranche_by_account(payload)
    L += [f"  {k}: ${v:,.0f}" for k, v in sorted(totals.items())] or ["  none ready"]
    L += ["", "ACCOUNTS"]
    L += [f"  {a.get('account_label')}: deployable ${_fmt(a.get('deployable_usd'), ',.0f')}, reserve ${_fmt(a.get('reserve_usd'), ',.0f')}"
          for a in (payload.get("accounts") or []) if isinstance(a, dict)] or ["  none reported"]
    return subject, "\n".join(L) + "\n"


def render_telegram(payload: dict[str, Any], *, slot: str, changes: list[str], top_n: int, stale: bool) -> str:
    cands = ranked(payload)
    L = [f"Market event {slot} ET", _headline(payload)]
    if stale:
        L.append("STALE payload")
    L += [f"- {c}" for c in changes[:3]]
    for c in cands[:top_n]:
        L.append(f"#{c.get('rank')} {c['symbol']} {c.get('state')} {_fmt(c.get('drawdown_pct'), '.0f')}% fPE {_fmt(_evidence(c, 'forward_pe'), '.0f')} q{_fmt(c.get('quality_score'), '.0f')}")
    totals = next_tranche_by_account(payload)
    if totals:
        L.append("Next tranche: " + ", ".join(f"{k} ${v:,.0f}" for k, v in sorted(totals.items())))
    L.append("Advisory only. Detail in the email / CC Event.")
    return "\n".join(L)


# --------------------------------------------------------------------------- text events
def text_events(payload: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Fi-text candidates: episode open/close and each name turning READY, each with a stable event id (the dedupe key)."""
    ep, gate = payload.get("episode") or {}, payload.get("market_gate") or {}
    eid, ep_state = ep.get("episode_id"), ep.get("state")
    out: list[dict[str, Any]] = []
    if not eid:
        return out
    prev = state.get("last") or {}
    cands = ranked(payload)
    n_ready = sum(1 for c in cands if c.get("state") == "READY")
    if ep_state != TERMINAL and prev.get("episode_id") != eid:
        out.append({"alert_class": "market_event", "event_id": f"market_event:{eid}:open", "symbol": "",
                    "trigger": f"{_event_name(ep, 'event')} opened, tier {gate.get('tier') or '?'}, {len(cands)} names watched",
                    "action": "read the brief; advisory only"})
    if ep_state == TERMINAL and prev.get("episode_id") == eid and prev.get("episode_state") != TERMINAL:
        out.append({"alert_class": "market_event", "event_id": f"market_event:{eid}:close", "symbol": "",
                    "trigger": f"{_event_name(ep, 'event')} closed", "action": "read the closing brief"})
    if ep_state != TERMINAL:
        for c in cands:
            tr = _tranche_no(c)
            if c.get("state") == "READY" and tr and not c.get("fell_for_reason"):
                out.append({"alert_class": "market_event", "event_id": f"market_event:{eid}:{c['symbol']}:T{tr}", "symbol": c["symbol"],
                            "trigger": f"READY tranche {tr}, down {_fmt(abs(_num(c.get('drawdown_pct')) or 0), '.0f')}%, fwd P/E {_fmt(_evidence(c, 'forward_pe'), '.0f')}, quality {_fmt(c.get('quality_score'), '.0f')}",
                            "action": f"review tranche {tr} in the brief; advisory only"})
    _ = n_ready
    return out


# --------------------------------------------------------------------------- delivery
def _default_email(subject: str, body: str) -> bool:
    from email_notifier import send_email
    return bool(send_email(subject, body))


def _default_telegram(text: str) -> bool:
    from telegram_alert import publish_operator_message
    res = publish_operator_message(text, source_producer=LANE_ID) or {}
    return bool(res.get("delivered") or res.get("accepted"))


def _default_text(event: dict[str, Any]) -> dict[str, Any]:
    from lib.critical_texts import send_critical_text
    return send_critical_text(event)


def run(payload: dict[str, Any], *, slot: str, state: dict[str, Any], policy: dict[str, Any], send: bool,
        email: Optional[Callable[[str, str], bool]] = None, telegram: Optional[Callable[[str], bool]] = None,
        text: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None, stale: bool = False) -> dict[str, Any]:
    """Render the brief and, when ``send`` is true, deliver it. Mutates ``state``; the caller persists it."""
    ep = payload.get("episode") or {}
    result: dict[str, Any] = {"schema": SCHEMA, "slot": slot, "mode": "send" if send else "dry_run", "channels": {}, "texts": []}
    if not ep.get("episode_id"):
        result["skipped"] = "no_episode"
        return result
    active = ep.get("state") in policy["active_states"]
    events = text_events(payload, state)
    prev = state.get("last") or {}
    just_closed = ep.get("state") == TERMINAL and prev.get("episode_id") == ep.get("episode_id") and prev.get("episode_state") != TERMINAL
    if not active and not just_closed:
        result["skipped"] = "episode_not_active"
        return result
    if slot in state["slots"] and send:
        result["skipped"] = "slot_already_delivered"
        return result
    snap = snapshot(payload)
    changes = changes_since(prev, snap)
    subject, body = render_email(payload, slot=slot, changes=changes, top_n=int(policy["top_n"]), stale=stale)
    tg = render_telegram(payload, slot=slot, changes=changes, top_n=int(policy["telegram_top_n"]), stale=stale)
    result.update(subject=subject, email_body=body, telegram_text=tg)
    from lib.critical_texts import format_text, CriticalTextError
    planned = []
    for ev in events:
        try:
            planned.append({"event_id": ev["event_id"], "text": format_text(ev)})
        except CriticalTextError as exc:
            planned.append({"event_id": ev["event_id"], "refused": str(exc)})
    result["texts_planned"] = planned
    if not send:
        return result
    ok_email = (email or _default_email)(subject, body)
    ok_tg = (telegram or _default_telegram)(tg)
    result["channels"] = {"email": bool(ok_email), "telegram": bool(ok_tg)}
    for ev in events:
        if ev["event_id"] in state["texts"]:
            result["texts"].append({"event_id": ev["event_id"], "sent": False, "reason": "already_texted"})
            continue
        res = (text or _default_text)(ev)
        result["texts"].append({"event_id": ev["event_id"], "sent": bool(res.get("sent")), "reason": res.get("reason")})
        if res.get("sent"):
            state["texts"][ev["event_id"]] = datetime.now(timezone.utc).isoformat()
    if ok_email or ok_tg:  # a slot with no confirmed channel stays open so a retry can still deliver it
        state["slots"][slot] = datetime.now(timezone.utc).isoformat()
        state["last"] = snap
    return result


# --------------------------------------------------------------------------- lane entry
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deliver", "--send", dest="send", action="store_true", help="deliver (default is a dry-run render: prints, sends nothing, writes no state)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (same as the default)")
    ap.add_argument("--input", help="a MarketEvent@v1 JSON file instead of the live API (synthetic fixtures)")
    ap.add_argument("--slot", help="slot id YYYY-MM-DDTHH:MM (ET); default derived from the clock")
    ap.add_argument("--render-to", help="write the rendered email and Telegram text to this file")
    ap.add_argument("--state", help="state file override (tests)")
    args = ap.parse_args(argv)
    send = args.send and not args.dry_run

    started = datetime.now(timezone.utc).isoformat()
    policy = load_policy()
    from lib import lane_output
    now = datetime.now(timezone.utc)
    slot = args.slot or slot_for(now, policy)
    mode = "live" if send else "dry_run"
    receipt_path = _state_root() / RECEIPT_REL

    def receipt(*, ok: bool, exit_code: int, produced: int, attempted: int, skipped: Optional[dict[str, int]],
                empty_reason: Optional[str], summary: dict[str, Any], error: Optional[str] = None) -> None:
        """LQ-20261107-415: the executor grades a live run ONLY from the per-attempt LaneRunReceipt@v2 (the allowlist
        sets ``output_receipt: "v2"``), so every live exit writes one. ``_last.json`` keeps ``ok_at`` for the registry's
        output_signal. A dry run writes nothing."""
        if not send:
            return
        from lib.lane_last_receipt import write_lane_receipt
        write_lane_receipt(LANE_ID, ok=ok, exit_code=exit_code, started_at=started, script="scripts/market_event_brief.py",
                           summary=summary, error=error, path=receipt_path, produced_count=produced, attempted_count=attempted,
                           skipped_reasons=skipped or {}, empty_reason=empty_reason)

    if not slot:
        lane_output.emit(LANE_ID, mode, lane_output.output_block(produced=0, attempted=0, empty_reason="no_slot_due", unit="briefs"), started_at=started)
        receipt(ok=True, exit_code=0, produced=0, attempted=0, skipped=None, empty_reason="no_slot_due", summary={"slot": None})
        print("no scheduled slot is due; nothing to do")
        return 0
    try:
        payload = unwrap(json.loads(Path(args.input).read_text(encoding="utf-8"))) if args.input else fetch_active(policy)
    except Exception as exc:  # noqa: BLE001 -- the lane fails visibly; a brief is never rendered from nothing
        print(f"market-event-brief: payload unavailable ({type(exc).__name__}): {exc}", file=sys.stderr)
        lane_output.emit(LANE_ID, mode, lane_output.output_block(produced=0, attempted=1, skipped={"payload_unavailable": 1}, empty_reason="payload_unavailable", unit="briefs"), started_at=started)
        receipt(ok=False, exit_code=1, produced=0, attempted=1, skipped={"payload_unavailable": 1}, empty_reason="payload_unavailable",
                summary={"slot": slot}, error=f"payload unavailable ({type(exc).__name__}: {exc})")
        return 1
    stale = bool(payload.get("stale"))
    state_path = Path(args.state) if args.state else _state_root() / STATE_REL
    state = load_state(state_path)
    result = run(payload, slot=slot, state=state, policy=policy, send=send, stale=stale)

    if args.render_to and result.get("email_body"):
        Path(args.render_to).write_text(f"SUBJECT: {result['subject']}\n\n{result['email_body']}\n---- TELEGRAM ----\n{result['telegram_text']}\n"
                                        "\n---- FI TEXTS (would send on --send) ----\n"
                                        + "\n".join(f"{t['event_id']}: {t.get('text') or t.get('refused')}  [{len(t.get('text') or '')} chars]" for t in result.get("texts_planned", [])) + "\n",
                                        encoding="utf-8")
    delivered = bool(send and any(result["channels"].values()))
    if send and delivered:
        save_state(state_path, state)
    elif not send and result.get("email_body"):
        print(result["subject"]); print(result["email_body"]); print("---- TELEGRAM ----"); print(result["telegram_text"])
        for t in result.get("texts_planned", []):
            print(f"[text would send] {t['event_id']}: {t.get('text') or t.get('refused')}")
    produced = 1 if (delivered if send else bool(result.get("email_body"))) else 0
    failed = send and not delivered and not result.get("skipped")
    empty_reason = result.get("skipped") or ("no_channel_confirmed" if send and not delivered else None)
    skipped = {result["skipped"]: 1} if result.get("skipped") else ({"no_channel_confirmed": 1} if failed else None)
    lane_output.emit(LANE_ID, mode, lane_output.output_block(produced=produced, attempted=1, skipped=skipped,
                                                             empty_reason=empty_reason, unit="briefs"), started_at=started)
    receipt(ok=not failed, exit_code=1 if failed else 0, produced=produced, attempted=1, skipped=skipped, empty_reason=empty_reason,
            summary={"schema": SCHEMA, "slot": slot, "channels": result["channels"], "texts": result["texts"]},
            error="no delivery channel confirmed" if failed else None)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
