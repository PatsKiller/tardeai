"""Bridge-side preconditions for governed n8n Agents (AGENTS.md 3.0.0 §23.3, §23.4, §23.10 P5, P6, P21).

Pure checks the governed bridge (scripts/lib/cio_governed_model_bridge.execute_governed_call) runs around
its existing pipeline. Each returns None (pass) or a typed refusal {code, status, message, extra}.

P5  tool allowlist (audit B H4). The process registry row's `tools_allowed` decides:
      list[str]       an allowlist: a request whose `tools` / `tool_choice` names anything else, or a name
                      that hits the gateway's FORBIDDEN_ROUTE_TOKENS, is refused 400 before reservation;
                      a model `tool_calls` entry naming a tool outside the list (or a forbidden one) is
                      refused typed after the call, never dropped (§23.3 "refused with a typed reason").
      false           no tools: any request `tools` is refused; any returned `tool_calls` is refused.
      true / absent   legacy pass-through (the OpenClaw agents alex/maria/steph/guardian/ledger/morgan);
                      unchanged until a row declares a list.
P6  output validation for every n8n_* process (audit B M3): the row's `output_schema_id` names a schema
    in config/schemas/n8n_model_job_outputs.json; the answer must be a JSON object that passes
    n8n_model_job.validate, carries no behaviour field (cio_instrument_record.BEHAVIOR_FIELDS plus the
    schema's forbidden_keys, any depth, case-insensitive) and no recommendation other than NONE.
    Other processes are not validated here.
P21 routing policy `cost_ceiling_usd` refuses before reservation when the projected cost exceeds it;
    `latency_budget_ms` becomes the provider deadline (the bridge's effective_upstream_deadline_s);
    the registry `advisory_only` flag: an n8n_* row that is not advisory_only is refused before
    reservation, and every advisory_only answer is stamped READ_ONLY_ADVISORY (n8n_*: recommendation
    NONE) on its `_tradeai` envelope.

AUTHORITY: READ_ONLY_ADVISORY. No provider call, no ledger write, no send.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

NO_CONSUMER_REASON = (
    "consumed in-process by scripts/lib/cio_governed_model_bridge.execute_governed_call; no CLI, no lane"
)

N8N_PROCESS_PREFIX = "n8n_"
ADVISORY_AUTHORITY = "READ_ONLY_ADVISORY"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_PATH = _PROJECT_ROOT / "config" / "schemas" / "n8n_model_job_outputs.json"

try:  # the bridge puts scripts/ on sys.path; tests may import through the scripts package
    from lib.cio_instrument_record import BEHAVIOR_FIELDS
    from lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS
    from lib.n8n_model_job import validate as _validate_schema
except ImportError:  # pragma: no cover
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS
    from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS
    from scripts.lib.n8n_model_job import validate as _validate_schema


def is_n8n_process(process_id: str) -> bool:
    return str(process_id or "").startswith(N8N_PROCESS_PREFIX)


def registry_row(process_id: str) -> dict[str, Any] | None:
    """The raw registry row (llm_consumption.get_process_config coerces tools_allowed to bool)."""
    try:
        import lib.llm_consumption as lc
    except ImportError:  # pragma: no cover
        import scripts.lib.llm_consumption as lc  # type: ignore[no-redef]
    row = lc._registry_process(process_id)
    return row if isinstance(row, dict) else None


def _refusal(code: str, status: int, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "status": status, "message": message, "extra": extra}


# ── P5: tool allowlist ─────────────────────────────────────────────────────

def tool_policy(row: Mapping[str, Any] | None) -> tuple[str, frozenset[str]]:
    """('passthrough', {}) | ('none', {}) | ('allowlist', names)."""
    raw = (row or {}).get("tools_allowed", None)
    if isinstance(raw, list):
        return "allowlist", frozenset(str(x) for x in raw if isinstance(x, str) and x)
    if raw is False:
        return "none", frozenset()
    return "passthrough", frozenset()


def tool_name_forbidden(name: str) -> str | None:
    """Same token rule as n8n_coordination_gateway.route_forbidden, without the route allowlist."""
    text = str(name or "").strip().lower()
    if not text:
        return "missing_tool_name"
    for token in (t for t in re.split(r"[^a-z0-9]+", text) if t):
        if token in FORBIDDEN_ROUTE_TOKENS:
            return token
    collapsed = re.sub(r"[^a-z0-9]", "", text)
    for token in FORBIDDEN_ROUTE_TOKENS:
        if token != "title" and token in collapsed:
            return token
    return None


def _declared_tool_names(tools: Any) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        if not isinstance(tool, Mapping):
            names.append("")
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), Mapping) else {}
        names.append(str(fn.get("name") or tool.get("name") or ""))
    return names


def _tool_choice_name(tool_choice: Any) -> str | None:
    if isinstance(tool_choice, Mapping):
        fn = tool_choice.get("function") if isinstance(tool_choice.get("function"), Mapping) else {}
        name = fn.get("name") or tool_choice.get("name")
        return str(name) if name else None
    return None


def _tool_verdict(name: str, mode: str, allowed: frozenset[str]) -> str | None:
    hit = tool_name_forbidden(name)
    if hit:
        return f"forbidden_token:{hit}"
    if mode == "none":
        return "tools_not_allowed_for_process"
    if name not in allowed:
        return "not_in_allowlist"
    return None


def request_tools_refusal(process_id: str, tools: Any, tool_choice: Any,
                          row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    mode, allowed = tool_policy(row)
    if mode == "passthrough":
        return None
    names = _declared_tool_names(tools)
    choice = _tool_choice_name(tool_choice)
    if choice is not None:
        names.append(choice)
    refused = [{"name": n[:64], "reason": r} for n in names if (r := _tool_verdict(n, mode, allowed))]
    if not refused:
        return None
    code = "TOOL_FORBIDDEN" if any(x["reason"].startswith("forbidden_token") for x in refused) else "TOOL_NOT_ALLOWED"
    return _refusal(code, 400,
                    f"Process '{process_id}' may not use tool(s) {[x['name'] for x in refused][:5]}",
                    tools_refused=refused[:10], tools_policy=mode)


def response_tool_calls_refusal(process_id: str, response: Mapping[str, Any],
                                row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    mode, allowed = tool_policy(row)
    if mode == "passthrough":
        return None
    refused = []
    for choice in response.get("choices") or []:
        msg = choice.get("message") if isinstance(choice, Mapping) else None
        for call in (msg or {}).get("tool_calls") or []:
            fn = call.get("function") if isinstance(call, Mapping) and isinstance(call.get("function"), Mapping) else {}
            name = str(fn.get("name") or "")
            reason = _tool_verdict(name, mode, allowed)
            if reason:
                refused.append({"name": name[:64], "reason": reason})
    if not refused:
        return None
    return _refusal("TOOL_CALL_REFUSED", 422,
                    f"Model named tool(s) process '{process_id}' may not call: {[x['name'] for x in refused][:5]}",
                    tool_calls_refused=refused[:10], tools_policy=mode)


# ── P6: n8n output schema + behaviour scan ─────────────────────────────────

def load_output_schemas(path: Path | None = None) -> dict[str, Any]:
    try:
        doc = json.loads((path or SCHEMAS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    schemas = doc.get("schemas") if isinstance(doc, dict) else None
    return schemas if isinstance(schemas, dict) else {}


def output_schema_for(row: Mapping[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    schema_id = (row or {}).get("output_schema_id")
    if not isinstance(schema_id, str) or not schema_id:
        return None, None
    schema = load_output_schemas().get(schema_id)
    return schema_id, schema if isinstance(schema, dict) else None


def behaviour_hits(value: Any, extra_keys: frozenset[str] = frozenset(), path: str = "$") -> list[str]:
    fields = {f.lower() for f in BEHAVIOR_FIELDS} | {k.lower() for k in extra_keys}
    hits: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            if str(k).lower() in fields:
                hits.append(f"{path}.{k}")
            hits.extend(behaviour_hits(v, extra_keys, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            hits.extend(behaviour_hits(v, extra_keys, f"{path}[{i}]"))
    return hits


def output_refusal(process_id: str, response: Mapping[str, Any],
                   row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """P5 tool_calls for every process with a declared tool policy; P6 for n8n_* processes only."""
    if not is_n8n_process(process_id):
        return response_tool_calls_refusal(process_id, response, row)
    schema_id, schema = output_schema_for(row)
    if schema is None:
        return _refusal("OUTPUT_SCHEMA_UNKNOWN", 500, f"No output schema for n8n process '{process_id}'",
                        output_schema_id=schema_id)
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return _refusal("OUTPUT_INVALID_JSON", 422, "model output choices must be a nonempty list",
                        output_schema_id=schema_id)
    for choice in choices:
        msg = choice.get("message") if isinstance(choice, Mapping) else None
        if not isinstance(msg, Mapping):
            return _refusal("OUTPUT_INVALID_JSON", 422, "each model output choice must contain a message object",
                            output_schema_id=schema_id)
        calls = msg.get("tool_calls")
        if calls is not None and (not isinstance(calls, list) or any(
            not isinstance(call, Mapping) or not isinstance(call.get("function"), Mapping) for call in calls
        )):
            return _refusal("OUTPUT_INVALID_JSON", 422, "model output tool_calls must be a list of function objects",
                            output_schema_id=schema_id)
    refused = response_tool_calls_refusal(process_id, response, row)
    if refused is not None:
        return refused
    extra_keys = frozenset(str(k) for k in schema.get("forbidden_keys") or [])
    for choice in choices:
        msg = (choice or {}).get("message") if isinstance(choice, Mapping) else None
        msg = msg if isinstance(msg, Mapping) else {}
        content = msg.get("content")
        calls = msg.get("tool_calls") or []
        for call in calls:   # an allowlisted tool call's arguments are scanned for behaviour too
            fn = call.get("function") if isinstance(call, Mapping) and isinstance(call.get("function"), Mapping) else {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                return _refusal("OUTPUT_INVALID_JSON", 422, "tool call arguments are not JSON",
                                output_schema_id=schema_id)
            hits = behaviour_hits(args, extra_keys)
            if hits:
                return _refusal("OUTPUT_BEHAVIOUR_FIELD", 422, f"tool call arguments carry behaviour fields {hits[:6]}",
                                output_schema_id=schema_id, behaviour_fields=hits[:10])
        if calls and not content:
            continue
        try:
            answer = json.loads(content) if isinstance(content, str) else content
        except ValueError:
            return _refusal("OUTPUT_INVALID_JSON", 422, "model output is not JSON", output_schema_id=schema_id)
        if not isinstance(answer, Mapping):
            return _refusal("OUTPUT_INVALID_JSON", 422, "model output is not a JSON object",
                            output_schema_id=schema_id)
        hits = behaviour_hits(answer, extra_keys)
        if hits:
            return _refusal("OUTPUT_BEHAVIOUR_FIELD", 422, f"model output carries behaviour fields {hits[:6]}",
                            output_schema_id=schema_id, behaviour_fields=hits[:10])
        if "recommendation" in answer and answer.get("recommendation") != "NONE":
            return _refusal("OUTPUT_RECOMMENDATION_FORBIDDEN", 422, "n8n output recommendation must be NONE",
                            output_schema_id=schema_id)
        errors = _validate_schema(answer, schema)
        if errors:
            return _refusal("OUTPUT_SCHEMA_INVALID", 422, "; ".join(errors[:6]), output_schema_id=schema_id)
    return None


# ── pre-reservation (P5 request side, P6 schema presence, P21 advisory_only) ──

def pre_reservation_refusal(process_id: str, tools: Any, tool_choice: Any) -> dict[str, Any] | None:
    row = registry_row(process_id)
    if is_n8n_process(process_id):
        if (row or {}).get("advisory_only") is not True:
            return _refusal("PROCESS_NOT_ADVISORY", 403,
                            f"n8n process '{process_id}' must be advisory_only in llm_process_registry.json")
        _schema_id, schema = output_schema_for(row)
        if schema is None:
            return _refusal("OUTPUT_SCHEMA_UNKNOWN", 500,
                            f"n8n process '{process_id}' declares no known output_schema_id",
                            output_schema_id=_schema_id)
    return request_tools_refusal(process_id, tools, tool_choice, row)


# ── P21: routing policy cost ceiling + latency budget ──────────────────────

def cost_ceiling_refusal(policy: Mapping[str, Any] | None, projected_usd: float) -> dict[str, Any] | None:
    try:
        ceiling = float((policy or {}).get("cost_ceiling_usd") or 0)
    except (TypeError, ValueError):
        ceiling = 0.0
    if ceiling > 0 and float(projected_usd) > ceiling:
        return _refusal("COST_CEILING_EXCEEDED", 429,
                        f"Projected ${float(projected_usd):.4f} exceeds the routing policy ceiling ${ceiling:.4f}",
                        cost_ceiling_usd=ceiling, projected_usd=round(float(projected_usd), 6))
    return None


def latency_budget_s(policy: Mapping[str, Any] | None) -> float | None:
    try:
        ms = float((policy or {}).get("latency_budget_ms") or 0)
    except (TypeError, ValueError):
        return None
    return ms / 1000.0 if ms > 0 else None


# ── response envelope (P21 advisory_only, P4 verdict, P6 schema id) ────────

def annotate_response(response: dict[str, Any], process_id: str, egress_verdict: Mapping[str, Any] | None) -> None:
    meta = response.setdefault("_tradeai", {})
    row = registry_row(process_id)
    if egress_verdict is not None:
        meta["egress_sanitiser"] = {k: egress_verdict.get(k) for k in ("mode", "action", "total")}
    if (row or {}).get("advisory_only") is True:
        meta["authority"] = ADVISORY_AUTHORITY
    if is_n8n_process(process_id):
        meta["authority"] = ADVISORY_AUTHORITY
        meta["recommendation"] = "NONE"
        meta["output_schema_id"] = (row or {}).get("output_schema_id")
        meta["output_validated"] = True
