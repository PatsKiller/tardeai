#!/usr/bin/env python3
"""Detached worker for bounded independent review of a validated Watch ticket.

The worker never constructs mechanics and never calls a model before mandatory
deterministic validation and quality admission complete. It persists critic
artifacts and deterministic reconciliation only; no proposal, broker, approval,
paid-lane or 2FA action is available here.
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))


def _facts_from_packet(symbol: str, packet: dict, validation: dict, conn, svc) -> dict:
    snapshot = packet.get("current_input_snapshot") or packet.get("input_snapshot") or {}
    market = snapshot.get("market") or {}
    fundamentals = svc._fundamentals_for(symbol) or {}
    quality_facts = (validation.get("quality_admission") or {}).get("facts_used") or {}
    price = packet.get("current_price") or market.get("price") or packet.get("price_used")
    atr = None
    atr_pct = quality_facts.get("atr_pct")
    if atr_pct is not None and price:
        try:
            atr = float(price) * float(atr_pct) / 100.0
        except (TypeError, ValueError):
            atr = None

    facts = {
        "symbol": symbol,
        "live_price": packet.get("current_price") or market.get("price"),
        "enriched_price": packet.get("price_used"),
        "live_price_as_of": packet.get("facts_as_of") or market.get("price_as_of"),
        "enriched_at": market.get("technical_as_of"),
        "atr": atr,
        "rvol": market.get("rvol"),
        "float_m": quality_facts.get("float_m"),
        "fundamentals": fundamentals,
        "technical_state": packet.get("technical_state") or {},
        "deterministic_thesis": packet.get("deterministic_thesis") or {},
        "data_quality": packet.get("data_quality") or {},
        "events": packet.get("event_state") or snapshot.get("events") or {},
        "support": packet.get("support") or [],
        "resistance": packet.get("resistance") or [],
    }

    try:
        cur = conn.cursor()
        cur.execute("""SELECT rvol, float_m, last_enriched_at
                       FROM watchlist_items WHERE upper(symbol)=%s
                       ORDER BY last_enriched_at DESC NULLS LAST LIMIT 1""",
                    (symbol,))
        row = cur.fetchone()
        if row:
            if row[0] is not None:
                facts["rvol"] = float(row[0])
            if row[1] is not None:
                facts["float_m"] = float(row[1])
            if row[2] is not None:
                facts["enriched_at"] = str(row[2])
        cur.execute("""SELECT headline, published_at, catalyst_type
                       FROM catalyst_events WHERE upper(symbol)=%s
                         AND published_at > now() - interval '30 days'
                       ORDER BY published_at DESC LIMIT 3""", (symbol,))
        facts["catalysts"] = [
            {"headline": headline, "published_at": str(published_at), "type": kind}
            for headline, published_at, kind in cur.fetchall()
        ]
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        facts["evidence_read_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return facts


def _persist(packet_id, prior: dict, reviews: dict, reconciled: dict,
             validation_source: str | None):
    import watch_decision_refresh as refresh
    merged = {**(prior.get("reviews") or {}), **reviews}
    ticket_review = {
        **prior,
        "reviews": merged,
        "reconciled": reconciled,
        "validation_source": validation_source,
    }
    conn = refresh._conn()
    cur = conn.cursor()
    cur.execute("""UPDATE decision_packets
                   SET packet = jsonb_set(packet, '{ticket_review}', %s::jsonb)
                   WHERE packet_id=%s""",
                (json.dumps(ticket_review, default=str), packet_id))
    conn.commit()
    return merged


def main(symbol: str, lanes: str):
    from env_bootstrap import load_env
    load_env()
    from db_adapter import _get_conn
    import shadow_decision_service as svc
    import strategy_ticket_reconciler as reconciler
    import strategy_ticket_review as reviewer
    import watch_packet_quality as packet_quality

    sym = symbol.upper()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT packet_id, packet FROM decision_packets
                   WHERE upper(symbol)=%s AND superseded_by IS NULL""", (sym,))
    row = cur.fetchone()
    if not row:
        print(json.dumps({"ok": False, "error": "no live packet"}))
        return

    packet_id, packet = row
    selected = packet_quality.select_governing_validation(packet)
    target = selected.get("ticket") or {}
    validation = selected.get("validation") or {}
    deterministic = selected.get("deterministic") or "NOT_RUN"
    quality = validation.get("quality_admission") or {}
    prior = packet.get("ticket_review") or {}

    # Deterministic basics and quality come first. Do not spend model calls on a
    # failed, missing or non-admitted ticket; persist the honest state instead.
    may_review = deterministic in {"PASS", "REVIEW_REQUIRED"}
    if quality and (quality.get("state") != "ADMITTED"
                    or quality.get("new_entry_allowed") is False):
        may_review = False

    facts = _facts_from_packet(sym, packet, validation, conn, svc)
    selected_lanes = tuple(
        lane for lane in (part.strip() for part in lanes.split(","))
        if lane in {"local", "grok", "chatgpt"}
    )
    reviews = {}
    if may_review and selected_lanes:
        reviews = reviewer.run_free_reviews(
            sym, target, facts, validation, lanes=selected_lanes,
        )

    prior_reviews = {**(prior.get("reviews") or {}), **reviews}
    reconciled = reconciler.reconcile(
        validation,
        prior_reviews,
        current_ticket_hash=validation.get("ticket_hash"),
    )
    merged_reviews = _persist(
        packet_id, prior, reviews, reconciled, selected.get("source"),
    )
    print(json.dumps({
        "ok": True,
        "packet_id": packet_id,
        "validation_source": selected.get("source"),
        "deterministic": deterministic,
        "quality_admission": quality.get("state"),
        "models_called": bool(reviews),
        "paid_lane_called": False,
        "verdicts": {
            key: value.get("verdict")
            for key, value in merged_reviews.items()
            if isinstance(value, dict) and not key.startswith("_")
        },
        "reconciled": reconciled.get("state"),
        "premium_recommended": reconciled.get("premium_recommended"),
    }))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "local,grok,chatgpt")
