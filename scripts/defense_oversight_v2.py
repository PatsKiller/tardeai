#!/usr/bin/env python3
"""Due-diligence-aware Defense oversight panel.

The legacy recommendations producer invokes free critics before the v11
postprocessor can attach deterministic research packets. This module allows the
v11 launcher to defer that call, attach/withhold first, then review only PASS or
REVIEW_REQUIRED cards. BLOCKED and unassessed cards consume zero provider calls.

Free ChatGPT/Grok OAuth and explicitly confirmed paid seats receive the same
curated brief. A response missing, duplicating or inventing any card id is
invalid. Critics remain advisory and cannot restore withheld cards or activate
recommendations.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import defense_oversight as base

ROOT = Path(__file__).resolve().parent.parent
RECOMMENDATIONS = ROOT / "data" / "runtime" / "defense_recommendations_latest.json"
REVIEW_CONTRACT = "defense-diligence-oversight-v2"

_ORIGINAL_BUILD = base.build_oversight_brief
_ORIGINAL_PAID_PREVIEW = base.paid_preview

CONTRACT = """MANDATORY COMPLETENESS: return exactly one verdict for EVERY card id in the brief, with no omissions, duplicates or extra ids. Deterministic state is sovereign: never restore a BLOCKED/withheld card, alter arithmetic, mechanics, sizing, allocation, mapping or sector state. Respond ONLY with JSON:
{"cards":[{"id":"<exact card id>","verdict":"CONCUR|QUALIFY|OBJECT","reason":"<=40 words","missed_risk":"<=25 words or null","evidence_citations":["packet.path"]}],"memo":{"top_concerns":[],"incoherences":[],"blind_spots":[],"strongest_objection":"required"}}"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diligence_map(recommendations: dict) -> dict[str, dict]:
    out = {}
    for cards in (recommendations.get("groups") or {}).values():
        for card in cards or []:
            if isinstance(card, dict) and card.get("id"):
                out[str(card["id"])] = card.get("due_diligence") or {}
    for pair in recommendations.get("pairs") or []:
        if isinstance(pair, dict) and pair.get("id"):
            out[str(pair["id"])] = pair.get("due_diligence") or {}
    for stance in recommendations.get("stances") or []:
        if not isinstance(stance, dict):
            continue
        sid = stance.get("id") or f"stance-{stance.get('symbol')}-{stance.get('account')}"
        out[str(sid)] = stance.get("due_diligence") or {}
    return out


def _summary(packet: dict) -> dict:
    return {
        "contract": packet.get("contract_version"),
        "state": packet.get("deterministic_state") or "NOT_ASSESSED",
        "packet_hash": packet.get("packet_hash"),
        "coverage": packet.get("coverage"),
        "hard_failures": (packet.get("hard_failures") or [])[:4],
        "warnings": (packet.get("warnings") or [])[:4],
        "checks": packet.get("checks") or [],
        "sources": packet.get("sources") or [],
        "authority": packet.get("authority") or {},
    }


def build_oversight_brief() -> dict:
    art = _ORIGINAL_BUILD()
    recommendations = json.loads(RECOMMENDATIONS.read_text())
    diligence = _diligence_map(recommendations)
    reviewable = []
    blocked = []
    for card in art["brief"].get("cards") or []:
        packet = diligence.get(str(card.get("id"))) or {}
        state = str(packet.get("deterministic_state") or "NOT_ASSESSED").upper()
        enriched = {**card, "due_diligence": _summary(packet)}
        if state in {"PASS", "REVIEW_REQUIRED"}:
            reviewable.append(enriched)
        else:
            blocked.append({
                "id": card.get("id"),
                "state": state,
                "packet_hash": packet.get("packet_hash"),
                "reason": (packet.get("hard_failures")
                           or ["deterministic due diligence not complete"])[0],
            })

    art["brief"]["cards"] = reviewable
    art["brief"]["deterministically_blocked_cards"] = blocked
    art["brief"]["due_diligence_contract"] = {
        "contract": "research-due-diligence-v1",
        "policy": "research-due-diligence-policy-v1",
        "review_contract": REVIEW_CONTRACT,
        "reviewable_states": ["PASS", "REVIEW_REQUIRED"],
        "blocked_provider_calls": 0,
        "critics_may_override": False,
    }
    art["brief"]["response_contract"] = CONTRACT
    markdown = json.dumps(art["brief"], indent=1, default=str)
    seed = str(recommendations.get("snapshot_hash") or "") + markdown
    art["markdown"] = markdown
    art["build_hash"] = hashlib.sha256(seed.encode()).hexdigest()[:16]
    art["token_estimate"] = len(markdown) // 4
    art["generated_at"] = _now()
    return art


def _parse_complete(raw: str, expected_ids: set[str]) -> dict | None:
    try:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.split("```", 1)[1].lstrip("json").strip()
        parsed = json.loads(text)
        cards = parsed.get("cards")
        memo = parsed.get("memo")
        if not isinstance(cards, list) or not isinstance(memo, dict):
            return None
        ids = [str(card.get("id") or "") for card in cards]
        if len(ids) != len(set(ids)) or set(ids) != expected_ids:
            return None
        for card in cards:
            if card.get("verdict") not in {"CONCUR", "QUALIFY", "OBJECT"}:
                return None
            if not isinstance(card.get("reason"), str):
                return None
            if not isinstance(card.get("evidence_citations"), list):
                return None
        if not isinstance(memo.get("strongest_objection"), str):
            return None
        for key in ("top_concerns", "incoherences", "blind_spots"):
            if not isinstance(memo.get(key), list):
                return None
        memo["coverage"] = f"{len(ids)}/{len(expected_ids)} cards"
        return parsed
    except Exception:
        return None


def _persist(cur, *, build_hash: str, seat: str, status: str,
             parsed: dict | None, raw: str, latency_ms: int,
             cost_est: float | None = None) -> None:
    base.ensure_tables(cur)
    if cost_est is not None:
        cur.execute(
            "ALTER TABLE oversight_reviews ADD COLUMN IF NOT EXISTS cost_est numeric"
        )
    cur.execute(
        """INSERT INTO oversight_reviews
             (build_hash, seat, status, verdicts, memo, raw, latency_ms, cost_est)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (build_hash, seat) DO UPDATE SET
             status=EXCLUDED.status, verdicts=EXCLUDED.verdicts,
             memo=EXCLUDED.memo, raw=EXCLUDED.raw,
             latency_ms=EXCLUDED.latency_ms, cost_est=EXCLUDED.cost_est""",
        (
            build_hash,
            seat,
            status,
            json.dumps(parsed["cards"]) if parsed else None,
            json.dumps(parsed["memo"]) if parsed else None,
            raw[:8000],
            latency_ms,
            cost_est,
        ),
    )
    cur.connection.commit()


def deferred_free_critiques(cur, force: bool = False) -> dict:
    """Installed during v10 production so critics run only after v11 attachment."""
    return {
        "deferred": True,
        "seats": {},
        "reason": "awaiting deterministic due-diligence attachment",
        "provider_calls": 0,
    }


def run_free_critiques(cur, force: bool = False) -> dict:
    art = build_oversight_brief()
    cards = art["brief"].get("cards") or []
    expected = {str(card["id"]) for card in cards}
    out = {
        "build_hash": art["build_hash"],
        "token_estimate": art["token_estimate"],
        "reviewable_cards": len(cards),
        "blocked_cards": len(art["brief"].get("deterministically_blocked_cards") or []),
        "seats": {},
        "provider_calls": 0,
        "paid_lane_called": False,
    }
    if not expected:
        out["skipped"] = "no PASS or REVIEW_REQUIRED cards"
        return out

    base.ensure_tables(cur)
    cur.connection.commit()
    from llm_lane import available, generate
    prompt = (
        "You are an independent risk overseer for a retirement-scale defensive "
        "trading desk. Judge within the constitution and deterministic research "
        "authority. Be adversarial where warranted.\n\n"
        + art["markdown"] + "\n\n" + CONTRACT
    )
    for seat, lane in (("chatgpt", "chatgpt"), ("grok", "grok")):
        cur.execute(
            "SELECT status FROM oversight_reviews WHERE build_hash=%s AND seat=%s",
            (art["build_hash"], seat),
        )
        if cur.fetchone() and not force:
            out["seats"][seat] = "cached"
            continue
        cur.execute(
            """SELECT count(*) FROM oversight_reviews
                 WHERE seat=%s AND created_at::date=CURRENT_DATE AND status='ok'""",
            (seat,),
        )
        if cur.fetchone()[0] >= base._daily_per_seat():
            out["seats"][seat] = "quota"
            continue
        if not available(lane):
            out["seats"][seat] = "unavailable"
            continue
        started = time.time()
        try:
            raw = generate(prompt, lane=lane, timeout=150)
            raw = raw if isinstance(raw, str) else json.dumps(raw)
            out["provider_calls"] += 1
        except Exception as exc:
            raw = f"__error__ {type(exc).__name__}: {exc}"
        latency_ms = int((time.time() - started) * 1000)
        parsed = _parse_complete(raw, expected) if not raw.startswith("__error__") else None
        status = "ok" if parsed else (
            "unavailable" if raw.startswith("__error__") else "unparseable"
        )
        _persist(
            cur,
            build_hash=art["build_hash"],
            seat=seat,
            status=status,
            parsed=parsed,
            raw=raw,
            latency_ms=latency_ms,
        )
        out["seats"][seat] = status
    return out


def paid_preview(cur, seats=None) -> dict:
    """Cost preview only; no provider call."""
    base.build_oversight_brief = build_oversight_brief
    return _ORIGINAL_PAID_PREVIEW(cur, seats=seats)


def run_paid_review(cur, seats=None, *, confirmed: bool = False) -> dict:
    """Strict operator-confirmed paid panel. Never called by a scheduler/producer."""
    if not confirmed:
        return {
            "ok": False,
            "error": "PAID_CONFIRMATION_REQUIRED",
            "paid_lane_called": False,
        }
    art = build_oversight_brief()
    cards = art["brief"].get("cards") or []
    expected = {str(card["id"]) for card in cards}
    if not expected:
        return {
            "ok": False,
            "error": "NO_REVIEWABLE_CARDS",
            "paid_lane_called": False,
        }
    preview = paid_preview(cur, seats=seats)
    if preview["panel_cost_usd"] > preview["budget_remaining_usd"]:
        return {
            "ok": False,
            "error": "PAID_BUDGET_EXCEEDED",
            "paid_lane_called": False,
            "preview": preview,
        }
    keys = {
        "anthropic": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        "openai": os.environ.get("OPENAI_API_KEY", "").strip(),
        "xai": os.environ.get("XAI_API_KEY", "").strip(),
    }
    prompt = (
        "You are an explicitly operator-selected senior paid reviewer. The "
        "deterministic due-diligence state is sovereign. Adjudicate methodology "
        "and evidence only.\n\n" + art["markdown"] + "\n\n" + CONTRACT
    )
    results = {}
    provider_calls = 0
    for name, seat in preview.get("seats", {}).items():
        provider = seat["provider"]
        if not keys.get(provider):
            results[name] = {"status": "unavailable", "error": f"{provider} key not set"}
            continue
        started = time.time()
        raw = base._call_provider(provider, seat["model"], prompt, keys)
        provider_calls += 1
        latency_ms = int((time.time() - started) * 1000)
        parsed = _parse_complete(raw, expected) if not raw.startswith("__error__") else None
        status = "ok" if parsed else (
            "unavailable" if raw.startswith("__error__") else "unparseable"
        )
        cost = seat["cost_est_usd"] if status in {"ok", "unparseable"} else 0
        _persist(
            cur,
            build_hash=art["build_hash"],
            seat=name,
            status=status,
            parsed=parsed,
            raw=raw,
            latency_ms=latency_ms,
            cost_est=cost,
        )
        results[name] = {
            "status": status,
            "model": seat["model"],
            "latency_ms": latency_ms,
            "cost_est_usd": cost if status == "ok" else 0,
        }
    return {
        "ok": any(value.get("status") == "ok" for value in results.values()),
        "results": results,
        "provider_calls": provider_calls,
        "paid_lane_called": provider_calls > 0,
    }


def install(*, defer_free: bool = True) -> None:
    """Patch only the module used by the existing Defense producer."""
    base.build_oversight_brief = build_oversight_brief
    base.run_free_critiques = deferred_free_critiques if defer_free else run_free_critiques
    base.paid_preview = paid_preview
    base.run_paid_review = run_paid_review


def activate_free() -> None:
    base.run_free_critiques = run_free_critiques
