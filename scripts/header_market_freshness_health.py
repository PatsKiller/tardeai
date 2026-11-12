#!/usr/bin/env python3
"""header-market-freshness-health — the header REGIME / VIX contracts (LQ-20261107-1610, CC v3 audit A4).

PROCESS   n8n lane ``header-market-freshness-health``, hourly, LaneRunReceipt@v2 under --apply. Reads, read-only:
          the served header projection (``data/runtime/trade_ai_cache.json``, what /api/v2/trade-ai serves), the
          CIO card's regime (``cio_truth.regime_for``), the one headline VIX (``lib.vix_headline``) and the regime
          envelope (``data_broker.market_regime.get_market_regime``).
CONTRACT  two contracts, each OK / DEGRADED / BROKEN / UNVERIFIABLE; the run verdict is the worst of the two.
          vix     OK           the header and the card both serve the headline: same admissible source (Schwab $VIX
                               or FRED VIXCLS), same value, same observation time, and it is FRESH against the
                               session rule -- inside the VIX printing window (config/market_regime_vix_complex.yaml)
                               that is the minute line; outside it the newest print Cboe publishes is the last
                               settlement, and the settlement print itself is FRESH (LQ-20261107-2600: the source
                               stops at 16:15 ET, so its evening age is expected, not a stall)
                  DEGRADED     the headline is STALE or UNDATED: inside the printing window no admissible print
                               within the line, or outside it a print that PREDATES the last settlement (a missed
                               settle write) -- the number is shown grey with its age -- or the header cache is
                               older than the newest print (lag)
                  BROKEN       no admissible VIX at all; the header or the card serves another source (the scanner
                               run's Yahoo-first VIX, an unfiltered regime row, a banned feed); or the header and the
                               card disagree on value or observation time (one VIX shown twice as two numbers)
                  UNVERIFIABLE the served header projection is missing or unreadable, or the DB read failed
          regime  OK           the newest classifier snapshot is within its envelope's stale_after_hours
                  DEGRADED     it is past that line (the tile keeps the label, grey, with its age)
                  BROKEN       no snapshot, or a snapshot with no clock (the tile cannot say how old it is)
                  UNVERIFIABLE the DB read failed
HEAL      none automatic. One ``system_health`` warning per contract per ESCALATION_COOLDOWN_H when it is BROKEN,
          under --apply, 0 sends. It may NOT write a VIX, fetch from a provider, re-run the classifier, re-warm or
          edit a cache: the producers are the Schwab off-hours lane, the FRED lane, the classifier and warm_caches.

Dry run is the default (reads only, nothing written, nothing escalated). MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "header-market-freshness-health"
ESCALATION_SOURCE = "header_market_freshness_health.py"
ESCALATION_COOLDOWN_H = 24
# The admissible sources, by the exact ``vix_source`` string the headline carries (``vix_complex`` writes
# ``<store>:<feed>:<symbol>``). ``market_quotes:schwab:$VIX`` is the continuous Schwab index-quote lane's row
# (vix-index-quotes-schwab, LQ-20261107-1669); from LQ-20261107-1856 it is live and its print is the newest admissible
# one for most of the day -- without it here, a fresh continuous print would read BROKEN header_source_inadmissible.
ADMISSIBLE_VIX_SOURCES = ("market_quotes_extended:schwab:$VIX", "market_quotes:schwab:$VIX",
                          "fred_economic_series:VIXCLS")
RANK = {"OK": 0, "UNVERIFIABLE": 1, "DEGRADED": 2, "BROKEN": 3}
VALUE_TOL = 0.005


def _ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _same_instant(a: Any, b: Any) -> bool:
    ta, tb = _ts(a), _ts(b)
    return ta is not None and tb is not None and abs((ta - tb).total_seconds()) < 1


def _same_value(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= VALUE_TOL
    except (TypeError, ValueError):
        return False


def _surface(view: Optional[Mapping[str, Any]], *, value_key: str, time_key: str) -> dict:
    view = view or {}
    return {"vix": view.get(value_key), "source": view.get("vix_source"), "as_of": view.get(time_key)}


def vix_contract(*, headline: Mapping[str, Any], header: Optional[Mapping[str, Any]],
                 card: Optional[Mapping[str, Any]], header_written_at: Optional[datetime] = None) -> dict:
    """Judge the header tile and the CIO card against the one headline VIX. Pure; no I/O."""
    h = {"vix": headline.get("vix"), "source": headline.get("vix_source"),
         "as_of": headline.get("vix_observation_time"), "state": headline.get("vix_state"),
         "age_hours": headline.get("vix_age_hours"), "stale_after_hours": headline.get("vix_stale_after_hours"),
         "rule": headline.get("vix_fresh_rule"), "expected_print": headline.get("vix_expected_print")}
    out = {"headline": h, "header": None, "card": None}
    if header is None:
        return {**out, "verdict": "UNVERIFIABLE", "reason": "served header projection missing or unreadable"}
    hd = _surface(header, value_key="vix", time_key="vix_observation_time")
    cd = _surface(card, value_key="vix", time_key="vix_as_of") if card is not None else None
    out.update(header=hd, card=cd)
    if h["vix"] is None:
        reason = str(headline.get("vix_reason") or "no admissible VIX")
        if "read failed" in reason or "config" in reason:
            return {**out, "verdict": "UNVERIFIABLE", "reason": reason}
        return {**out, "verdict": "BROKEN", "reason": f"no_admissible_vix: {reason}"}
    for name, s in (("header", hd), ("card", cd)):
        if s is None:
            continue
        if s["vix"] is not None and s["source"] not in ADMISSIBLE_VIX_SOURCES:
            return {**out, "verdict": "BROKEN", "reason": f"{name}_source_inadmissible:{s['source']}"}
    if cd is not None and (not _same_value(cd["vix"], h["vix"]) or not _same_instant(cd["as_of"], h["as_of"])):
        return {**out, "verdict": "BROKEN", "reason": "card_disagrees_with_headline"}
    if not _same_value(hd["vix"], h["vix"]) or not _same_instant(hd["as_of"], h["as_of"]):
        # A header cache written before the newest print is lag (warm_caches has not run since), not a second source.
        h_obs, hd_obs = _ts(h["as_of"]), _ts(hd["as_of"])
        if (header_written_at is not None and h_obs is not None and header_written_at < h_obs
                and (hd_obs is None or hd_obs <= h_obs)):
            return {**out, "verdict": "DEGRADED", "reason": "header_cache_older_than_newest_print"}
        return {**out, "verdict": "BROKEN", "reason": "header_disagrees_with_headline"}
    if h["state"] != "FRESH":
        return {**out, "verdict": "DEGRADED",
                "reason": f"vix_{str(h['state']).lower()}: {headline.get('vix_reason') or 'not current'}"}
    return {**out, "verdict": "OK", "reason": None}


def regime_contract(envelope: Optional[Mapping[str, Any]]) -> dict:
    """Judge the regime tile's clock from the /risk-regime/latest read envelope. Pure; no I/O."""
    if envelope is None:
        return {"verdict": "UNVERIFIABLE", "reason": "regime read failed"}
    clock = {k: envelope.get(k) for k in ("as_of", "age_hours", "stale", "stale_after_hours")}
    if not envelope.get("regime"):
        return {**clock, "verdict": "BROKEN", "reason": "no classifier snapshot"}
    if not clock["as_of"] or clock["age_hours"] is None:
        return {**clock, "verdict": "BROKEN", "reason": "regime_clock_not_reported"}
    if clock["stale"]:
        return {**clock, "verdict": "DEGRADED",
                "reason": f"regime {float(clock['age_hours']):.1f} h old, past {clock['stale_after_hours']} h"}
    return {**clock, "verdict": "OK", "reason": None}


def state_root() -> Path:
    if os.environ.get("TRADEAI_STATE_ROOT"):
        return Path(os.environ["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore  # noqa: PLC0415
        return Path(production_state_root())
    except Exception:  # noqa: BLE001 — the documented default
        return Path.home() / "trade-ai-releases" / "persistent-state"


def read_header(root: Path) -> tuple[Optional[dict], Optional[datetime]]:
    path = root / "data" / "runtime" / "trade_ai_cache.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError):
        return None, None
    return (doc if isinstance(doc, dict) else None), written


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415

    kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"), "user": os.getenv("DB_USER", "johnclaw"),
                              "host": os.getenv("DB_HOST", "/var/run/postgresql"), "connect_timeout": 10}
    if read_only:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg2.connect(**kwargs)


def _db_query_for(conn) -> Callable[..., Any]:
    from psycopg2.extras import RealDictCursor  # noqa: PLC0415

    def q(sql, params=None, fetch="all"):
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            return cur.fetchall()
    return q


def _recently_escalated(conn, contract: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM alert_events WHERE source_script = %s AND alert_type = 'system_health' "
                    "AND parsed_payload->>'contract' = %s AND created_at > now() - make_interval(hours => %s) LIMIT 1",
                    (ESCALATION_SOURCE, contract, ESCALATION_COOLDOWN_H))
        return cur.fetchone() is not None


def _escalate_default(contract: str, result: Mapping[str, Any]) -> bool:
    from alert_event_writer import save_alert_event  # noqa: PLC0415

    return save_alert_event(
        alert_type="system_health", severity="warning", source_script=ESCALATION_SOURCE,
        raw_text=f"[{LANE_ID}] header {contract} contract BROKEN: {result.get('reason')}",
        parsed_payload={"kind": "header_market_contract", "contract": contract, "reason": result.get("reason")},
    ) is not None


def run(*, root: Path, apply: bool, conn=None, now: Optional[datetime] = None,
        escalate: Callable[[str, Mapping[str, Any]], bool] = _escalate_default) -> dict:
    now = now or datetime.now(timezone.utc)
    started = datetime.now(timezone.utc).isoformat()
    header, written = read_header(root)
    own = conn is None
    escalated: list[str] = []
    suppressed: list[str] = []
    try:
        if own:
            conn = _connect(read_only=not apply)
        q = _db_query_for(conn)
        from lib.vix_headline import vix_headline  # noqa: PLC0415
        from lib import cio_truth  # noqa: PLC0415
        from lib.data_broker.market_regime import get_market_regime  # noqa: PLC0415

        headline = vix_headline(db_query=q, now=now)
        conn.rollback()
        try:
            envelope = get_market_regime(q, history=1, now=now)
            card = cio_truth.regime_for(db_query=q, projection=envelope, now=now)
        except Exception as exc:  # noqa: BLE001 — named, graded UNVERIFIABLE
            envelope, card = None, None
            headline = {**headline, "regime_read_error": type(exc).__name__}
        conn.rollback()
        contracts = {"vix": vix_contract(headline=headline, header=header, card=card, header_written_at=written),
                     "regime": regime_contract(envelope)}
        if apply:
            for name, res in contracts.items():
                if res["verdict"] != "BROKEN":
                    continue
                if _recently_escalated(conn, name):
                    suppressed.append(name)
                elif escalate(name, res):
                    escalated.append(name)
            conn.commit()
    finally:
        if own and conn is not None:
            conn.close()
    verdict = max((c["verdict"] for c in contracts.values()), key=RANK.__getitem__)
    return {"lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started, "verdict": verdict,
            "broken": sum(c["verdict"] == "BROKEN" for c in contracts.values()), "contracts": contracts,
            "header_cache_written_at": written.isoformat() if written else None, "escalated": escalated,
            "escalation_suppressed_cooldown": suppressed, "sends": 0}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="escalate a BROKEN contract and write the receipt")
    ap.add_argument("--root", help="state root (default: the production state root)")
    a = ap.parse_args(argv)
    summary = run(root=Path(a.root) if a.root else state_root(), apply=a.apply)
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    if a.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415
        except ImportError:
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore[no-redef]  # noqa: PLC0415
        write_lane_receipt(
            LANE_ID, ok=True, exit_code=0, started_at=summary["started_at"], script=__file__,
            summary={"verdict": summary["verdict"], "broken": summary["broken"], "escalated": summary["escalated"],
                     "contracts": {k: v["verdict"] for k, v in summary["contracts"].items()},
                     "reasons": {k: v.get("reason") for k, v in summary["contracts"].items()}},
            produced_count=len(summary["contracts"]), attempted_count=len(summary["contracts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
