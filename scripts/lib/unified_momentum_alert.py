"""Unified momentum alert -- ONE threaded alert per symbol/event/day (Gate 4, operator-approved design 2026-10-22).

Replaces the two separate operator alerts for the same move -- the Momentum Scalp alert
(``social_scalp_scanner.send_scalp_alert``) and the Active Trader alert (``active_trader/momentum_alerts``) --
with one lifecycle:

    WATCH -> APPROACHING -> ARMED -> TRIGGERED -> STAND DOWN   (+ EXTENDED / PULLBACK_ZONE / TRIGGER_CANCELLED)

Each state CHANGE is a new Telegram message sent as a threaded reply to the thread's first message (the first
message id is stored per chat, per symbol/event/day), so the phone still notifies and the history reads as one
conversation. Every message carries the catalyst title, grade, AI verdict + confidence ("—" when not available),
float, volume, RVOL, which sources agree (scan / social / L2) and the lit L2 signals, and keeps the line
"ADVISORY ONLY — NOT AN ORDER".

Mode (``config/scalp_signal_engine.yaml`` ``unified_momentum_alert.mode``; env ``UNIFIED_MOMENTUM_ALERT_MODE``
overrides for one process; anything unreadable or unknown resolves to ``shadow``, never to ``live``):

- ``off``    -- nothing is built; callers behave exactly as before Gate 4.
- ``shadow`` -- (default) callers send today's alert unchanged; the unified message is built and appended to the
                ledger with action ``SHADOW_LOGGED``. Nothing is sent.
- ``live``   -- the unified message is sent through the host communications gateway (``send_telegram`` as a
                notification intent: priority, content dedupe window, producer, route receipt -- AGENTS.md §9.1,
                §24.1) and the caller does NOT send its old alert.

Dedupe: notify on transitions (AGENTS.md §9.1) -- a state equal to the thread's last emitted state is not
re-emitted (``DEDUPED_SAME_STATE``), and an event whose ``origin_ref`` is already in the thread is a replay
(``DUPLICATE_ORIGIN``). The intent router then applies its own content dedupe window on the body.

Store: ``<state root>/data/runtime/unified_momentum_alerts.jsonl`` (``UnifiedMomentumAlert@v1`` rows), one writer
(this module), append-only under an flock. It holds the shadow builds and the live thread roots. Proposed as a
history copy of the ``alert_events`` domain in ``config/data_source_authority.json`` (AGENTS.md §26.2, proposed,
not granted).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0 -- an alert is awareness; it never sizes, orders or stops, and
nothing here reaches a broker. Time-critical sends stay host-side; nothing here depends on n8n.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

try:  # scripts/ on sys.path (lanes) or the repo root (tests)
    from lib import l2_book_signals as l2sig
except ImportError:  # pragma: no cover
    from scripts.lib import l2_book_signals as l2sig  # type: ignore

SCHEMA = "UnifiedMomentumAlert@v1"
PRODUCER = "unified_momentum_alert"
ET = ZoneInfo("America/New_York")
REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "scalp_signal_engine.yaml"
CONFIG_SECTION = "unified_momentum_alert"
LEDGER_REL = Path("data") / "runtime" / "unified_momentum_alerts.jsonl"
MODES = ("off", "shadow", "live")
DEFAULT_MODE = "shadow"
DEFAULT_DEDUPE_MINUTES = 30
ADVISORY_LINE = "ADVISORY ONLY — NOT AN ORDER. Your decision, your broker."
DASH = "—"

STATES = ("WATCH", "APPROACHING", "ARMED", "TRIGGERED", "EXTENDED", "PULLBACK_ZONE", "TRIGGER_CANCELLED",
          "STAND_DOWN")
LABEL = {"PULLBACK_ZONE": "PULLBACK ZONE", "TRIGGER_CANCELLED": "TRIGGER CANCELLED", "STAND_DOWN": "STAND DOWN"}
ICON = {"WATCH": "👀", "APPROACHING": "🔵", "ARMED": "🟠", "TRIGGERED": "🟢", "EXTENDED": "🟣",
        "PULLBACK_ZONE": "🟡", "TRIGGER_CANCELLED": "⚪", "STAND_DOWN": "🔴"}
# Time-critical states interrupt (P1: never quiet-held); WATCH / cancel / stand-down are P2 (held 22:00-07:00 ET
# to the digest, AGENTS.md §9.1 -- a held message is archived, never dropped).
P1_STATES = frozenset({"APPROACHING", "ARMED", "TRIGGERED", "EXTENDED", "PULLBACK_ZONE"})
# Active Trader journal kinds -> lifecycle states (the engine's own vocabulary; PREMARKET_WATCH is its WATCH).
AT_KIND_MAP = {"PREMARKET_WATCH": "WATCH", "WATCH": "WATCH", "APPROACHING": "APPROACHING", "ARMED": "ARMED",
               "TRIGGERED": "TRIGGERED", "EXTENDED": "EXTENDED", "PULLBACK_ZONE": "PULLBACK_ZONE",
               "TRIGGER_CANCELLED": "TRIGGER_CANCELLED", "STAND_DOWN": "STAND_DOWN", "STANDDOWN": "STAND_DOWN"}
# Rows that count as "emitted" for the transition rule. A failed send did not reach the operator, so the same
# state may be tried again.
EMITTED_ACTIONS = frozenset({"SHADOW_LOGGED", "SENT", "ACCEPTED_NOT_DELIVERED"})
_MD = re.compile(r"[*`\[\]]")


@dataclass
class UnifiedAlertEvent:
    """One observation of a symbol's momentum lifecycle, from any source. Absent values stay None ("—")."""

    symbol: str
    state: str
    ts_epoch: float
    origin: str                                   # "scan" | "social" | "active_trader"
    event_key: str = "momentum"                   # one thread per symbol/event/day
    origin_ref: Optional[str] = None              # idempotency key of the source row
    catalyst_title: Optional[str] = None
    catalyst_origin: Optional[str] = None
    grade: Optional[str] = None
    verdict: Optional[str] = None                 # AI / Brave verdict text
    confidence: Optional[float] = None
    float_m: Optional[float] = None
    volume: Optional[float] = None
    rvol: Optional[float] = None
    price: Optional[float] = None
    sources: dict = field(default_factory=dict)   # {"scan": bool|None, "social": bool|None, "l2": bool|None}
    source_detail: dict = field(default_factory=dict)
    l2: Optional[dict] = None                     # l2_book_signals result
    lit_signals: list = field(default_factory=list)   # extra engine signals, display tokens ("● Broke PMH")
    levels: dict = field(default_factory=dict)    # trigger / entry / stop / r
    detail: Optional[str] = None

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(float(self.ts_epoch), tz=ET).strftime("%Y-%m-%d")

    @property
    def thread_key(self) -> str:
        return f"{self.day}:{self.symbol.upper()}:{self.event_key}"


# ── mode ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _config(path: Optional[Path] = None) -> dict:
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 -- unreadable config resolves to the default (shadow), never to live
        return {}
    sec = doc.get(CONFIG_SECTION) if isinstance(doc, dict) else None
    return sec if isinstance(sec, dict) else {}


def resolve_mode(config_path: Optional[Path] = None, env: Optional[dict] = None) -> str:
    """off | shadow | live. Env override first, then config, then ``shadow``. Unknown values -> ``shadow``."""
    env = os.environ if env is None else env
    raw = str(env.get("UNIFIED_MOMENTUM_ALERT_MODE") or "").strip().lower()
    if not raw:
        raw = str(_config(config_path).get("mode") or DEFAULT_MODE).strip().lower()
    return raw if raw in MODES else DEFAULT_MODE


def dedupe_minutes(config_path: Optional[Path] = None) -> int:
    try:
        return max(0, int(_config(config_path).get("dedupe_minutes", DEFAULT_DEDUPE_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_DEDUPE_MINUTES


# ── rendering ───────────────────────────────────────────────────────────────────────────────────────────────────

def _clean(text: Any, limit: int = 160) -> Optional[str]:
    if text is None:
        return None
    s = " ".join(_MD.sub("", str(text)).replace("_", " ").split())
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _num(v: Any, fmt: str = "{:,.2f}") -> str:
    try:
        return DASH if v is None else fmt.format(float(v))
    except (TypeError, ValueError):
        return DASH


def _vol(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return DASH
    if f <= 0:
        return DASH
    if f >= 1e6:
        return f"{f / 1e6:.1f}M"
    if f >= 1e3:
        return f"{f / 1e3:.0f}K"
    return f"{f:.0f}"


def _mark(v: Optional[bool]) -> str:
    return "✓" if v is True else "✗" if v is False else DASH


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=ET).strftime("%H:%M")


def label(state: str) -> str:
    return LABEL.get(state, state)


def render(event: UnifiedAlertEvent, *, root: Optional[dict] = None) -> str:
    """The operator text (plain; no Markdown markup, free text stripped of Markdown metacharacters)."""
    sym = event.symbol.upper()
    lines = [f"{ICON.get(event.state, '•')} {label(event.state)} · {sym} · {_hhmm(event.ts_epoch)} ET"]
    if root:
        lines.append(f"↳ update to {label(str(root.get('state')))} · {sym} {_hhmm(float(root.get('ts_epoch') or 0))}")
    cat = _clean(event.catalyst_title)
    origin = _clean(event.catalyst_origin, 40)
    lines.append(f"Catalyst: {cat or DASH}" + (f" ({origin})" if cat and origin else ""))
    conf = DASH if event.confidence is None else _num(event.confidence, "{:.2f}")
    lines.append(f"Grade {_clean(event.grade, 12) or DASH} · {_clean(event.verdict, 80) or 'AI ' + DASH}"
                 f" · confidence {conf}")
    fl = DASH if event.float_m is None else _num(event.float_m, "{:,.2f}M")
    rv = DASH if event.rvol is None else _num(event.rvol, "{:.1f}x")
    lines.append(f"Float {fl} · Vol {_vol(event.volume)} · RVOL {rv}")
    parts = []
    for name in ("scan", "social", "l2"):
        detail = _clean((event.source_detail or {}).get(name), 30)
        parts.append(f"{'L2' if name == 'l2' else name} {_mark((event.sources or {}).get(name))}"
                     + (f" {detail}" if detail else ""))
    lines.append("Sources: " + " · ".join(parts))
    l2_tokens = l2sig.lit_lines(event.l2) if event.l2 else []
    l2_tokens += [str(t) for t in (event.lit_signals or []) if t]
    lines.append("L2: " + (" · ".join(l2_tokens) if l2_tokens else "not computed"))
    lv = event.levels or {}
    lv_parts = [f"{k} {_num(lv.get(k))}" for k in ("trigger", "entry", "stop") if lv.get(k) is not None]
    if lv.get("r") is not None:
        lv_parts.append(f"R {_num(lv.get('r'))}")
    if event.price is not None:
        lv_parts.insert(0, f"last {_num(event.price)}")
    if lv_parts:
        lines.append("Levels: " + " · ".join(lv_parts))
    det = _clean(event.detail, 200)
    if det:
        lines.append(det)
    lines.append(ADVISORY_LINE)
    return "\n".join(lines)


# ── the ledger (single store, single writer) ────────────────────────────────────────────────────────────────────

def ledger_path(state_root: Optional[Path] = None) -> Path:
    env = os.environ.get("UNIFIED_MOMENTUM_ALERT_LEDGER", "").strip()
    if env:
        return Path(env)
    if state_root is None:
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:  # pragma: no cover
            from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
        state_root = production_state_root()
    return Path(state_root) / LEDGER_REL


class Ledger:
    """Append-only JSONL under an exclusive flock (the scanner and other host callers may write concurrently)."""

    TAIL_BYTES = 4_000_000

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def locked(self) -> Iterator["Ledger"]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + ".lock", "a+") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                yield self
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    def rows(self, day: Optional[str] = None) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        with self.path.open("rb") as fh:
            if size > self.TAIL_BYTES:
                fh.seek(size - self.TAIL_BYTES)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace").splitlines()
        out = []
        for line in raw:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and (day is None or r.get("day") == day):
                out.append(r)
        return out

    def append(self, row: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


class MemoryLedger(Ledger):
    """Dry-run ledger: seeded from a real file (read-only), appends stay in memory."""

    def __init__(self, seed: Optional[Path] = None):
        super().__init__(seed or Path("/nonexistent"))
        self._seed = Ledger(seed).rows() if seed else []
        self.appended: list[dict] = []

    @contextmanager
    def locked(self) -> Iterator["Ledger"]:
        yield self

    def rows(self, day: Optional[str] = None) -> list[dict]:
        return [r for r in self._seed + self.appended if day is None or r.get("day") == day]

    def append(self, row: dict) -> None:
        self.appended.append(row)


# ── emit ────────────────────────────────────────────────────────────────────────────────────────────────────────

SendFn = Callable[..., dict]


def _telegram_module():
    try:
        import telegram_alert as ta  # scripts/ on sys.path: the same module object the lanes use
    except ImportError:  # pragma: no cover
        from scripts import telegram_alert as ta  # type: ignore
    return ta


def gateway_send(text: str, *, priority: str, dedupe_minutes: int, reply_to: Optional[dict],
                 symbol: str) -> dict:
    """The live send: one notification intent through the host gateway (send_telegram), threaded per chat."""
    ta = _telegram_module()
    token = None
    try:
        from lib.comms_editor import reset_primary_symbols, set_primary_symbols

        token = set_primary_symbols([symbol])
    except Exception:  # noqa: BLE001 -- link binding is cosmetic; the send still happens
        reset_primary_symbols = None  # type: ignore[assignment]
    try:
        accepted = ta.send_telegram(text, priority=priority, dedupe_minutes=dedupe_minutes, producer=PRODUCER,
                                    **({"reply_to_message_ids": dict(reply_to)} if reply_to else {}))
    finally:
        if token is not None and reset_primary_symbols is not None:
            reset_primary_symbols(token)
    by_chat = {}
    try:
        by_chat = ta.last_message_ids_by_chat()
    except AttributeError:  # pragma: no cover
        by_chat = {}
    try:
        route = ta.last_intent_route()
    except AttributeError:  # pragma: no cover
        route = {}
    return {"accepted": bool(accepted), "message_ids_by_chat": by_chat,
            "route_decision": (route or {}).get("decision")}


def _thread(rows: list[dict], key: str, mode: str) -> list[dict]:
    t = [r for r in rows if r.get("thread_key") == key and r.get("mode") == mode]
    return sorted(t, key=lambda r: float(r.get("ts_epoch") or 0))


def _root(thread: list[dict], mode: str) -> Optional[dict]:
    for r in thread:
        if r.get("action") not in EMITTED_ACTIONS:
            continue
        if mode == "live" and not r.get("message_ids_by_chat"):
            continue  # a held/deduped first message has no id to reply to; the first DELIVERED one is the root
        return r
    return None


def emit(event: UnifiedAlertEvent, *, mode: Optional[str] = None, ledger: Optional[Ledger] = None,
         send: Optional[SendFn] = None, config_path: Optional[Path] = None,
         legacy_alert: Optional[str] = None) -> dict:
    """Build (and in live mode send) one lifecycle message. Returns the ledger row, or a dict with ``action``.

    ``legacy_alert`` names the alert the caller sent the old way (shadow), so the ledger shows both side by side.
    """
    mode = mode or resolve_mode(config_path)
    if mode not in MODES:
        mode = DEFAULT_MODE
    if mode == "off":
        return {"action": "OFF", "mode": "off"}
    if event.state not in STATES:
        return {"action": "REJECTED_STATE", "mode": mode, "state": event.state}
    ledger = ledger or Ledger(ledger_path())
    key = event.thread_key
    with ledger.locked():
        thread = _thread(ledger.rows(event.day), key, mode)
        if event.origin_ref and any(r.get("origin_ref") == event.origin_ref for r in thread):
            return {"action": "DUPLICATE_ORIGIN", "mode": mode, "thread_key": key}
        prior = [r for r in thread if r.get("action") in EMITTED_ACTIONS
                 and float(r.get("ts_epoch") or 0) <= float(event.ts_epoch)]
        if prior and prior[-1].get("state") == event.state:
            return {"action": "DEDUPED_SAME_STATE", "mode": mode, "thread_key": key, "state": event.state}
        root = _root(thread, mode)
        text = render(event, root=root)
        priority = "P1" if event.state in P1_STATES else "P2"
        row: dict[str, Any] = {
            "schema": SCHEMA, "day": event.day, "thread_key": key, "symbol": event.symbol.upper(),
            "event_key": event.event_key, "state": event.state,
            "prev_state": prior[-1].get("state") if prior else None,
            "origin": event.origin, "origin_ref": event.origin_ref, "mode": mode, "priority": priority,
            "ts_epoch": float(event.ts_epoch), "logged_at": datetime.now(timezone.utc).isoformat(),
            "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "is_root": root is None, "root_ref": (root or {}).get("row_id"),
            "event": _event_json(event), "legacy_alert": legacy_alert,
            "authority": {"read_only": True, "order": False, "broker_write": False},
        }
        row["row_id"] = hashlib.sha256(f"{key}|{mode}|{event.state}|{event.ts_epoch}|{event.origin_ref}"
                                       .encode("utf-8")).hexdigest()[:16]
        if mode == "shadow":
            row["action"] = "SHADOW_LOGGED"
            row["would_reply_to"] = (root or {}).get("row_id")
        else:
            reply_to = dict((root or {}).get("message_ids_by_chat") or {}) or None
            row["reply_to"] = reply_to
            try:
                res = (send or gateway_send)(text, priority=priority, dedupe_minutes=dedupe_minutes(config_path),
                                             reply_to=reply_to, symbol=event.symbol.upper())
            except Exception as exc:  # noqa: BLE001
                # ALARM-DELIVERY-DECLARED: the failure is written to the ledger row (durable) and returned, and the
                # caller falls back to its legacy alert -- the operator is never left with nothing.
                res = {"accepted": False, "message_ids_by_chat": {}, "error": f"{type(exc).__name__}: {exc}"[:200]}
            ids = {str(k): str(v) for k, v in (res.get("message_ids_by_chat") or {}).items() if v}
            row["message_ids_by_chat"] = ids
            row["route_decision"] = res.get("route_decision")
            row["error"] = res.get("error")
            if ids:
                row["action"] = "SENT"
            elif res.get("accepted"):
                row["action"] = "ACCEPTED_NOT_DELIVERED"   # router deduped / held for the digest: not a failure
            else:
                row["action"] = "SEND_FAILED"
            row["is_root"] = root is None and bool(ids)
        ledger.append(row)
        return row


def _event_json(event: UnifiedAlertEvent) -> dict:
    d = asdict(event)
    d.pop("l2", None)
    d["l2_summary"] = ({k: (event.l2 or {}).get(k) for k in ("status", "spread_bps", "imbalance", "levels")}
                       if event.l2 else None)
    return d


# ── adapters ────────────────────────────────────────────────────────────────────────────────────────────────────

def catalyst_from_hermes(symbol: str, day: str, lookup: Optional[Callable[[str, str], dict]] = None) -> dict:
    """AI verdict + confidence from today's Hermes scalp-catalyst research (read-only projection). {} when none."""
    try:
        if lookup is None:
            try:
                from lib import hermes_catalyst_store as store
                from lib.data_broker.scalp_list import get_scalp_catalyst
            except ImportError:  # pragma: no cover
                from scripts.lib import hermes_catalyst_store as store  # type: ignore
                from scripts.lib.data_broker.scalp_list import get_scalp_catalyst  # type: ignore
            # The single writer's store (persistent state first, legacy code-root copy second): the root is the
            # directory above data/hermes/momentum_catalysts/<day>_catalysts.jsonl.
            root = store.day_file_for_read(day).parents[3]
            rec = get_scalp_catalyst(symbol, day, root) or {}
        else:
            rec = lookup(symbol, day) or {}
    except Exception:  # noqa: BLE001 -- an unavailable projection renders "—", never blocks the alert
        return {}
    status = rec.get("status")
    if status == "FOUND":
        ctype = str(rec.get("catalyst_type") or "catalyst").replace("_", " ")
        n = rec.get("source_count")
        return {"verdict": f"AI: {ctype}" + (f" ({n} src)" if n else ""), "confidence": rec.get("confidence"),
                "title": rec.get("summary")}
    if status == "NONE_FOUND":
        return {"verdict": "AI: no clear catalyst", "confidence": rec.get("confidence"), "title": None}
    return {}


def enrich_catalyst(event: UnifiedAlertEvent, lookup: Optional[Callable[[str, str], dict]] = None) -> UnifiedAlertEvent:
    """Fill a missing AI verdict / confidence / catalyst title from today's Hermes research (read-only)."""
    if event.verdict is not None and event.confidence is not None and event.catalyst_title:
        return event
    cat = catalyst_from_hermes(event.symbol, event.day, lookup)
    if event.verdict is None:
        event.verdict = cat.get("verdict")
    if event.confidence is None:
        event.confidence = cat.get("confidence")
    if not event.catalyst_title and cat.get("title"):
        event.catalyst_title, event.catalyst_origin = cat.get("title"), "hermes"
    return event


def _at_signal_tokens(signals: Any) -> list[str]:
    out = []
    if not isinstance(signals, dict):
        return out
    for name, v in sorted(signals.items()):
        if name == "status":
            continue
        on = v.get("on") if isinstance(v, dict) else v
        if on is True:
            out.append(f"● {name.replace('_', ' ')}")
    return out


def event_from_at_row(row: dict) -> Optional[UnifiedAlertEvent]:
    """An Active Trader journal row (contract active-trader-momentum-alert-v1) -> event. None when unmapped."""
    if not isinstance(row, dict):
        return None
    state = AT_KIND_MAP.get(str(row.get("kind") or "").upper())
    cand = row.get("candidate") or {}
    sym = str(cand.get("symbol") or "").upper()
    if not state or not sym:
        return None
    ts = float(row.get("ts_epoch") or 0)
    ta = cand.get("trade_ai") or {}
    cat = ta.get("day_catalyst") or {}
    ev = ta.get("setup_evidence") or {}
    ev_cat = ev.get("catalyst") or {}
    decision = ta.get("decision")
    passed, req = ev.get("passed_count"), ev.get("required_count")
    l2 = l2sig.from_at_l2(row.get("l2"))
    entry_lit = [s for s in ("tight_spread", "bid_ask_imbalance") if (l2.get("signals") or {}).get(s, {}).get("on")]
    heavy = ((l2.get("signals") or {}).get("ask_heavy") or {}).get("on")
    l2_agrees = None if l2.get("status") != "OK" else bool(entry_lit) and not heavy
    entry, stop = cand.get("entry_ref"), cand.get("stop_ref")
    r = None
    try:
        r = round(float(entry) - float(stop), 4) if entry is not None and stop is not None else None
    except (TypeError, ValueError):
        r = None
    social = "social" in str(cat.get("source") or "").lower()
    return UnifiedAlertEvent(
        symbol=sym, state=state, ts_epoch=ts, origin="active_trader",
        origin_ref=f"at:{row.get('run_id')}:{sym}:{row.get('kind')}:{ts}",
        catalyst_title=cat.get("text"), catalyst_origin=cat.get("source"),
        grade=None,
        verdict=(f"verification {str(ev_cat.get('verification_status')).lower()}"
                 if ev_cat.get("verification_status") not in (None, "UNKNOWN") else None),
        confidence=ev_cat.get("model_confidence"),
        float_m=cand.get("float_mm"), volume=None, rvol=cand.get("rvol"), price=cand.get("last"),
        sources={"scan": (str(decision).upper() == "GO") if decision else None,
                 "social": True if social else None, "l2": l2_agrees},
        source_detail={"scan": (f"{decision} {passed}/{req}" if decision and passed is not None and req
                                else decision),
                       "l2": f"{len(entry_lit)}/2 lit" if l2.get("status") == "OK" else "no book"},
        l2=l2, lit_signals=_at_signal_tokens(row.get("signals")),
        levels={"trigger": cand.get("break_level"), "entry": entry, "stop": stop, "r": r},
        detail=(f"Stand-down: {cand.get('stand_down_reason')}" if cand.get("stand_down_reason") else None),
    )


def at_journal_path() -> Path:
    try:
        from lib.data_broker.microstructure import store_dir
    except ImportError:  # pragma: no cover
        from scripts.lib.data_broker.microstructure import store_dir  # type: ignore
    return store_dir().parent / "momentum_alerts.jsonl"


def at_rows(day: str, *, path: Optional[Path] = None, symbol: Optional[str] = None,
            tail_bytes: int = 8_000_000) -> list[dict]:
    """Active Trader journal rows for one session day (read-only, bounded tail)."""
    p = Path(path or at_journal_path())
    try:
        size = p.stat().st_size
    except OSError:
        return []
    with p.open("rb") as fh:
        if size > tail_bytes:
            fh.seek(size - tail_bytes)
            fh.readline()
        lines = fh.read().decode("utf-8", "replace").splitlines()
    out = []
    sym = symbol.upper() if symbol else None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        cand = (r or {}).get("candidate") or {}
        if cand.get("session_date") != day:
            continue
        if sym and str(cand.get("symbol") or "").upper() != sym:
            continue
        out.append(r)
    return out


def latest_at_l2(symbol: str, day: str, *, path: Optional[Path] = None) -> Optional[dict]:
    """The latest L2 evidence the Active Trader journal holds for ``symbol`` today (None when none)."""
    for r in reversed(at_rows(day, path=path, symbol=symbol, tail_bytes=2_000_000)):
        if isinstance(r.get("l2"), dict) and r["l2"].get("ok"):
            return r["l2"]
    return None


def event_from_scalp(symbol: str, *, score: int, grade: str, decision: str, finviz_data: dict,
                     mention_count: int, sources: list, ts_epoch: float,
                     catalyst_lookup: Optional[Callable[[str, str], dict]] = None,
                     l2_lookup: Optional[Callable[[str, str], Optional[dict]]] = None) -> UnifiedAlertEvent:
    """The social scalp scanner's GO / A+ alert -> a WATCH event (scan + social agree; L2 from the AT journal)."""
    sym = str(symbol).upper()
    day = datetime.fromtimestamp(float(ts_epoch), tz=ET).strftime("%Y-%m-%d")
    cat = catalyst_from_hermes(sym, day, catalyst_lookup)
    try:
        raw_l2 = (l2_lookup or (lambda s, d: latest_at_l2(s, d)))(sym, day)
    except Exception:  # noqa: BLE001 -- no L2 evidence renders as "not computed", never blocks the alert
        raw_l2 = None
    l2 = l2sig.from_at_l2(raw_l2) if raw_l2 else None
    l2_ok = bool(l2 and l2.get("status") == "OK")
    lit = [s for s in ("tight_spread", "bid_ask_imbalance") if l2_ok and l2["signals"][s].get("on")]
    heavy = bool(l2_ok and l2["signals"]["ask_heavy"].get("on"))
    fd = finviz_data or {}
    return UnifiedAlertEvent(
        symbol=sym, state="WATCH", ts_epoch=float(ts_epoch), origin="social",
        origin_ref=f"scalp:{day}:{sym}:{int(ts_epoch)}",
        catalyst_title=cat.get("title"), catalyst_origin="hermes" if cat.get("title") else None,
        grade=grade, verdict=cat.get("verdict"), confidence=cat.get("confidence"),
        float_m=fd.get("float_m"), volume=fd.get("volume_base") or fd.get("volume"), rvol=fd.get("rvol"),
        price=fd.get("price"),
        sources={"scan": str(decision).upper() == "GO" or None, "social": bool(mention_count) or None,
                 "l2": (bool(lit) and not heavy) if l2_ok else None},
        source_detail={"scan": f"{decision} {score}/55", "social": f"{mention_count}x " + ", ".join(
            str(s) for s in (sources or [])[:2]), "l2": f"{len(lit)}/2 lit" if l2_ok else "not armed"},
        l2=l2,
    )
