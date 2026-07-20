#!/usr/bin/env python3
"""opening_intelligence.py — overnight futures / market-open evidence synthesis.

ADVISORY CONTEXT ONLY. This module must never approve a proposal, submit an
order, raise a strategy score, bypass a gate, or change exposure. It produces an
evidence synthesis about how the session is shaping up, with its own coverage
and freshness stated, and nothing else consumes it as authority.

    OPENING INTELLIGENCE EXECUTION AUTHORITY: NO

PROVIDER AUDIT (2026-07-20, empirical):
  * Schwab quotes DO NOT serve index futures under this entitlement. Worse, the
    endpoint answers HTTP 200 for "/ES" with EVERSOURCE ENERGY (assetMainType
    EQUITY) — a naive implementation would have built the entire futures layer
    on a utility stock. "/NQ", "/ESU26" and ":XCME" forms all 400/404.
  * yfinance serves genuine index futures (ES=F, NQ=F, RTY=F, YM=F) but reports
    quoteSourceName "Delayed Quote" with exchangeDataDelayedBy=10 and a measured
    quote age of ~600s.
  => TRUE_FUTURES_DELAYED. Realtime is NOT claimed anywhere.

Canonical internal names are vendor-independent; the vendor symbol is stored
alongside so a provider swap cannot silently change meaning.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, time as dtime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ET = ZoneInfo("America/New_York")
SNAPSHOT_DIR = ROOT / "data" / "runtime" / "opening_intelligence"

# Provider capability states (§9)
TRUE_FUTURES_REALTIME = "TRUE_FUTURES_REALTIME"
TRUE_FUTURES_DELAYED = "TRUE_FUTURES_DELAYED"
ETF_PREMARKET_PROXY_ONLY = "ETF_PREMARKET_PROXY_ONLY"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

# Opening-bias states (§14)
STRONG_HIGHER = "STRONG_HIGHER_OPEN_BIAS"
HIGHER = "HIGHER_OPEN_BIAS"
MIXED = "MIXED_OPEN"
LOWER = "LOWER_OPEN_BIAS"
STRONG_LOWER = "STRONG_LOWER_OPEN_BIAS"
DATA_INSUFFICIENT = "DATA_INSUFFICIENT"

# Confidence = evidence coverage, never an invented probability (§15)
HIGH_COVERAGE = "HIGH_COVERAGE"
MEDIUM_COVERAGE = "MEDIUM_COVERAGE"
LOW_COVERAGE = "LOW_COVERAGE"
CONFLICTED = "CONFLICTED"

# canonical -> vendor
FUTURES_MAP = {
    "SP500_FUT": "ES=F",
    "NASDAQ100_FUT": "NQ=F",
    "RUSSELL2000_FUT": "RTY=F",
    "DOW_FUT": "YM=F",
}
PROXY_MAP = {"SP500_FUT": "SPY", "NASDAQ100_FUT": "QQQ",
             "RUSSELL2000_FUT": "IWM", "DOW_FUT": "DIA"}

# A quote older than this is not presented as current.
MAX_QUOTE_AGE_SEC = int(os.getenv("OPENING_MAX_QUOTE_AGE_SEC", "1800"))
# Delay above which we say DELAYED rather than REALTIME.
REALTIME_MAX_AGE_SEC = 120


class ProviderError(RuntimeError):
    """Provider could not answer. Never collapsed into 'no movement'."""


def market_session(now: Optional[datetime] = None) -> str:
    """Which session are we in? Drives price-field selection (§11)."""
    n = (now or datetime.now(timezone.utc)).astimezone(ET)
    if n.weekday() >= 5:
        return "weekend"
    t = n.time()
    if t < dtime(4, 0):
        return "overnight"
    if t < dtime(9, 30):
        return "premarket"
    if t < dtime(16, 0):
        return "regular"
    if t < dtime(20, 0):
        return "afterhours"
    return "overnight"


@dataclass
class Quote:
    canonical: str
    vendor_symbol: str
    price: Optional[float] = None
    previous_close: Optional[float] = None
    change_pct: Optional[float] = None
    quote_ts: Optional[str] = None
    age_sec: Optional[float] = None
    delayed: bool = True
    source: str = ""
    stale: bool = False
    error: str = ""

    @property
    def usable(self) -> bool:
        return (self.price is not None and self.change_pct is not None
                and not self.stale and not self.error)


class OpeningMarketProvider:
    """Interface (§9). Implementations must never fabricate a value."""

    def get_index_futures(self) -> dict: raise NotImplementedError
    def get_cross_asset_context(self) -> dict: raise NotImplementedError
    def get_premarket_etfs(self) -> dict: raise NotImplementedError
    def health(self) -> dict: raise NotImplementedError


class YFinanceOpeningProvider(OpeningMarketProvider):
    """yfinance-backed provider. Delayed futures; labels itself as such."""

    name = "yfinance"

    def _quote(self, canonical: str, vendor: str) -> Quote:
        q = Quote(canonical=canonical, vendor_symbol=vendor, source=self.name)
        # One bounded retry: a single network timeout was dropping a whole index
        # (NQ=F, observed 2026-07-20) and a missing major future materially
        # changes the bias. The failure is still recorded if both attempts fail —
        # never silently treated as "no movement".
        info, last_err = None, None
        for attempt in (1, 2):
            try:
                import yfinance as yf
                info = yf.Ticker(vendor).info or {}
                break
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"[:160]
                if attempt == 1:
                    import time as _t
                    _t.sleep(1.5)
        if info is None:
            q.error = f"{last_err} (2 attempts)"
            return q
        px = info.get("regularMarketPrice") or info.get("last_price")
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
        ts = info.get("regularMarketTime")
        if px is None or prev in (None, 0):
            q.error = "provider returned no usable price/previous close"
            return q
        q.price, q.previous_close = float(px), float(prev)
        q.change_pct = round((q.price - q.previous_close) / q.previous_close * 100, 3)
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            q.quote_ts = dt.isoformat()
            q.age_sec = round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
            q.stale = q.age_sec > MAX_QUOTE_AGE_SEC
            q.delayed = q.age_sec > REALTIME_MAX_AGE_SEC
        else:
            # No timestamp means we cannot prove freshness -> treat as stale.
            q.stale = True
            q.error = "no quote timestamp — freshness unprovable"
        delay = info.get("exchangeDataDelayedBy")
        if delay:
            q.delayed = True
        return q

    def get_index_futures(self) -> dict:
        return {c: self._quote(c, v) for c, v in FUTURES_MAP.items()}

    def get_premarket_etfs(self) -> dict:
        return {c: self._quote(f"{c}_PROXY", v) for c, v in PROXY_MAP.items()}

    def get_cross_asset_context(self) -> dict:
        wanted = {"VIX": "^VIX", "US10Y": "^TNX", "US2Y": "^IRX",
                  "DOLLAR": "DX-Y.NYB", "CRUDE": "CL=F", "GOLD": "GC=F",
                  "BITCOIN": "BTC-USD"}
        return {k: self._quote(k, v) for k, v in wanted.items()}

    def health(self) -> dict:
        probe = self._quote("SP500_FUT", FUTURES_MAP["SP500_FUT"])
        if probe.error or probe.price is None:
            return {"ok": False, "state": SOURCE_UNAVAILABLE, "detail": probe.error}
        state = (TRUE_FUTURES_REALTIME
                 if (probe.age_sec is not None and probe.age_sec <= REALTIME_MAX_AGE_SEC
                     and not probe.delayed)
                 else TRUE_FUTURES_DELAYED)
        return {"ok": True, "state": state, "provider": self.name,
                "probe_age_sec": probe.age_sec, "delayed": probe.delayed}


def capability() -> str:
    """Classify what the environment can actually supply (§9)."""
    try:
        h = YFinanceOpeningProvider().health()
    except Exception:
        return SOURCE_UNAVAILABLE
    return h.get("state", SOURCE_UNAVAILABLE) if h.get("ok") else SOURCE_UNAVAILABLE


def _bias_from(changes: list) -> str:
    """Map average index change to a bias bucket. Evidence, not prediction."""
    if not changes:
        return DATA_INSUFFICIENT
    avg = sum(changes) / len(changes)
    if avg >= 0.60:
        return STRONG_HIGHER
    if avg >= 0.15:
        return HIGHER
    if avg <= -0.60:
        return STRONG_LOWER
    if avg <= -0.15:
        return LOWER
    return MIXED


def build_snapshot(provider: Optional[OpeningMarketProvider] = None,
                   now: Optional[datetime] = None) -> dict:
    """Assemble the opening-intelligence snapshot (§12). Never fabricates."""
    p = provider or YFinanceOpeningProvider()
    n = now or datetime.now(timezone.utc)
    session = market_session(n)
    evidence, conflicts, stale_fields, limitations = [], [], [], []

    futures = {k: v for k, v in (p.get_index_futures() or {}).items()}
    etfs = p.get_premarket_etfs() or {}
    cross = p.get_cross_asset_context() or {}

    for name, q in list(futures.items()) + list(etfs.items()) + list(cross.items()):
        if q.stale or q.error:
            stale_fields.append(f"{name}: {q.error or f'stale {q.age_sec}s'}")

    fut_ok = {k: q for k, q in futures.items() if q.usable}
    etf_ok = {k: q for k, q in etfs.items() if q.usable}

    prov_state = capability()
    if fut_ok:
        source_kind = "TRUE_FUTURES"
    elif etf_ok and session in ("premarket", "regular"):
        source_kind = "ETF_PREMARKET_PROXY"
        limitations.append("ETF PREMARKET PROXY — NOT FUTURES")
    else:
        source_kind = "NONE"

    # §10: never present the prior close as an overnight move.
    if source_kind == "NONE":
        bias, coverage = DATA_INSUFFICIENT, LOW_COVERAGE
        limitations.append(
            "No usable futures and no valid ETF premarket quote for this session — "
            "prior close is NOT presented as an overnight move.")
    else:
        primary = fut_ok if fut_ok else etf_ok
        bias = _bias_from([q.change_pct for q in primary.values()])
        for k, q in primary.items():
            evidence.append(f"{k} {q.change_pct:+.2f}% ({q.vendor_symbol}, "
                            f"{'delayed' if q.delayed else 'realtime'})")
        # confirmation / conflict between futures and their ETF proxies
        if fut_ok and etf_ok:
            for k, fq in fut_ok.items():
                eq = etf_ok.get(f"{k}_PROXY") or etf_ok.get(k)
                if eq and eq.usable and (fq.change_pct > 0) != (eq.change_pct > 0):
                    conflicts.append(
                        f"{k} {fq.change_pct:+.2f}% vs proxy {eq.change_pct:+.2f}%")
        vix = cross.get("VIX")
        if vix and vix.usable:
            evidence.append(f"VIX {vix.change_pct:+.2f}%")
            up = bias in (HIGHER, STRONG_HIGHER)
            if up and vix.change_pct > 1.0:
                conflicts.append("higher-open bias with VIX up — risk appetite not confirmed")

        n_sources = len(fut_ok) + (1 if etf_ok else 0) + (1 if vix and vix.usable else 0)
        if conflicts:
            coverage = CONFLICTED
        elif source_kind == "TRUE_FUTURES" and n_sources >= 4 and not stale_fields:
            coverage = HIGH_COVERAGE
        elif source_kind == "TRUE_FUTURES":
            coverage = MEDIUM_COVERAGE
        else:
            coverage = LOW_COVERAGE

    if prov_state == TRUE_FUTURES_DELAYED:
        limitations.append("Futures quotes are DELAYED (~10 min) — not realtime.")
    limitations.append("Advisory context only. A bias is not a guaranteed open; "
                       "revalidate at 09:30 ET.")

    return {
        "captured_at": n.astimezone(timezone.utc).isoformat(),
        "market_date": n.astimezone(ET).date().isoformat(),
        "session": session,
        "provider_state": prov_state,
        "source_kind": source_kind,
        "futures": {k: asdict(v) for k, v in futures.items()},
        "premarket_etfs": {k: asdict(v) for k, v in etfs.items()},
        "cross_asset": {k: asdict(v) for k, v in cross.items()},
        "opening_bias": bias,
        "confidence_state": coverage,
        "evidence": evidence,
        "conflicts": conflicts,
        "stale_fields": stale_fields,
        "limitations": limitations,
        "execution_authority": False,
    }


def persist(snap: dict) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    day = SNAPSHOT_DIR / f"{snap['market_date']}.jsonl"
    with day.open("a") as fh:
        fh.write(json.dumps(snap, default=str) + "\n")
    (SNAPSHOT_DIR / "latest.json").write_text(json.dumps(snap, indent=1, default=str))
    return day


def render_opening_read(snap: dict) -> str:
    """Telegram / Aegis text (§17). States evidence and its limits, never a call."""
    et = datetime.fromisoformat(snap["captured_at"]).astimezone(ET)
    head = f"🌐 OPENING READ · {et:%H:%M} ET\n{snap['opening_bias']} · {snap['confidence_state']}"
    if snap["source_kind"] == "ETF_PREMARKET_PROXY":
        head += "\nETF PREMARKET PROXY — TRUE FUTURES SOURCE UNAVAILABLE"
    if snap["opening_bias"] == DATA_INSUFFICIENT:
        return head + "\nOPENING BIAS: DATA INSUFFICIENT — no usable overnight source."
    lines = [head, ""]
    lines += ["· " + e for e in snap["evidence"][:6]]
    if snap["conflicts"]:
        lines += ["", "Conflicts:"] + ["· " + c for c in snap["conflicts"][:3]]
    lines += ["", "Read: evidence synthesis only — not a prediction of the cash open.",
              "Revalidate at 09:30 ET."]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Opening intelligence (advisory only)")
    ap.add_argument("--capability", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--persist", action="store_true")
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    if a.capability:
        print(json.dumps(YFinanceOpeningProvider().health(), indent=1, default=str))
    else:
        s = build_snapshot()
        if a.persist:
            print("persisted:", persist(s))
        if a.render:
            print(render_opening_read(s))
        if a.snapshot or not (a.persist or a.render):
            print(json.dumps(s, indent=1, default=str)[:2500])
