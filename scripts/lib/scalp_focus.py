"""Scalp focus list -- the ranked top-N the 1-minute premarket evaluation, threaded alerts and critique run on.

Operator 2026-10-23 (verbatim): "And this should just be critiqued at least the top 20 that's it. We don't need
everything, but we should have a mechanism that's bringing stuff in and out of the top 20. Or the top 30 or
whatever. We're not trying to do the whole universe."

What it is. The scalp hot list (``run_finviz_momentum_scalp_scan.py --hot-list-only``, lane ``scalp-hot-list``,
kill file in ``lib/scalp_hot_tier``) keeps the Finviz scalp-screener MEMBERSHIP fresh every 2 minutes; it has no
rank and no size bound (~110 names on 2026-10-23). This module turns that pool into a bounded, ranked FOCUS list:
it does not build a second list, it ranks the hot list's pool. The premarket watch (the only writer) re-ranks
every minute from the closed 1-minute candle and calls :func:`update`.

Rank (pure, :func:`score`): a weighted sum of normalised components -- RVOL, % change, volume vs float, L2 book
strength, tape strength, five-fact evidence count, recency of the move. Unknown inputs contribute 0, never a
guess.

Membership with hysteresis (pure, :func:`update`):
- ENTER at rank <= N, while there is room;
- when full, an entrant at rank <= N displaces the worst-ranked member only when that member is ranked worse than N
  by at least ``displace_margin`` places (so two names trading places around rank N never flap);
- LEAVE after ranking below the exit rank (ceil(exit_rank_mult x N), default 1.5N) for ``exit_minutes`` consecutive
  minutes, or at once on stand-down / invalidation;
- NEVER leave, and never be displaced, while the thread state is ARMED or TRIGGERED;
- the list never holds more than N names (size default 20, hard max 30);
- every entry and exit is recorded with a reason ("entered: RVOL 14x, +22%, rank 6" /
  "left: faded below VWAP, rank 41 for 5 min").

Store (single writer: scripts/active_trader/premarket_watch.py):
- ``<state root>/data/runtime/scalp_focus_list.json``    ``ScalpFocusList@v1`` (atomic replace): members with rank,
  score, state, entered_at and reason, plus the ranked contenders -- the one source the Trade AI page, the Active
  Trader page (``momentum_alerts_api.alerts_snapshot['focus_list']``) and the critique gate read;
- ``<state root>/data/runtime/scalp_focus_events.jsonl`` ``ScalpFocusEvent@v1`` (append-only): ENTER / LEAVE / HOLD.

Critique gate (:func:`restrict_to_focus`): expensive critique (Hermes catalyst research) runs only for focus names
while a fresh focus list exists; with no fresh list (outside the premarket window, legacy cadence, writer down) the
caller's own selection is unchanged -- fail-soft, never a silent stop.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0: a rank is attention, never a size, order or stop. Stdlib only.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "ScalpFocusList@v1"
EVENT_SCHEMA = "ScalpFocusEvent@v1"
LIST_REL = Path("data") / "runtime" / "scalp_focus_list.json"
EVENTS_REL = Path("data") / "runtime" / "scalp_focus_events.jsonl"
ENV_DIR = "SCALP_FOCUS_DIR"
HARD_MAX = 30
DEFAULT_SIZE = 20
PROTECTED_STATES = frozenset({"ARMED", "TRIGGERED"})
INVALIDATING_STATES = frozenset({"STAND_DOWN"})
DEFAULT_WEIGHTS = {"rvol": 0.25, "change": 0.20, "rotation": 0.15, "l2": 0.10, "tape": 0.10, "evidence": 0.10,
                   "recency": 0.10}
#: a focus list older than this is not "fresh": the critique gate falls back to the caller's own selection
DEFAULT_FRESH_S = 180.0


@dataclass(frozen=True)
class FocusConfig:
    """``scalp_focus:`` in config/scalp_signal_engine.yaml overrides any field (operator-ratified only)."""

    size: int = DEFAULT_SIZE
    exit_rank_mult: float = 1.5
    exit_minutes: int = 5
    displace_margin_mult: float = 0.5
    critique_gate: str = "focus"            # focus = critique only focus names (when fresh) | all = unchanged
    fresh_s: float = DEFAULT_FRESH_S
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    @property
    def n(self) -> int:
        return max(1, min(HARD_MAX, int(self.size)))

    @property
    def exit_rank(self) -> int:
        return int(math.ceil(self.n * float(self.exit_rank_mult)))

    @property
    def displace_margin(self) -> int:
        return max(1, int(math.ceil(self.n * float(self.displace_margin_mult))))

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "FocusConfig":
        raw = dict(raw or {})
        kw: dict[str, Any] = {}
        for k in ("size", "exit_minutes"):
            if k in raw:
                kw[k] = int(raw[k])
        for k in ("exit_rank_mult", "displace_margin_mult", "fresh_s"):
            if k in raw:
                kw[k] = float(raw[k])
        if raw.get("critique_gate") in ("focus", "all"):
            kw["critique_gate"] = raw["critique_gate"]
        if isinstance(raw.get("weights"), dict):
            w = dict(DEFAULT_WEIGHTS)
            w.update({k: float(v) for k, v in raw["weights"].items() if k in DEFAULT_WEIGHTS})
            kw["weights"] = w
        cfg = cls(**kw)
        if not 1 <= int(cfg.size) <= HARD_MAX:
            raise ValueError(f"scalp_focus.size must be 1..{HARD_MAX}, got {cfg.size}")
        return cfg


def load_config(path: Optional[Path] = None) -> FocusConfig:
    try:
        import yaml  # type: ignore

        p = path or Path(__file__).resolve().parents[2] / "config" / "scalp_signal_engine.yaml"
        doc = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
        return FocusConfig.from_mapping(doc.get("scalp_focus"))
    except Exception:  # noqa: BLE001 -- unreadable config -> code defaults (size 20)
        return FocusConfig()


# ── rank ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def components(feat: Mapping[str, Any]) -> dict[str, float]:
    """Each component in [0, 1]; an unknown input is 0 (never a guessed pass)."""
    rvol, chg, rot = _f(feat.get("rvol")), _f(feat.get("change_pct")), _f(feat.get("rotation_pct"))
    l2, tape, ev = _f(feat.get("depth_ratio")), _f(feat.get("buy_ratio")), _f(feat.get("evidence_passed"))
    rec = _f(feat.get("minutes_since_high"))
    return {
        "rvol": 0.0 if rvol is None or rvol <= 0 else _clamp(math.log1p(rvol) / math.log1p(20.0)),
        "change": 0.0 if chg is None else _clamp(abs(chg) / 50.0),
        "rotation": 0.0 if rot is None or rot <= 0 else _clamp(rot / 100.0),
        "l2": 0.0 if l2 is None else _clamp((l2 - 0.5) / 1.5),
        "tape": 0.0 if tape is None else _clamp((tape - 0.4) / 0.4),
        "evidence": 0.0 if ev is None else _clamp(ev / 5.0),
        "recency": 0.0 if rec is None or rec < 0 else math.exp(-rec / 15.0),
    }


def score(feat: Mapping[str, Any], weights: Optional[Mapping[str, float]] = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    c = components(feat)
    return round(sum(float(w.get(k, 0.0)) * v for k, v in c.items()), 6)


def rank(features: Mapping[str, Mapping[str, Any]], cfg: Optional[FocusConfig] = None) -> list[dict]:
    """[{symbol, rank, score, features}] best first; ties broken by symbol so the order is deterministic."""
    cfg = cfg or FocusConfig()
    rows = [{"symbol": str(s).upper(), "score": score(f, cfg.weights), "features": dict(f)}
            for s, f in features.items() if s]
    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def describe_entry(feat: Mapping[str, Any], rank_no: int) -> str:
    parts = []
    rvol, chg = _f(feat.get("rvol")), _f(feat.get("change_pct"))
    if rvol is not None:
        parts.append(f"RVOL {rvol:.0f}x" if rvol >= 10 else f"RVOL {rvol:.1f}x")
    if chg is not None:
        parts.append(f"{chg:+.0f}%")
    rot = _f(feat.get("rotation_pct"))
    if rot is not None and rot >= 10:
        parts.append(f"{rot:.0f}% of float traded")
    parts.append(f"rank {rank_no}")
    return "entered: " + ", ".join(parts)


def describe_fade(feat: Optional[Mapping[str, Any]]) -> str:
    feat = feat or {}
    if feat.get("above_vwap") is False:
        return "faded below VWAP"
    rec = _f(feat.get("minutes_since_high"))
    if rec is not None and rec >= 15:
        return f"no new high for {rec:.0f} min"
    return "lost rank"


# ── membership (pure) ───────────────────────────────────────────────────────────────────────────────────────────

def _hm(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo

        from datetime import datetime

        return datetime.fromtimestamp(float(ts), ZoneInfo("America/New_York")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return str(int(ts))


def update(prev: Optional[Mapping[str, Any]], ranked: Sequence[Mapping[str, Any]], *, now: float,
           cfg: Optional[FocusConfig] = None, states: Optional[Mapping[str, str]] = None,
           invalidated: Optional[Mapping[str, str]] = None) -> tuple[dict, list[dict]]:
    """One minute of membership. Returns (new state, events). Pure.

    prev: the previous state ({"members": {SYM: {...}}}) or None. ranked: :func:`rank` output (pool order).
    states: SYM -> lifecycle state (ARMED / TRIGGERED members are protected). invalidated: SYM -> reason (leave now
    unless protected)."""
    cfg = cfg or FocusConfig()
    n, exit_rank, margin = cfg.n, cfg.exit_rank, cfg.displace_margin
    states = {str(k).upper(): str(v).upper() for k, v in (states or {}).items() if v}
    invalidated = {str(k).upper(): str(v) for k, v in (invalidated or {}).items() if v}
    by_sym = {str(r["symbol"]).upper(): r for r in ranked}
    members: dict[str, dict] = {k: dict(v) for k, v in ((prev or {}).get("members") or {}).items()}
    events: list[dict] = []

    def ev(kind: str, sym: str, reason: str, **extra: Any) -> None:
        events.append({"schema": EVENT_SCHEMA, "ts_epoch": float(now), "event": kind, "symbol": sym,
                       "reason": reason, **extra})

    def protected(sym: str) -> bool:
        return states.get(sym, members.get(sym, {}).get("state") or "") in PROTECTED_STATES

    # 1) members: refresh rank, run the exit rules
    for sym in sorted(members):
        m = members[sym]
        r = by_sym.get(sym)
        rk = int(r["rank"]) if r else None
        m["rank"], m["score"] = rk, (r or {}).get("score")
        if sym in states:
            m["state"] = states[sym]
        feat = (r or {}).get("features") or m.get("features") or {}
        if r:
            m["features"] = {k: feat.get(k) for k in ("rvol", "change_pct", "rotation_pct", "above_vwap",
                                                     "minutes_since_high", "evidence_passed") if k in feat}
        reason_now = invalidated.get(sym) or (
            "stand-down" if m.get("state") in INVALIDATING_STATES else None)
        if reason_now:
            if protected(sym):
                if not m.get("held_reason"):
                    ev("HOLD", sym, f"held: {m.get('state')} (would leave: {reason_now})", rank=rk)
                m["held_reason"] = reason_now
                continue
            members.pop(sym)
            ev("LEAVE", sym, f"left: {reason_now}" + (f", rank {rk}" if rk else ""), rank=rk)
            continue
        if rk is None or rk > exit_rank:
            m.setdefault("out_since", float(now))
            out_min = (float(now) - float(m["out_since"])) / 60.0
            if out_min + 1e-6 >= max(0, int(cfg.exit_minutes) - 1):
                if protected(sym):
                    if not m.get("held_reason"):
                        ev("HOLD", sym, f"held: {m.get('state')} (rank {rk or 'unranked'} below exit {exit_rank})",
                           rank=rk)
                    m["held_reason"] = "below exit rank"
                    continue
                members.pop(sym)
                where = f"rank {rk}" if rk else "out of the pool"
                ev("LEAVE", sym, f"left: {describe_fade(feat)}, {where} for {int(cfg.exit_minutes)} min", rank=rk)
        else:
            m.pop("out_since", None)
            m.pop("held_reason", None)

    # 2) entrants at rank <= N, best first
    for r in ranked:
        sym, rk = str(r["symbol"]).upper(), int(r["rank"])
        if rk > n:
            break
        if sym in members or sym in invalidated or states.get(sym) in INVALIDATING_STATES:
            continue
        victim = None
        if len(members) >= n:
            cands = [(s, m) for s, m in members.items() if not protected(s)
                     and (m.get("rank") is None or int(m["rank"]) > n)
                     and ((m.get("rank") or 10 ** 6) - rk) >= margin]
            if not cands:
                continue  # list full and nobody is outranked by enough: the entrant waits (no flapping)
            victim = max(cands, key=lambda x: (x[1].get("rank") or 10 ** 6, x[0]))[0]
            vr = members[victim].get("rank")
            members.pop(victim)
            ev("LEAVE", victim, f"left: displaced by {sym} (rank {rk}) at rank {vr or 'unranked'}", rank=vr)
        feat = r.get("features") or {}
        reason = describe_entry(feat, rk)
        members[sym] = {"symbol": sym, "rank": rk, "score": r.get("score"), "entered_at": float(now),
                        "entered_hm": _hm(now), "reason": reason, "state": states.get(sym),
                        "features": {k: feat.get(k) for k in ("rvol", "change_pct", "rotation_pct", "above_vwap",
                                                               "minutes_since_high", "evidence_passed") if k in feat}}
        ev("ENTER", sym, reason, rank=rk, displaced=victim)

    state = {"schema": SCHEMA, "as_of": float(now), "size": n, "exit_rank": exit_rank,
             "exit_minutes": int(cfg.exit_minutes), "displace_margin": margin, "members": members,
             "pool_size": len(ranked),
             "contenders": [{"symbol": r["symbol"], "rank": r["rank"], "score": r.get("score")}
                            for r in list(ranked)[:exit_rank]]}
    return state, events


def members_by_rank(state: Optional[Mapping[str, Any]]) -> list[dict]:
    ms = list(((state or {}).get("members") or {}).values())
    return sorted(ms, key=lambda m: (m.get("rank") is None, m.get("rank") or 0, m.get("symbol") or ""))


# ── store (single writer: premarket_watch) ──────────────────────────────────────────────────────────────────────

def _root(state_root: Optional[Path] = None) -> Path:
    env = os.environ.get(ENV_DIR, "").strip()
    if env:
        return Path(env)
    if state_root is None:
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:  # pragma: no cover
            try:
                from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
            except ImportError:
                return Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "runtime"
        state_root = production_state_root()
    return Path(state_root) / "data" / "runtime"


def list_path(state_root: Optional[Path] = None) -> Path:
    return _root(state_root) / LIST_REL.name


def events_path(state_root: Optional[Path] = None) -> Path:
    return _root(state_root) / EVENTS_REL.name


def load_state(path: Optional[Path] = None, *, day: Optional[str] = None) -> Optional[dict]:
    """The stored list, or None (missing / unreadable / another session's list when ``day`` is given)."""
    try:
        doc = json.loads(Path(path or list_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if day and doc.get("day") and doc.get("day") != day:
        return None
    return doc


def save(state: Mapping[str, Any], events: Iterable[Mapping[str, Any]], *, day: str,
         path: Optional[Path] = None, events_file: Optional[Path] = None) -> Path:
    p = Path(path or list_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(state)
    doc["day"] = day
    doc["writer"] = "scripts/active_trader/premarket_watch.py"
    doc["authority"] = "READ_ONLY_ADVISORY"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(p)
    evs = list(events)
    if evs:
        ep = Path(events_file or events_path())
        with ep.open("a", encoding="utf-8") as fh:
            for e in evs:
                fh.write(json.dumps({**e, "day": day}, sort_keys=True, default=str) + "\n")
    return p


def read_focus(*, now: Optional[float] = None, path: Optional[Path] = None,
               fresh_s: float = DEFAULT_FRESH_S) -> dict:
    """Reader for every consumer (critique gate, Active Trader page, Trade AI page). Never raises.

    {status: ok | stale | missing, age_s, symbols (rank order), members}."""
    now = time.time() if now is None else float(now)
    doc = load_state(path)
    if not doc:
        return {"schema": SCHEMA, "status": "missing", "age_s": None, "symbols": [], "members": []}
    age = now - float(doc.get("as_of") or 0)
    ms = members_by_rank(doc)
    return {"schema": SCHEMA, "status": "ok" if 0 <= age <= fresh_s else "stale", "age_s": round(age, 1),
            "day": doc.get("day"), "size": doc.get("size"), "exit_rank": doc.get("exit_rank"),
            "pool_size": doc.get("pool_size"), "symbols": [m.get("symbol") for m in ms],
            "members": [{k: m.get(k) for k in ("symbol", "rank", "score", "state", "entered_hm", "reason",
                                               "features", "held_reason")} for m in ms],
            "contenders": doc.get("contenders") or []}


def recent_events(*, day: str, path: Optional[Path] = None, limit: int = 50) -> list[dict]:
    p = Path(path or events_path())
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-2000:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("day") == day:
            out.append(r)
    return out[-int(limit):]


def restrict_to_focus(candidates: Sequence[Any], *, focus: Optional[Mapping[str, Any]] = None,
                      cfg: Optional[FocusConfig] = None) -> tuple[list[Any], dict]:
    """Keep only focus names when the gate is on and the list is fresh. (kept, report). Pure given ``focus``.

    candidates may be symbols or dicts with ``symbol``. No fresh focus list -> candidates unchanged (fail-soft)."""
    cfg = cfg or FocusConfig()
    focus = read_focus(fresh_s=cfg.fresh_s) if focus is None else focus
    report = {"gate": cfg.critique_gate, "focus_status": focus.get("status"), "focus_size": len(focus.get("symbols")
                                                                                                or [])}
    if cfg.critique_gate != "focus" or focus.get("status") != "ok":
        report["applied"] = False
        return list(candidates), report
    allowed = {str(s).upper() for s in focus.get("symbols") or []}

    def sym(c: Any) -> str:
        return str(c.get("symbol") if isinstance(c, dict) else c).upper()

    kept = [c for c in candidates if sym(c) in allowed]
    report.update(applied=True, kept=len(kept), dropped=sorted({sym(c) for c in candidates} - allowed))
    return kept, report
