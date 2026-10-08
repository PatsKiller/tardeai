"""Governed model job for n8n coordination (plan tranche D, 2026-10-07).

n8n passes a process id, an artifact reference, a correlation id, a deadline and the output schema
it wants. Trade AI resolves the artifact from its own stores, calls the existing governed bridge
(`cio_governed_model_bridge.execute_governed_call`: registration, policy, caps, reservation,
provider, settlement), validates the answer against the named output contract, and returns a
receipt that joins the reservation to its provider-cost event. Every failure is a typed refusal
with no fallback. Nothing here sends, writes a canonical table, or chooses a model: the bridge
chooses the model server-side from the process registry.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

NO_CONSUMER_REASON = (
    "called by tests and, after the gateway PR lands, by the coordination gateway's model_job operation; "
    "no scheduled lane; never a send"
)
RECEIPT_SCHEMA = "N8nModelJobReceipt@v1"
ALLOWED_STORES = frozenset({"data/runtime", "data/cio"})
MAX_ARTIFACT_BYTES = 256_000
DEFAULT_SCHEMAS_PATH = Path(__file__).resolve().parents[2] / "config" / "schemas" / "n8n_model_job_outputs.json"
REFUSALS = frozenset({
    "deadline_passed", "deadline_invalid", "artifact_store_refused", "artifact_unresolved", "artifact_hash_mismatch",
    "artifact_too_large", "unknown_output_schema", "governance_refused", "provider_outage", "over_cap",
    "invalid_json", "schema_invalid", "forbidden_content", "no_cost_receipt", "process_mismatch",
})


class ModelJobRefused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        assert code in REFUSALS, code
        super().__init__(code)
        self.code, self.detail = code, detail


def state_root(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def load_schemas(path: Optional[Path] = None) -> dict[str, Any]:
    doc = json.loads(Path(path or DEFAULT_SCHEMAS_PATH).read_text(encoding="utf-8"))
    return doc.get("schemas") or {}


# ── structural validation (no jsonschema on this host) ───────────────────────────────────────
def validate(value: Any, schema: Mapping[str, Any], *, path: str = "$") -> list[str]:
    errors: list[str] = []
    typ = schema.get("type")
    if typ == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
        if "max_length" in schema and len(value) > int(schema["max_length"]):
            errors.append(f"{path}: longer than {schema['max_length']}")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: not in {schema['enum']}")
        return errors
    if typ == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path}: expected number"]
        return errors
    if typ == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        if "max_items" in schema and len(value) > int(schema["max_items"]):
            errors.append(f"{path}: more than {schema['max_items']} items")
        item_schema = schema.get("items") or {}
        for i, item in enumerate(value):
            errors.extend(validate(item, item_schema, path=f"{path}[{i}]"))
        return errors
    # object (default)
    if not isinstance(value, Mapping):
        return [f"{path}: expected object"]
    for key in schema.get("required") or []:
        if key not in value:
            errors.append(f"{path}.{key}: required")
    props = schema.get("properties") or {}
    for key, sub in props.items():
        if key in value:
            errors.extend(validate(value[key], sub, path=f"{path}.{key}"))
    extra = set(value) - set(props)
    if props and extra:
        errors.append(f"{path}: unexpected keys {sorted(extra)[:5]}")
    return errors


def _forbidden_keys(value: Any, forbidden: set[str], path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            if str(k).lower() in forbidden:
                hits.append(f"{path}.{k}")
            hits.extend(_forbidden_keys(v, forbidden, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            hits.extend(_forbidden_keys(v, forbidden, f"{path}[{i}]"))
    return hits


# ── artifact resolution (server-side, allowlisted stores, hash-checked) ──────────────────────
def resolve_artifact(ref: Mapping[str, Any], *, root: Optional[Path] = None) -> dict[str, Any]:
    store = str(ref.get("store") or "")
    rel = str(ref.get("ref") or "")
    if store not in ALLOWED_STORES or not rel or ".." in rel or rel.startswith("/"):
        raise ModelJobRefused("artifact_store_refused", f"{store}/{rel}")
    path = (root or state_root()) / store / rel
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ModelJobRefused("artifact_unresolved", f"{path}: {type(exc).__name__}") from exc
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ModelJobRefused("artifact_too_large", str(len(raw)))
    digest = hashlib.sha256(raw).hexdigest()
    expected = ref.get("sha256")
    if expected and str(expected).lower() != digest:
        raise ModelJobRefused("artifact_hash_mismatch", f"expected {str(expected)[:12]}… got {digest[:12]}…")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        body = {"text": raw.decode("utf-8", errors="replace")}
    return {"path": str(path), "sha256": digest, "bytes": len(raw), "body": body}


def _parse_time(value: Any) -> _dt.datetime:
    try:
        ts = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ModelJobRefused("deadline_invalid", str(value)[:40]) from exc
    if ts.tzinfo is None:
        raise ModelJobRefused("deadline_invalid", "naive timestamp")
    return ts


def _cost_event_for(request_id: str, *, root: Path) -> Optional[dict[str, Any]]:
    """The provider_cost event whose client_request_id is this job's request id, if one was emitted."""
    p = root / "data" / "runtime" / "provider_cost" / "events.jsonl"
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        if request_id not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if str(row.get("client_request_id") or "") == request_id:
            return {k: row.get(k) for k in ("event_id", "calculated_cost_usd", "model", "input_tokens", "output_tokens",
                                             "reservation_id", "observed_at", "cost_source")}
    return None


def build_messages(schema_id: str, schema: Mapping[str, Any], artifact: Mapping[str, Any], job: Mapping[str, Any]) -> list[dict[str, str]]:
    """Prompt from the artifact only. No credential, no portfolio dump, no instruction to act."""
    body = json.dumps(artifact["body"], default=str)[:60_000]
    system = (
        f"You draft a {schema_id} for a human reviewer. Use ONLY the supplied artifact. Cite each source id you use. "
        f"Return one JSON object with exactly these keys: {sorted((schema.get('properties') or {}).keys())}. "
        f"Required: {schema.get('required')}. Never recommend an action; if a recommendation key exists it must be \"NONE\". "
        f"If the artifact does not support a claim, say so in confidence_note."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"correlation_id={job.get('correlation_id')}\nartifact sha256={artifact['sha256']}\n{body}"}]


def run_model_job(job: Mapping[str, Any], *, governed_call: Callable[..., dict[str, Any]], now: Optional[_dt.datetime] = None,
                  root: Optional[Path] = None, schemas: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Run one job. Returns N8nModelJobReceipt@v1 with state ARTIFACT_WRITTEN or REFUSED (typed)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    root = root or state_root()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "correlation_id": job.get("correlation_id"), "process_id": job.get("process_id"),
        "output_schema_id": job.get("output_schema_id"), "state": "REFUSED", "reason": None, "detail": None,
        "started_at": now.isoformat(), "effects": [], "outbound": "blocked", "mutation": "blocked",
        "fallback": "none", "artifact_in": None, "artifact_out": None, "cost": None,
    }
    try:
        deadline = _parse_time(job.get("deadline"))
        if deadline <= now:
            raise ModelJobRefused("deadline_passed", deadline.isoformat())
        schema_id = str(job.get("output_schema_id") or "")
        schema = (schemas if schemas is not None else load_schemas()).get(schema_id)
        if not schema:
            raise ModelJobRefused("unknown_output_schema", schema_id)
        artifact = resolve_artifact(job.get("artifact_ref") or {}, root=root)
        receipt["artifact_in"] = {k: artifact[k] for k in ("path", "sha256", "bytes")}
        request_id = str(job.get("correlation_id") or "")[:64]
        result = governed_call(build_messages(schema_id, schema, artifact, job), process_id=str(job.get("process_id") or ""),
                               response_format={"type": "json_object"}, request_id=request_id)
        if not isinstance(result, Mapping):
            raise ModelJobRefused("governance_refused", "no result")
        err = result.get("error")
        if err:
            code = str((err or {}).get("code") or "")
            status = int((err or {}).get("status") or 0)
            if "CAP" in code or "BUDGET" in code:
                raise ModelJobRefused("over_cap", code)
            if status >= 500 or "PROVIDER" in code or "TIMEOUT" in code or "CIRCUIT" in code:
                raise ModelJobRefused("provider_outage", code)
            raise ModelJobRefused("governance_refused", code)
        if result.get("process_id") not in (None, job.get("process_id")):
            raise ModelJobRefused("process_mismatch", str(result.get("process_id")))
        if not result.get("governance_pass"):
            raise ModelJobRefused("governance_refused", "governance_pass false")
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelJobRefused("invalid_json", "no content") from exc
        try:
            answer = json.loads(content) if isinstance(content, str) else content
        except ValueError as exc:
            raise ModelJobRefused("invalid_json", str(exc)[:80]) from exc
        errors = validate(answer, schema)
        if errors:
            raise ModelJobRefused("schema_invalid", "; ".join(errors[:6]))
        hits = _forbidden_keys(answer, {k.lower() for k in schema.get("forbidden_keys") or []})
        if hits:
            raise ModelJobRefused("forbidden_content", ", ".join(hits[:6]))
        reservation = result.get("reservation_id")
        if reservation in (None, "") and not result.get("mock"):
            raise ModelJobRefused("no_cost_receipt", "bridge returned no reservation_id")
        cost_event = _cost_event_for(request_id, root=root) if request_id else None
        receipt["cost"] = {"reservation_id": reservation, "cost_estimate_usd": result.get("cost_estimate"),
                           "model_id": result.get("model_id"), "provider": result.get("provider"), "mock": bool(result.get("mock")),
                           "provider_cost_event": cost_event, "settlement": "MEASURED" if cost_event else "NOT_MEASURED",
                           "usage": result.get("usage")}
        receipt["artifact_out"] = {"schema_id": schema_id, "sha256": hashlib.sha256(json.dumps(answer, sort_keys=True).encode()).hexdigest(),
                                   "body": answer}
        receipt["state"] = "ARTIFACT_WRITTEN"
    except ModelJobRefused as exc:
        receipt["state"], receipt["reason"], receipt["detail"] = "REFUSED", exc.code, exc.detail[:300]
    receipt["ended_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    return receipt


BRIDGE_URL_ENV = "TRADEAI_GOVERNED_BRIDGE_URL"
BRIDGE_CALLER = "n8n_model_job"


def bridge_governed_call(messages: list[dict[str, str]], *, process_id: str, response_format: Optional[dict] = None,
                         request_id: Optional[str] = None, timeout_s: float = 60.0, task_type: str = "model_job") -> dict[str, Any]:
    """Loopback HTTP to the running governed bridge (cio-governed-bridge.service, 127.0.0.1:8766).

    The bridge maps the caller header to the process server-side (CALLER_PROCESS_MAP); the job's
    process_id is checked against what the bridge reports, never sent as an instruction. No key
    lives here: the bridge holds the provider credential. A transport failure is a provider_outage."""
    import urllib.error
    import urllib.request
    url = os.environ.get(BRIDGE_URL_ENV) or "http://127.0.0.1:8766/v1/chat/completions"
    body = json.dumps({"model": "tradeai_governed", "messages": messages, "response_format": response_format or {"type": "json_object"},
                       "max_tokens": 2048, "request_id": request_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                          "X-TradeAI-Agent": BRIDGE_CALLER,
                                                                          "X-TradeAI-Task-Type": task_type})   # 2026-10-08: ops_summary selects n8n_ops_summary_draft server-side
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except ValueError:
            return {"error": {"code": "PROVIDER_HTTP_ERROR", "status": exc.code, "message": str(exc)[:120]}, "governance_pass": False}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": {"code": "PROVIDER_TIMEOUT", "status": 504, "message": type(exc).__name__}, "governance_pass": False}


def write_receipt(receipt: Mapping[str, Any], *, root: Optional[Path] = None) -> Path:
    """Durable job receipt under data/runtime/n8n_model_jobs/<correlation_id>.json (atomic)."""
    root = root or state_root()
    d = root / "data" / "runtime" / "n8n_model_jobs"
    d.mkdir(parents=True, exist_ok=True)
    name = "".join(c for c in str(receipt.get("correlation_id") or "job") if c.isalnum() or c in "-_")[:80] or "job"
    out = d / f"{name}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out
