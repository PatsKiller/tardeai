"""Market-risk phone cards and delivery intents (DSN-20261031-market-risk-engine, plan §5.10 and §4A).

``render`` turns a MarketRiskAssessment@v1 dict into the phone-length card: tier and score, the portfolio uplift
line, the top five contributors with points and ``as_of``, the "Your book" line (symbols and stop distances only),
the one change that would de-escalate, and the advisory line. ``intent_for`` decides whether a tier transition
sends at all and at what priority; ``deliver`` is the one send path, through the ``telegram_alert.send_telegram``
chokepoint (AGENTS §24.1). This module reads no market data of its own: it formats what the engine computed.
Deterministic text; an LLM may only rephrase the "why" afterwards (builder G, curation) and never a number.
"""

from __future__ import annotations

import json
import os
import sys
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from lib.market_risk.contract import TIERS, assert_no_behavior_fields
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk.contract import TIERS, assert_no_behavior_fields

ET = ZoneInfo("America/New_York")
ADVISORY = "Advisory. No order, size or stop level is implied."
ICON = {"RED": "🔴", "ORANGE": "🟠", "YELLOW": "🟡", "BLUE": "🔵", "GREEN": "🟢"}


def _rank(tier: str | None) -> int:
    t = str(tier or "NONE").upper()
    return TIERS.index(t) if t in TIERS else TIERS.index("NONE")


def _num(v: Any) -> str:
    try:
        return str(round(float(v)))
    except (TypeError, ValueError):
        return "—"


def _short_time(iso: str | None) -> str:
    if not iso:
        return "time n/a"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:16]
    return t.astimezone(ET).strftime("%m-%d %H:%M ET")


def render(a: dict[str, Any], *, max_contributors: int = 5, repeat: dict[str, Any] | None = None) -> str:
    """Phone card for one assessment. ``repeat`` (from escalation.due_repeats) adds the acknowledgment banner."""
    assert_no_behavior_fields(a)
    tier = str(a.get("tier") or "NONE").upper()
    lines: list[str] = []
    if repeat:
        lines.append(
            f"{ICON.get(tier, '')} {tier} ALERT ACTIVE — acknowledgment required "
            f"(repeat {repeat.get('repeat_number')}, {repeat.get('elapsed_min')} min since it opened)"
        )
    head = f"{ICON.get(tier, '')} MARKET RISK {tier} {_num(a.get('score'))}/100".strip()
    if a.get("confirming") is not None:
        head += f" · {a.get('confirming')} of 9 categories confirm"
    lines.append(head)
    up = a.get("uplift") or None
    if up:
        why = "; ".join(str(r) for r in (up.get("reasons") or [])) or (
            f"portfolio vulnerability {_num(up.get('vulnerability'))}"
        )
        lines.append(f"Market {_num(a.get('market_score'))} ({a.get('market_tier')}) → {tier} because {why}")
    for c in (a.get("contributors") or [])[:max_contributors]:
        pts = float(c.get("points") or 0)
        lines.append(
            f"{c.get('category')} {'+' if pts >= 0 else ''}{round(pts)} · {c.get('headline')} · {_short_time(c.get('as_of'))}"
        )
    book = a.get("portfolio") or {}
    parts = []
    # "Your book" carries symbols, stop distances and budget NAMES only — never a book-weight number, an actual or a
    # limit (review of #2362, M3). Free-text reasons pass the same behaviour lexicon as curated prose, else dropped.
    breached = sorted({str(b.get("budget")) for b in book.get("budget_breaches") or [] if b.get("budget")})
    if breached:
        parts.append("over budget: " + ", ".join(breached))
    for d in book.get("drivers") or []:
        s = str(d.get("symbol") or "")
        if d.get("stop_distance_pct") is not None:
            s += f" stop {round(float(d['stop_distance_pct']), 1)}% below"
        reason = safe_reason(d.get("reason"))
        if reason:
            s += f" ({reason})"
        parts.append(s)
    if parts:
        lines.append("Your book: " + " · ".join(parts))
    unknown = [
        o.get("category") for o in a.get("observations") or [] if isinstance(o, dict) and o.get("state") == "UNKNOWN"
    ]
    if unknown:
        lines.append("Not measured: " + ", ".join(str(u) for u in unknown))
    if a.get("deescalates_if"):
        lines.append(f"De-escalates if: {a['deescalates_if']}")
    if tier == "RED":
        lines.append("Reply ACK RED or tap Acknowledge on Home / Risk.")
    lines.append(f"Evaluated {_short_time(a.get('as_of'))}. {ADVISORY}")
    return "\n".join(lines)


_REASON_DIGITS = re.compile(r"\d")


def safe_reason(reason: Any) -> str | None:
    """A driver's free-text reason, or None when it carries a number or behaviour wording (MBI_BEHAVIOR = 0)."""
    if not reason:
        return None
    text = str(reason)
    if _REASON_DIGITS.search(text):
        return None
    try:
        from lib.market_risk import curation as _cur
    except ImportError:  # pragma: no cover - imported as scripts.lib
        from scripts.lib.market_risk import curation as _cur
    try:
        patterns = list(_cur.load_config().get("behaviour_patterns") or [])
    except (OSError, ValueError):
        return None  # cannot check it, so it is not shown
    if _cur.behaviour_hits(_cur.normalize(text), patterns):
        return None
    return text[:80]


def intent_for(assessment: dict[str, Any], prior: dict[str, Any] | None, policy: dict[str, Any]) -> dict | None:
    """Transitions only. Escalation into any tier sends at that tier's priority; a drop out of ORANGE/RED sends a
    de-escalation card; anything else (same tier, small moves below YELLOW) sends nothing."""
    cfg = policy.get("alerts") or {}
    tier = str(assessment.get("tier") or "NONE").upper()
    was = str((prior or {}).get("tier") or "NONE").upper()
    if tier == was:
        return None
    if _rank(tier) > _rank(was):
        if tier == "NONE":
            return None
        key, transition = tier, f"up_from_{was.lower()}"
    else:
        if _rank(was) < _rank("ORANGE"):
            if tier == "GREEN":
                key, transition = "GREEN", f"to_green_from_{was.lower()}"
            else:
                return None
        else:
            key, transition = "deescalated", f"down_from_{was.lower()}"
    pri = (cfg.get("priority") or {}).get(key, "P2")
    dedupe = int((cfg.get("dedupe_minutes") or {}).get(key, 240))
    as_of = assessment.get("as_of")
    try:
        session_date = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    except (TypeError, ValueError):
        session_date = "unknown"
    return {
        "priority": pri,
        "dedupe_minutes": 0 if tier == "RED" else dedupe,
        "dedupe_key": f"market_risk:{tier}:{session_date}:{transition}",
        "tier": tier,
        "transition": transition,
    }


def sent_ledger_path() -> Path:
    """Where the engine records each dedupe key it has claimed (``MARKET_RISK_SENT_LEDGER`` overrides)."""
    env = os.environ.get("MARKET_RISK_SENT_LEDGER")
    if env:
        return Path(env)
    try:
        from lib.market_risk import escalation as _esc
    except ImportError:  # pragma: no cover
        from scripts.lib.market_risk import escalation as _esc
    return _esc.store_path().with_name("sent_keys.json")


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": "MarketRiskSentKeys@v1", "keys": {}}
    except ValueError:
        # a torn ledger must not block a card: start fresh, keep the torn file for inspection
        path.replace(path.with_suffix(f".corrupt-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"))
        return {"schema": "MarketRiskSentKeys@v1", "keys": {}}


def _save_ledger(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = data.get("keys") or {}
    if len(keys) > 2000:  # keep the newest 2000 claims
        data["keys"] = dict(sorted(keys.items(), key=lambda kv: kv[1].get("at", ""))[-2000:])
    fd, tmp = tempfile.mkstemp(prefix=".sent_keys.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def claim(key: str, dedupe_minutes: int, *, now: datetime, path: Path, claim_ttl_min: float = 10.0) -> bool:
    """Claim ``key`` BEFORE sending (review of #2362, B5c/d; #2383, B5d). True when this caller may send now:

    * the key is new, or outside its ``dedupe_minutes`` window (0 = once per key ever);
    * the key is queued in the outbox (``pending``) — written by ``outbox_put`` before the prior was persisted;
    * the key was ``claimed`` more than ``claim_ttl_min`` ago and never settled (a crash between claim and send):
      a stale claim expires, so a crash can delay a card by one cycle but never wedge it.

    False when the key is already ``sent``, or freshly claimed by another run."""
    data = _load_ledger(path)
    keys = data.setdefault("keys", {})
    prev = keys.get(key)
    if prev:
        st = prev.get("status")
        if st == "pending":
            pass
        elif st == "claimed":
            at = datetime.fromisoformat(str(prev.get("claimed_at") or prev["at"]))
            if now - at < timedelta(minutes=float(claim_ttl_min)):
                return False
            prev["stale_claims"] = int(prev.get("stale_claims") or 0) + 1
        elif st == "sent":
            if int(dedupe_minutes) <= 0:
                return False
            at = datetime.fromisoformat(str(prev["at"]))
            if now - at < timedelta(minutes=int(dedupe_minutes)):
                return False
            prev = None
    rec = dict(prev or {})
    rec.update(status="claimed", claimed_at=now.astimezone(timezone.utc).isoformat())
    rec.setdefault("at", now.astimezone(timezone.utc).isoformat())
    keys[key] = rec
    _save_ledger(path, data)
    return True


def settle(key: str, ok: bool, *, path: Path) -> None:
    """A sent key becomes ``sent``; a failed send goes back to ``pending`` so the next cycle retries it (the outbox
    keeps the text), up to ``max_attempts`` recorded on the entry, then ``failed``."""
    data = _load_ledger(path)
    rec = (data.get("keys") or {}).get(key)
    if rec is None:
        return
    if ok:
        rec["status"] = "sent"
        rec["sent_at"] = datetime.now(timezone.utc).isoformat()
    else:
        rec["attempts"] = int(rec.get("attempts") or 0) + 1
        if "text" not in rec:  # a bare claim with nothing queued: release it, as before
            data["keys"].pop(key, None)
        else:
            rec["status"] = "failed" if rec["attempts"] >= int(rec.get("max_attempts") or 8) else "pending"
    _save_ledger(path, data)


def outbox_put(entry: dict[str, Any], *, now: datetime, path: Path) -> bool:
    """Queue one intent in the sent-key ledger as ``pending`` (the outbox). Written BEFORE the prior and snapshot are
    persisted (market_risk_evaluate._cycle), so a crash after it leaves the card queued, and a crash before it leaves
    the prior unpersisted so the next cycle recomputes the same transition (review of #2383, B5d). False when the
    key is already queued, claimed or sent inside its window."""
    key = str(entry["key"])
    data = _load_ledger(path)
    keys = data.setdefault("keys", {})
    prev = keys.get(key)
    dm = int((entry.get("intent") or {}).get("dedupe_minutes") or 0)
    if prev and prev.get("status") in ("pending", "claimed", "sent", "failed"):
        if dm <= 0 or prev.get("status") != "sent":
            return False
        if now - datetime.fromisoformat(str(prev["at"])) < timedelta(minutes=dm):
            return False
    keys[key] = {
        "at": now.astimezone(timezone.utc).isoformat(),
        "status": "pending",
        "text": entry["text"],
        "intent": entry["intent"],
        "kind": entry.get("kind"),
        "episode_id": entry.get("episode_id"),
        "recorded": False,
        "attempts": 0,
        "max_attempts": int(entry.get("max_attempts") or 8),
    }
    _save_ledger(path, data)
    return True


def outbox_due(*, now: datetime, path: Path, claim_ttl_min: float = 10.0) -> list[dict[str, Any]]:
    """Entries to act on this cycle, oldest first: ``pending``, stale ``claimed``, and ``sent`` but not yet recorded
    in the episode store (a crash between the send and ``record_send``)."""
    out = []
    for key, rec in (_load_ledger(path).get("keys") or {}).items():
        if "text" not in rec:
            continue
        st = rec.get("status")
        stale = st == "claimed" and now - datetime.fromisoformat(str(rec.get("claimed_at") or rec["at"])) >= timedelta(
            minutes=float(claim_ttl_min)
        )
        if st == "pending" or stale or (st == "sent" and rec.get("episode_id") and not rec.get("recorded")):
            out.append({"key": key, **rec})
    return sorted(out, key=lambda r: str(r.get("at")))


def mark_recorded(key: str, *, path: Path) -> None:
    data = _load_ledger(path)
    rec = (data.get("keys") or {}).get(key)
    if rec is not None:
        rec["recorded"] = True
        _save_ledger(path, data)


def deliver(
    message: str,
    intent: dict[str, Any],
    policy: dict[str, Any],
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    ledger: Path | None = None,
) -> dict[str, Any]:
    """The one send path. Dry run returns what would be sent; a live send's failure is returned, never swallowed.
    The router dedupes on the exact body, which carries "Evaluated HH:MM", so the engine's own ``dedupe_key`` is
    enforced here through the sent-key ledger (claimed before the send)."""
    producer = str((policy.get("alerts") or {}).get("producer") or "market_risk_engine")
    out = {"dry_run": dry_run, "intent": intent, "chars": len(message)}
    key = str(intent.get("dedupe_key") or "")
    now = now or datetime.now(timezone.utc)
    if dry_run:
        out["sent"] = False
        if key and ledger is not None and not claim(key, int(intent.get("dedupe_minutes") or 0), now=now, path=ledger):
            out["deduped"] = True
        return out
    path = ledger or sent_ledger_path()
    ttl = float((policy.get("escalation") or {}).get("claim_ttl_min") or 10)
    if key and not claim(key, int(intent.get("dedupe_minutes") or 0), now=now, path=path, claim_ttl_min=ttl):
        out.update(sent=False, deduped=True)
        return out
    from telegram_alert import send_telegram

    try:
        ok = send_telegram(
            message,
            priority=intent["priority"],
            dedupe_minutes=int(intent["dedupe_minutes"]),
            producer=producer,
            message_class="market_risk",
        )
    except Exception as exc:  # noqa: BLE001 — a transport error is a failed send: returned, logged, retried next cycle
        print(f"market_risk alerts: send failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        ok, out["error"] = False, f"send raised {type(exc).__name__}"
    out["sent"] = bool(ok)
    if key:
        settle(key, bool(ok), path=path)
    if not ok:
        out.setdefault("error", "send_telegram returned False")
    return out
