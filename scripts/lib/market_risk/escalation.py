"""Mandatory escalation and acknowledgment — MarketRiskEpisode@v1 (DSN-20261031-market-risk-engine P3-T7, plan §5.8).

A Red episode cannot be buried: it repeats at +15, +30 and +60 minutes and then hourly until acknowledged, capped per
episode. Orange repeats once at +60 and then once at each session boundary. An acknowledgment silences repeats; a
tier upgrade or a newly STRESSed category re-opens the episode. The evaluator calls ``due_repeats`` on every run —
there is no second scheduler. ``stalled`` is what health_tick calls to page "escalation stalled".

Store: one atomic JSON file (``MARKET_RISK_EPISODES_PATH`` overrides the default path). The governed
``market_risk_episodes`` table replaces it once its §7A registry row is granted; until then this file is the ledger
and every send and acknowledgment is a receipt in it. Advisory only: an episode holds tiers, categories, times and
receipts — never a size, order, stop value or weight (``contract.assert_no_behavior_fields``).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from lib.market_risk import sessions
    from lib.market_risk.contract import TIERS, assert_no_behavior_fields
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk import sessions
    from scripts.lib.market_risk.contract import TIERS, assert_no_behavior_fields

SCHEMA = "MarketRiskEpisode@v1"
ET = ZoneInfo("America/New_York")
DEFAULT_PATH = (
    Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "runtime" / "market_risk" / "episodes.json"
)


def store_path() -> Path:
    return Path(os.environ.get("MARKET_RISK_EPISODES_PATH") or DEFAULT_PATH)


def _rank(tier: str | None) -> int:
    t = str(tier or "NONE").upper()
    return TIERS.index(t) if t in TIERS else TIERS.index("NONE")


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


_HELD = threading.local()


@contextlib.contextmanager
def locked(path: Path):
    """Exclusive ``fcntl.flock`` on ``<path>.lock`` around one load-modify-save (review of #2383 round 3, H5): an API
    ACK and an evaluator write never interleave, and two evaluators never both open an episode. Re-entrant within one
    thread (a nested writer in the same thread does not deadlock); separate threads and processes exclude each other."""
    key = str(Path(path).resolve())
    held = getattr(_HELD, "paths", None)
    if held is None:
        held = _HELD.paths = {}
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    lp = Path(path).with_name(Path(path).name + ".lock")
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lp), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held[key] = 1
        try:
            yield
        finally:
            held[key] = 0
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _acks_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".acks.jsonl")


def _fold_acks(data: dict[str, Any], path: Path) -> dict[str, Any]:
    """Re-apply operator ACKs from the append-only sidecar. A write that raced an ACK (read before it, saved after it)
    can drop the ACK from the ledger; the sidecar puts it back on every read (review of #2383 round 3, H5 case C).
    An ACK only applies to the episode it named and only if it is not older than the episode's current anchor (an
    ACK never silences a later reopen)."""
    ap = _acks_path(path)
    if not ap.exists():
        return data
    eps = {e.get("id"): e for e in data.get("episodes") or []}
    for line in ap.read_text(encoding="utf-8").splitlines():
        try:
            ack = json.loads(line)
        except ValueError:
            continue
        ep = eps.get(ack.get("episode_id"))
        if ep is None:
            continue
        seen = {a.get("ack_id") for a in ep.get("acks") or []}
        if ack.get("ack_id") in seen:
            continue
        anchor = _parse(ep.get("anchor_at")) or _parse(ep.get("opened_at"))
        at = _parse(ack.get("at"))
        if anchor is not None and at is not None and at < anchor:
            continue
        rec = {k: ack.get(k) for k in ("ack_id", "at", "actor", "channel", "tier")}
        ep.setdefault("acks", []).append(rec)
        if ep.get("status") in ("OPEN", "CAPPED"):
            ep.update(status="ACKED", acknowledged_at=rec["at"], acknowledged_by=rec["actor"], below_open=False)
    return data


class EpisodeStoreCorrupt(ValueError):
    """The episode ledger exists but cannot be parsed (a torn write). Readers that only display report it."""


def load(path: Path | None = None) -> dict[str, Any]:
    """Read the ledger. A torn file raises ``EpisodeStoreCorrupt`` (display readers report it); the message names the
    file, never its absolute path, because API callers may echo it."""
    p = path or store_path()
    if not p.exists():
        return {"schema": "MarketRiskEpisodeStore@v1", "episodes": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EpisodeStoreCorrupt(f"{p.name} is unreadable ({type(exc).__name__})") from exc
    return _fold_acks(data, p)


def load_for_write(path: Path | None = None) -> dict[str, Any]:
    """The writers' read. A torn ledger is moved aside to ``<name>.corrupt-<UTC>`` (kept for inspection, never
    deleted) and the writer starts a fresh ledger, so a torn file can never stop every send (review of #2383, M2) —
    the same rule as the sent-key ledger (``alerts._load_ledger``). The move is logged."""
    p = path or store_path()
    try:
        return load(p)
    except EpisodeStoreCorrupt as exc:
        dest = p.with_name(f"{p.name}.corrupt-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}")
        p.replace(dest)
        print(f"market_risk escalation: {exc}; moved aside to {dest.name}, starting a fresh ledger", file=sys.stderr)
        return {"schema": "MarketRiskEpisodeStore@v1", "episodes": [], "recovered_from": dest.name}


def save(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomic write: temp file in the same directory, fsync, rename. A full disk leaves the old file intact."""
    assert_no_behavior_fields(data)
    p = path or store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".episodes.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def open_episode(data: dict[str, Any]) -> dict[str, Any] | None:
    for ep in reversed(data.get("episodes") or []):
        if ep.get("status") in ("OPEN", "ACKED", "CAPPED"):
            return ep
    return None


def _stress_set(assessment: dict[str, Any]) -> set[str]:
    return {
        str(o.get("category"))
        for o in assessment.get("observations") or []
        if isinstance(o, dict) and o.get("state") == "STRESS"
    }


def observe(assessment: dict[str, Any], *, now: datetime, policy: dict[str, Any], path: Path | None = None) -> dict:
    """``_observe`` under the ledger lock (H5)."""
    with locked(path or store_path()):
        return _observe(assessment, now=now, policy=policy, path=path)


def _observe(assessment: dict[str, Any], *, now: datetime, policy: dict[str, Any], path: Path | None = None) -> dict:
    """Fold one evaluation into the episode ledger. Returns {"event", "episode"}; events: opened, upgraded, reopened,
    unchanged, resolved, none. Writes the store (callers in dry-run pass a temp path)."""
    cfg = policy.get("escalation") or {}
    opens = {str(t).upper() for t in cfg.get("opens_at") or ["ORANGE", "RED"]}
    tier = str(assessment.get("tier") or "NONE").upper()
    stress = _stress_set(assessment)
    data = load_for_write(path)
    ep = open_episode(data)
    event = "none"
    if ep is None:
        if tier in opens:
            ep = {
                "schema": SCHEMA,
                "id": f"mre-{now.astimezone(ET):%Y%m%d-%H%M}-{secrets.token_hex(2)}",
                "status": "OPEN",
                "tier": tier,
                "opened_at": _iso(now),
                "anchor_at": _iso(now),
                "score": assessment.get("score"),
                "stress_categories": sorted(stress),
                "tier_history": [{"at": _iso(now), "tier": tier}],
                "sends": [],
                "repeats": 0,
                "acks": [],
                "below_sessions": [],
                "current_tier": tier,
            }
            data.setdefault("episodes", []).append(ep)
            event = "opened"
    else:
        ep["score"] = assessment.get("score")
        ep["current_tier"] = tier
        new_stress = stress - set(ep.get("stress_categories") or [])
        if _rank(tier) > _rank(ep["tier"]):
            ep["tier"] = tier
            ep["tier_history"].append({"at": _iso(now), "tier": tier})
            ep.update(status="OPEN", anchor_at=_iso(now), repeats=0, below_sessions=[], below_open=False)
            event = "upgraded"
        elif new_stress and ep["status"] in ("ACKED", "CAPPED"):
            ep.update(status="OPEN", anchor_at=_iso(now), repeats=0, below_open=False)
            event = "reopened"
        elif tier in opens and ep.get("below_open") and ep["status"] in ("ACKED", "CAPPED"):
            # the market left the episode's opening range and came back: a fresh alarm, not a stale ack
            # (review of #2383, N3: a RED two weeks after an acked RED stayed silent)
            ep.update(status="OPEN", anchor_at=_iso(now), repeats=0, below_open=False)
            ep["tier_history"].append({"at": _iso(now), "tier": tier, "reentered": True})
            event = "reopened"
        else:
            event = "unchanged"
        if tier not in opens:
            ep["below_open"] = True
        elif ep["status"] == "OPEN":
            # back in the opening range while still OPEN: nothing to reopen later (review round 3, H3 case A)
            ep["below_open"] = False
        ep["stress_categories"] = sorted(set(ep.get("stress_categories") or []) | stress)
        below = str(cfg.get("resolve_below_tier") or "YELLOW").upper()
        if _rank(tier) < _rank(below):
            # only a closed NYSE trading session counts (sessions.py; review of #2362, B4)
            day = sessions.completed_session(now)
            if day and day not in ep["below_sessions"]:
                ep["below_sessions"].append(day)
            if len(ep["below_sessions"]) >= int(cfg.get("resolve_after_sessions_below") or 3):
                ep.update(status="RESOLVED", resolved_at=_iso(now))
                event = "resolved"
        else:
            ep["below_sessions"] = []
    save(data, path)
    return {"event": event, "episode": ep}


def _last_send(ep: dict[str, Any]) -> datetime | None:
    """The last DELIVERED send. A failed attempt is not a send: a dead transport must still read as stalled."""
    sends = [x for x in ep.get("sends") or [] if x.get("ok", True)]
    return _parse(sends[-1]["at"]) if sends else None


def effective_tier(ep: dict[str, Any]) -> str:
    """The tier repeats follow: the episode tier, or the current market tier when the market has fallen below it
    (review of #2362, B5a: a RED episode kept paging "ALERT ACTIVE" for ten hours after the market fell to YELLOW)."""
    cur = ep.get("current_tier")
    if cur and _rank(cur) < _rank(ep.get("tier")):
        return str(cur).upper()
    return str(ep.get("tier") or "NONE").upper()


def repeat_cap(tier: str, cfg: dict[str, Any]) -> int:
    if tier == "RED":
        return int(cfg.get("red_repeat_cap") or 12)
    if tier == "ORANGE":
        return int(cfg.get("orange_repeat_cap") or 4)
    return 0


def _next_due(ep: dict[str, Any], cfg: dict[str, Any], now: datetime) -> tuple[datetime | None, str]:
    anchor = _parse(ep.get("anchor_at")) or _parse(ep.get("opened_at"))
    n = int(ep.get("repeats") or 0)
    tier = effective_tier(ep)
    if tier == "RED":
        if n >= int(cfg.get("red_repeat_cap") or 12):
            return None, "cap"
        offs = [int(x) for x in cfg.get("red_repeat_offsets_min") or [15, 30, 60]]
        every = int(cfg.get("red_repeat_every_min") or 60)
        minutes = offs[n] if n < len(offs) else offs[-1] + every * (n - len(offs) + 1)
        return anchor + timedelta(minutes=minutes), "red"
    if tier == "ORANGE":
        if n >= int(cfg.get("orange_repeat_cap") or 4):
            return None, "cap"
        offs = [int(x) for x in cfg.get("orange_repeat_offsets_min") or [60]]
        if n < len(offs):
            return anchor + timedelta(minutes=offs[n]), "orange"
        last = _last_send(ep) or anchor
        local = last.astimezone(ET)
        for day in range(0, 8):
            d = (local + timedelta(days=day)).date()
            if not sessions.is_trading_day(d):  # no 05:00 repeat on a weekend or holiday (review of #2362, Low)
                continue
            for hhmm in cfg.get("orange_session_boundaries_et") or ["05:00", "09:45", "16:30"]:
                h, m = (int(x) for x in str(hhmm).split(":"))
                cand = datetime(d.year, d.month, d.day, h, m, tzinfo=ET)
                if cand > local:
                    return cand.astimezone(timezone.utc), "orange_boundary"
    return None, "none"


def due_repeats(*, now: datetime, policy: dict[str, Any], path: Path | None = None) -> list[dict[str, Any]]:
    """Repeat intents due now for the open, unacknowledged episode. Pure read; call ``record_send`` after sending."""
    cfg = policy.get("escalation") or {}
    ep = open_episode(load_for_write(path))
    if ep is None or ep.get("status") != "OPEN":
        return []
    last = _last_send(ep)
    if last is not None and (now - last).total_seconds() < float(cfg.get("min_seconds_between_sends") or 60):
        return []
    due, kind = _next_due(ep, cfg, now)
    if due is None or now < due:
        return []
    opened = _parse(ep["anchor_at"]) or now
    return [
        {
            "episode_id": ep["id"],
            "tier": effective_tier(ep),
            "episode_tier": ep["tier"],
            "kind": kind,
            "repeat_number": int(ep.get("repeats") or 0) + 1,
            "elapsed_min": int((now - opened).total_seconds() // 60),
            "due_at": _iso(due),
        }
    ]


def record_send(episode_id: str, **kw: Any) -> dict[str, Any] | None:
    """``_record_send`` under the ledger lock (H5). Returns None for an episode the ledger does not hold (H2)."""
    with locked(kw.get("path") or store_path()):
        return _record_send(episode_id, **kw)


def _record_send(
    episode_id: str,
    *,
    now: datetime,
    kind: str,
    ok: bool,
    detail: str = "",
    path: Path | None = None,
    policy_escalation: dict[str, Any] | None = None,
    key: str | None = None,
):
    """Append a send receipt; a successful repeat advances the repeat counter. Idempotent on ``key`` (the dedupe key
    of the card): recording the same key twice — a retry after a crash between the send and this write — is a no-op,
    so the counter advances exactly once per card (review of #2383, B5d)."""
    data = load_for_write(path)
    for ep in data.get("episodes") or []:
        if ep.get("id") == episode_id:
            done = ep.setdefault("recorded_keys", [])
            if key and key in done:
                return ep
            ep.setdefault("sends", []).append({"at": _iso(now), "kind": kind, "ok": bool(ok), "detail": detail[:200]})
            if key and ok:
                done.append(key)
                del done[:-200]
            if ok and kind != "initial":
                ep["repeats"] = int(ep.get("repeats") or 0) + 1
                cap = repeat_cap(effective_tier(ep), policy_escalation or {})
                if cap and ep["repeats"] >= cap and ep.get("status") == "OPEN":
                    # terminal for repeats: still acknowledgeable, never repeats again, never reads as "stalled"
                    ep.update(status="CAPPED", capped_at=_iso(now))
            save(data, path)
            return ep
    # an outbox entry can outlive its episode (a torn ledger moved aside, H2): report it, never crash the cycle
    print(f"market_risk escalation: record_send for unknown episode {episode_id}; skipped", file=sys.stderr)
    return None


def acknowledge(
    episode_id: str | None,
    *,
    actor: str,
    channel: str,
    now: datetime,
    path: Path | None = None,
    expected_tier: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Operator acknowledgment (safe direction, one click, AGENTS §27.3). Returns (http_status, body).

    The ACK is written to the ledger under the lock AND appended to the ``.acks.jsonl`` sidecar first, so a racing
    writer that drops it from the ledger cannot lose it (H5). It clears ``below_open`` (H3)."""
    p = path or store_path()
    with locked(p):
        return _acknowledge(episode_id, actor=actor, channel=channel, now=now, path=p, expected_tier=expected_tier)


def _acknowledge(
    episode_id: str | None,
    *,
    actor: str,
    channel: str,
    now: datetime,
    path: Path,
    expected_tier: str | None = None,
) -> tuple[int, dict[str, Any]]:
    data = load_for_write(path)
    ep = open_episode(data)
    if ep is None:
        return 409, {"ok": False, "error": "no open market-risk episode to acknowledge"}
    if episode_id and str(episode_id) != ep["id"]:
        return 409, {"ok": False, "error": f"episode {episode_id} is not the open episode {ep['id']}"}
    if not actor:
        return 403, {"ok": False, "error": "acknowledgment needs an authenticated operator principal"}
    if expected_tier and str(expected_tier).upper() != str(ep.get("tier") or "").upper():
        # checked under the ledger lock: an ORANGE->RED upgrade that lands after the operator read ORANGE must not
        # let "ACK ORANGE" silence the RED (review of #2354, race)
        return 409, {
            "ok": False,
            "error": f"the open episode is {ep.get('tier')}, not {str(expected_tier).upper()}",
            "episode_tier": ep.get("tier"),
        }
    ack = {
        "ack_id": f"ack-{secrets.token_hex(4)}",
        "at": _iso(now),
        "actor": actor[:120],
        "channel": channel[:40],
        "tier": ep["tier"],
    }
    ap = _acks_path(path)
    ap.parent.mkdir(parents=True, exist_ok=True)
    with open(ap, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"episode_id": ep["id"], **ack}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    ep.setdefault("acks", []).append(ack)
    ep.update(status="ACKED", acknowledged_at=ack["at"], acknowledged_by=ack["actor"], below_open=False)
    save(data, path)
    return 200, {"ok": True, "episode": ep}


def stalled(*, now: datetime, policy: dict[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    """An OPEN RED episode with no send receipt for ``stalled_after_min`` → a finding for health_tick to page."""
    cfg = policy.get("escalation") or {}
    ep = open_episode(load(path))
    if ep is None or ep.get("status") != "OPEN" or effective_tier(ep) != "RED":
        return None
    if int(ep.get("repeats") or 0) >= repeat_cap("RED", cfg):  # a finished cap is not a stall (review B5b)
        return None
    last = _last_send(ep) or _parse(ep.get("anchor_at"))
    limit = float(cfg.get("stalled_after_min") or 75)
    age = (now - last).total_seconds() / 60 if last else None
    if age is None or age < limit:
        return None
    return {"episode_id": ep["id"], "tier": "RED", "minutes_since_last_send": int(age), "limit_min": int(limit)}
