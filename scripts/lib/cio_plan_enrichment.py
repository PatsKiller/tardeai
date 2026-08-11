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


def build_evidence_pack(plan: dict[str, Any], *, extra_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Strict context block for the model."""
    facts = evidence_facts_from_plan(plan)
    pack = {
        "authority": "READ_ONLY_ADVISORY",
        "instruction": (
            "Use ONLY the facts in this pack. If a field is missing, write DATA_UNAVAILABLE. "
            "Never invent prices, targets, stops, or weights. Output JSON only matching the schema. "
            "Advisory only — no order/stop execution language."
        ),
        "situation_type": plan.get("situation_type"),
        "symbols": plan.get("symbols") or [],
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "existing_summary": plan.get("summary") or "",
        "existing_recommendation": plan.get("recommendation") or "",
        "options_stub": facts.get("_options_stub") or [],
        "evidence_refs": facts.get("_evidence_refs") or [],
        "allowed_numeric_tokens": facts.get("_allowed_numeric_tokens") or [],
        "fire_reasons": plan.get("fire_reasons") or [],
        "extra_context": extra_context or {},
        "output_schema": {
            "summary": "string",
            "options": [{"id": "string", "label": "string", "pros": "string", "cons": "string"}],
            "recommendation": "string",
            "risks": ["string"],
            "revisit_hint": "string",
            "cited_fields": ["string"],
        },
    }
    return pack


def collect_allowed_numbers(pack: dict[str, Any]) -> set[str]:
    allowed = set(str(x) for x in (pack.get("allowed_numeric_tokens") or []))
    # always allow small structural ints used in counts
    allowed.update({str(i) for i in range(0, 25)})
    blob = json.dumps(pack, default=str)
    for tok in NUM_RE.findall(blob):
        allowed.add(tok)
    return allowed


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    # fenced
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # raw object
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


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
                    "pros": str(o.get("pros") or ""),
                    "cons": str(o.get("cons") or ""),
                })
            elif isinstance(o, str) and o.strip():
                norm.append({"id": f"opt_{i}", "label": o.strip(), "pros": "", "cons": ""})
        out["options"] = norm
    risks = out.get("risks")
    if isinstance(risks, str):
        out["risks"] = [risks]
    elif not isinstance(risks, list):
        out["risks"] = []
    if not isinstance(out.get("cited_fields"), list):
        out["cited_fields"] = []
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
    for tok in NUM_RE.findall(blob):
        if tok not in allowed:
            # allow year-like 2026 and iso fragments already in pack
            if len(tok) == 4 and tok.startswith("20"):
                continue
            invented.append(tok)
    if invented:
        errs.append(f"invented_numbers:{sorted(set(invented))[:12]}")
    return (len(errs) == 0), errs


def template_narrative_from_plan(plan: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Deterministic enrichment when LLM blocked."""
    opts = plan.get("options") or pack.get("options_stub") or []
    if not opts:
        opts = [
            {"id": "hold", "label": "Hold", "pros": "No change", "cons": "Risk remains"},
            {"id": "review", "label": "Review with more evidence", "pros": "Safer", "cons": "Delay"},
        ]
    summary = plan.get("summary") or plan.get("title") or "Advisory plan (template)"
    # ensure LLM deferred marker for operator clarity
    if "LLM deferred" not in summary and "template" not in summary.lower():
        summary = f"{summary} [LLM deferred — deterministic view only]"
    rec = plan.get("recommendation") or (
        "Review evidence_refs and options. READ_ONLY_ADVISORY — no auto execution."
    )
    if "LLM deferred" not in rec:
        rec = f"{rec} (LLM deferred — deterministic view only)"
    risks = list(plan.get("risks") or ["Evidence incomplete", "No auto-execution"])
    return {
        "summary": summary[:1200],
        "options": opts,
        "recommendation": rec[:1200],
        "risks": risks[:8],
        "revisit_hint": "24h or on material evidence change",
        "cited_fields": list(
            {f for r in (plan.get("evidence_refs") or []) for f in (r.get("fields_used") or [])}
        )[:20],
        "narrative_source": "template",
        "llm_deferred": True,
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


def call_governed_llm(
    messages: list[dict[str, str]],
    policy: dict[str, Any],
    *,
    use_pro: bool = False,
) -> dict[str, Any]:
    """HTTP call to governed bridge. Never hits api.deepseek.com directly.

    Flash path uses advisory_desk / advisory_opinion (FAST) — reliable JSON under
    modest max_tokens. Pro path uses alex / cio_synthesis (PRO); needs higher
    max_tokens because Pro-think can burn completion budget on reasoning.
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
        max_tokens = int(llm.get("max_tokens") or 700)
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
        with urllib.request.urlopen(req, timeout=45) as resp:
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
        content = body["choices"][0]["message"]["content"]
    except Exception:
        return {
            "ok": False,
            "error": "malformed_bridge_response",
            "governance_refused": True,
            "governance_code": "MALFORMED",
            "model": model,
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
    result: dict[str, Any] = {
        "plan_id": plan.get("plan_id"),
        "source": source,
        "wake_id": wake_id,
        "llm": "skipped_non_material",
        "narrative_source": plan.get("narrative_source") or "none",
        "authority": "READ_ONLY_ADVISORY",
    }

    if not is_material_source(source, pol) and not force_llm and not force_template:
        result["llm"] = "skipped_non_material"
        _log_enrich({**result, "ts": _now()})
        return result

    if should_skip_enrich_dedup(plan, pol) and not force_llm and not force_template:
        result["llm"] = "skipped_dedup"
        result["narrative_source"] = plan.get("narrative_source") or "template"
        _log_enrich({**result, "ts": _now()})
        return {**result, "plan": plan}

    pack = build_evidence_pack(plan, extra_context=extra_context)
    ehash = evidence_hash(plan)

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
        system = (
            "You are Alex, CIO advisory (READ_ONLY). "
            "Use only facts in the user evidence pack. "
            "Never invent numbers. Missing → DATA_UNAVAILABLE. "
            "Return JSON only per output_schema."
        )
        user = json.dumps(pack, indent=2, default=str)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        max_retries = int((pol.get("validator") or {}).get("max_retries") or 1)
        for attempt in range(max_retries + 1):
            llm_res = call_governed_llm(messages, pol, use_pro=use_pro)
            if not llm_res.get("ok"):
                result["llm"] = (
                    "blocked_cap"
                    if "CAP" in str(llm_res.get("governance_code") or "")
                    else "blocked_provider"
                )
                result["llm_error"] = llm_res.get("error")
                break
            model_id = llm_res.get("model")
            parsed = extract_json_object(str(llm_res.get("content") or ""))
            if not parsed:
                result["llm"] = "blocked_provider"
                result["llm_error"] = "non_json_response"
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
                _inc_hour_calls()
                break
            if attempt < max_retries:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Validation failed: {verrs}. "
                        f"Only use numbers from allowed_numeric_tokens={pack.get('allowed_numeric_tokens')}. "
                        "Return corrected JSON only."
                    ),
                })
                continue
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
    updated["summary"] = narrative.get("summary") or plan.get("summary")
    updated["options"] = narrative.get("options") or plan.get("options")
    updated["recommendation"] = narrative.get("recommendation") or plan.get("recommendation")
    updated["risks"] = narrative.get("risks") or plan.get("risks")
    # revisit_at from hint if present
    if narrative.get("revisit_hint") and not plan.get("revisit_at"):
        updated["revisit_at"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    updated["narrative_source"] = result["narrative_source"]
    updated["narrative_enriched_at"] = _now()
    updated["evidence_hash"] = ehash
    updated["llm_model"] = model_id
    updated["llm_status"] = result["llm"]
    if narrative.get("llm_deferred"):
        updated["llm_deferred"] = True

    # Persist
    if plan_store is not None and updated.get("plan_id"):
        try:
            plan_store.update_plan(
                updated["plan_id"],
                summary=updated.get("summary"),
                options=updated.get("options"),
                recommendation=updated.get("recommendation"),
                risks=updated.get("risks"),
                status="proposed" if result["narrative_source"] == "llm" else plan.get("status") or "draft",
                actor_id="cio_plan_enrichment",
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
                    "llm_model": updated.get("llm_model"),
                    "llm_status": updated.get("llm_status"),
                    "llm_deferred": updated.get("llm_deferred"),
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


def maybe_notify_plan(plan: dict[str, Any], policy: Optional[dict[str, Any]] = None) -> bool:
    """Optional Telegram notify for High/Critical situations. Default off."""
    pol = policy or load_llm_policy()
    if not pol.get("situation_notify_telegram"):
        return False
    if os.environ.get("CIO_SITUATION_NOTIFY", "0").strip() not in ("1", "true", "yes", "on"):
        return False
    # only proposed plans
    if plan.get("status") not in ("proposed", "draft"):
        return False
    try:
        from scripts.lib.cio_telegram_converse import format_structured_reply, send_cio_message, allowlist_chat_ids
        text = format_structured_reply(
            summary=plan.get("summary") or plan.get("title") or "",
            evidence_refs=plan.get("evidence_refs"),
            options=plan.get("options"),
            recommendation=plan.get("recommendation") or "",
            risks=plan.get("risks"),
            plan_id=plan.get("plan_id"),
            revisit_at=plan.get("revisit_at"),
            llm_deferred=plan.get("narrative_source") == "template",
            deep_links=plan.get("cc_deep_links"),
        )
        chats = allowlist_chat_ids()
        ok_any = False
        for cid in chats:
            r = send_cio_message(cid, text)
            ok_any = ok_any or bool(r.get("ok"))
        return ok_any
    except Exception:
        return False
