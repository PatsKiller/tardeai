#!/usr/bin/env python3
"""Detached worker for bounded independent review of a validated Watch ticket.

The worker never constructs mechanics and never calls a model before mandatory
deterministic validation and quality admission complete. It persists critic
artifacts and deterministic reconciliation only; no proposal, broker, approval,
paid-lane or 2FA action is available here.

2026-08-03: run each lane independently with a hard wall-clock timeout and
persist after every lane. Prior multi-lane jobs hung forever on Grok OAuth
(:8645) and never wrote DeepSeek Flash results that had already finished.
"""
import concurrent.futures
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

# Hard wall-clock caps per lane (seconds). Keeps "Re-run critics" from stalling
# the whole ticket when one OAuth proxy accepts TCP but never returns a body.
_LANE_TIMEOUT_S = {
    "deepseek-flash": 150,
    "deepseek-v4": 240,
    "local": 100,
    "grok": 130,
    "chatgpt": 130,
}


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

    # Deterministic basics and quality come first. Missing quality is not a soft
    # default: the worker requires an explicit ADMITTED decision before spending
    # a local or OAuth call. RESEARCH_ONLY, QUARANTINED and UNASSESSED all stop.
    may_review = (
        deterministic in {"PASS", "REVIEW_REQUIRED"}
        and quality.get("state") == "ADMITTED"
        and quality.get("new_entry_allowed") is not False
    )

    facts = _facts_from_packet(sym, packet, validation, conn, svc)
    # 2026-08-02: DeepSeek Flash/v4 are first-class critics (UI buttons). Prior filter
    # only allowed local/grok/chatgpt — DeepSeek clicks queued then silently dropped,
    # leaving REVIEW_UNAVAILABLE / NOT RUN with "All critics queued" toast only.
    _ALLOWED = {"local", "grok", "chatgpt", "deepseek-flash", "deepseek-v4"}
    selected_lanes = tuple(
        lane for lane in (part.strip() for part in lanes.split(","))
        if lane in _ALLOWED
    )
    reviews: dict = {}
    if may_review and not selected_lanes:
        # Surface mis-routed lane strings instead of silent no-op
        print(json.dumps({
            "ok": False,
            "error": f"no allowed lanes in request (got {lanes!r}; allowed={sorted(_ALLOWED)})",
            "symbol": sym,
        }))
        return

    # Gate closed: no ticket / quality not ADMITTED. Persist an explicit block so the
    # UI stops polling and shows the real reason (not "DeepSeek broken").
    if not may_review:
        if deterministic in (None, "", "NOT_RUN", "NOT RUN"):
            block_code = "DETERMINISTIC_NOT_RUN"
            block_detail = (
                "No validated ticket on the decision packet. Build an entry plan "
                "(POST /api/v2/watchlist/{symbol}/plan) and refresh the packet "
                "before DeepSeek / multi-lane critics can run."
            )
        elif quality.get("state") != "ADMITTED":
            block_code = "QUALITY_NOT_ADMITTED"
            block_detail = (
                f"Quality admission is {quality.get('state') or 'missing'} — "
                "critics only run after ADMITTED deterministic validation."
            )
        else:
            block_code = "CRITIC_GATE_BLOCKED"
            block_detail = (
                f"deterministic={deterministic} quality={quality.get('state')} "
                f"new_entry_allowed={quality.get('new_entry_allowed')}"
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        for lane in selected_lanes or ("deepseek-flash",):
            reviews[lane] = {
                "review_type": f"{lane.upper().replace('-', '_')}_CRITIC",
                "provider_family": lane.upper(),
                "model": None,
                "verdict": "UNAVAILABLE",
                "error": f"blocked: {block_code}",
                "ticket_hash_reviewed": validation.get("ticket_hash"),
                "facts_hash_reviewed": validation.get("facts_hash"),
                "reviewed_at": now_iso,
                "review_contract": "watch-ticket-independent-review-v2",
                "math_check": {},
                "semantic_contradictions": [],
                "missing_evidence": [],
                "stale_inputs": [],
                "risk_objections": [],
                "questions": [],
                "evidence_citations": [],
            }
        prior_reviews = {**(prior.get("reviews") or {}), **reviews}
        reconciled = reconciler.reconcile(
            validation or {"state": deterministic or "NOT_RUN"},
            prior_reviews,
            current_ticket_hash=validation.get("ticket_hash"),
        )
        # Stamp operator-visible block fields onto ticket_review envelope
        blocked_prior = {
            **prior,
            "run_status": "BLOCKED",
            "block_code": block_code,
            "block_detail": block_detail,
            "blocked_at": now_iso,
            "requested_lanes": list(selected_lanes),
        }
        merged = _persist(
            packet_id, blocked_prior, reviews, reconciled, selected.get("source"),
        )
        print(json.dumps({
            "ok": False,
            "blocked": True,
            "block_code": block_code,
            "block_detail": block_detail,
            "packet_id": packet_id,
            "deterministic": deterministic,
            "quality_admission": quality.get("state"),
            "models_called": False,
            "verdicts": {
                k: (v or {}).get("verdict")
                for k, v in merged.items()
                if isinstance(v, dict) and not str(k).startswith("_")
            },
            "reconciled": reconciled.get("state"),
            "next_action": "POST /api/v2/watchlist/{symbol}/plan then re-run critics",
        }), flush=True)
        return

    # Per-lane run + persist so a hung Grok/ChatGPT proxy cannot erase DeepSeek
    # results that already completed earlier in the same "Re-run critics" click.
    if may_review and selected_lanes:
        # Clear prior block stamp so UI does not keep showing DETERMINISTIC_NOT_RUN
        prior = {
            **prior,
            "run_status": "RUNNING",
            "block_code": None,
            "block_detail": None,
            "requested_lanes": list(selected_lanes),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        for lane in selected_lanes:
            t0 = time.monotonic()
            wall = int(_LANE_TIMEOUT_S.get(lane, 150))
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        reviewer.run_free_reviews,
                        sym, target, facts, validation,
                        lanes=(lane,),
                    )
                    one = fut.result(timeout=wall)
                if not isinstance(one, dict):
                    one = {}
                for key, value in one.items():
                    if str(key).startswith("_"):
                        continue
                    if isinstance(value, dict):
                        reviews[key] = value
                print(json.dumps({
                    "event": "lane_done",
                    "symbol": sym,
                    "lane": lane,
                    "verdict": (reviews.get(lane) or {}).get("verdict"),
                    "elapsed_s": round(time.monotonic() - t0, 1),
                }), flush=True)
            except concurrent.futures.TimeoutError:
                reviews[lane] = {
                    "review_type": f"{lane.upper().replace('-', '_')}_CRITIC",
                    "provider_family": lane.upper(),
                    "model": None,
                    "verdict": "UNAVAILABLE",
                    "error": f"{lane} wall-clock timeout after {wall}s",
                    "ticket_hash_reviewed": validation.get("ticket_hash"),
                    "facts_hash_reviewed": validation.get("facts_hash"),
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "review_contract": "watch-ticket-independent-review-v2",
                    "math_check": {},
                    "semantic_contradictions": [],
                    "missing_evidence": [],
                    "stale_inputs": [],
                    "risk_objections": [],
                    "questions": [],
                    "evidence_citations": [],
                }
                print(json.dumps({
                    "event": "lane_timeout",
                    "symbol": sym,
                    "lane": lane,
                    "timeout_s": wall,
                }), flush=True)
            except Exception as exc:
                reviews[lane] = {
                    "review_type": f"{lane.upper().replace('-', '_')}_CRITIC",
                    "provider_family": lane.upper(),
                    "model": None,
                    "verdict": "UNAVAILABLE",
                    "error": f"{type(exc).__name__}: {str(exc)[:140]}",
                    "ticket_hash_reviewed": validation.get("ticket_hash"),
                    "facts_hash_reviewed": validation.get("facts_hash"),
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "review_contract": "watch-ticket-independent-review-v2",
                    "math_check": {},
                    "semantic_contradictions": [],
                    "missing_evidence": [],
                    "stale_inputs": [],
                    "risk_objections": [],
                    "questions": [],
                    "evidence_citations": [],
                }
                print(json.dumps({
                    "event": "lane_error",
                    "symbol": sym,
                    "lane": lane,
                    "error": f"{type(exc).__name__}: {str(exc)[:140]}",
                }), flush=True)

            # Incremental persist after every lane (DeepSeek visible even if later lanes hang)
            prior_reviews = {**(prior.get("reviews") or {}), **reviews}
            reconciled = reconciler.reconcile(
                validation,
                prior_reviews,
                current_ticket_hash=validation.get("ticket_hash"),
            )
            try:
                _persist(
                    packet_id, prior, reviews, reconciled, selected.get("source"),
                )
                # Keep accumulating into prior so next lane merge is correct
                prior = {
                    **prior,
                    "reviews": {**(prior.get("reviews") or {}), **reviews},
                    "reconciled": reconciled,
                    "validation_source": selected.get("source"),
                }
            except Exception as exc:
                print(json.dumps({
                    "event": "persist_error",
                    "symbol": sym,
                    "lane": lane,
                    "error": f"{type(exc).__name__}: {str(exc)[:140]}",
                }), flush=True)

    prior_reviews = {**(prior.get("reviews") or {}), **reviews}
    reconciled = reconciler.reconcile(
        validation,
        prior_reviews,
        current_ticket_hash=validation.get("ticket_hash"),
    )
    prior = {
        **prior,
        "run_status": "COMPLETE",
        "block_code": None,
        "block_detail": None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
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
        "paid_lane_called": any(k.startswith("deepseek") for k in reviews),
        "verdicts": {
            key: value.get("verdict")
            for key, value in merged_reviews.items()
            if isinstance(value, dict) and not key.startswith("_")
        },
        "reconciled": reconciled.get("state"),
        "premium_recommended": reconciled.get("premium_recommended"),
    }), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "deepseek-flash,local,grok,chatgpt")
