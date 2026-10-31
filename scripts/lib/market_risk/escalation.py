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

import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from lib.market_risk.contract import TIERS, assert_no_behavior_fields
except ImportError:  # pragma: no cover - imported as scripts.lib
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


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or store_path()
    if not p.exists():
        return {"schema": "MarketRiskEpisodeStore@v1", "episodes": []}
    return json.loads(p.read_text(encoding="utf-8"))


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
        if ep.get("status") in ("OPEN", "ACKED"):
            return ep
    return None


def _stress_set(assessment: dict[str, Any]) -> set[str]:
    return {
        str(o.get("category"))
        for o in assessment.get("observations") or []
        if isinstance(o, dict) and o.get("state") == "STRESS"
    }


def observe(assessment: dict[str, Any], *, now: datetime, policy: dict[str, Any], path: Path | None = None) -> dict:
    """Fold one evaluation into the episode ledger. Returns {"event", "episode"}; events: opened, upgraded, reopened,
    unchanged, resolved, none. Writes the store (callers in dry-run pass a temp path)."""
    cfg = policy.get("escalation") or {}
    opens = {str(t).upper() for t in cfg.get("opens_at") or ["ORANGE", "RED"]}
    tier = str(assessment.get("tier") or "NONE").upper()
    stress = _stress_set(assessment)
    data = load(path)
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
            }
            data.setdefault("episodes", []).append(ep)
            event = "opened"
    else:
        ep["score"] = assessment.get("score")
        new_stress = stress - set(ep.get("stress_categories") or [])
        if _rank(tier) > _rank(ep["tier"]):
            ep["tier"] = tier
            ep["tier_history"].append({"at": _iso(now), "tier": tier})
            ep.update(status="OPEN", anchor_at=_iso(now), repeats=0, below_sessions=[])
            event = "upgraded"
        elif new_stress and ep["status"] == "ACKED":
            ep.update(status="OPEN", anchor_at=_iso(now), repeats=0)
            event = "reopened"
        else:
            event = "unchanged"
        ep["stress_categories"] = sorted(set(ep.get("stress_categories") or []) | stress)
        below = str(cfg.get("resolve_below_tier") or "YELLOW").upper()
        if _rank(tier) < _rank(below):
            day = now.astimezone(ET).date().isoformat()
            if day not in ep["below_sessions"]:
                ep["below_sessions"].append(day)
            if len(ep["below_sessions"]) >= int(cfg.get("resolve_after_sessions_below") or 3):
                ep.update(status="RESOLVED", resolved_at=_iso(now))
                event = "resolved"
        else:
            ep["below_sessions"] = []
    save(data, path)
    return {"event": event, "episode": ep}


def _last_send(ep: dict[str, Any]) -> datetime | None:
    sends = ep.get("sends") or []
    return _parse(sends[-1]["at"]) if sends else None


def _next_due(ep: dict[str, Any], cfg: dict[str, Any], now: datetime) -> tuple[datetime | None, str]:
    anchor = _parse(ep.get("anchor_at")) or _parse(ep.get("opened_at"))
    n = int(ep.get("repeats") or 0)
    if ep["tier"] == "RED":
        if n >= int(cfg.get("red_repeat_cap") or 12):
            return None, "cap"
        offs = [int(x) for x in cfg.get("red_repeat_offsets_min") or [15, 30, 60]]
        every = int(cfg.get("red_repeat_every_min") or 60)
        minutes = offs[n] if n < len(offs) else offs[-1] + every * (n - len(offs) + 1)
        return anchor + timedelta(minutes=minutes), "red"
    if ep["tier"] == "ORANGE":
        if n >= int(cfg.get("orange_repeat_cap") or 4):
            return None, "cap"
        offs = [int(x) for x in cfg.get("orange_repeat_offsets_min") or [60]]
        if n < len(offs):
            return anchor + timedelta(minutes=offs[n]), "orange"
        last = _last_send(ep) or anchor
        local = last.astimezone(ET)
        for day in range(0, 4):
            d = (local + timedelta(days=day)).date()
            for hhmm in cfg.get("orange_session_boundaries_et") or ["05:00", "09:45", "16:30"]:
                h, m = (int(x) for x in str(hhmm).split(":"))
                cand = datetime(d.year, d.month, d.day, h, m, tzinfo=ET)
                if cand > local:
                    return cand.astimezone(timezone.utc), "orange_boundary"
    return None, "none"


def due_repeats(*, now: datetime, policy: dict[str, Any], path: Path | None = None) -> list[dict[str, Any]]:
    """Repeat intents due now for the open, unacknowledged episode. Pure read; call ``record_send`` after sending."""
    cfg = policy.get("escalation") or {}
    ep = open_episode(load(path))
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
            "tier": ep["tier"],
            "kind": kind,
            "repeat_number": int(ep.get("repeats") or 0) + 1,
            "elapsed_min": int((now - opened).total_seconds() // 60),
            "due_at": _iso(due),
        }
    ]


def record_send(episode_id: str, *, now: datetime, kind: str, ok: bool, detail: str = "", path: Path | None = None):
    """Append a send receipt; a successful repeat advances the repeat counter."""
    data = load(path)
    for ep in data.get("episodes") or []:
        if ep.get("id") == episode_id:
            ep.setdefault("sends", []).append({"at": _iso(now), "kind": kind, "ok": bool(ok), "detail": detail[:200]})
            if ok and kind != "initial":
                ep["repeats"] = int(ep.get("repeats") or 0) + 1
            save(data, path)
            return ep
    raise KeyError(f"episode {episode_id} not found")


def acknowledge(
    episode_id: str | None, *, actor: str, channel: str, now: datetime, path: Path | None = None
) -> tuple[int, dict[str, Any]]:
    """Operator acknowledgment (safe direction, one click, AGENTS §27.3). Returns (http_status, body)."""
    data = load(path)
    ep = open_episode(data)
    if ep is None:
        return 409, {"ok": False, "error": "no open market-risk episode to acknowledge"}
    if episode_id and str(episode_id) != ep["id"]:
        return 409, {"ok": False, "error": f"episode {episode_id} is not the open episode {ep['id']}"}
    if not actor:
        return 403, {"ok": False, "error": "acknowledgment needs an authenticated operator principal"}
    ack = {"at": _iso(now), "actor": actor[:120], "channel": channel[:40], "tier": ep["tier"]}
    ep.setdefault("acks", []).append(ack)
    ep.update(status="ACKED", acknowledged_at=ack["at"], acknowledged_by=ack["actor"])
    save(data, path)
    return 200, {"ok": True, "episode": ep}


def stalled(*, now: datetime, policy: dict[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    """An OPEN RED episode with no send receipt for ``stalled_after_min`` → a finding for health_tick to page."""
    cfg = policy.get("escalation") or {}
    ep = open_episode(load(path))
    if ep is None or ep.get("status") != "OPEN" or ep.get("tier") != "RED":
        return None
    last = _last_send(ep) or _parse(ep.get("anchor_at"))
    limit = float(cfg.get("stalled_after_min") or 75)
    age = (now - last).total_seconds() / 60 if last else None
    if age is None or age < limit:
        return None
    return {"episode_id": ep["id"], "tier": "RED", "minutes_since_last_send": int(age), "limit_min": int(limit)}
