"""CIO plan enrichment — evidence pack → governed LLM (or template) → plan fields.

Phase P2b. READ_ONLY_ADVISORY. Numbers only from evidence_refs / pack facts.
Cap/provider blocked → template + narrative_source=template + llm deferred.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = PROJECT_ROOT / "config" / "cio_llm_policy.yaml"
DEFAULT_ENRICH_LOG = PROJECT_ROOT / "data" / "cio" / "cio_llm_enrich_log.jsonl"
DEFAULT_CALL_COUNTER = PROJECT_ROOT / "data" / "cio" / "cio_llm_hour_counter.json"
DEFAULT_NOTIFY_LEDGER = PROJECT_ROOT / "data" / "cio" / "cio_plan_notify_ledger.json"

NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_llm_policy(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_POLICY)
    if not p.exists():
        return {
            "enabled": True,
            "shadow": True,
            "material_sources": ["situation.raised", "OPERATOR_MESSAGE"],
            "non_material_sources": ["system.heartbeat_ok"],
            "situation_notify_telegram": False,
            "llm": {
                "enabled": True,
                "max_llm_per_wake": 1,
                "enrich_dedup_hours": 6,
                "prefer_flash": True,
                "pro_for": ["OPERATOR_MESSAGE", "S0_OPERATOR_CONVERSE"],
                "bridge_endpoint": "http://127.0.0.1:8766/v1/chat/completions",
                "caller": "alex",
                "task_type_flash": "cio_synthesis",
                "task_type_pro": "cio_synthesis",
                "max_tokens": 700,
                "temperature": 0.2,
                "max_calls_per_hour": 12,
            },
            "validator": {"reject_invented_numbers": True, "max_retries": 1},
        }
    with open(p) as fh:
        cfg = yaml.safe_load(fh) or {}
    # env overrides
    if os.environ.get("CIO_LLM_ENRICH", "").strip().lower() in ("0", "false", "off", "no"):
        cfg.setdefault("llm", {})["enabled"] = False
    if os.environ.get("CIO_SITUATION_NOTIFY", "").strip() in ("1", "true", "on", "yes"):
        cfg["situation_notify_telegram"] = True
    return cfg


def is_material_source(source: str, policy: Optional[dict[str, Any]] = None) -> bool:
    pol = policy or load_llm_policy()
    s = (source or "").strip()
    non = set(pol.get("non_material_sources") or [])
    if s in non:
        return False
    mat = set(pol.get("material_sources") or [])
    if s in mat:
        return True
    # situation types
    if s.startswith("S") and "_" in s:
        return s in mat or s.startswith("S")
    return False


def evidence_facts_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Flatten evidence_refs + plan fields into a facts dict for pack/validation."""
    facts: dict[str, Any] = {
        "symbols": list(plan.get("symbols") or []),
        "situation_type": plan.get("situation_type"),
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "fire_reasons": list(plan.get("fire_reasons") or []),
    }
    numeric_tokens: set[str] = set()
    for ref in plan.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        for k, v in ref.items():
            if k in ("domain", "as_of", "fields_used", "quality_state"):
                continue
            facts[f"ref.{ref.get('domain', '?')}.{k}"] = v
            if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(?:\.\d+)?", v)):
                numeric_tokens.add(str(v))
        # fields_used may only name keys — collect from parent plan summary later
        for tok in NUM_RE.findall(json.dumps(ref, default=str)):
            numeric_tokens.add(tok)
    # also harvest numbers already in plan text (from detector — evidence-grounded)
    for field in ("summary", "recommendation", "title"):
        for tok in NUM_RE.findall(str(plan.get(field) or "")):
            numeric_tokens.add(tok)
    # options
    for o in plan.get("options") or []:
        for tok in NUM_RE.findall(json.dumps(o, default=str)):
            numeric_tokens.add(tok)
    facts["_allowed_numeric_tokens"] = sorted(numeric_tokens)
    facts["_evidence_refs"] = list(plan.get("evidence_refs") or [])
    facts["_options_stub"] = list(plan.get("options") or [])
    return facts


def is_material_plan(plan: dict[str, Any]) -> bool:
    """Graduated depth: material situations get longer thesis-aware advisory."""
    st = str(plan.get("situation_type") or "")
    fire = [str(x) for x in (plan.get("fire_reasons") or (plan.get("extra") or {}).get("fire_reasons") or [])]
    fire_blob = " ".join(fire).lower()
    # Always material types
    if st in (
        "S5_CASH_DEPLOYMENT",
        "S6_CONCENTRATION_OR_DISPOSITION",
        "S8_DEFENSIVE_REGIME",
    ):
        return True
    if st == "S1_POSITION_LIFECYCLE":
        if any(
            x.startswith("deep_drawdown") or x.startswith("partial_recovery") or "catalyst" in x
            for x in fire
        ):
            return True
        # pure reclaim is routine
        if fire == ["basis_reclaim_zone"] or (len(fire) == 1 and "reclaim" in fire_blob):
            return False
        return "drawdown" in fire_blob or "recovery" in fire_blob
    if st == "S2_STOP_GAP":
        return False  # routine card unless flagged critical in fire
    if plan.get("force_material"):
        return True
    return False


def _domain_as_of(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("as_of") or payload.get("ts") or "")[:24]
    return ""


def augment_multi_domain_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    """Ensure holdings + cash/portfolio (and risk when available) on material plans.

    Mutates a copy of the plan's evidence_refs. Fail-soft if Data Broker down.
    """
    updated = dict(plan)
    refs = [dict(r) for r in (plan.get("evidence_refs") or []) if isinstance(r, dict)]
    have = {str(r.get("domain") or "") for r in refs}
    symbols = [str(s).upper() for s in (plan.get("symbols") or [])]
    try:
        try:
            from lib.data_broker.cio_portfolio import get_cio_snapshot
        except Exception:
            from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot  # type: ignore
        snap = get_cio_snapshot(max_age_s=60) or {}
        domains = snap.get("domains") or snap
        if not isinstance(domains, dict):
            domains = {}

        def _pull(name: str, fields: list[str], extra: Optional[dict] = None) -> None:
            nonlocal refs, have
            if name in have:
                return
            raw = domains.get(name)
            if not isinstance(raw, dict):
                return
            # unwrap nested data
            body = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            if not isinstance(body, dict):
                return
            ref: dict[str, Any] = {
                "domain": name,
                "as_of": _domain_as_of(raw) or _domain_as_of(body) or _now()[:19],
                "fields_used": [],
                "quality_state": body.get("state") or raw.get("state") or "OK",
            }
            for f in fields:
                if f in body and body[f] is not None:
                    ref[f] = body[f]
                    ref["fields_used"].append(f)
            # holdings rows for symbol weight
            if name == "holdings_detail" and symbols:
                rows = body.get("holdings") or body.get("positions") or body.get("rows") or []
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
                        if sym in symbols:
                            for k in ("weight_pct", "basis", "last", "market_value", "qty", "unrealized_pl_pct"):
                                if k in row and row[k] is not None:
                                    ref[k] = row[k]
                                    if k not in ref["fields_used"]:
                                        ref["fields_used"].append(k)
                            ref["symbol"] = sym
                            break
            if extra:
                ref.update(extra)
            if ref["fields_used"] or any(k not in ("domain", "as_of", "fields_used", "quality_state") for k in ref):
                refs.append(ref)
                have.add(name)

        # Core pair for synthesis (notify requires multi-domain)
        _pull("holdings_detail", ["holdings_count", "total_value"])
        _pull("cash_buying_power", ["cash_pct", "total_cash", "buying_power", "cash_weight_pct"])
        # portfolio aggregate if cash domain missing fields
        _pull("portfolio", ["total_value", "cash_pct", "day_change_pct", "holdings_count"])
        _pull("risk", ["portfolio_heat_pct", "stops_active", "gross_exposure_pct"])
        # concentration if present
        _pull("concentration", ["top_weight_pct", "top_symbol", "hhi"])
        # recent activity / hermes research when available
        _pull("recent_activity", ["trade_count", "last_trade_ts", "turnover_pct"])
        _pull("hermes_research", ["promoted_research_count", "staged_research_count", "model_provider"])
    except Exception:
        pass

    # Require at least 2 domains for material notify quality flag
    domains_present = sorted({str(r.get("domain")) for r in refs if r.get("domain")})
    # Triggering domain + holdings or cash is preferred
    has_holdings = "holdings_detail" in domains_present
    has_cash_or_port = bool({"cash_buying_power", "portfolio"} & set(domains_present))
    updated["evidence_refs"] = refs
    updated["_evidence_domains"] = domains_present
    updated["_multi_domain_ok"] = len(domains_present) >= 2 and (has_holdings or has_cash_or_port)
    return updated


def maybe_request_hermes(plan: dict[str, Any], *, reason: str = "") -> Optional[str]:
    """Enqueue Hermes research challenge for material situations. Fail-soft.

    READ_ONLY — research only, no trading authority.
    """
    if not is_material_plan(plan) and not plan.get("hermes_requested"):
        return None
    st = str(plan.get("situation_type") or "")
    syms = ",".join(str(s) for s in (plan.get("symbols") or [])[:4]) or "book"
    pid = plan.get("plan_id") or ""
    desc = (
        reason
        or f"Material CIO situation {st} ({syms}) plan={pid}. "
        f"Independently verify multi-domain evidence vs desk thesis; "
        f"flag contradictions or research gaps. READ_ONLY_ADVISORY."
    )
    try:
        try:
            from lib.cio_hermes_challenge_queue import HermesChallengeQueue
        except Exception:
            from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue  # type: ignore
        q = HermesChallengeQueue()
        ev = q.enqueue(
            challenge_type="research_gap",
            description=desc[:800],
            source=f"cio_plan:{pid or st}",
            priority="high" if st in ("S6_CONCENTRATION_OR_DISPOSITION", "S8_DEFENSIVE_REGIME") else "normal",
            evidence_refs=[
                f"plan:{pid}" if pid else f"situation:{st}",
                *[f"domain:{d}" for d in (plan.get("evidence_domains") or plan.get("_evidence_domains") or [])[:4]],
            ],
            actor_id="cio_plan_enrichment",
            metadata={
                "plan_id": pid,
                "situation_type": st,
                "symbols": list(plan.get("symbols") or []),
                "thesis_version": plan.get("thesis_version"),
                "authority": "READ_ONLY_ADVISORY",
            },
        )
        return (ev.get("stream_id") if isinstance(ev, dict) else None) or "enqueued"
    except Exception:
        return None


def build_evidence_pack(plan: dict[str, Any], *, extra_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Strict context block for the model — full desk thesis + multi-domain evidence."""
    # Ensure multi-domain before packing
    plan_aug = augment_multi_domain_evidence(plan)
    facts = evidence_facts_from_plan(plan_aug)
    material = is_material_plan(plan_aug)
    # Always load CURRENT desk thesis as governing context (not historical pin)
    desk_thesis = None
    try:
        from scripts.lib.cio_theses import (
            safe_context_block,
            safe_current_pin,
            recent_operator_learning,
        )
        try:
            desk_thesis = safe_context_block("desk", full=True)
        except TypeError:
            desk_thesis = safe_context_block("desk")
        current_pin = safe_current_pin("desk")
        if desk_thesis and current_pin:
            desk_thesis["thesis_version"] = current_pin
        # Prefer CURRENT pin as the version used for this enrichment
        if current_pin:
            plan_aug["thesis_version"] = current_pin
        elif desk_thesis and desk_thesis.get("thesis_version"):
            plan_aug["thesis_version"] = desk_thesis.get("thesis_version")
        # recent operator dispositions for same type/symbol
        sym0 = (plan_aug.get("symbols") or [None])[0]
        try:
            recent_learn = recent_operator_learning(
                situation_type=str(plan_aug.get("situation_type") or ""),
                symbol=str(sym0) if sym0 else None,
                limit=6,
            )
        except Exception:
            recent_learn = []
    except Exception:
        desk_thesis = None
        recent_learn = []

    pack = {
        "authority": "READ_ONLY_ADVISORY",
        "material": material,
        "instruction": (
            "You are the desk CIO. Desk thesis is BINDING governing context. "
            "Synthesize across ALL evidence domains — never restate detector fire alone. "
            "Use ONLY numbers present in the pack. Missing → DATA_UNAVAILABLE. "
            "No orders/stops/broker steps. READ_ONLY_ADVISORY."
        ),
        "situation_type": plan_aug.get("situation_type"),
        "symbols": plan_aug.get("symbols") or [],
        "plan_id": plan_aug.get("plan_id"),
        "title": plan_aug.get("title"),
        "thesis_version": plan_aug.get("thesis_version") or (desk_thesis or {}).get("thesis_version"),
        "desk_thesis": desk_thesis,
        "recent_operator_learning": recent_learn,
        "existing_summary": plan_aug.get("summary") or "",
        "existing_recommendation": plan_aug.get("recommendation") or "",
        "options_stub": facts.get("_options_stub") or [],
        "evidence_refs": facts.get("_evidence_refs") or [],
        "evidence_domains": plan_aug.get("_evidence_domains") or [],
        "multi_domain_ok": bool(plan_aug.get("_multi_domain_ok")),
        "allowed_numeric_tokens": facts.get("_allowed_numeric_tokens") or [],
        "fire_reasons": plan_aug.get("fire_reasons")
        or (plan_aug.get("extra") or {}).get("fire_reasons")
        or [],
        "extra_context": extra_context or {},
        "output_schema": {
            "summary": "string — multi-domain situation, not detector echo",
            "thesis_alignment": "string — how advice fits or tensions with desk thesis",
            "multi_domain_summary": "string — holdings + cash/portfolio (+ risk) synthesis",
            "options": [{"id": "string", "label": "string", "pros": "string", "cons": "string"}],
            "recommendation": "string — option_id + why highest-signal under thesis pin",
            "risks": ["string"],
            "revisit_hint": "string",
            "cited_fields": ["string"],
            "thesis_version": "string — echo desk pin exactly",
        },
    }
    return pack


def collect_allowed_numbers(pack: dict[str, Any]) -> set[str]:
    allowed = set(str(x) for x in (pack.get("allowed_numeric_tokens") or []))
    # always allow small structural ints used in counts / option indices
    allowed.update({str(i) for i in range(0, 25)})
    blob = json.dumps(pack, default=str)
    for tok in NUM_RE.findall(blob):
        allowed.add(tok)
    # Rounded variants + simple derived % gaps (basis vs last etc.)
    floats: list[float] = []
    for tok in list(allowed):
        try:
            f = float(tok)
            floats.append(f)
            allowed.add(f"{f:.2f}")
            allowed.add(f"{f:.1f}")
            if abs(f - round(f)) < 1e-9:
                allowed.add(str(int(round(f))))
        except Exception:
            continue
    # pairwise relative drawdown / gap percents commonly cited
    for i, a in enumerate(floats):
        for b in floats[i + 1 :]:
            if a == 0:
                continue
            pct = abs(a - b) / abs(a) * 100.0
            if 0.1 <= pct <= 99.9:
                allowed.add(f"{pct:.1f}")
                allowed.add(f"{pct:.0f}")
                allowed.add(f"{pct:.2f}")
    return allowed


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    # fenced ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Prefer first balanced object via raw_decode (tolerates trailing prose)
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        end = text.rfind("}")
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _as_short_text(val: Any, limit: int = 280) -> str:
    """Flatten list/dict pros/cons into an operator-facing string (word-safe)."""
    if val is None:
        return ""
    if isinstance(val, list):
        parts = [str(x).strip() for x in val if str(x).strip()]
        t = "; ".join(parts)
    elif isinstance(val, dict):
        t = json.dumps(val, default=str)
    else:
        t = str(val).strip()
    if len(t) <= limit:
        return t
    cut = t[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def normalize_narrative(narrative: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM shape quirks into plan schema."""
    out = dict(narrative)
    opts = out.get("options")
    if isinstance(opts, list):
        norm = []
        for i, o in enumerate(opts):
            if isinstance(o, dict) and (o.get("id") or o.get("label")):
                norm.append({
                    "id": str(o.get("id") or f"opt_{i}"),
                    "label": str(o.get("label") or o.get("id") or f"Option {i}"),
                    "pros": _as_short_text(o.get("pros")),
                    "cons": _as_short_text(o.get("cons")),
                })
            elif isinstance(o, str) and o.strip():
                norm.append({"id": f"opt_{i}", "label": o.strip(), "pros": "", "cons": ""})
        out["options"] = norm
    risks = out.get("risks")
    if isinstance(risks, str):
        out["risks"] = [risks]
    elif isinstance(risks, list):
        out["risks"] = [_as_short_text(r, 240) for r in risks if r is not None][:8]
    else:
        out["risks"] = []
    if not isinstance(out.get("cited_fields"), list):
        out["cited_fields"] = []
    # recommendation sometimes arrives as {id,label}
    rec = out.get("recommendation")
    if isinstance(rec, dict):
        out["recommendation"] = str(rec.get("label") or rec.get("id") or rec)[:1200]
    elif rec is not None:
        out["recommendation"] = str(rec)[:1200]
    if out.get("summary") is not None:
        out["summary"] = str(out.get("summary"))[:1600]
    # Material longer-form fields
    if out.get("thesis_alignment") is not None:
        out["thesis_alignment"] = str(out.get("thesis_alignment"))[:800]
    if out.get("multi_domain_summary") is not None:
        out["multi_domain_summary"] = str(out.get("multi_domain_summary"))[:800]
    if out.get("thesis_version") is not None:
        out["thesis_version"] = str(out.get("thesis_version")).strip()
    return out


def validate_narrative(
    narrative: dict[str, Any],
    pack: dict[str, Any],
    *,
    reject_invented: bool = True,
) -> tuple[bool, list[str]]:
    """Return (ok, errors). Reject numeric tokens not in evidence pack."""
    errs: list[str] = []
    if not isinstance(narrative, dict):
        return False, ["not_a_dict"]
    narrative = normalize_narrative(narrative)
    for req in ("summary", "recommendation", "options", "risks"):
        if req not in narrative:
            errs.append(f"missing:{req}")
    if not isinstance(narrative.get("options"), list) or not narrative.get("options"):
        errs.append("options_empty")
    if errs:
        return False, errs
    if not reject_invented:
        return True, []
    allowed = collect_allowed_numbers(pack)
    blob = " ".join(
        [
            str(narrative.get("summary") or ""),
            str(narrative.get("recommendation") or ""),
            json.dumps(narrative.get("options") or [], default=str),
            json.dumps(narrative.get("risks") or [], default=str),
            str(narrative.get("revisit_hint") or ""),
        ]
    )
    invented = []
    allowed_f = []
    for a in allowed:
        try:
            allowed_f.append(float(a))
        except Exception:
            pass
    for tok in NUM_RE.findall(blob):
        if tok in allowed:
            continue
        # allow year-like 2026 and iso fragments already in pack
        if len(tok) == 4 and tok.startswith("20"):
            continue
        # soft match: within 0.05 abs or 0.2% relative of an allowed float
        try:
            tf = float(tok)
        except Exception:
            invented.append(tok)
            continue
        if any(abs(tf - af) <= 0.05 or (af and abs(tf - af) / abs(af) <= 0.002) for af in allowed_f):
            continue
        invented.append(tok)
    if invented:
        errs.append(f"invented_numbers:{sorted(set(invented))[:12]}")
    return (len(errs) == 0), errs


def template_narrative_from_plan(plan: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Deterministic enrichment when LLM blocked — still thesis + multi-domain aware."""
    opts = plan.get("options") or pack.get("options_stub") or []
    if not opts:
        opts = [
            {"id": "hold", "label": "Hold", "pros": "No change", "cons": "Risk remains"},
            {"id": "review", "label": "Review with more evidence", "pros": "Safer", "cons": "Delay"},
        ]
    th = pack.get("desk_thesis") or {}
    pin = pack.get("thesis_version") or th.get("thesis_version") or "desk"
    stance = th.get("stance") or "unknown"
    fire = pack.get("fire_reasons") or plan.get("fire_reasons") or []
    fire_s = ", ".join(str(x) for x in fire[:4]) or "n/a"
    domains = pack.get("evidence_domains") or []
    dom_s = ", ".join(str(d) for d in domains[:6]) or "partial"
    symbols = plan.get("symbols") or pack.get("symbols") or []
    sym_s = ",".join(str(s) for s in symbols[:4]) or "book"
    st = plan.get("situation_type") or pack.get("situation_type") or "situation"

    # Multi-domain fact snips from pack refs
    fact_bits = []
    for r in (pack.get("evidence_refs") or [])[:6]:
        if not isinstance(r, dict):
            continue
        dom = r.get("domain") or "?"
        nums = []
        for k, v in r.items():
            if k in ("domain", "as_of", "fields_used", "quality_state"):
                continue
            if isinstance(v, (int, float)):
                nums.append(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}")
            elif isinstance(v, str) and NUM_RE.fullmatch(v.strip() or ""):
                nums.append(f"{k}={v.strip()}")
        if nums:
            fact_bits.append(f"{dom}({', '.join(nums[:4])})")
    multi = (
        f"Domains {dom_s}: " + "; ".join(fact_bits[:5])
        if fact_bits
        else f"Domains available: {dom_s} (partial facts)"
    )
    principles = th.get("principles") or []
    p0 = str(principles[0]) if principles else "evidence before narrative"
    rps = th.get("risk_posture_structured") or {}
    risk_note = ""
    if isinstance(rps, dict) and rps:
        risk_note = (
            f" Posture: max_name={rps.get('max_single_name_weight_pct')}% "
            f"cash_min={rps.get('cash_band_min_pct')}% "
            f"dd={rps.get('deep_dd_threshold_pct')}%."
        )
    thesis_align = (
        f"Fits {pin} ({stance}): {p0}. "
        f"Escalate material concentration/cash/DD to the operator; avoid force-deploy; "
        f"preserve optionality and evidence quality.{risk_note}"
    )
    base = (
        f"{st} on {sym_s}: fire={fire_s}. "
        f"Under {pin}, synthesize {dom_s} — not detector echo alone."
    )
    # Prefer prior LLM summary if it already has content without deferred marker
    prior = str(plan.get("summary") or "").strip()
    for noise in (
        "[LLM deferred — deterministic view only]",
        "(LLM deferred — deterministic view only)",
        "LLM deferred",
        "deterministic view only",
    ):
        prior = prior.replace(noise, "")
    prior = " ".join(prior.split())
    if prior and len(prior) > 40 and "LLM deferred" not in prior:
        summary = prior
    else:
        summary = base
    # Choose default option by stance
    opt_id = "hold"
    if opts:
        ids = [str(o.get("id") or "") for o in opts if isinstance(o, dict)]
        if stance.startswith("defensive") and any("hold" in i for i in ids):
            opt_id = next(i for i in ids if "hold" in i)
        elif ids:
            opt_id = ids[0]
    rec = (
        f"Highest-signal under {pin} ({stance}): choose {opt_id} — stage/observe rather than "
        f"force action until multi-domain evidence supports size. "
        f"This is non-action as a feature of defensive_observe, not a detector restatement."
    )
    risks = list(plan.get("risks") or [])
    # strip deferred markers from risks
    risks = [
        str(r).replace("[LLM deferred — deterministic view only]", "").replace(
            "(LLM deferred — deterministic view only)", ""
        ).strip()
        for r in risks if r is not None
    ]
    if not risks:
        risks = ["Evidence incomplete", "No auto-execution", f"Thesis {pin} is advisory only"]
    material = bool(pack.get("material"))
    return {
        "summary": summary[:1600],
        "thesis_alignment": thesis_align[:800],
        "multi_domain_summary": multi[:800],
        "options": opts,
        "recommendation": rec[:1600],
        "risks": risks[:8],
        "revisit_hint": "24h or on material evidence change",
        "cited_fields": list(
            {f for r in (pack.get("evidence_refs") or plan.get("evidence_refs") or []) for f in (r.get("fields_used") or [])}
        )[:20],
        "thesis_version": pin,
        # Material uses desk_synthesis (not "LLM deferred") when model blocked
        "narrative_source": "template",
        "llm_deferred": False if material else True,
    }


def _hour_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H")


def _local_hour_calls(counter_path: Path | None = None) -> int:
    path = counter_path or DEFAULT_CALL_COUNTER
    try:
        if not path.exists():
            return 0
        data = json.loads(path.read_text())
        if data.get("hour") != _hour_bucket():
            return 0
        return int(data.get("count") or 0)
    except Exception:
        return 0


def _inc_hour_calls(counter_path: Path | None = None) -> int:
    path = counter_path or DEFAULT_CALL_COUNTER
    path.parent.mkdir(parents=True, exist_ok=True)
    hour = _hour_bucket()
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        data = {}
    if data.get("hour") != hour:
        data = {"hour": hour, "count": 0}
    data["count"] = int(data.get("count") or 0) + 1
    path.write_text(json.dumps(data))
    return int(data["count"])


def _log_enrich(row: dict[str, Any], path: Path | None = None) -> None:
    p = path or DEFAULT_ENRICH_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except Exception:
        pass


def _thesis_block_for_prompt(pack: dict[str, Any], *, max_bullets: int = 4, full: bool = False) -> str:
    """Desk thesis block — full text for material events."""
    th = pack.get("desk_thesis") or {}
    if not isinstance(th, dict) or not th:
        pin = pack.get("thesis_version") or ""
        return f"thesis={pin or 'none'} stance=unknown"
    pin = th.get("thesis_version") or pack.get("thesis_version") or ""
    stance = th.get("stance") or ""
    summary = " ".join(str(th.get("summary") or "").split())
    # Keep thesis ultra-tight — Flash empty_content on fat prompts
    summary = summary[:180] if full else summary[:120]
    bullets = th.get("bullets") or []
    b_s = "; ".join(str(b).strip() for b in bullets[:max_bullets] if str(b).strip())[:160]
    principles = th.get("principles") or []
    p_s = "; ".join(str(x).strip() for x in principles[:3] if str(x).strip())[:140]
    risk_p = str(th.get("risk_posture") or "")[:100]
    rps = th.get("risk_posture_structured") or {}
    if isinstance(rps, dict) and rps:
        risk_p = (
            f"max_name={rps.get('max_single_name_weight_pct')} "
            f"cash_min={rps.get('cash_band_min_pct')} "
            f"dd={rps.get('deep_dd_threshold_pct')} "
            f"conc_fire={rps.get('concentration_fire_pct')}"
        )[:120]
    esc = th.get("escalation_rules") or []
    e_s = "; ".join(str(x).strip() for x in esc[:2] if str(x).strip())[:120]
    linked = th.get("linked_symbols") or []
    link_s = ",".join(str(x) for x in linked[:8])
    learn = pack.get("recent_operator_learning") or th.get("learning_log") or []
    learn_bits = []
    for L in (learn or [])[:4]:
        if isinstance(L, dict):
            learn_bits.append(
                f"{L.get('disposition') or L.get('kind')}:{L.get('situation_type') or ''}:"
                f"{','.join(str(s) for s in (L.get('symbols') or [])[:2])}"
            )
    lines = [
        f"thesis={pin} stance={stance}",
        f"thesis_summary={summary}",
        f"thesis_bullets={b_s}",
        f"thesis_symbols={link_s}",
    ]
    if p_s:
        lines.append(f"principles={p_s}")
    if risk_p:
        lines.append(f"risk_posture={risk_p}")
    if e_s:
        lines.append(f"escalation={e_s}")
    if learn_bits:
        lines.append(f"recent_operator_dispositions={';'.join(learn_bits)}")
    return "\n".join(lines)


def _evidence_lines(refs: list[Any], *, limit: int = 8) -> list[str]:
    lines = []
    for r in refs[:limit]:
        if not isinstance(r, dict):
            continue
        dom = r.get("domain") or "?"
        bits = [f"domain={dom}"]
        for k, v in r.items():
            if k in ("domain", "as_of", "fields_used", "quality_state"):
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                bits.append(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}")
            elif isinstance(v, str) and NUM_RE.fullmatch(v.strip() or ""):
                bits.append(f"{k}={v.strip()}")
            elif isinstance(v, str) and k in ("symbol", "quality_state") and v:
                bits.append(f"{k}={v[:24]}")
        as_of = r.get("as_of")
        if as_of:
            bits.append(f"as_of={str(as_of)[:10]}")
        lines.append("- " + "; ".join(bits))
    return lines


def compact_user_prompt(pack: dict[str, Any], *, minimal: bool = False) -> str:
    """Evidence + full thesis for Flash. Material plans get longer synthesis task.

    minimal=True: ultra-short retry after empty_content / non_json.
    """
    refs = pack.get("evidence_refs") or []
    material = bool(pack.get("material"))

    def _strip_noise(s: str) -> str:
        for n in (
            "[LLM deferred — deterministic view only]",
            "(LLM deferred — deterministic view only)",
            "LLM deferred",
            "deterministic view only",
            "READ_ONLY_ADVISORY",
            "no auto stop",
        ):
            s = s.replace(n, "")
        return " ".join(s.split())

    existing = _strip_noise(str(pack.get("existing_summary") or ""))[:200]
    existing_rec = _strip_noise(str(pack.get("existing_recommendation") or ""))[:120]
    fire = pack.get("fire_reasons") or []
    fire_s = ",".join(str(x) for x in fire[:4])
    thesis = _thesis_block_for_prompt(
        pack, max_bullets=4 if material else 3, full=material and not minimal,
    )
    domains = ",".join(str(d) for d in (pack.get("evidence_domains") or [])[:8])

    key_nums: list[str] = []
    for r in refs[:10]:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if k in ("domain", "as_of", "fields_used", "quality_state"):
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                key_nums.append(f"{v:.4g}" if isinstance(v, float) else str(v))
            elif isinstance(v, str) and NUM_RE.fullmatch(v.strip()):
                key_nums.append(v.strip())
    for tok in NUM_RE.findall(existing + " " + existing_rec + " " + fire_s):
        if tok in ("00", "0", "08", "11") or (len(tok) == 4 and tok.startswith("20")):
            continue
        key_nums.append(tok)
    cleaned: list[str] = []
    seen: set[str] = set()
    for tok in key_nums:
        try:
            f = float(tok)
            pretty = str(int(f)) if abs(f - round(f)) < 1e-9 else f"{f:.2f}"
        except Exception:
            pretty = tok
        if pretty not in seen:
            seen.add(pretty)
            cleaned.append(pretty)
    allowed = ",".join(cleaned[:28])
    opts = pack.get("options_stub") or []
    opt_ids = []
    for o in opts[:5]:
        if isinstance(o, dict):
            opt_ids.append(str(o.get("id") or o.get("label") or "?"))
        else:
            opt_ids.append(str(o))

    pin = pack.get("thesis_version") or (pack.get("desk_thesis") or {}).get("thesis_version") or ""
    ev_lines = _evidence_lines(refs, limit=8 if material else 4)

    # Single compact shape for routine + material (material only adds task emphasis).
    # Long dumps caused Flash empty_content; evidence is one-line domain facts.
    mat_tag = " material=1" if material else ""
    task = (
        f"{'MATERIAL ' if material else ''}Advisory under {pin}. Synthesize domains; never echo fire alone. "
        f"recommendation = option_id + why under {pin}. "
        "Include thesis_alignment and multi_domain_summary. pros/cons complete short strings."
    )
    if minimal:
        return (
            f"{pack.get('situation_type')} symbols={pack.get('symbols')} fire={fire_s}{mat_tag}\n"
            f"thesis={pin} stance={(pack.get('desk_thesis') or {}).get('stance')}\n"
            f"domains={domains}\n"
            f"facts={existing[:140]}\n"
            f"numbers={allowed}\n"
            f"option_ids={opt_ids}\n"
            f"{task}\n"
            'JSON only: summary,thesis_alignment,multi_domain_summary,recommendation,options,'
            f'risks,revisit_hint,cited_fields,thesis_version={pin!r}\n'
            "Numbers only from list. READ_ONLY."
        )
    return (
        f"{pack.get('situation_type')} {pack.get('symbols')} fire={fire_s}{mat_tag}\n"
        f"domains={domains}\n"
        f"{thesis}\n"
        + ("\n".join(ev_lines[:4]) + "\n" if ev_lines else "")
        + f"numbers={allowed}\n"
        f"option_ids={opt_ids}\n"
        f"{task}\n"
        "JSON only {summary,thesis_alignment,multi_domain_summary,recommendation,"
        f"options[{{id,label,pros,cons}}],risks,cited_fields,revisit_hint,thesis_version={pin!r}}}\n"
        "Use only listed numbers. READ_ONLY no orders."
    )


def call_governed_llm(
    messages: list[dict[str, str]],
    policy: dict[str, Any],
    *,
    use_pro: bool = False,
) -> dict[str, Any]:
    """HTTP call to governed bridge. Never hits api.deepseek.com directly.

    Flash path uses advisory_desk / advisory_opinion (FAST). Use compact prompts —
    large JSON evidence packs cause Flash to spend max_tokens on reasoning with
    empty content. Pro path uses alex / cio_synthesis when required.
    """
    llm = policy.get("llm") or {}
    endpoint = llm.get("bridge_endpoint") or "http://127.0.0.1:8766/v1/chat/completions"
    if use_pro:
        caller = llm.get("caller_pro") or "alex"
        task = llm.get("task_type_pro") or "cio_synthesis"
        process_id = "alex_cio_synthesis"
        model = "deepseek-v4-pro"
        max_tokens = int(llm.get("max_tokens_pro") or llm.get("max_tokens") or 1600)
    else:
        # Prefer advisory_desk Flash — not alex PRO — for plan JSON enrichment
        caller = llm.get("caller_flash") or "advisory_desk"
        task = llm.get("task_type_flash") or "advisory_opinion"
        process_id = "advisory_desk_opinion"
        model = "deepseek-v4-flash"
        # Headroom so reasoning_tokens cannot consume entire completion budget
        max_tokens = int(llm.get("max_tokens_flash") or llm.get("max_tokens") or 1200)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(llm.get("temperature") or 0.2),
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "X-TradeAI-Agent": caller,
        "X-TradeAI-Task-Type": task,
        "X-TradeAI-Process-Id": process_id,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {"error": {"message": str(e), "code": f"HTTP_{e.code}"}}
        err = err_body.get("error") or {}
        return {
            "ok": False,
            "error": f"{err.get('code') or e.code}: {err.get('message') or e}",
            "governance_refused": True,
            "governance_code": err.get("code") or f"HTTP_{e.code}",
            "model": model,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "governance_refused": True,
            "governance_code": "PROVIDER_ERROR",
            "model": model,
        }

    if isinstance(body, dict) and body.get("error") and not body.get("choices"):
        err = body.get("error") or {}
        return {
            "ok": False,
            "error": f"{err.get('code')}: {err.get('message')}",
            "governance_refused": True,
            "governance_code": err.get("code") or "GOVERNANCE_ERROR",
            "model": model,
        }
    try:
        msg = body["choices"][0]["message"]
        content = msg.get("content") or ""
        # Fallback: some Flash responses put text only in reasoning fields
        if not str(content).strip():
            content = (
                msg.get("reasoning_content")
                or msg.get("reasoning")
                or ""
            )
    except Exception:
        return {
            "ok": False,
            "error": "malformed_bridge_response",
            "governance_refused": True,
            "governance_code": "MALFORMED",
            "model": model,
        }
    if not str(content).strip():
        usage = body.get("usage") or {}
        return {
            "ok": False,
            "error": "empty_content",
            "governance_refused": False,
            "governance_code": "EMPTY_CONTENT",
            "model": model,
            "usage": usage,
        }
    return {"ok": True, "content": content, "model": model, "raw": body}


def evidence_hash(plan: dict[str, Any]) -> str:
    refs = plan.get("evidence_refs") or []
    raw = json.dumps(refs, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def should_skip_enrich_dedup(
    plan: dict[str, Any],
    policy: dict[str, Any],
) -> bool:
    """Skip re-LLM if same plan enriched recently with same evidence hash."""
    hours = float((policy.get("llm") or {}).get("enrich_dedup_hours") or 6)
    last = plan.get("narrative_enriched_at")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - dt > timedelta(hours=hours):
            return False
    except Exception:
        return False
    prev_hash = plan.get("evidence_hash")
    if prev_hash and prev_hash == evidence_hash(plan) and plan.get("narrative_source") in ("llm", "template"):
        return True
    return False


def enrich_plan(
    plan: dict[str, Any],
    *,
    source: str,
    wake_id: str = "",
    force_template: bool = False,
    force_llm: bool = False,
    extra_context: Optional[dict[str, Any]] = None,
    plan_store: Any = None,
    policy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Enrich a plan dict; optionally persist via plan_store.

    Returns result with keys: plan, narrative_source, llm, log fields.
    Never raises to callers for provider failures.
    """
    pol = policy or load_llm_policy()
    llm_cfg = pol.get("llm") or {}
    t0_enrich = time.time()
    result: dict[str, Any] = {
        "plan_id": plan.get("plan_id"),
        "source": source,
        "wake_id": wake_id,
        "llm": "skipped_non_material",
        "narrative_source": plan.get("narrative_source") or "none",
        "authority": "READ_ONLY_ADVISORY",
    }

    def _trace_update(**kw: Any) -> None:
        try:
            from scripts.lib.cio_wake_traces import safe_update_from_enrich
            safe_update_from_enrich(
                wake_id=str(wake_id or plan.get("plan_id") or ""),
                plan=plan,
                source=source,
                **kw,
            )
        except Exception:
            try:
                from lib.cio_wake_traces import safe_update_from_enrich  # type: ignore
                safe_update_from_enrich(
                    wake_id=str(wake_id or plan.get("plan_id") or ""),
                    plan=plan,
                    source=source,
                    **kw,
                )
            except Exception:
                pass

    def _trace_close(**kw: Any) -> None:
        plan_arg = kw.pop("plan", None) or plan
        dur = int((time.time() - t0_enrich) * 1000)
        try:
            from scripts.lib.cio_wake_traces import safe_close_from_enrich
            safe_close_from_enrich(
                wake_id=str(wake_id or plan_arg.get("plan_id") or plan.get("plan_id") or ""),
                plan=plan_arg,
                source=source,
                duration_ms=dur,
                **kw,
            )
        except Exception:
            try:
                from lib.cio_wake_traces import safe_close_from_enrich  # type: ignore
                safe_close_from_enrich(
                    wake_id=str(wake_id or plan_arg.get("plan_id") or plan.get("plan_id") or ""),
                    plan=plan_arg,
                    source=source,
                    duration_ms=dur,
                    **kw,
                )
            except Exception:
                pass

    if not is_material_source(source, pol) and not force_llm and not force_template:
        result["llm"] = "skipped_non_material"
        _log_enrich({**result, "ts": _now()})
        _trace_close(llm="skipped_non_material", outcome="ok")
        return result

    # Skip dedup when thesis pin is stale vs live desk@vN (must re-pin)
    pin_stale = False
    try:
        from scripts.lib.cio_theses import safe_current_pin
        live = safe_current_pin("desk")
        if live and plan.get("thesis_version") != live:
            pin_stale = True
    except Exception:
        pass
    if (
        should_skip_enrich_dedup(plan, pol)
        and not force_llm
        and not force_template
        and not pin_stale
    ):
        result["llm"] = "skipped_dedup"
        result["narrative_source"] = plan.get("narrative_source") or "template"
        _log_enrich({**result, "ts": _now()})
        _trace_close(
            llm="skipped_dedup",
            narrative_source=result["narrative_source"],
            plan=plan,
            outcome="ok",
        )
        return {**result, "plan": plan}

    # Multi-domain augmentation first so hash + pack share evidence
    plan = augment_multi_domain_evidence(plan)
    pack = build_evidence_pack(plan, extra_context=extra_context)
    ehash = evidence_hash(plan)
    result["material"] = bool(pack.get("material"))
    result["multi_domain_ok"] = bool(pack.get("multi_domain_ok"))
    result["evidence_domains"] = list(pack.get("evidence_domains") or [])
    result["thesis_version"] = pack.get("thesis_version")

    # Material situations: never skip LLM for routine force_template / tests
    # unless CIO_LLM_FORCE_TEMPLATE=1 (true emergency).
    hard_tpl = os.environ.get("CIO_LLM_FORCE_TEMPLATE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if force_template and pack.get("material") and not hard_tpl:
        force_template = False

    use_llm = (
        not force_template
        and bool(llm_cfg.get("enabled", True))
        and bool(pol.get("enabled", True))
    )
    max_hour = int(llm_cfg.get("max_calls_per_hour") or 12)
    if use_llm and _local_hour_calls() >= max_hour:
        use_llm = False
        result["llm"] = "blocked_cap"
    elif not use_llm and force_template:
        result["llm"] = "forced_template"
    elif not use_llm:
        result["llm"] = "blocked_disabled"

    narrative: Optional[dict[str, Any]] = None
    model_id = None

    if use_llm:
        use_pro = source in set(llm_cfg.get("pro_for") or []) or plan.get("situation_type") in set(
            llm_cfg.get("pro_for") or []
        )
        # Prefer Flash for situation plans. Pro only when policy lists source.
        material = is_material_plan(plan) or bool(pack.get("material"))
        system = (
            "You are Alex, Chief Investment Officer for Trade AI (READ_ONLY_ADVISORY). "
            "You manage a coherent portfolio under a living desk thesis (desk@vN). "
            "Output ONE JSON object only — first character must be '{'. "
            "No markdown fences, no chain-of-thought, no prose outside JSON. "
            "Use ONLY numbers listed in the user numbers= line. "
            "Missing → DATA_UNAVAILABLE. Never invent prices/weights/sizes. "
            "GOVERNING CONTEXT: full desk thesis (stance, principles, risk_posture, "
            "escalation_rules). Recommendation MUST cite the exact thesis_version pin "
            "and explain fit or tension with that thesis. "
            "SYNTHESIS: combine all evidence domains (holdings + cash/portfolio + risk). "
            "Never pure-regurgitate detector fire_reasons. "
            "Preserve option ids. options[].pros/cons are complete short strings. "
            + (
                "MATERIAL: include thesis_alignment and multi_domain_summary paragraphs; "
                "summary 3–5 sentences; recommendation names option_id + why highest-signal. "
                if material
                else "ROUTINE: keep tight 2–3 sentence summary; still cite thesis pin. "
            )
            + "Never invent orders, stops, or broker steps."
        )
        # Compact prompts — material tries minimal first (higher Flash success rate).
        max_retries = int((pol.get("validator") or {}).get("max_retries") or 1)
        if material:
            attempt_modes = ["minimal", "compact"]
        else:
            attempt_modes = ["compact"]
            if max_retries >= 1:
                attempt_modes.append("minimal")
        for attempt, mode in enumerate(attempt_modes):
            user = compact_user_prompt(pack, minimal=(mode == "minimal"))
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            llm_res = call_governed_llm(messages, pol, use_pro=use_pro)
            if llm_res.get("model"):
                model_id = llm_res.get("model")
            if not llm_res.get("ok"):
                err = str(llm_res.get("error") or "")
                code = str(llm_res.get("governance_code") or "")
                result["llm_error"] = err
                if "CAP" in code:
                    result["llm"] = "blocked_cap"
                    break
                # empty_content / provider noise → try minimal mode if available
                if mode == "compact" and "minimal" in attempt_modes:
                    result["llm"] = "blocked_provider"
                    continue
                result["llm"] = "blocked_provider"
                break
            parsed = extract_json_object(str(llm_res.get("content") or ""))
            if not parsed:
                result["llm"] = "blocked_provider"
                result["llm_error"] = "non_json_response"
                if mode == "compact" and "minimal" in attempt_modes:
                    continue
                break
            parsed = normalize_narrative(parsed)
            ok, verrs = validate_narrative(
                parsed,
                pack,
                reject_invented=bool((pol.get("validator") or {}).get("reject_invented_numbers", True)),
            )
            if ok:
                narrative = parsed
                narrative["narrative_source"] = "llm"
                narrative["llm_deferred"] = False
                result["llm"] = "invoked"
                result.pop("llm_error", None)
                _inc_hour_calls()
                break
            # one-shot validation repair on the same conversation
            if attempt < len(attempt_modes) - 1 or max_retries >= 1:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Validation failed: {verrs}. "
                        f"Only use numbers from numbers= line ({','.join(str(x) for x in (pack.get('allowed_numeric_tokens') or [])[:20])}). "
                        "Return corrected JSON only. pros/cons as strings."
                    ),
                })
                llm_res2 = call_governed_llm(messages, pol, use_pro=use_pro)
                if llm_res2.get("model"):
                    model_id = llm_res2.get("model")
                if llm_res2.get("ok"):
                    parsed2 = extract_json_object(str(llm_res2.get("content") or ""))
                    if parsed2:
                        parsed2 = normalize_narrative(parsed2)
                        ok2, verrs2 = validate_narrative(
                            parsed2,
                            pack,
                            reject_invented=bool(
                                (pol.get("validator") or {}).get("reject_invented_numbers", True)
                            ),
                        )
                        if ok2:
                            narrative = parsed2
                            narrative["narrative_source"] = "llm"
                            narrative["llm_deferred"] = False
                            result["llm"] = "invoked"
                            result.pop("llm_error", None)
                            _inc_hour_calls()
                            break
                        verrs = verrs2
            result["llm"] = "blocked_provider"
            result["llm_error"] = f"validation_failed:{verrs}"
            break

    if narrative is None:
        narrative = template_narrative_from_plan(plan, pack)
        if result.get("llm") not in ("blocked_cap", "blocked_provider", "blocked_disabled", "forced_template"):
            result["llm"] = "blocked_provider"
        result["narrative_source"] = "template"
    else:
        result["narrative_source"] = "llm"

    # Apply to plan fields
    updated = dict(plan)
    summary = str(narrative.get("summary") or plan.get("summary") or "")
    # Strip prior folded thesis/multi-domain blocks so re-enrich doesn't stack stale pins
    for marker in ("Thesis alignment", "Multi-domain"):
        if marker in summary:
            summary = summary.split(marker)[0].rstrip()
    for noise in (
        "[LLM deferred — deterministic view only]",
        "(LLM deferred — deterministic view only)",
        "LLM deferred — deterministic view only",
    ):
        summary = summary.replace(noise, "")
    summary = summary.strip()
    # Fold material paragraphs into stored summary for Telegram / CC without schema change
    ta = str(narrative.get("thesis_alignment") or "").strip()
    md = str(narrative.get("multi_domain_summary") or "").strip()
    if ta:
        summary = f"{summary}\n\nThesis alignment: {ta}".strip()
    if md:
        summary = f"{summary}\n\nMulti-domain: {md}".strip()
    if pack.get("material"):
        updated_material_flag = True
    else:
        updated_material_flag = False
    updated["summary"] = summary[:2400]
    updated["options"] = narrative.get("options") or plan.get("options")
    rec = str(narrative.get("recommendation") or plan.get("recommendation") or "")
    pin_echo = (
        narrative.get("thesis_version")
        or pack.get("thesis_version")
        or (pack.get("desk_thesis") or {}).get("thesis_version")
    )
    if pin_echo and str(pin_echo) not in rec:
        rec = f"{rec} [{pin_echo}]".strip()
    updated["recommendation"] = rec[:1600]
    updated["risks"] = narrative.get("risks") or plan.get("risks")
    updated["thesis_alignment"] = ta or plan.get("thesis_alignment")
    updated["multi_domain_summary"] = md or plan.get("multi_domain_summary")
    updated["material"] = bool(pack.get("material")) or updated_material_flag
    updated["evidence_domains"] = list(pack.get("evidence_domains") or [])
    # Hermes research depth for material events
    if updated["material"]:
        updated["hermes_suggested"] = True
        hid = maybe_request_hermes(updated)
        if hid:
            updated["hermes_challenge_id"] = hid
            result["hermes_challenge_id"] = hid
    # revisit_at from hint if present
    if narrative.get("revisit_hint") and not plan.get("revisit_at"):
        updated["revisit_at"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    updated["narrative_source"] = result["narrative_source"]
    updated["narrative_enriched_at"] = _now()
    updated["evidence_hash"] = ehash
    updated["evidence_refs"] = plan.get("evidence_refs") or updated.get("evidence_refs")
    updated["llm_model"] = model_id
    updated["llm_status"] = result["llm"]
    if narrative.get("llm_deferred"):
        updated["llm_deferred"] = True
    # Always pin the LIVE desk thesis used for this enrichment (desk@v4+)
    try:
        from scripts.lib.cio_theses import safe_current_pin
        pin = safe_current_pin("desk") or pin_echo
        if pin:
            updated["thesis_version"] = pin
            result["thesis_version"] = pin
    except Exception:
        if pin_echo:
            updated["thesis_version"] = pin_echo
            result["thesis_version"] = pin_echo
    # Strip any residual deferred markers from stored text
    for fld in ("summary", "recommendation"):
        val = str(updated.get(fld) or "")
        for noise in (
            "[LLM deferred — deterministic view only]",
            "(LLM deferred — deterministic view only)",
            "LLM deferred — deterministic view only",
        ):
            val = val.replace(noise, "")
        updated[fld] = " ".join(val.split())

    # Persist
    if plan_store is not None and updated.get("plan_id"):
        try:
            plan_store.update_plan(
                updated["plan_id"],
                summary=updated.get("summary"),
                options=updated.get("options"),
                recommendation=updated.get("recommendation"),
                risks=updated.get("risks"),
                evidence_refs=updated.get("evidence_refs"),
                status="proposed" if result["narrative_source"] == "llm" else plan.get("status") or "draft",
                actor_id="cio_plan_enrichment",
                thesis_version=updated.get("thesis_version"),
                thesis_alignment=updated.get("thesis_alignment"),
                multi_domain_summary=updated.get("multi_domain_summary"),
                material=updated.get("material"),
                evidence_domains=updated.get("evidence_domains"),
                narrative_source=updated.get("narrative_source"),
                llm_status=updated.get("llm_status") or result.get("llm"),
                llm_model=updated.get("llm_model"),
            )
            # store enrichment metadata via second update using allowed fields only —
            # put extras via update that merges if we add fields... update_plan only allows certain fields.
            # Re-read and patch projection for narrative metadata by creating a lightweight PLAN_UPDATED
            # through a small helper:
            _patch_plan_meta(
                plan_store,
                updated["plan_id"],
                {
                    "narrative_source": updated.get("narrative_source"),
                    "narrative_enriched_at": updated.get("narrative_enriched_at"),
                    "evidence_hash": updated.get("evidence_hash"),
                    "evidence_refs": updated.get("evidence_refs"),
                    "llm_model": updated.get("llm_model"),
                    "llm_status": updated.get("llm_status"),
                    "llm_deferred": updated.get("llm_deferred"),
                    "thesis_version": updated.get("thesis_version"),
                    "thesis_alignment": updated.get("thesis_alignment"),
                    "multi_domain_summary": updated.get("multi_domain_summary"),
                    "material": updated.get("material"),
                    "evidence_domains": updated.get("evidence_domains"),
                },
            )
            refreshed = plan_store.get_plan(updated["plan_id"])
            if refreshed:
                updated = refreshed
        except Exception as exc:
            result["persist_error"] = f"{type(exc).__name__}:{exc}"

    # optional event
    try:
        from scripts.lib.cio_event_bus import CIOEventBus
        CIOEventBus().emit(
            "plan.enriched",
            {
                "plan_id": updated.get("plan_id"),
                "narrative_source": result["narrative_source"],
                "llm": result["llm"],
                "source": source,
                "wake_id": wake_id,
            },
            source="cio_plan_enrichment",
            priority="LOW",
        )
    except Exception:
        pass

    result["plan"] = updated
    result["narrative_source"] = updated.get("narrative_source") or result["narrative_source"]
    _log_enrich({**{k: result[k] for k in result if k != "plan"}, "ts": _now(), "model": model_id})
    # P5: close/update wake trace with final llm path (fail-soft)
    _llm = result.get("llm") or "template"
    # Prefer schema values: template when narrative is template unless already blocked_cap
    if result.get("narrative_source") == "template" and _llm not in (
        "blocked_cap", "blocked_provider", "blocked_disabled", "forced_template", "skipped_dedup",
    ):
        # keep blocked_* ; map generic provider fallthrough
        pass
    _trace_close(
        llm=_llm,
        model_id=model_id,
        narrative_source=result.get("narrative_source"),
        llm_error=result.get("llm_error") or result.get("persist_error"),
        plan=updated,
        outcome="deferred" if _llm == "blocked_cap" else "ok",
    )
    return result


def _patch_plan_meta(store: Any, plan_id: str, meta: dict[str, Any]) -> None:
    """Best-effort: append PLAN_UPDATED with meta keys if store allows free patch."""
    try:
        # Direct projection patch via internal event if available
        if hasattr(store, "_append_event"):
            store._append_event(
                "PLAN_UPDATED",
                plan_id,
                {**meta, "updated_ts": _now()},
                actor_id="cio_plan_enrichment",
            )
    except Exception:
        pass


def _notify_ledger_path(path: Path | None = None) -> Path:
    return Path(path) if path else DEFAULT_NOTIFY_LEDGER


def _load_notify_ledger(path: Path | None = None) -> dict[str, Any]:
    p = _notify_ledger_path(path)
    try:
        if p.exists():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_notify_ledger(ledger: dict[str, Any], path: Path | None = None) -> None:
    p = _notify_ledger_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True, default=str) + "\n")
    tmp.replace(p)


def notify_fingerprint(plan: dict[str, Any]) -> str:
    """Stable fingerprint of situation material content for re-notify gating.

    Same plan_id + same evidence_hash (or fire_reasons + refs) → no re-notify.
    Material change (new evidence hash / fire reasons) → may re-notify.
    """
    pid = str(plan.get("plan_id") or "")
    eh = plan.get("evidence_hash")
    if not eh:
        try:
            eh = evidence_hash(plan)
        except Exception:
            eh = ""
    fire = plan.get("fire_reasons") or (plan.get("extra") or {}).get("fire_reasons") or []
    fire_s = ",".join(str(x) for x in fire[:8])
    raw = f"{pid}|{eh}|{fire_s}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def should_skip_notify(
    plan: dict[str, Any],
    *,
    force: bool = False,
    policy: Optional[dict[str, Any]] = None,
    ledger_path: Path | None = None,
) -> tuple[bool, str]:
    """Return (skip, reason). Re-enrich must not re-push by default.

    Skip when:
      - plan_id already notified with same fingerprint (material unchanged)
      - plan_id notified within notify_cooldown_hours (default 12) even if
        fingerprint missing on older rows
    Allow when:
      - force=True or CIO_SITUATION_NOTIFY_FORCE=1
      - fingerprint changed (new evidence / fire reasons)
      - never notified
    """
    if force or os.environ.get("CIO_SITUATION_NOTIFY_FORCE", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False, "force"
    pol = policy or load_llm_policy()
    # once-per-fingerprint is default on
    if pol.get("notify_once_per_fingerprint", True) is False:
        return False, "once_disabled"
    pid = str(plan.get("plan_id") or "")
    if not pid:
        return True, "no_plan_id"
    fp = notify_fingerprint(plan)
    try:
        cooldown_h = float(pol["notify_cooldown_hours"]) if "notify_cooldown_hours" in pol else 12.0
    except (TypeError, ValueError):
        cooldown_h = 12.0
    ledger = _load_notify_ledger(ledger_path)
    row = ledger.get(pid) or {}
    prev_fp = str(row.get("fingerprint") or "")
    prev_ts = row.get("ts")
    if prev_fp and prev_fp == fp:
        return True, "already_notified_same_fingerprint"
    # Short cooldown even when fingerprint missing/legacy
    if prev_ts and not prev_fp:
        try:
            dt = datetime.fromisoformat(str(prev_ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - dt < timedelta(hours=cooldown_h):
                return True, "cooldown_no_fingerprint"
        except Exception:
            pass
    if prev_ts and prev_fp and prev_fp != fp:
        # material change → allow (optional min gap to avoid thrash)
        try:
            min_gap_m = float(pol["notify_min_gap_minutes"]) if "notify_min_gap_minutes" in pol else 5.0
        except (TypeError, ValueError):
            min_gap_m = 5.0
        if min_gap_m > 0:
            try:
                dt = datetime.fromisoformat(str(prev_ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - dt < timedelta(minutes=min_gap_m):
                    return True, "min_gap_after_prior_notify"
            except Exception:
                pass
        return False, "material_change"
    return False, "first_notify"


def record_notify(
    plan: dict[str, Any],
    *,
    ok: bool,
    ledger_path: Path | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Persist successful (or attempted) notify for plan_id."""
    pid = str(plan.get("plan_id") or "")
    if not pid or not ok:
        return
    ledger = _load_notify_ledger(ledger_path)
    prev = ledger.get(pid) or {}
    ledger[pid] = {
        "plan_id": pid,
        "ts": _now(),
        "fingerprint": notify_fingerprint(plan),
        "evidence_hash": plan.get("evidence_hash") or evidence_hash(plan),
        "situation_type": plan.get("situation_type"),
        "symbols": list(plan.get("symbols") or []),
        "count": int(prev.get("count") or 0) + 1,
        **(extra or {}),
    }
    _save_notify_ledger(ledger, ledger_path)


def maybe_notify_plan(
    plan: dict[str, Any],
    policy: Optional[dict[str, Any]] = None,
    *,
    force: bool = False,
    ledger_path: Path | None = None,
) -> bool:
    """Optional Telegram notify via dedicated CIO bot. Default off.

    Requires CIO_SITUATION_NOTIFY=1 (or policy situation_notify_telegram) and
    TELEGRAM_CIO_BOT_TOKEN + allowlist. Never uses OpenClaw main bot.

    Re-notify guard: same plan_id + same fingerprint is notified at most once
    (unless force=True / CIO_SITUATION_NOTIFY_FORCE=1, or evidence/fire_reasons change).
    Re-enrichment alone must not re-push.
    """
    pol = policy or load_llm_policy()
    env_on = os.environ.get("CIO_SITUATION_NOTIFY", "0").strip().lower() in ("1", "true", "yes", "on")
    # Fail-closed: need env OR policy flag (prefer env for host ops)
    if not env_on and not pol.get("situation_notify_telegram"):
        return False
    # only draft/proposed plans
    if plan.get("status") not in ("proposed", "draft"):
        return False
    # Prefer high-value situation types for notify (S1/S2/S5/S6/S8)
    st = str(plan.get("situation_type") or "")
    allow_types = set(pol.get("notify_situation_types") or [
        "S1_POSITION_LIFECYCLE",
        "S2_STOP_GAP",
        "S5_CASH_DEPLOYMENT",
        "S6_CONCENTRATION_OR_DISPOSITION",
        "S8_DEFENSIVE_REGIME",
        "S0_OPERATOR_CONVERSE",
    ])
    if st and allow_types and st not in allow_types:
        return False

    # Multi-domain synthesis required for notified material plans (desk@v2+)
    # Routine converse (S0) exempt; force bypasses.
    if not force and st != "S0_OPERATOR_CONVERSE":
        domains = plan.get("evidence_domains") or []
        if not domains:
            domains = [
                str(r.get("domain"))
                for r in (plan.get("evidence_refs") or [])
                if isinstance(r, dict) and r.get("domain")
            ]
        multi_ok = plan.get("_multi_domain_ok")
        if multi_ok is None:
            multi_ok = len(set(domains)) >= 2
        if is_material_plan(plan) and not multi_ok:
            try:
                _log_enrich({
                    "ts": _now(),
                    "plan_id": plan.get("plan_id"),
                    "llm": "notify_skipped",
                    "narrative_source": plan.get("narrative_source"),
                    "source": st,
                    "notify_skip": "multi_domain_required",
                    "evidence_domains": domains,
                    "authority": "READ_ONLY_ADVISORY",
                })
            except Exception:
                pass
            return False

    skip, skip_reason = should_skip_notify(
        plan, force=force, policy=pol, ledger_path=ledger_path,
    )
    if skip:
        try:
            _log_enrich({
                "ts": _now(),
                "plan_id": plan.get("plan_id"),
                "llm": "notify_skipped",
                "narrative_source": plan.get("narrative_source"),
                "source": st,
                "notify_skip": skip_reason,
                "authority": "READ_ONLY_ADVISORY",
            })
        except Exception:
            pass
        return False

    try:
        from scripts.lib.cio_telegram_converse import (
            allowlist_chat_ids,
            format_structured_reply,
            send_cio_message,
        )
        goals = plan.get("linked_goal_ids") or []
        # Why this fired (from detector) — one short line for operator clarity
        fire = plan.get("fire_reasons") or (plan.get("extra") or {}).get("fire_reasons") or []
        why = ""
        if fire:
            why = "Why: " + ", ".join(str(x) for x in fire[:4]) + "\n"
        text = why + format_structured_reply(
            summary=plan.get("summary") or plan.get("title") or "",
            evidence_refs=plan.get("evidence_refs"),
            options=plan.get("options"),
            recommendation=plan.get("recommendation") or "",
            risks=plan.get("risks"),
            plan_id=plan.get("plan_id"),
            goal_id=(goals[0] if goals else None),
            revisit_at=plan.get("revisit_at"),
            thesis_version=plan.get("thesis_version"),
            situation_type=st,
            llm_deferred=plan.get("narrative_source") == "template",
            deep_links=plan.get("cc_deep_links"),
            symbols=plan.get("symbols"),
        )
        chats = allowlist_chat_ids()
        if not chats:
            return False
        ok_any = False
        for cid in chats:
            r = send_cio_message(cid, text)
            ok_any = ok_any or bool(r.get("ok"))
        if ok_any:
            record_notify(plan, ok=True, ledger_path=ledger_path)
            # best-effort plan meta so operators can see notify state
            try:
                if plan.get("plan_id"):
                    plan["telegram_notified_at"] = _now()
                    plan["telegram_notify_fingerprint"] = notify_fingerprint(plan)
            except Exception:
                pass
        return ok_any
    except Exception:
        return False
