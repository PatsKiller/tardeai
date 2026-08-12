"""LLM-as-judge for CIO advisories via DeepSeek Flash (governed bridge).

Does NOT send Telegram, change recommendations, or mutate thesis.
Scores are advisory for prompt promotion; operator rate/dispositions win.
"""
from __future__ import annotations

import json
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_prompt_eval import (
    QUALITY_WEIGHTS,
    PROBE_PLAN_IDS,
    score_quality,
    record_eval,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def advisory_text_from_plan(plan: dict[str, Any]) -> str:
    lines = [
        f"thesis_version: {plan.get('thesis_version') or ''}",
        f"situation: {plan.get('situation_type')} symbols={plan.get('symbols')}",
        "",
        "SUMMARY:",
        str(plan.get("summary") or ""),
        "",
        "THESIS_ALIGNMENT:",
        str(plan.get("thesis_alignment") or ""),
        "",
        "MULTI_DOMAIN:",
        str(plan.get("multi_domain_summary") or ""),
        "",
        "OPTIONS:",
    ]
    for i, o in enumerate(plan.get("options") or [], 1):
        if not isinstance(o, dict):
            continue
        lines.append(f"{i}. {o.get('id') or o.get('label')}: {o.get('label')}")
        lines.append(f"   + {o.get('pros') or ''}")
        lines.append(f"   - {o.get('cons') or ''}")
    lines += ["", "RECOMMENDATION:", str(plan.get("recommendation") or ""), "", "RISKS:"]
    for r in plan.get("risks") or []:
        lines.append(f"- {r}")
    return "\n".join(lines)


def evidence_pack_for_judge(plan: dict[str, Any]) -> str:
    rows = []
    for r in (plan.get("evidence_refs") or [])[:12]:
        if not isinstance(r, dict):
            continue
        bits = [f"domain={r.get('domain')}", f"as_of={str(r.get('as_of') or '')[:19]}"]
        for k, v in r.items():
            if k in ("domain", "as_of", "fields_used", "quality_state"):
                continue
            if isinstance(v, (int, float)):
                bits.append(f"{k}={v}")
            elif isinstance(v, str) and len(v) < 48:
                bits.append(f"{k}={v}")
        if r.get("quality_state"):
            bits.append(f"quality={r.get('quality_state')}")
        rows.append("- " + "; ".join(bits))
    domains = plan.get("evidence_domains") or []
    head = f"domains={','.join(str(d) for d in domains[:10]) or 'DATA_UNAVAILABLE'}"
    body = "\n".join(rows) if rows else "(no evidence_refs on plan)"
    return head + "\n" + body


def thesis_block_for_judge() -> str:
    try:
        try:
            from scripts.lib.cio_theses import safe_context_block, safe_current_pin
        except Exception:
            from lib.cio_theses import safe_context_block, safe_current_pin  # type: ignore
        pin = safe_current_pin("desk")
        try:
            th = safe_context_block("desk", full=True) or {}
        except TypeError:
            th = safe_context_block("desk") or {}
        rps = th.get("risk_posture_structured") or {}
        lines = [
            f"thesis_version={pin or th.get('thesis_version')}",
            f"stance={th.get('stance')}",
            f"authority={th.get('authority') or 'READ_ONLY_ADVISORY'}",
            f"summary={(' '.join(str(th.get('summary') or '').split()))[:320]}",
        ]
        if isinstance(rps, dict) and rps:
            lines.append(
                "risk_posture_structured: "
                f"max_name={rps.get('max_single_name_weight_pct')} "
                f"cash_min={rps.get('cash_band_min_pct')} "
                f"deep_dd={rps.get('deep_dd_threshold_pct')} "
                f"conc_fire={rps.get('concentration_fire_pct')}"
            )
        principles = th.get("principles") or []
        if principles:
            lines.append("principles: " + " | ".join(str(x) for x in principles[:6]))
        return "\n".join(lines)
    except Exception as e:
        return f"thesis=DATA_UNAVAILABLE ({type(e).__name__})"


def _parse_judge_json(content: str) -> Optional[dict[str, Any]]:
    if not content:
        return None
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _normalize_defects(defects: list[Any]) -> list[str]:
    out = []
    for d in defects:
        dl = str(d).lower().replace(" ", "_")
        if "execution" in dl or "buy_now" in dl or "place_stop" in dl:
            out.append("execution_language")
        elif "invent" in dl:
            out.append("invented_numbers")
        elif "missing_rec" in dl or "missing_recommendation" in dl:
            out.append("missing_recommendation")
        elif "footer" in dl:
            out.append("thesis_footer_only")
        elif "truncat" in dl:
            out.append("truncated_options")
        else:
            out.append(dl)
    return out


def llm_judge_plan(
    plan: dict[str, Any],
    *,
    persist: bool = True,
    plan_store: Any = None,
    policy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Score advisory with DeepSeek Flash. Never notifies or rewrites recommendation."""
    try:
        try:
            from scripts.lib.cio_prompt_loader import load_active_judge, render_user_prompt
        except Exception:
            from lib.cio_prompt_loader import load_active_judge, render_user_prompt  # type: ignore
        try:
            from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy, extract_json_object
        except Exception:
            from lib.cio_plan_enrichment import call_governed_llm, load_llm_policy, extract_json_object  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"import:{type(e).__name__}:{e}", "scored_by": "llm_judge"}

    judge = load_active_judge()
    pol = dict(policy or load_llm_policy())
    llm = dict(pol.get("llm") or {})
    llm["temperature"] = float(judge.get("temperature") or 0.1)
    llm["max_tokens_flash"] = int(judge.get("max_tokens") or 900)
    pol["llm"] = llm

    syms = plan.get("symbols") or []
    symbol = str(syms[0]) if syms else "null"
    # Full template for provenance; Flash gets a compact user body to leave tokens for JSON
    # (Flash often spends the full budget on reasoning_tokens → empty content if max_tokens too low)
    full_user = render_user_prompt(
        str(judge.get("user_template") or ""),
        variables={
            "thesis_block": thesis_block_for_judge()[:1400],
            "situation_type": plan.get("situation_type") or "",
            "symbol": symbol,
            "plan_id": plan.get("plan_id") or "",
            "thesis_version": plan.get("thesis_version") or "",
            "prompt_version": plan.get("prompt_version") or "",
            "evidence_pack": evidence_pack_for_judge(plan)[:1800],
            "advisory_text": advisory_text_from_plan(plan)[:3200],
        },
    )
    # Compact Flash packet: keep rubric in system, shrink user
    compact_user = (
        f"THESIS:\n{thesis_block_for_judge()[:1000]}\n\n"
        f"SITUATION: type={plan.get('situation_type')} symbol={symbol} "
        f"plan_id={plan.get('plan_id')} thesis={plan.get('thesis_version')} "
        f"prompt={plan.get('prompt_version')}\n\n"
        f"EVIDENCE:\n{evidence_pack_for_judge(plan)[:1200]}\n\n"
        f"ADVISORY:\n{advisory_text_from_plan(plan)[:2800]}\n\n"
        "Return ONLY JSON with keys: scores "
        "(thesis_use,synthesis,options,recommendation,evidence,tone as 1-5), "
        "rationales (one line each), critical_defects (list), summary (one sentence)."
    )
    system = str(judge.get("system") or "")
    # Prefer compact system for Flash budget (full system still recorded in judge_prompt_version)
    if len(system) > 2200:
        system_flash = system[:2200] + "\nOutput ONLY valid JSON. No markdown."
    else:
        system_flash = system
    messages = [
        {"role": "system", "content": system_flash},
        {"role": "user", "content": compact_user},
    ]
    llm["max_tokens_flash"] = max(int(judge.get("max_tokens") or 900), 4096)
    pol["llm"] = llm
    llm_res = call_governed_llm(messages, pol, use_pro=False)
    # One retry with even tighter user if empty_content
    if not llm_res.get("ok") and "empty" in str(llm_res.get("error") or "").lower():
        tight = (
            f"Score 1-5: thesis_use synthesis options recommendation evidence tone.\n"
            f"pin={plan.get('thesis_version')} type={plan.get('situation_type')} "
            f"symbols={plan.get('symbols')}\n"
            f"summary={(plan.get('summary') or '')[:450]}\n"
            f"thesis_alignment={(plan.get('thesis_alignment') or '')[:350]}\n"
            f"multi_domain={(plan.get('multi_domain_summary') or '')[:350]}\n"
            f"recommendation={(plan.get('recommendation') or '')[:350]}\n"
            f"options={json.dumps(plan.get('options') or [], default=str)[:500]}\n"
            f"domains={plan.get('evidence_domains')}\n"
            "JSON only: scores,rationales,critical_defects,summary"
        )
        llm_res = call_governed_llm(
            [
                {"role": "system", "content": (
                    "Judge CIO advisory. READ_ONLY. Non-action can be 5. "
                    "Do not reward length. JSON only."
                )},
                {"role": "user", "content": tight},
            ],
            pol,
            use_pro=False,
        )
    if not llm_res.get("ok"):
        return {
            "ok": False,
            "error": llm_res.get("error") or "judge_llm_failed",
            "governance_code": llm_res.get("governance_code"),
            "judge_prompt_version": judge.get("judge_prompt_version"),
            "judge_content_hash": judge.get("content_hash"),
            "model": llm_res.get("model") or judge.get("model"),
            "scored_by": "llm_judge",
            "scored_ts": _now(),
            "calibration_status": "shadow",
        }

    content = str(llm_res.get("content") or "")
    parsed = None
    try:
        parsed = extract_json_object(content)
    except Exception:
        parsed = None
    if not parsed:
        parsed = _parse_judge_json(content)
    if not parsed or not isinstance(parsed, dict):
        return {
            "ok": False,
            "error": "judge_non_json",
            "raw_preview": content[:500],
            "judge_prompt_version": judge.get("judge_prompt_version"),
            "model": llm_res.get("model"),
            "scored_by": "llm_judge",
            "scored_ts": _now(),
            "calibration_status": "shadow",
        }

    raw_scores = parsed.get("scores") or {}
    clean: dict[str, float] = {}
    for k in QUALITY_WEIGHTS:
        try:
            clean[k] = max(1.0, min(5.0, float(raw_scores.get(k))))
        except Exception:
            clean[k] = 1.0
    recomputed = score_quality(clean)
    total = recomputed.get("total")

    defects = parsed.get("critical_defects") or []
    if not isinstance(defects, list):
        defects = [str(defects)]
    critical_norm = _normalize_defects(defects)
    structural_fail = any(
        x in critical_norm for x in ("execution_language", "invented_numbers", "missing_recommendation")
    )

    out: dict[str, Any] = {
        "ok": True,
        "plan_id": plan.get("plan_id"),
        "prompt_version": plan.get("prompt_version"),
        "thesis_version": plan.get("thesis_version"),
        "judge_prompt_version": judge.get("judge_prompt_version"),
        "judge_content_hash": judge.get("content_hash"),
        "model": llm_res.get("model") or judge.get("model"),
        "scores_raw": raw_scores,
        "scores": clean,
        "total": total,
        "total_100": recomputed.get("total_100"),
        "rationales": parsed.get("rationales") or {},
        "critical_defects": critical_norm,
        "summary": str(parsed.get("summary") or "")[:400],
        "structural_fail_from_judge": structural_fail,
        "scored_by": "llm_judge",
        "scored_ts": _now(),
        "weights_applied": True,
        "calibration_status": "shadow",
    }

    if persist and plan.get("plan_id"):
        try:
            if plan_store is None:
                try:
                    from scripts.lib.cio_plans import CIOPlanStore
                    plan_store = CIOPlanStore()
                except Exception:
                    from lib.cio_plans import CIOPlanStore  # type: ignore
                    plan_store = CIOPlanStore()
            plan_store.update_plan(
                str(plan.get("plan_id")),
                eval_judge_total=total,
                eval_judge_scores=json.dumps(clean, sort_keys=True),
                judge_prompt_version=judge.get("judge_prompt_version"),
                judge_scored_ts=out["scored_ts"],
                actor_id="cio_llm_judge",
            )
        except Exception as e:
            out["persist_error"] = f"{type(e).__name__}:{e}"

    try:
        record_eval(
            str(plan.get("plan_id") or ""),
            str(plan.get("prompt_version") or "unknown"),
            structural=None,
            quality={
                "quality": clean,
                "total": total,
                "scored_by": "llm_judge",
                "judge_prompt_version": judge.get("judge_prompt_version"),
                "critical_defects": critical_norm,
                "summary": out.get("summary"),
            },
            thesis_version=str(plan.get("thesis_version") or ""),
        )
    except Exception:
        pass

    return out


def judge_probe_set(*, persist: bool = True) -> dict[str, Any]:
    try:
        from scripts.lib.cio_plans import CIOPlanStore
        store = CIOPlanStore()
    except Exception:
        from lib.cio_plans import CIOPlanStore  # type: ignore
        store = CIOPlanStore()
    rows = []
    for pid in PROBE_PLAN_IDS:
        plan = store.get_plan(pid)
        if not plan:
            rows.append({"plan_id": pid, "ok": False, "error": "not_found"})
            continue
        rows.append(llm_judge_plan(plan, persist=persist, plan_store=store))
    totals = [r.get("total") for r in rows if r.get("ok") and r.get("total") is not None]
    mean = round(sum(totals) / len(totals), 2) if totals else None
    return {
        "probes": rows,
        "mean_judge_total": mean,
        "n_ok": sum(1 for r in rows if r.get("ok")),
        "n": len(rows),
        "calibration_status": "shadow",
        "note": (
            "Operator rate remains ground truth. Judge is promotion-assist only until "
            "gold-set calibration freezes judge@vN."
        ),
    }


if __name__ == "__main__":
    import sys
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "probe").strip()
    if cmd == "probe":
        print(json.dumps(judge_probe_set(), indent=2, default=str))
    elif cmd == "score" and len(sys.argv) > 2:
        from scripts.lib.cio_plans import CIOPlanStore
        plan = CIOPlanStore().get_plan(sys.argv[2])
        if not plan:
            print(json.dumps({"ok": False, "error": "plan_not_found"}))
            raise SystemExit(1)
        print(json.dumps(llm_judge_plan(plan), indent=2, default=str))
    else:
        print("Usage: python -m scripts.lib.cio_prompt_judge probe|score <plan_id>")
        raise SystemExit(2)
