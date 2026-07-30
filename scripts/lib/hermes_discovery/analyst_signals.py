"""Universal Research Discovery Layer — analyst-signal discovery.

Turns *current analyst ratings* into discovery candidates: per-symbol rating
changes, price-target moves and new-coverage initiations become
TICKER_CANDIDATE rows, and a per-sector roll-up of qualifying moves becomes a
TREND_CANDIDATE — so analyst activity can drive sector/theme discovery, not
just per-name scoring.

Primary input: yahoo_analyst_targets_history (recommendation_mean,
target_mean_price, number_of_analyst_opinions) — each symbol's latest snapshot
compared to its immediately-prior snapshot within the lookback window.
symbol_profiles.sector supplies the sector roll-up attribution.

HARD RULES (mirrors entity_spikes.py — tested):
  * candidates ONLY — safe_action_level=OPERATOR_REVIEW_REQUIRED, never
    promotes, never transitions status, never auto-adds to a watchlist, never
    touches trading thresholds or execution (no broker/execution/promotion
    imports anywhere in this module);
  * shadow-first: when analyst_signal_enabled is false in the schedule config
    the pass computes + reports but writes NOTHING (effective dry-run) — an
    operator flips the flag to go live;
  * dedupe against existing candidates is free from upsert idempotency
    (unique candidate_type + normalized_key → seen_count bump + evidence merge);
  * sector roll-ups whose key is already covered by an active watch_directive
    are skipped (reuses entity_spikes.covered_keys).

All DB reads go through this module's _execute wrapper (one statement per call,
db_adapter under the hood) so tests can monkeypatch it with synthetic rows and
the 120s idle-in-transaction guard can never bite.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains, entity_spikes, inbox

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_CONFIG_PATH = Path(os.getenv("HERMES_DISCOVERY_SCHEDULE_JSON")
                            or PROJECT_ROOT / "config" / "hermes_discovery_schedule.json")

PRODUCER = "analyst_signal_discovery"
ACTOR = "discovery:analyst_signal"
LANE = "analyst_signal"

LOOKBACK_DAYS = 21         # window in which "latest vs prior snapshot" is compared
SCAN_LIMIT = 1500          # max symbols pulled from the history table
SIGNAL_TTL_DAYS = 21       # analyst moves go stale on the same horizon we grade on
MAG_FULL_SCALE = 3.0       # combined-magnitude at/above this → analyst_momentum 1.0

# Yahoo recommendation_mean is a 1(Strong Buy)..5(Sell) scale: a DROP is an
# upgrade. Everything downstream reads `direction` ("bullish"/"bearish"), never
# the raw sign, so the scale convention stays isolated to compute_signals.


# ── plumbing ─────────────────────────────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute
    (one statement per call, immediate commit)."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _table_exists(table: str) -> bool:
    try:
        return bool(_execute(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = %s",
            (table,), fetch="one"))
    except Exception:
        return False


def load_analyst_config(path: Path | str | None = None) -> dict[str, Any]:
    """Thresholds from config/hermes_discovery_schedule.json with safe defaults.
    A broken config falls back to conservative defaults (higher bar, never a
    wider intake)."""
    p = Path(path) if path else SCHEDULE_CONFIG_PATH
    cfg: dict[str, Any] = {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}

    def _f(key: str, default: float) -> float:
        try:
            return max(0.0, float(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _i(key: str, default: int) -> int:
        try:
            return max(1, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "analyst_signal_enabled": bool(cfg.get("analyst_signal_enabled", False)),
        "analyst_new_coverage_enabled": bool(cfg.get("analyst_new_coverage_enabled", True)),
        "analyst_rating_delta_min": _f("analyst_rating_delta_min", 0.5),
        "analyst_target_move_pct_min": _f("analyst_target_move_pct_min", 10.0),
        "analyst_min_opinions": _i("analyst_min_opinions", 3),
        "analyst_signal_min_symbols_per_sector": _i("analyst_signal_min_symbols_per_sector", 3),
        "max_candidates_per_run": _i("max_candidates_per_run", 25),
        "lookback_days": _i("analyst_lookback_days", LOOKBACK_DAYS),
    }


# ── input collectors (defensive; missing table → [] + note) ─────────────────

def collect_analyst_snapshots(lookback_days: int = LOOKBACK_DAYS,
                              notes: list[str] | None = None) -> list[dict[str, Any]]:
    """Each symbol's latest snapshot + its immediately-prior snapshot within the
    lookback window, from yahoo_analyst_targets_history. prev_* is NULL when the
    symbol has only one snapshot in the window (new-coverage candidate)."""
    if not _table_exists("yahoo_analyst_targets_history"):
        if notes is not None:
            notes.append("yahoo_analyst_targets_history missing — analyst stream skipped")
        return []
    d = max(1, int(lookback_days))
    return _rows(
        f"""WITH ranked AS (
                SELECT symbol, snapshot_date,
                       recommendation_mean, target_mean_price, current_price,
                       number_of_analyst_opinions,
                       row_number() OVER (PARTITION BY symbol
                                          ORDER BY snapshot_date DESC) AS rn
                FROM yahoo_analyst_targets_history
                WHERE snapshot_date > (CURRENT_DATE - {d})
                  AND symbol IS NOT NULL
             )
             SELECT cur.symbol,
                    cur.snapshot_date       AS cur_date,
                    prev.snapshot_date      AS prev_date,
                    cur.recommendation_mean AS cur_rec,
                    prev.recommendation_mean AS prev_rec,
                    cur.target_mean_price   AS cur_tgt,
                    prev.target_mean_price  AS prev_tgt,
                    cur.current_price       AS cur_px,
                    cur.number_of_analyst_opinions  AS cur_n,
                    prev.number_of_analyst_opinions AS prev_n
             FROM ranked cur
             LEFT JOIN ranked prev
               ON prev.symbol = cur.symbol AND prev.rn = 2
             WHERE cur.rn = 1
             ORDER BY cur.symbol
             LIMIT %s""", (SCAN_LIMIT,))


def sector_map(symbols: list[str], notes: list[str] | None = None) -> dict[str, str]:
    """symbol → sector from symbol_profiles (covered taxonomy). Symbols with no
    profile / null sector are omitted; callers treat them as 'unclassified'."""
    out: dict[str, str] = {}
    syms = sorted({str(s).upper() for s in symbols if s})
    if not syms or not _table_exists("symbol_profiles"):
        return out
    try:
        for r in _rows(
            "SELECT UPPER(symbol) AS symbol, sector FROM symbol_profiles "
            "WHERE UPPER(symbol) = ANY(%s) AND sector IS NOT NULL AND sector <> ''",
                (syms,)):
            out[str(r["symbol"])] = str(r["sector"]).strip()
    except Exception as e:  # pragma: no cover - defensive
        if notes is not None:
            notes.append(f"symbol_profiles sector map unavailable: {e}")
    return out


# ── pure detection core (unit-testable without a DB) ─────────────────────────

def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_signals(rows: list[dict[str, Any]], *,
                    rating_delta_min: float,
                    target_move_pct_min: float,
                    min_opinions: int,
                    new_coverage_enabled: bool,
                    skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Apply rating-change / target-move / new-coverage gates to per-symbol
    latest-vs-prior snapshot rows. Returns one signal dict per qualifying
    symbol (carrying every event it fired), sorted by magnitude desc."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    out: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym:
            _skip("empty_symbol")
            continue
        cur_n = int(r.get("cur_n") or 0)
        if cur_n < max(1, int(min_opinions)):
            _skip("low_coverage")
            continue

        cur_rec, prev_rec = _num(r.get("cur_rec")), _num(r.get("prev_rec"))
        cur_tgt, prev_tgt = _num(r.get("cur_tgt")), _num(r.get("prev_tgt"))
        prev_date = r.get("prev_date")
        events: list[dict[str, Any]] = []
        magnitude = 0.0
        bullish = 0
        bearish = 0

        # new coverage: no prior snapshot in the window (first-in-window)
        if prev_date is None:
            if new_coverage_enabled:
                direction = ("bullish" if (cur_rec is not None and cur_rec <= 2.5)
                             else "bearish" if (cur_rec is not None and cur_rec >= 3.5)
                             else "neutral")
                events.append({"type": "NEW_COVERAGE", "direction": direction,
                               "analysts": cur_n, "rec_mean": cur_rec})
                magnitude += 1.0
                bullish += direction == "bullish"
                bearish += direction == "bearish"
            else:
                _skip("new_coverage_disabled")
        else:
            # rating change (recommendation_mean; DROP = upgrade on the 1..5 scale)
            if cur_rec is not None and prev_rec is not None:
                delta = cur_rec - prev_rec
                if abs(delta) >= float(rating_delta_min):
                    direction = "bullish" if delta < 0 else "bearish"
                    events.append({"type": "RATING_CHANGE", "direction": direction,
                                   "from": round(prev_rec, 3), "to": round(cur_rec, 3),
                                   "delta": round(delta, 3)})
                    magnitude += abs(delta)
                    bullish += direction == "bullish"
                    bearish += direction == "bearish"
            # target-mean move
            if cur_tgt is not None and prev_tgt is not None and prev_tgt > 0:
                pct = (cur_tgt - prev_tgt) / prev_tgt * 100.0
                if abs(pct) >= float(target_move_pct_min):
                    direction = "bullish" if pct > 0 else "bearish"
                    events.append({"type": "TARGET_MOVE", "direction": direction,
                                   "from": round(prev_tgt, 2), "to": round(cur_tgt, 2),
                                   "pct": round(pct, 2)})
                    magnitude += abs(pct) / 10.0  # 10% target move ≈ 1.0 magnitude unit
                    bullish += direction == "bullish"
                    bearish += direction == "bearish"

        if not events:
            _skip("no_material_move")
            continue

        direction = ("bullish" if bullish > bearish
                     else "bearish" if bearish > bullish else "mixed")
        out.append({
            "symbol": sym,
            "events": events,
            "direction": direction,
            "magnitude": round(magnitude, 4),
            "analysts": cur_n,
            "cur_rec": cur_rec,
            "cur_tgt": cur_tgt,
            "cur_px": _num(r.get("cur_px")),
            "cur_date": str(r.get("cur_date") or ""),
            "prev_date": str(prev_date or ""),
        })
    out.sort(key=lambda s: (-s["magnitude"], s["symbol"]))
    return out


def momentum_signal(magnitude: float) -> float:
    """Combined move magnitude → 0..1 analyst_momentum signal, hard-clamped."""
    return round(min(1.0, max(0.0, float(magnitude)) / MAG_FULL_SCALE), 4)


def _event_phrase(sig: dict[str, Any]) -> str:
    parts = []
    for e in sig["events"]:
        if e["type"] == "RATING_CHANGE":
            parts.append(f"rating {e['from']}→{e['to']}")
        elif e["type"] == "TARGET_MOVE":
            parts.append(f"target {e['pct']:+.1f}%")
        elif e["type"] == "NEW_COVERAGE":
            parts.append(f"new coverage ({e['analysts']} analysts)")
    return ", ".join(parts)


# ── payload builders ─────────────────────────────────────────────────────────

def build_ticker_payloads(signals: list[dict[str, Any]], *,
                          sectors: dict[str, str],
                          limit: int,
                          skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """One TICKER_CANDIDATE per qualifying symbol. Label is the BARE symbol —
    the inbox validates TICKER_CANDIDATE labels via validate_ticker(label), so a
    descriptive label fails the ticker-shape check and lands every candidate in
    NEEDS_VALIDATION. Bare symbol is also naturally stable per name (re-sightings
    bump seen_count); the changing detail lives in summary + evidence + meta."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    payloads: list[dict[str, Any]] = []
    for sig in signals:
        if len(payloads) >= max(1, int(limit)):
            _skip("run_cap")
            continue
        sym = sig["symbol"]
        sector = sectors.get(sym)
        label = sym
        summary = (f"{sym}: {_event_phrase(sig)} "
                   f"({sig['direction']}, {sig['analysts']} analysts)"
                   f"{f' — {sector}' if sector else ''}")[:300]
        payloads.append(dict(
            candidate_type="TICKER_CANDIDATE",
            label=label,
            summary=summary,
            evidence=[{"source_domain": "yahoo_analyst_targets_history",
                       "note": _event_phrase(sig),
                       "as_of": sig["cur_date"]}],
            seed_symbols=[sym],
            meta={
                "producer": PRODUCER,
                "lane": LANE,
                "sector": sector,
                "direction": sig["direction"],
                "events": sig["events"],
                "analysts": sig["analysts"],
                "as_of": sig["cur_date"],
                "prior_as_of": sig["prev_date"],
            },
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=SIGNAL_TTL_DAYS,
            signals={"analyst_momentum": momentum_signal(sig["magnitude"])},
        ))
    return payloads


def build_sector_payloads(signals: list[dict[str, Any]], *,
                          sectors: dict[str, str],
                          min_symbols: int,
                          covered: set[str],
                          skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Roll qualifying symbols up by (sector, direction) → TREND_CANDIDATE when
    at least `min_symbols` names move the same way — this is what lets analyst
    ratings drive *sector* discovery. Sectors already covered by an active
    watch_directive are skipped."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sig in signals:
        sector = sectors.get(sig["symbol"])
        if not sector or sig["direction"] not in ("bullish", "bearish"):
            continue
        buckets.setdefault((sector, sig["direction"]), []).append(sig)

    payloads: list[dict[str, Any]] = []
    for (sector, direction), members in sorted(
            buckets.items(), key=lambda kv: -len(kv[1])):
        if len(members) < max(2, int(min_symbols)):
            _skip("sector_below_min_symbols")
            continue
        word = "tailwind" if direction == "bullish" else "pressure"
        label = f"{sector} sector analyst {word}"
        key = dedupe.normalize_key(label)
        if key and key in covered:
            _skip("covered_by_directive")
            continue
        syms = [m["symbol"] for m in members]
        avg_mag = sum(m["magnitude"] for m in members) / len(members)
        payloads.append(dict(
            candidate_type="TREND_CANDIDATE",
            label=label,
            summary=(f"{len(members)} {sector} names with {direction} analyst moves: "
                     f"{', '.join(syms[:8])}")[:300],
            evidence=[{"source_domain": "yahoo_analyst_targets_history",
                       "note": f"{m['symbol']}: {_event_phrase(m)}"}
                      for m in members[:10]],
            seed_symbols=syms[:12],
            meta={
                "producer": PRODUCER,
                "lane": LANE,
                "sector": sector,
                "direction": direction,
                "n_symbols": len(members),
                "symbols": syms[:20],
            },
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=SIGNAL_TTL_DAYS,
            signals={"trend_momentum": momentum_signal(avg_mag)},
        ))
    return payloads


def _payload_domain(payload: dict[str, Any]) -> str:
    try:
        return domains.classify_domain({
            "candidate_type": payload["candidate_type"],
            "label": payload["label"],
            "summary": payload.get("summary"),
            "meta": payload.get("meta") or {},
            "evidence": payload.get("evidence") or [],
        })
    except Exception:
        return "unclassified"


# ── run entry point ──────────────────────────────────────────────────────────

def run_discovery(*, dry_run: bool = False, limit: int | None = None,
                  config_path: Path | str | None = None) -> dict[str, Any]:
    """Full analyst-signal pass. Returns the JSON run report; live writes go
    exclusively through inbox.upsert_candidate. Shadow-first: when the schedule
    config has analyst_signal_enabled=false the pass is forced to effective
    dry-run (computes + reports, writes nothing)."""
    cfg = load_analyst_config(config_path)
    notes: list[str] = []
    skipped: dict[str, int] = {}

    effective_dry = bool(dry_run) or not cfg["analyst_signal_enabled"]
    if effective_dry and not dry_run:
        notes.append("analyst_signal_enabled=false — computed only, no writes "
                     "(operator flips the flag to go live)")

    snapshots = collect_analyst_snapshots(cfg["lookback_days"], notes)
    signals = compute_signals(
        snapshots,
        rating_delta_min=cfg["analyst_rating_delta_min"],
        target_move_pct_min=cfg["analyst_target_move_pct_min"],
        min_opinions=cfg["analyst_min_opinions"],
        new_coverage_enabled=cfg["analyst_new_coverage_enabled"],
        skipped=skipped)

    sectors = sector_map([s["symbol"] for s in signals], notes)
    run_cap = int(limit) if limit else cfg["max_candidates_per_run"]
    ticker_payloads = build_ticker_payloads(
        signals, sectors=sectors, limit=run_cap, skipped=skipped)
    sector_payloads = build_sector_payloads(
        signals, sectors=sectors,
        min_symbols=cfg["analyst_signal_min_symbols_per_sector"],
        covered=entity_spikes.covered_keys(notes), skipped=skipped)
    payloads = ticker_payloads + sector_payloads

    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        domain = _payload_domain(p)
        by_type[p["candidate_type"]] = by_type.get(p["candidate_type"], 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "domain": domain, "lane": LANE,
                   "direction": p["meta"].get("direction"),
                   "signals": p["signals"]}
        if not effective_dry:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({"id": row.get("id"), "status": row.get("status"),
                            "seen_count": row.get("seen_count")})
            upserted += 1
        candidates.append(summary)

    return {
        "mode": "analyst_signals",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "effective_dry_run": effective_dry,
        "enabled_in_schedule": cfg["analyst_signal_enabled"],
        "thresholds": {
            "lookback_days": cfg["lookback_days"],
            "analyst_rating_delta_min": cfg["analyst_rating_delta_min"],
            "analyst_target_move_pct_min": cfg["analyst_target_move_pct_min"],
            "analyst_min_opinions": cfg["analyst_min_opinions"],
            "analyst_signal_min_symbols_per_sector":
                cfg["analyst_signal_min_symbols_per_sector"],
        },
        "scanned_symbols": len(snapshots),
        "signals_detected": len(signals),
        "upserted": upserted,
        "would_upsert": len(candidates) if effective_dry else None,
        "by_type": by_type,
        "by_domain": by_domain,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    }
