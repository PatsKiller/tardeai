"""model_chooser.py — ONE model chooser (Wave 4 O-W4-3), shipped in SHADOW.

Today four places pick a model: llm_router's static tables, gate_and_generate's caller-supplied lane,
the governed bridge's hard-coded process_policy_map, and forty callers of llm_lane.generate with a lane
string. ``choose(process_id, purpose=…, caller=…)`` derives the lane + policy from the process registry
(allowed_lanes, deepseek_default_policy, lane_policy) and the model registry, and returns

    {process_id, lane, policy, model, reason, registered}

Mode (``TRADEAI_MODEL_CHOOSER``): ``shadow`` (default) — callers keep their own choice and the chooser's
disagreement is written to ``data/runtime/model_chooser_receipts.jsonl`` (``ModelChoice@v1``);
``advise`` — the chooser's lane is used only when the caller passed none; ``enforce`` — the chooser's lane
replaces a caller lane that the process does not allow. No paid provider is ever introduced by the chooser:
it only picks among the process's declared allowed_lanes. Authority READ_ONLY_ADVISORY.

Task classes (LQ-20261107-197, DSN-20261107 §3C/§5.1): ``config/llm_task_classes.json`` maps a task class to an
ordered chain of logical steps (anthropic tier / deepseek policy / grok). ``task_class_route`` resolves that chain,
turning each anthropic tier into its model through the credit policy's ``models`` block. ``choose`` reports the
process's task class and resolved route next to its lane; it does not yet change the lane (the shadow → advise →
enforce rollout of the task-class route is a lead step). A process without ``task_class`` reports
TASK_CLASS_UNASSIGNED.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from functools import lru_cache
from pathlib import Path

SCHEMA = "ModelChoice@v1"
MODES = ("shadow", "advise", "enforce")
DEEPSEEK_LANES = ("deepseek-flash", "fast", "fast_think", "pro", "pro_think", "pro_max", "deepseek-pro")
FREE_FIRST = ("grok", "chatgpt", "gemini", "local")


def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]


def mode(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    m = str(env.get("TRADEAI_MODEL_CHOOSER", "shadow")).lower()
    return m if m in MODES else "shadow"


@lru_cache(maxsize=2)
def _registry(path: str, mtime: float) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    procs = d.get("processes") or []
    return {p.get("id"): p for p in procs if isinstance(p, dict) and p.get("id")}


def process(process_id: str, env: dict | None = None) -> dict | None:
    env = os.environ if env is None else env
    p = Path(env.get("TRADEAI_LLM_PROCESS_REGISTRY") or _proj_root() / "config" / "llm_process_registry.json")
    try:
        return _registry(str(p), p.stat().st_mtime).get(process_id)
    except OSError:
        return None


TASK_CLASS_UNASSIGNED = "TASK_CLASS_UNASSIGNED"
TASK_CLASS_UNKNOWN = "TASK_CLASS_UNKNOWN"


def _json_file(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def task_classes(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    p = Path(env.get("TRADEAI_LLM_TASK_CLASSES") or _proj_root() / "config" / "llm_task_classes.json")
    return _json_file(p)


def _tier_models(matrix: dict, env: dict) -> dict:
    src = matrix.get("tier_model_source") or {}
    p = Path(env.get("TRADEAI_ANTHROPIC_CREDIT_POLICY") or _proj_root() / str(src.get("file") or "config/anthropic_credit_policy.json"))
    models = _json_file(p).get(str(src.get("key") or "models"))
    return models if isinstance(models, dict) else {}


def task_class_route(task_class: str | None, env: dict | None = None) -> dict:
    """Resolve a task class to its ordered route. Pure given the two config files. Never raises.

    Each step keeps its logical name (tier / policy) and gains ``model`` where it resolves; an anthropic tier with no
    model row resolves to None and is flagged ``unresolved`` rather than guessed."""
    env = os.environ if env is None else env
    if not task_class:
        return {"task_class": None, "status": TASK_CLASS_UNASSIGNED, "chain": []}
    matrix = task_classes(env)
    spec = (matrix.get("classes") or {}).get(task_class)
    if not isinstance(spec, dict):
        return {"task_class": task_class, "status": TASK_CLASS_UNKNOWN, "chain": []}
    tiers = _tier_models(matrix, env)
    chain = []
    for step in spec.get("chain") or []:
        if not isinstance(step, dict):
            continue
        out = dict(step)
        if step.get("provider") == "anthropic":
            out["model"] = tiers.get(str(step.get("tier") or "")) or None
        elif step.get("provider") == "deepseek":
            out["model"] = _model_for(str(step.get("policy") or "FAST"), "deepseek-flash")
        else:
            out["model"] = None
        out["unresolved"] = step.get("provider") in ("anthropic", "deepseek") and not out["model"]
        chain.append(out)
    return {"task_class": task_class, "status": "OK", "chain": chain, "fail_closed": bool(spec.get("fail_closed")),
            "primary_model": chain[0]["model"] if chain else None}


def _model_for(policy: str, lane: str) -> str | None:
    try:
        try:
            import llm_model_registry as mr  # type: ignore
        except ImportError:
            from scripts.lib import llm_model_registry as mr  # type: ignore
        if lane in DEEPSEEK_LANES and hasattr(mr, "deepseek_model_id"):
            return mr.deepseek_model_id(policy or "FAST")
    except Exception:  # noqa: BLE001
        return None
    return None


def choose(process_id: str, *, purpose: str | None = None, caller: str | None = None, requested_lane: str | None = None,
           budget_state: dict | None = None, env: dict | None = None, task_class: str | None = None) -> dict:
    """Pure given the registry. Never raises."""
    env = os.environ if env is None else env
    p = process(process_id, env) or {}
    allowed = [str(x) for x in (p.get("allowed_lanes") or []) if x]
    seen: list[str] = []
    for x in allowed:
        if x not in seen:
            seen.append(x)
    allowed = seen
    policy = str(p.get("deepseek_default_policy") or "FAST").upper()
    lane_policy = str(p.get("lane_policy") or "")
    reason = ""
    if not p:
        lane = requested_lane or "grok"
        reason = "UNREGISTERED_PROCESS: caller's lane kept"
    elif requested_lane and requested_lane in allowed:
        lane = requested_lane
        reason = "caller lane is allowed"
    elif requested_lane and requested_lane not in allowed:
        lane = allowed[0] if allowed else requested_lane
        reason = f"caller lane {requested_lane} not in allowed_lanes → first allowed"
    else:
        # no caller lane: prefer a free lane when the process allows one and nothing forces paid
        free = [l for l in allowed if l in FREE_FIRST]
        if free and lane_policy not in ("deepseek_only",):
            lane = free[0]; reason = "free lane first (lane_policy permits)"
        else:
            lane = allowed[0] if allowed else "grok"; reason = "first allowed lane"
    if budget_state and budget_state.get("paid_exhausted") and lane in DEEPSEEK_LANES:
        free = [l for l in allowed if l in FREE_FIRST]
        if free:
            lane, reason = free[0], "paid cap exhausted → free allowed lane"
    route = task_class_route(task_class or p.get("task_class"), env)
    return {"schema": SCHEMA, "process_id": process_id, "purpose": purpose, "caller": caller, "requested_lane": requested_lane,
            "task_class": route["task_class"], "task_class_status": route["status"],
            "task_class_primary_model": route.get("primary_model"), "task_class_route": route["chain"],
            "lane": lane, "policy": policy if lane in DEEPSEEK_LANES else None, "model": _model_for(policy, lane),
            "allowed_lanes": allowed, "lane_policy": lane_policy or None, "registered": bool(p), "reason": reason,
            "mode": mode(env), "authority": "READ_ONLY_ADVISORY"}


def receipts_path(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_MODEL_CHOOSER_RECEIPTS_PATH"):
        return Path(env["TRADEAI_MODEL_CHOOSER_RECEIPTS_PATH"])
    root = env.get("TRADEAI_STATE_ROOT")
    base = Path(root) if root else None
    if base is None:
        try:
            from canonical_store_registry import production_state_root  # type: ignore
            base = Path(production_state_root())
        except Exception:  # noqa: BLE001
            base = Path.cwd()
    return base / "data" / "runtime" / "model_chooser_receipts.jsonl"


def apply(process_id: str, requested_lane: str | None, *, purpose: str | None = None, caller: str | None = None,
          budget_state: dict | None = None, env: dict | None = None, site: str = "gate_and_generate") -> tuple[str | None, dict]:
    """What the call site should use: (lane, choice). shadow → the caller's lane; advise → chooser only when
    the caller passed none; enforce → chooser when the caller's lane is not allowed. A disagreement is
    always written to the receipts file (fail-soft)."""
    env = os.environ if env is None else env
    ch = choose(process_id, purpose=purpose, caller=caller, requested_lane=requested_lane, budget_state=budget_state, env=env)
    m = ch["mode"]
    use = requested_lane
    if m == "advise" and not requested_lane:
        use = ch["lane"]
    elif m == "enforce" and ch["registered"] and (not requested_lane or requested_lane not in ch["allowed_lanes"]):
        use = ch["lane"]
    ch["used_lane"] = use
    ch["disagree"] = bool(requested_lane) and requested_lane != ch["lane"]
    ch["site"] = site
    ch["ts"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    if ch["disagree"] or m != "shadow":
        try:
            rp = receipts_path(env)
            rp.parent.mkdir(parents=True, exist_ok=True)
            with rp.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ch, sort_keys=True, default=str) + "\n")
        except OSError:
            pass
    return use, ch
