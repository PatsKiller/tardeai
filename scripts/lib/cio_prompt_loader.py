"""Versioned Alex enrichment prompt loader.

Source of truth: prompts/cio_alex_enrich/
Active pin: active.json → immutable system/user/fewshot files.

Fail-closed: missing files → last-known-good inline fallback (v2 contract text)
rather than running an unknown empty prompt.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

PROMPT_DIR_NAME = "cio_alex_enrich"
DEFAULT_ALIAS = "v2"


def _project_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("TRADEAI_PROJECT_ROOT") or os.environ.get("TRADEAI_ROOT") or "").strip()
    if env:
        roots.append(Path(env))
    roots.append(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"))
    try:
        roots.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    roots.append(Path.cwd())
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        k = str(rp)
        if k not in seen and (rp / "prompts" / PROMPT_DIR_NAME).exists():
            seen.add(k)
            out.append(rp)
    return out


def prompt_bundle_dir() -> Optional[Path]:
    for root in _project_roots():
        d = root / "prompts" / PROMPT_DIR_NAME
        if d.is_dir():
            return d
    return None


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Inline last-known-good if files missing (matches v2 contract essence)
_FALLBACK_SYSTEM = """You are Alex, the CIO advisory colleague under the live desk thesis.
Authority = READ_ONLY_ADVISORY. Non-action (hold/stage/monitor) is often highest-signal.
Thesis is governing context, not a footer tag. Evidence before narrative.
Output ONE JSON object only; first character '{'. Use only numbers in evidence.
DESK OS CONTRACT: open with Under {pin}/stance; multi-domain synthesis mandatory;
options 2-3 with complete pros/cons; rec names option_id + fit/tension; no orders/stops;
honor operator dispositions on first sentence when present.
FORBIDDEN: detector-only echo; invented numbers; buy-now language; truncated options.
"""


def load_active_prompt(*, force_alias: Optional[str] = None) -> dict[str, Any]:
    """Load active (or forced) prompt bundle.

    Returns:
      system, user_template, fewshot, prompt_version, content_hash,
      compatible_thesis, alias, source (files|fallback)
    """
    d = prompt_bundle_dir()
    meta: dict[str, Any] = {}
    if d and (d / "active.json").exists():
        try:
            meta = json.loads((d / "active.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    alias = force_alias or str(meta.get("alias") or DEFAULT_ALIAS)
    version = str(meta.get("prompt_version") or f"cio_alex_enrich@{alias}")
    sys_name = str(meta.get("system_file") or f"{alias}_system.md")
    user_name = str(meta.get("user_template_file") or f"{alias}_user_template.md")
    few_name = str(meta.get("fewshot_file") or f"{alias}_fewshot.md")
    compatible = list(meta.get("compatible_thesis") or ["desk@v4", "desk@v5"])

    system = _FALLBACK_SYSTEM
    user_template = (
        "type={{situation_type}} symbols={{symbols}} fire={{fire}}\n"
        "thesis={{pin}} domains={{domains}} numbers={{numbers}}\n"
        "DESK:\n{{desk_context}}\nLEARNING:\n{{learning_block}}\n"
        "EVIDENCE:\n{{evidence_facts}}\n{{task}}\n"
        "JSON: summary,thesis_alignment,multi_domain_summary,recommendation,"
        "options,risks,revisit_hint,cited_fields,thesis_version={{pin}}"
    )
    fewshot = ""
    source = "fallback"

    if d:
        sys_p = d / sys_name
        user_p = d / user_name
        few_p = d / few_name
        if sys_p.exists():
            system = _read(sys_p)
            source = "files"
        if user_p.exists():
            user_template = _read(user_p)
            source = "files"
        if few_p.exists():
            fewshot = _read(few_p)

    # Strip markdown H1 comments for model (keep body)
    def _strip_md_title(s: str) -> str:
        lines = s.splitlines()
        out = []
        for i, ln in enumerate(lines):
            if i == 0 and ln.startswith("#"):
                continue
            out.append(ln)
        return "\n".join(out).strip()

    system_body = _strip_md_title(system)
    user_body = _strip_md_title(user_template)
    few_body = _strip_md_title(fewshot) if fewshot else ""

    bundle_text = "\n---\n".join([system_body, user_body, few_body])
    content_hash = _sha256_text(bundle_text)

    return {
        "prompt_version": version,
        "alias": alias,
        "system": system_body,
        "user_template": user_body,
        "fewshot": few_body,
        "content_hash": content_hash,
        "compatible_thesis": compatible,
        "source": source,
        "bundle_dir": str(d) if d else None,
    }


def thesis_compatible(prompt: dict[str, Any], thesis_version: Optional[str]) -> bool:
    pin = (thesis_version or "").strip()
    if not pin:
        return True
    allowed = prompt.get("compatible_thesis") or []
    if not allowed:
        return True
    return pin in allowed or any(pin.startswith(str(a).split("@")[0] + "@") for a in allowed)


def render_user_prompt(
    template: str,
    *,
    variables: dict[str, Any],
) -> str:
    """Simple {{var}} substitution; unknown keys → empty."""
    out = template
    for k, v in variables.items():
        out = out.replace("{{" + k + "}}", str(v if v is not None else ""))
    # clear any leftover placeholders
    import re
    out = re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "", out)
    return out.strip()


def build_desk_context_block(pack: dict[str, Any]) -> str:
    """Deterministic Desk Context for injection (technique 1)."""
    th = pack.get("desk_thesis") or {}
    pin = pack.get("thesis_version") or th.get("thesis_version") or "desk@?"
    stance = th.get("stance") or "unknown"
    rps = th.get("risk_posture_structured") or {}
    principles = th.get("principles") or []
    esc = th.get("escalation_rules") or []
    lines = [
        f"thesis_version={pin}",
        f"stance={stance}",
        f"authority={pack.get('authority') or th.get('authority') or 'READ_ONLY_ADVISORY'}",
        f"summary={(' '.join(str(th.get('summary') or '').split()))[:280]}",
    ]
    if isinstance(rps, dict) and rps:
        lines.append(
            "risk_posture_structured: "
            f"max_single_name={rps.get('max_single_name_weight_pct')} "
            f"cash_band_min={rps.get('cash_band_min_pct')} "
            f"deep_dd={rps.get('deep_dd_threshold_pct')} "
            f"concentration_fire={rps.get('concentration_fire_pct')}"
        )
    elif th.get("risk_posture"):
        lines.append(f"risk_posture={str(th.get('risk_posture'))[:160]}")
    if principles:
        lines.append("principles: " + " | ".join(str(p) for p in principles[:5]))
    if esc:
        lines.append("escalation: " + " | ".join(str(e) for e in esc[:4]))
    domains = pack.get("evidence_domains") or []
    if domains:
        lines.append("evidence_domains=" + ",".join(str(d) for d in domains[:10]))
    else:
        lines.append("evidence_domains=DATA_UNAVAILABLE")
    return "\n".join(lines)


def build_learning_block(pack: dict[str, Any], *, limit: int = 5) -> str:
    rows = list(pack.get("recent_operator_learning") or [])
    if not rows:
        th = pack.get("desk_thesis") or {}
        rows = [x for x in (th.get("learning_log") or []) if isinstance(x, dict)]
    lines = []
    for L in rows[:limit]:
        if not isinstance(L, dict):
            continue
        if str(L.get("kind") or "") == "seed" and not L.get("disposition"):
            continue
        disp = L.get("disposition") or L.get("kind") or "?"
        st = L.get("situation_type") or ""
        syms = ",".join(str(s) for s in (L.get("symbols") or [])[:3]) or "—"
        note = str(L.get("note") or "")[:80]
        pid = L.get("plan_id") or ""
        lines.append(f"- {pid} ({st} {syms}): {disp}" + (f" — {note}" if note else ""))
    return "\n".join(lines) if lines else "(none)"


# ── Judge prompt loader (separate from Alex) ────────────────────────────────

JUDGE_DIR_NAME = "cio_judge"


def load_active_judge(*, force_alias: Optional[str] = None) -> dict[str, Any]:
    """Load active LLM-as-judge prompt bundle (DeepSeek Flash grader)."""
    roots: list[Path] = []
    env = (os.environ.get("TRADEAI_PROJECT_ROOT") or os.environ.get("TRADEAI_ROOT") or "").strip()
    if env:
        roots.append(Path(env))
    roots.append(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"))
    try:
        roots.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    roots.append(Path.cwd())
    d = None
    for root in roots:
        cand = root / "prompts" / JUDGE_DIR_NAME
        if cand.is_dir():
            d = cand
            break
    meta: dict[str, Any] = {}
    if d and (d / "active.json").exists():
        try:
            meta = json.loads((d / "active.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    alias = force_alias or str(meta.get("alias") or "v1")
    version = str(meta.get("judge_prompt_version") or f"cio_judge@{alias}")
    sys_name = str(meta.get("system_file") or f"{alias}_system.md")
    user_name = str(meta.get("user_template_file") or f"{alias}_user_template.md")

    def _strip(s: str) -> str:
        lines = s.splitlines()
        out = []
        for i, ln in enumerate(lines):
            if i == 0 and ln.startswith("#"):
                continue
            out.append(ln)
        return "\n".join(out).strip()

    system = (
        "You are an evaluation judge for CIO advisory messages. Score 1-5 per rubric. "
        "JSON only. READ_ONLY defects: execution language, invented numbers."
    )
    user_template = (
        "THESIS:\n{{thesis_block}}\nSITUATION: {{situation_type}} {{symbol}} {{plan_id}}\n"
        "EVIDENCE:\n{{evidence_pack}}\nADVISORY:\n{{advisory_text}}\n"
        "Return JSON scores thesis_use,synthesis,options,recommendation,evidence,tone + rationales + critical_defects."
    )
    source = "fallback"
    if d:
        sp, up = d / sys_name, d / user_name
        if sp.exists():
            system = _strip(sp.read_text(encoding="utf-8"))
            source = "files"
        if up.exists():
            user_template = _strip(up.read_text(encoding="utf-8"))
            source = "files"
    bundle = system + "\n---\n" + user_template
    return {
        "judge_prompt_version": version,
        "alias": alias,
        "system": system,
        "user_template": user_template,
        "content_hash": _sha256_text(bundle),
        "model": meta.get("model") or "deepseek-v4-flash",
        "temperature": float(meta.get("temperature") if meta.get("temperature") is not None else 0.1),
        "max_tokens": int(meta.get("max_tokens") or 900),
        "source": source,
        "bundle_dir": str(d) if d else None,
    }
