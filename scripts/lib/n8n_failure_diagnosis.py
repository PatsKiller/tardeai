"""n8n lane failure diagnosis: pure logic (no DB, no network, no model call, no execution).

REMEDIATION_PLAN §6 R1–R5 with the operator's decisions of 2026-10-09 23:38 ET:

1. §2A scope = lane metadata, error text and logs only. ``scrub_text`` / ``scrub_obj`` remove secrets and portfolio
   fields, and ``egress_violations`` is the last check before anything is handed to the governed path: a pack that
   still carries a forbidden key or pattern is refused, never trimmed silently.
2. The model is reached only through ``n8n_model_job.run_model_job`` (process ``n8n_lane_failure_diagnosis``,
   template ``lane_failure_diagnosis.v1``) -> the governed bridge (grok OAuth -> chatgpt OAuth -> deepseek).
3. The model only CHOOSES an ``action_id``. ``check_verdict`` validates it against the lane's catalogue row;
   ``decide`` applies the human-approval threshold (V9 §6.4). Execution is the CLI's deterministic handlers.
4. One writer per store (AGENTS.md §9.4; operator "Ok" 2026-10-10 ~00:35 ET): the diagnoser writes its own
   ``N8nLaneDiagnosis@v1`` records (``diagnosis_record`` / ``remediation_record``) and never ``system_health_events``;
   the SIEM bridge folds them into the row it owns (``n8n_siem_bridge.read_diagnoses`` / ``diagnosis_suffix``).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: nothing here sizes, orders, stops or touches a broker.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from scripts.lib.n8n_remediation_catalogue import SUGGEST_ONLY, lane_action
from scripts.lib.n8n_siem_bridge import COMPONENT_PREFIX, DIAGNOSIS_SCHEMA, strip_diagnosis
from scripts.lib.n8n_siem_bridge import incident_key as _incident_key

SCHEMA = "N8nFailureDiagnosis@v1"
EVIDENCE_SCHEMA = "N8nLaneFailureEvidence@v1"
LANE_ID = "n8n-failure-diagnosis"
PROCESS_ID = "n8n_lane_failure_diagnosis"
TEMPLATE_ID = "lane_failure_diagnosis.v1"
OUTPUT_SCHEMA_ID = "lane_failure_diagnosis/v1"
PER_CALL_CAP_USD = 0.05          # operator decision 2: <= $0.05 per diagnosis
DAILY_CAP_USD = 0.10             # the process row's daily_cost_cap_usd (inside the $2.00 global cap)
MAX_CALLS_PER_LANE_DAY = 3
MAX_CALLS_PER_DAY = 40           # the process row's daily_soft_cap
CONFIDENCE_MIN = 0.7             # V9 §6.4
MAX_TAIL_CHARS = 1500
MAX_MESSAGE_CHARS = 900
#: Conservative per-call projection before the bridge's own (deepseek-flash PEAK, cache miss, AGENTS.md §12).
PROJ_INPUT_USD_PER_M = 0.30
PROJ_OUTPUT_USD_PER_M = 1.20
PROJ_MAX_OUTPUT_TOKENS = 1024
SEVERITY_ORDER = {"CRITICAL": 0, "URGENT": 1, "WARN": 2, "INFO": 3}

# ---------------------------------------------------------------- §2A scrub

#: Keys whose VALUE is portfolio or account data: dropped from the pack wherever they appear (any depth).
PORTFOLIO_KEYS = frozenset({
    "position", "positions", "holding", "holdings", "account", "accounts", "account_id", "account_number",
    "account_hash", "accountnumber", "qty", "quantity", "shares", "cost_basis", "basis", "market_value",
    "marketvalue", "balance", "balances", "cash", "buying_power", "portfolio", "portfolio_value", "nav", "pnl",
    "unrealized_pnl", "realized_pnl", "lots", "lot", "weight", "target_weight_pct", "size_usd", "notional",
    "order", "orders", "stop", "stops", "trade", "trades", "execution", "fills",
})
#: Keys whose VALUE is a credential: dropped wherever they appear.
SECRET_KEYS = frozenset({"password", "passwd", "token", "secret", "api_key", "apikey", "authorization", "cookie",
                         "bearer", "private_key", "client_secret", "refresh_token", "access_token", "env", "environ"})
_SECRET_RES = (
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|COOKIE|AUTH)[A-Z0-9_]*)"
                r"\s*[=:]\s*(\"[^\"]*\"|'[^']*'|\S+)"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(?:sk|pk|xox[abp]|ghp|gho|github_pat|AKIA)[-_A-Za-z0-9]{12,}"), "[REDACTED_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b(postgres(?:ql)?|mysql|redis|amqp|https?)://[^\s:/@]+:[^\s@]+@"), r"\1://[REDACTED]@"),
    (re.compile(r"\b\d{3}-\d\d-\d{4}\b"), "[REDACTED_ID]"),
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "[REDACTED_HEX]"),
    (re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}"), "[REDACTED_B64]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
)
#: Portfolio values in free text: account-like numbers and dollar amounts.
_PORTFOLIO_RES = (
    (re.compile(r"(?i)\b(?:acct|account)(?:[ _#-]*(?:no|number|id|hash))?\s*[#:=]?\s*[A-Za-z0-9*-]{4,}"), "[REDACTED_ACCOUNT]"),
    (re.compile(r"(?<![\w.])\$\s?-?[\d,]+(?:\.\d+)?[kKmM]?\b"), "[REDACTED_USD]"),
    (re.compile(r"(?i)\bUSD\s?-?[\d,]+(?:\.\d+)?\b"), "[REDACTED_USD]"),
    (re.compile(r"(?<![\w.:-])\d{8,}(?![\w.:-])"), "[REDACTED_NUM]"),
)
#: A log line naming a portfolio field is withheld whole: its numbers are not safe to keep.
_PORTFOLIO_LINE = re.compile(
    r"(?i)\b(positions?|holdings?|cost[_ ]basis|market[_ ]value|buying[_ ]power|portfolio[_ ]value|"
    r"unrealized|realized[_ ]pnl|shares|quantity|qty|balance|account(?:s|_id|_number|_hash)?)\b")
WITHHELD_LINE = "[line withheld: portfolio field]"


def scrub_text(text: Any, *, max_chars: Optional[int] = None) -> str:
    """Secrets and portfolio values out of one free-text blob (log tail, error text, message)."""
    out_lines = []
    for line in str(text or "").splitlines() or [""]:
        if _PORTFOLIO_LINE.search(line):
            out_lines.append(WITHHELD_LINE)
            continue
        for rx, rep in _SECRET_RES:
            line = rx.sub(rep, line)
        for rx, rep in _PORTFOLIO_RES:
            line = rx.sub(rep, line)
        out_lines.append(line)
    text = "\n".join(out_lines)
    if max_chars is not None and len(text) > max_chars:
        text = text[-max_chars:]
    return text


def scrub_obj(value: Any) -> Any:
    """Recursive: drop portfolio and secret keys, scrub every string."""
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            kl = str(k).lower()
            if kl in PORTFOLIO_KEYS or kl in SECRET_KEYS:
                continue
            out[str(k)] = scrub_obj(v)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub_obj(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def egress_violations(value: Any, path: str = "$") -> list[str]:
    """Everything in a pack that §2A forbids. Empty = may leave the box (decision 1 scope only)."""
    hits: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            kl = str(k).lower()
            if kl in PORTFOLIO_KEYS or kl in SECRET_KEYS:
                hits.append(f"{path}.{k}: forbidden key")
            hits.extend(egress_violations(v, f"{path}.{k}"))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            hits.extend(egress_violations(v, f"{path}[{i}]"))
    elif isinstance(value, str):
        for rx, rep in (*_SECRET_RES, *_PORTFOLIO_RES):
            if rx.sub(rep, value) != value:   # an already-redacted value is a fixed point, not a hit
                hits.append(f"{path}: pattern {rx.pattern[:40]}")
                break
        for line in value.splitlines():
            if line != WITHHELD_LINE and _PORTFOLIO_LINE.search(line):
                hits.append(f"{path}: portfolio line")
                break
    return hits


# ---------------------------------------------------------------- SIEM rows -> incidents

_MSG_FIELD = re.compile(r'\b(lane|kind|severity|source|workflow|execution|run|at|env)=("[^"]*"|\S+)')
_MSG_QUOTED = re.compile(r'\b(error|remediation)="([^"]*)"')


def parse_message(message: Any) -> dict[str, str]:
    """The SIEM bridge's one-line message (n8n_siem_bridge.message) back into fields. Unknown -> absent."""
    base = strip_diagnosis(message)
    out = {k: v.strip('"') for k, v in _MSG_FIELD.findall(base)}
    out.update(dict(_MSG_QUOTED.findall(base)))
    return out


def lane_of(row: Mapping[str, Any]) -> str:
    comp = str(row.get("component") or "")
    return comp[len(COMPONENT_PREFIX):] if comp.startswith(COMPONENT_PREFIX) else ""


def incident_key(row: Mapping[str, Any]) -> str:
    """One diagnosis per (row, finding text): a re-written finding is new evidence; a timestamp change or the
    bridge's folded diagnosis suffix is not. Same function the SIEM bridge matches records with."""
    return _incident_key(row.get("id"), row.get("severity"), row.get("message"))


def severity_at_least(severity: Any, minimum: str) -> bool:
    return SEVERITY_ORDER.get(str(severity or "").upper(), 9) <= SEVERITY_ORDER.get(minimum.upper(), 2)


def eligible(rows: Iterable[Mapping[str, Any]], catalogue: Mapping[str, Any], *, min_severity: str,
             done: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """(eligible rows, skipped [{id, lane, reason}]). Only catalogue lanes; never the diagnoser's own rows."""
    ok, skipped = [], []
    for r in rows:
        lane = lane_of(r)
        why = None
        if not lane:
            why = "not_an_n8n_row"
        elif lane == LANE_ID or lane.startswith("n8n_failure_diagnosis"):
            why = "own_row"
        elif lane not in catalogue:
            why = "lane_not_in_catalogue"
        elif not severity_at_least(r.get("severity"), min_severity):
            why = f"below_{min_severity.upper()}"
        elif incident_key(r) in done:
            why = "already_diagnosed"
        if why:
            skipped.append({"id": r.get("id"), "lane": lane, "reason": why})
        else:
            ok.append(dict(r))
    ok.sort(key=lambda r: (SEVERITY_ORDER.get(str(r.get("severity")).upper(), 9), -int(r.get("id") or 0)))
    return ok, skipped


# ---------------------------------------------------------------- evidence pack


def _ts(value: Any) -> Optional[float]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def run_evidence(run: Mapping[str, Any], *, timeout_s: Optional[float], now: float) -> dict[str, Any]:
    try:
        rec = json.loads(run.get("receipt_json") or "") or {}
    except (TypeError, ValueError):
        rec = {}
    item = {
        "id": f"run:{run.get('run_id')}", "kind": "ledger_run", "state": run.get("state"), "mode": run.get("mode"),
        "exit_code": run.get("exit_code"), "duration_s": run.get("duration_s"), "requested_at": run.get("requested_at"),
        "finished_at": run.get("finished_at"), "reason": rec.get("reason"),
        "timed_out": rec.get("timed_out"), "lock_skipped": rec.get("lock_skipped"),
        "output_signal": rec.get("output_signal"),
        "output_signal_advanced": (None if rec.get("output_signal_mtime_after") is None
                                   or rec.get("output_signal_mtime_before") is None
                                   else float(rec["output_signal_mtime_after"]) > float(rec["output_signal_mtime_before"])),
        "receipt_present": bool(rec),
        "stderr_tail": scrub_text(rec.get("stderr_tail"), max_chars=MAX_TAIL_CHARS) if rec.get("stderr_tail") else None,
        "stdout_tail": scrub_text(rec.get("stdout_tail"), max_chars=600) if rec.get("stdout_tail") else None,
    }
    if run.get("state") in ("RUNNING", "RUN_RUNNING"):
        started = _ts(run.get("started_at") or run.get("requested_at"))
        hb = _ts(run.get("heartbeat_at"))
        item["running_age_s"] = None if started is None else round(now - started, 1)
        item["heartbeat_age_s"] = None if hb is None else round(now - hb, 1)
        item["overdue_2x_timeout"] = bool(started is not None and timeout_s and now - started > 2 * float(timeout_s))
    return {k: v for k, v in item.items() if v is not None}


def build_evidence(row: Mapping[str, Any], entry: Mapping[str, Any], *, registry_row: Optional[Mapping[str, Any]],
                   runs: list[Mapping[str, Any]], now: float) -> dict[str, Any]:
    """The grounded pack the model sees. Built only from metadata, error text and log lines, then scrubbed."""
    lane = lane_of(row)
    fields = parse_message(row.get("message"))
    actions = entry.get("actions") or []
    timeout = next((a.get("timeout_s") for a in actions if a.get("timeout_s")), None)
    sched = (registry_row or {}).get("scheduler") or {}
    evidence: list[dict[str, Any]] = [{
        "id": f"siem:{row.get('id')}", "kind": "siem_row", "event_type": row.get("event_type"),
        "severity": row.get("severity"), "created_at": str(row.get("created_at") or ""),
        "finding_source": fields.get("source"), "n8n_workflow_id": fields.get("workflow"),
        "n8n_execution_id": fields.get("execution"),
        "run": fields.get("run"), "error": scrub_text(fields.get("error"), max_chars=MAX_MESSAGE_CHARS),
        "default_remediation_hint": scrub_text(fields.get("remediation"), max_chars=400),
    }, {
        "id": f"registry:{lane}", "kind": "lane_registry", "state": (registry_row or {}).get("state"),
        "scheduler_kind": sched.get("kind"), "cadence": sched.get("cadence") or sched.get("expression"),
        "expected_cadence_hours": (registry_row or {}).get("expected_cadence_hours"),
        "output_signal": ((registry_row or {}).get("output_signal") or {}).get("path"),
    }, {
        "id": f"catalogue:{lane}", "kind": "remediation_catalogue", "severity": entry.get("severity"),
        "known_issues": [scrub_text(k.get("known_issues"), max_chars=600) for k in entry.get("known_issues") or []][:3],
        "actions": [{"action_id": a.get("action_id"), "auto": a.get("auto"), "mode_sequence": a.get("mode_sequence"),
                     "preconditions": a.get("preconditions")} for a in actions],
        "suggest_only_reason": entry.get("suggest_only_reason"),
    }]
    for r in runs[:6]:
        evidence.append(run_evidence(r, timeout_s=timeout, now=now))
    pack = {
        "schema": EVIDENCE_SCHEMA, "lane_id": lane, "event_type": row.get("event_type"),
        "allowed_action_ids": [a.get("action_id") for a in actions] + [SUGGEST_ONLY],
        "data_scope": "lane metadata, error text, log lines (AGENTS.md §2A, operator decision 2026-10-09 23:38 ET)",
        "evidence": evidence,
    }
    return scrub_obj(pack)


def evidence_ids(pack: Mapping[str, Any]) -> set[str]:
    return {str(e.get("id")) for e in pack.get("evidence") or [] if e.get("id")}


# ---------------------------------------------------------------- verdict + decision


def projected_cost_usd(prompt_chars: int, max_output_tokens: int = PROJ_MAX_OUTPUT_TOKENS) -> float:
    tokens_in = prompt_chars / 3.0
    return round(tokens_in * PROJ_INPUT_USD_PER_M / 1e6 + max_output_tokens * PROJ_OUTPUT_USD_PER_M / 1e6, 6)


def check_verdict(answer: Any, entry: Optional[Mapping[str, Any]], ids: set[str]) -> dict[str, Any]:
    """Validate one model answer against the lane's catalogue and the pack's evidence ids."""
    out: dict[str, Any] = {"ok": False, "action_id": SUGGEST_ONLY, "confidence": 0.0, "problems": [], "grounded": False}
    if not isinstance(answer, Mapping):
        out["problems"].append("not_an_object")
        return out
    conf = answer.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
        out["problems"].append("confidence_out_of_range")
        conf = 0.0
    out["confidence"] = float(conf)
    aid = str(answer.get("action_id") or "")
    if aid != SUGGEST_ONLY and lane_action(entry, aid) is None:
        out["problems"].append(f"action_not_in_catalogue:{aid[:64]}")
        out["refused_action_id"] = aid[:64]
    else:
        out["action_id"] = aid
    cites = [str(c) for c in answer.get("citations") or []]
    out["citations"] = cites[:12]
    out["grounded"] = bool(cites) and all(c in ids for c in cites)
    if not out["grounded"]:
        out["problems"].append("ungrounded_citations" if cites else "no_citations")
    out["cause"] = scrub_text(answer.get("cause"), max_chars=400)
    out["rationale"] = scrub_text(answer.get("rationale"), max_chars=600)
    out["ok"] = not out["problems"]
    return out


def decide(verdict: Mapping[str, Any], entry: Mapping[str, Any], *, lane_remediations_today: int,
           lane_recent_remediation: bool) -> dict[str, Any]:
    """execute | escalate. P1 = low confidence (incl. ungrounded) or a refused action; P2 = needs a human."""
    aid = str(verdict.get("action_id") or SUGGEST_ONLY)
    if any(str(p).startswith("action_not_in_catalogue") for p in verdict.get("problems") or []):
        return {"kind": "escalate", "priority": "P1", "reason": "action_not_in_catalogue_refused", "action_id": SUGGEST_ONLY}
    if float(verdict.get("confidence") or 0.0) < CONFIDENCE_MIN or not verdict.get("grounded"):
        why = "low_confidence" if verdict.get("grounded") else "low_confidence_ungrounded"
        return {"kind": "escalate", "priority": "P1", "reason": why, "action_id": SUGGEST_ONLY}
    if aid == SUGGEST_ONLY:
        return {"kind": "escalate", "priority": "P2", "reason": "suggest_only", "action_id": SUGGEST_ONLY}
    action = lane_action(entry, aid) or {}
    if not action.get("auto"):
        return {"kind": "escalate", "priority": "P2", "reason": f"approval_required:{action.get('approval_reason')}",
                "action_id": aid}
    if lane_recent_remediation and aid != "reap_orphan_run":
        return {"kind": "escalate", "priority": "P2", "reason": "repeat_failure_within_24h", "action_id": aid}
    if lane_remediations_today >= int(action.get("max_per_lane_per_day") or 3):
        return {"kind": "escalate", "priority": "P2", "reason": "lane_daily_remediation_cap", "action_id": aid}
    return {"kind": "execute", "priority": None, "reason": "catalogue_auto_action", "action_id": aid, "action": action}


def remediation_run_id(key: str, mode: str) -> str:
    """Ledger run id for a remediation request (gateway RUN_ID_RE: [A-Za-z0-9._:-]{16,128})."""
    return f"rem-{key}-{mode}"[:128]


def incident_refs(row: Mapping[str, Any]) -> dict[str, Any]:
    """The incident's references as the bridge's message names them (run / workflow / execution / source)."""
    f = parse_message(row.get("message"))
    return {k: f.get(k) for k in ("run", "workflow", "execution", "source", "at") if f.get(k) not in (None, "n/a")}


def diagnosis_record(res: Mapping[str, Any], row: Mapping[str, Any], *, outcome: Any, now: datetime) -> dict[str, Any]:
    """One N8nLaneDiagnosis@v1 line for the diagnoser's own store (never the SIEM table)."""
    v = res.get("verdict") or {}
    dec = res.get("decision") or {}
    return {
        "schema": DIAGNOSIS_SCHEMA, "kind": "diagnosis", "at": now.isoformat(),
        "incident_key": res.get("incident_key"), "siem_id": res.get("siem_id"),
        "component": row.get("component") or f"{COMPONENT_PREFIX}{res.get('lane')}",
        "event_type": res.get("event_type"), "severity": res.get("severity"), "lane": res.get("lane"),
        "incident_refs": incident_refs(row),
        "cause": v.get("cause") or res.get("reason"), "confidence": v.get("confidence"),
        "action_id": dec.get("action_id"), "decision": {k: dec.get(k) for k in ("kind", "priority", "reason")},
        "outcome": outcome, "escalation": res.get("escalation"),
        "provider": res.get("provider"), "model_id": res.get("model_id"), "cost_usd": res.get("cost_usd"),
        "cost_basis": res.get("cost_basis"), "latency_ms": res.get("latency_ms"),
        "citations": v.get("citations"), "evidence_artifact": res.get("evidence_artifact"),
        "remediation_run_id": (res.get("action_result") or {}).get("run_id"),
        "live_phase_dropped": res.get("live_phase_dropped"),
    }


def remediation_record(ev: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """One N8nLaneDiagnosis@v1 remediation-step line (a pending rerun moved on)."""
    return {
        "schema": DIAGNOSIS_SCHEMA, "kind": "remediation", "at": now.isoformat(),
        "incident_key": ev.get("incident_key"), "siem_id": ev.get("siem_id"), "lane": ev.get("lane"),
        "remediation_run_id": ev.get("run_id"), "run_state": ev.get("run_state"), "outcome": ev.get("outcome"),
        "next": ev.get("next"), "escalation": ev.get("escalate"),
    }


#: no_diagnosis reasons that would repeat identically next cycle: recorded as done (escalated once).
#: Everything else (deferral, caps, a refused/failed model call) is retried, bounded by the per-lane call cap.
FINAL_NO_DIAGNOSIS = ("egress_refused", "per_call_cost_cap")
