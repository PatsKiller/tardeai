"""Level 2 book signals: spread (bps) and bid/ask imbalance (Gate 4 design, operator-approved 2026-10-22).

Two computed signals from one order-book snapshot, in the same {on, value, threshold, status} shape the Active
Trader entry signals use, so an alert can show which are lit:

- ``tight_spread``     on when spread_bps <= ``spread_bps_max``;
- ``bid_ask_imbalance`` on when bid size / ask size over the top ``levels`` >= ``imbalance_min``.
  ``ask_heavy`` is the matching WARNING: on when that ratio <= ``ask_heavy_max``.

Thresholds are v1 PRIORS in ``config/scalp_signal_engine.yaml`` section ``microstructure_signals`` (the same
keys ``active_trader/microstructure_signals.SignalConfig`` reads: spread_bps_max, imbalance_min, ask_heavy_max,
imbalance_levels); changes are operator-ratified only. Defaults below equal the shipped priors; parity with
SignalConfig is pinned by tests.

Inputs are read-only: a recorder snapshot (``{"b": [[px, sz], ...], "a": [...], "t": epoch}``, the
``active_trader_microstructure`` data-broker domain), or the ``l2`` block an Active Trader journal row already
carries (``best_bid``, ``best_ask``, ``bid_depth``, ``ask_depth``, ``levels``). Fail closed: a missing, one-sided
or crossed book gives status ``NO_BOOK`` and ``on: None`` -- never a lit signal from absent data.

Pure: no network, no broker, no write. AUTHORITY: READ_ONLY_ADVISORY; MBI_BEHAVIOR=0 (a signal is evidence for an
advisory alert, never a size, order or stop).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "L2BookSignals@v1"
CONFIG_SECTION = "microstructure_signals"
_KEYS = {"spread_bps_max": "spread_bps_max", "imbalance_min": "imbalance_min", "ask_heavy_max": "ask_heavy_max",
         "imbalance_levels": "levels"}
REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "scalp_signal_engine.yaml"


@dataclass(frozen=True)
class L2BookSignalConfig:
    """v1 priors (operator-ratified changes only)."""

    spread_bps_max: float = 50.0   # same bound as config/scalp_confirmations.yaml max_spread_bps
    imbalance_min: float = 1.5     # bids >= 1.5x asks over the top levels = bid-side support
    ask_heavy_max: float = 0.67    # bids <= 0.67x asks = ask-heavy (warning)
    levels: int = 5                # top-of-book levels summed for the imbalance


def load_config(path: Optional[Path] = None) -> L2BookSignalConfig:
    """Read the ``microstructure_signals`` section; other keys are ignored, a bad value keeps the prior."""
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 -- no config = priors, never a crash on an alert path
        return L2BookSignalConfig()
    sec = doc.get(CONFIG_SECTION) if isinstance(doc, dict) else None
    if not isinstance(sec, dict):
        return L2BookSignalConfig()
    base = asdict(L2BookSignalConfig())
    for key, name in _KEYS.items():
        if key in sec:
            try:
                base[name] = int(sec[key]) if name == "levels" else float(sec[key])
            except (TypeError, ValueError):
                pass
    return L2BookSignalConfig(**base)


def _levels(side: Iterable[Any], n: int) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for lv in side or []:
        try:
            px, sz = float(lv[0]), float(lv[1])
        except (TypeError, ValueError, IndexError):
            continue
        if px > 0 and sz >= 0:
            out.append((px, sz))
        if len(out) >= n:
            break
    return out


def _signal(on: Optional[bool], value: Optional[float], threshold: float, status: str, *, kind: str) -> dict:
    return {"on": on, "value": value, "threshold": threshold, "status": status, "kind": kind}


def _no_book(cfg: L2BookSignalConfig, reason: str) -> dict:
    return {
        "schema": SCHEMA,
        "status": "NO_BOOK",
        "reason": reason,
        "spread_bps": None,
        "imbalance": None,
        "levels": 0,
        "signals": {
            "tight_spread": _signal(None, None, cfg.spread_bps_max, "NO_BOOK", kind="entry"),
            "bid_ask_imbalance": _signal(None, None, cfg.imbalance_min, "NO_BOOK", kind="entry"),
            "ask_heavy": _signal(None, None, cfg.ask_heavy_max, "NO_BOOK", kind="warning"),
        },
    }


def compute(best_bid: Any, best_ask: Any, bid_size: Any, ask_size: Any, *, levels: int,
            cfg: Optional[L2BookSignalConfig] = None, source: str = "book") -> dict:
    """Signals from inside prices and summed sizes. Fail closed on a missing, one-sided or crossed book."""
    cfg = cfg or L2BookSignalConfig()
    try:
        bid, ask = float(best_bid), float(best_ask)
    except (TypeError, ValueError):
        return _no_book(cfg, "missing_inside")
    if bid <= 0 or ask <= 0:
        return _no_book(cfg, "one_sided")
    if ask < bid:
        return _no_book(cfg, "crossed")
    mid = (bid + ask) / 2.0
    spread_bps = round((ask - bid) / mid * 10_000.0, 1)
    try:
        bsz, asz = float(bid_size), float(ask_size)
    except (TypeError, ValueError):
        bsz = asz = None  # type: ignore[assignment]
    imbalance: Optional[float]
    if bsz is None or asz is None or asz <= 0:
        imbalance = None
    else:
        imbalance = round(bsz / asz, 2)
    sig = {
        "tight_spread": _signal(spread_bps <= cfg.spread_bps_max, spread_bps, cfg.spread_bps_max, "OK",
                                kind="entry"),
        "bid_ask_imbalance": (
            _signal(imbalance >= cfg.imbalance_min, imbalance, cfg.imbalance_min, "OK", kind="entry")
            if imbalance is not None else _signal(None, None, cfg.imbalance_min, "NO_SIZE", kind="entry")),
        "ask_heavy": (
            _signal(imbalance <= cfg.ask_heavy_max, imbalance, cfg.ask_heavy_max, "OK", kind="warning")
            if imbalance is not None else _signal(None, None, cfg.ask_heavy_max, "NO_SIZE", kind="warning")),
    }
    return {"schema": SCHEMA, "status": "OK", "source": source, "spread_bps": spread_bps,
            "imbalance": imbalance, "levels": int(levels), "signals": sig}


def from_snapshot(snapshot: Optional[dict], cfg: Optional[L2BookSignalConfig] = None) -> dict:
    """Signals from one recorder snapshot (``b``/``a`` level lists, best first)."""
    cfg = cfg or L2BookSignalConfig()
    if not isinstance(snapshot, dict):
        return _no_book(cfg, "no_snapshot")
    bids, asks = _levels(snapshot.get("b") or [], cfg.levels), _levels(snapshot.get("a") or [], cfg.levels)
    if not bids or not asks:
        return _no_book(cfg, "one_sided")
    n = min(len(bids), len(asks))
    out = compute(bids[0][0], asks[0][0], sum(s for _, s in bids[:n]), sum(s for _, s in asks[:n]),
                  levels=n, cfg=cfg, source=f"store:{snapshot.get('bs') or 'recorder'}")
    out["as_of"] = snapshot.get("bt") or snapshot.get("t")
    return out


def from_at_l2(l2: Optional[dict], cfg: Optional[L2BookSignalConfig] = None) -> dict:
    """Signals from the ``l2`` evidence block of an Active Trader journal row (depth over its own ``levels``)."""
    cfg = cfg or L2BookSignalConfig()
    if not isinstance(l2, dict) or not l2.get("ok"):
        return _no_book(cfg, "l2_not_ok")
    return compute(l2.get("best_bid"), l2.get("best_ask"), l2.get("bid_depth"), l2.get("ask_depth"),
                   levels=int(l2.get("levels") or 0), cfg=cfg, source=str(l2.get("source") or "at_l2"))


def lit_lines(result: dict) -> list[str]:
    """Display tokens: '●' lit, '○' unlit, '—' not computed. Warnings are shown only when lit."""
    sig = (result or {}).get("signals") or {}
    out: list[str] = []
    ts = sig.get("tight_spread") or {}
    out.append(("●" if ts.get("on") else "○" if ts.get("on") is False else "—")
               + f" Spread {_fmt(ts.get('value'), 'bps')}")
    im = sig.get("bid_ask_imbalance") or {}
    out.append(("●" if im.get("on") else "○" if im.get("on") is False else "—")
               + f" Bid/ask {_ratio(im.get('value'))}")
    ah = sig.get("ask_heavy") or {}
    if ah.get("on"):
        out.append(f"⚠ Ask-heavy {_ratio(ah.get('value'))}")
    return out


def _fmt(v: Any, unit: str) -> str:
    return "—" if v is None else f"{float(v):g} {unit}"


def _ratio(v: Any) -> str:
    return "—" if v is None else f"{float(v):.1f}:1"
