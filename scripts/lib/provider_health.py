"""Provider-health classification for the LLM consumption ledger.

Why this exists: between 2026-09-17 and 2026-09-19 the DeepSeek account ran to a -$0.09
balance and returned HTTP 402 on every single call. 660+ failures accumulated over three
days across `watchlist_maria_flash_narrative` and `hermes_external_research`, risk/steph/tax
produced nothing, and **no check anywhere looked at why the calls were failing** — the health
agents inspect data freshness, not provider errors. A dead paid lane drained request-cap
reservations silently.

Pure functions only: no DB, no network, no Telegram. The caller supplies rows and decides
what to do with the findings, so this stays testable without touching production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# A lane is only judged once it has done enough work for a rate to mean anything.
DEFAULT_MIN_CALLS = 5
DEFAULT_FAIL_RATE = 0.9

# Successes after a lane's last failure that count as recovery. The window is hours wide,
# so a resolved outage stays inside it and would otherwise be re-paged after the operator
# had already fixed it — measured 2026-09-19: the last 402 landed at 19:15:06, the account
# was topped up by 19:46, and the 3h window still reported CRITICAL with the lane healthy.
# Paging someone for a thing they just fixed is how alerts get ignored. More than one
# success is required because a partial outage can let a single call through.
DEFAULT_RECOVERY_SUCCESSES = 3

BILLING_MARKERS = (
    "HTTP_402",
    "402",
    "INSUFFICIENT BALANCE",
    "INSUFFICIENT_BALANCE",
    "PAYMENT REQUIRED",
    "PAYMENT_REQUIRED",
    "QUOTA EXCEEDED",
    "BILLING",
)
AUTH_MARKERS = (
    "HTTP_401",
    "HTTP_403",
    "401",
    "403",
    "INVALID API KEY",
    "INVALID_API_KEY",
    "UNAUTHORIZED",
    "AUTHENTICATION",
)
TRANSPORT_MARKERS = (
    "HTTP_5",
    "502",
    "503",
    "504",
    "BAD GATEWAY",
    "NETWORK_ERROR",
    "TIMEOUT",
    "TIMED OUT",
    "CONNECTION",
)

# Billing and auth are the operator's problem and nothing retries them away; transport
# failures usually heal on their own and must not page at the same severity.
SEVERITY = {"BILLING": "CRITICAL", "AUTH": "CRITICAL", "TRANSPORT": "WARN", "UNKNOWN": "WARN"}


def classify_error(message: str | None) -> str | None:
    """BILLING | AUTH | TRANSPORT | UNKNOWN for a failure, None for a success."""
    if not message:
        return None
    up = str(message).upper()
    # Billing first: a 402 body often also mentions the word "authentication".
    if any(m in up for m in BILLING_MARKERS):
        return "BILLING"
    if any(m in up for m in AUTH_MARKERS):
        return "AUTH"
    if any(m in up for m in TRANSPORT_MARKERS):
        return "TRANSPORT"
    return "UNKNOWN"


@dataclass
class Finding:
    lane: str
    kind: str
    severity: str
    calls: int
    failures: int
    processes: list[str] = field(default_factory=list)
    sample_error: str = ""
    # The lane failed inside the window but has since succeeded: reported, never paged.
    recovered: bool = False

    @property
    def fail_rate(self) -> float:
        return (self.failures / self.calls) if self.calls else 0.0


def evaluate(
    rows: Iterable[dict[str, Any]],
    *,
    min_calls: int = DEFAULT_MIN_CALLS,
    fail_rate: float = DEFAULT_FAIL_RATE,
    recovery_successes: int = DEFAULT_RECOVERY_SUCCESSES,
) -> list[Finding]:
    """Findings for lanes that are failing hard enough to be someone's problem.

    Each row is one ledger call: model_name, process_id, success, error_message, and
    optionally created_at — supplied, it lets a recovered lane be marked instead of paged.
    A lane is reported when its failure rate meets the threshold over enough calls.
    Billing and auth failures are reported at ANY volume — one 402 is already the
    whole account, and waiting for five of them wastes five more calls.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        lane = str(row.get("model_name") or row.get("model_lane") or "unknown")
        b = buckets.setdefault(
            lane,
            {
                "calls": 0,
                "failures": 0,
                "kinds": {},
                "processes": set(),
                "sample": "",
                "success_at": [],
                "failure_at": [],
            },
        )
        b["calls"] += 1
        if row.get("success"):
            b["success_at"].append(row.get("created_at"))
            continue
        b["failures"] += 1
        b["failure_at"].append(row.get("created_at"))
        kind = classify_error(row.get("error_message")) or "UNKNOWN"
        b["kinds"][kind] = b["kinds"].get(kind, 0) + 1
        if row.get("process_id"):
            b["processes"].add(str(row["process_id"]))
        if not b["sample"]:
            b["sample"] = str(row.get("error_message") or "")[:200]

    findings: list[Finding] = []
    for lane, b in sorted(buckets.items()):
        if not b["failures"]:
            continue
        kind = max(b["kinds"].items(), key=lambda kv: kv[1])[0]
        hard = kind in ("BILLING", "AUTH")
        rate = b["failures"] / b["calls"]
        if not hard and (b["calls"] < min_calls or rate < fail_rate):
            continue
        findings.append(
            Finding(
                lane=lane,
                kind=kind,
                severity=SEVERITY.get(kind, "WARN"),
                calls=b["calls"],
                failures=b["failures"],
                processes=sorted(b["processes"]),
                sample_error=b["sample"],
                recovered=_recovered(b, recovery_successes),
            )
        )
    # Loudest first, so a truncated alert still carries the billing line.
    findings.sort(key=lambda f: (f.severity != "CRITICAL", -f.failures))
    return findings


def _recovered(bucket: dict[str, Any], needed: int) -> bool:
    """True when the lane has succeeded enough times since its last failure.

    Timestamps are optional, and a caller that supplies none gets the old behaviour:
    everything that failed in the window is still a finding.
    """
    if needed <= 0:
        return False
    fails = [t for t in bucket["failure_at"] if t is not None]
    if not fails or len(fails) != bucket["failures"]:
        return False  # partial timestamps prove nothing; stay loud
    try:
        last_fail = max(fails)
        after = sum(1 for t in bucket["success_at"] if t is not None and t > last_fail)
    except TypeError:
        return False  # mixed naive/aware datetimes — not worth a wrong silence
    return after >= needed


def pageable(findings: Iterable[Finding]) -> list[Finding]:
    """The findings worth waking someone for: everything that has not recovered."""
    return [f for f in findings if not f.recovered]


def format_alert(
    findings: list[Finding],
    *,
    window_hours: float,
    balance: dict[str, Any] | None = None,
) -> str:
    """Operator-facing text. Names the lane, the cause, and what to do about it."""
    if not findings:
        return ""
    worst = findings[0].severity
    head = "🔴" if worst == "CRITICAL" else "⚠️"
    lines = [f"{head} LLM provider lane failing — last {window_hours:g}h", ""]
    for f in findings:
        lines.append(f"• {f.lane}: {f.failures}/{f.calls} calls failed ({f.fail_rate:.0%}) — {f.kind}")
        if f.processes:
            shown = ", ".join(f.processes[:4])
            more = f" +{len(f.processes) - 4} more" if len(f.processes) > 4 else ""
            lines.append(f"  callers: {shown}{more}")
        if f.sample_error:
            lines.append(f"  {f.sample_error[:120]}")
    if balance:
        bal = balance.get("total_balance")
        avail = balance.get("is_available")
        lines += ["", f"DeepSeek balance: {bal} (available={avail})"]
    if any(f.kind == "BILLING" for f in findings):
        lines += ["", "Billing failure — no retry clears this. Top up the provider account."]
    elif any(f.kind == "AUTH" for f in findings):
        lines += ["", "Auth failure — the key is rejected. Rotate or re-issue it."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- stalls
#
# 2026-10-15: from 00:33Z DeepSeek held every bridge request to the deadline or answered 503, across four
# processes, and llm_provider_health.json said OK (560 calls, no findings). Two reasons: the governed bridge
# writes llm_consumption_log only for SERVED calls, so its failed attempts never reached `evaluate` above; and a
# 3 h, 90 % aggregate cannot see a 30 minute burst. Stalls are judged from the provider_cost event ledger,
# which records every bridge attempt (TIMEOUT / HTTP_503 as possibly_billable_attempt), over a short window.
# Thresholds come from config/llm_provider_health.json; these are only the fallbacks when it is unreadable.

DEFAULT_STALL_POLICY: dict[str, Any] = {
    "window_minutes": 30,
    "consecutive_threshold": 3,
    "ratio_threshold": 0.5,
    "min_events_for_ratio": 3,
    "consecutive_lookback_minutes": 120,
    "recovery_successes": 3,
    "stall_error_classes": ["TIMEOUT", "HTTP_502", "HTTP_503", "HTTP_504", "HTTP_529"],
    "tail_bytes": 8 * 1024 * 1024,
    "dedupe_minutes": 120,
    "priority_degraded": "P3",
    "priority_all_lanes_down": "P1",
}

STALL_DEGRADED = "DEGRADED"
STALL_CRITICAL = "CRITICAL"


def stall_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    """DEFAULT_STALL_POLICY overlaid with the config's `stall` block (unknown keys ignored)."""
    out = dict(DEFAULT_STALL_POLICY)
    block = config.get("stall") if isinstance(config, dict) else None
    if isinstance(block, dict):
        for key, value in block.items():
            if key in out and value is not None:
                out[key] = value
    return out


@dataclass
class StallFinding:
    provider: str
    # DEGRADED: a lane is down but every caller still has another (digest). CRITICAL: some caller has none (page).
    severity: str
    consecutive_stalls: int
    window_events: int
    window_stalls: int
    window_minutes: float
    error_classes: dict[str, int] = field(default_factory=dict)
    processes: list[str] = field(default_factory=list)
    all_lanes_down_processes: list[str] = field(default_factory=list)
    last_stall_at: str = ""
    recovered: bool = False

    @property
    def stall_rate(self) -> float:
        return (self.window_stalls / self.window_events) if self.window_events else 0.0


def _event_time(ev: dict[str, Any]) -> Any:
    from datetime import datetime, timezone

    for key in ("usage_start", "observed_at", "usage_end"):
        raw = ev.get(key)
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def _event_kind(ev: dict[str, Any], stall_classes: set[str]) -> str | None:
    """'ok' | 'stall' | 'other' (a failure that is not a stall) | None (not a provider attempt)."""
    if ev.get("is_test") is True:
        return None
    outcome = str(ev.get("outcome") or "")
    if outcome == "success":
        return "ok"
    if outcome != "possibly_billable_attempt":
        return None  # pre_send_failure and the like never reached the provider
    cls = str(ev.get("error_class") or "").upper()
    if cls in stall_classes or "OVERLOAD" in cls:
        return "stall"
    return "other"


def process_lane_providers(routing_doc: dict[str, Any] | None, process_id: str, provider: str) -> set[str]:
    """The providers a process can be served by. A row that walks routes (transport_failover) has every lane's
    provider; any other row is served only by its primary lane. A process with no row has the provider it used."""
    doc = routing_doc if isinstance(routing_doc, dict) else {}
    blocks: list[dict[str, Any]] = []
    policies = doc.get("policies")
    if isinstance(policies, dict):
        default = str(doc.get("default_policy_id") or "default")
        ordered = [default] + [k for k in policies if k != default]
        blocks = [policies[k] for k in ordered if isinstance(policies.get(k), dict)]
    if isinstance(doc.get("processes"), dict):
        blocks.append(doc)
    for block in blocks:
        processes = block.get("processes")
        row = processes.get(process_id) if isinstance(processes, dict) else None
        if not isinstance(row, dict):
            continue
        lanes = ("primary", "secondary", "fallback") if row.get("transport_failover") is True else ("primary",)
        found = {
            str(row[k].get("provider") or "").lower()
            for k in lanes
            if isinstance(row.get(k), dict) and row[k].get("provider")
        }
        if found:
            return found
    return {str(provider).lower()}


def evaluate_stalls(
    events: Iterable[dict[str, Any]],
    *,
    now: Any,
    policy: dict[str, Any] | None = None,
    routing_doc: dict[str, Any] | None = None,
) -> list[StallFinding]:
    """Providers whose recent attempts are mostly timeouts or overload answers.

    `events` are provider_cost events; `now` is an aware datetime. A provider is stalling when its newest
    `consecutive_threshold` attempts inside the lookback are all stalls (other failure kinds are skipped, a
    success ends the run), or when more than `ratio_threshold` of its attempts in the last `window_minutes`
    stalled (given at least `min_events_for_ratio` attempts). It has recovered once its newest
    `recovery_successes` attempts succeeded: reported, never paged. Severity is CRITICAL when some process that
    stalled on it has no allowed lane whose provider is not itself stalling, else DEGRADED.
    """
    from datetime import timedelta

    pol = stall_policy({"stall": policy or {}})
    stall_classes = {str(c).upper() for c in pol["stall_error_classes"]}
    window = timedelta(minutes=float(pol["window_minutes"]))
    lookback = max(window, timedelta(minutes=float(pol["consecutive_lookback_minutes"])))
    per: dict[str, list[tuple[Any, str, dict[str, Any]]]] = {}
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("provider"):
            continue
        kind = _event_kind(ev, stall_classes)
        ts = _event_time(ev)
        if kind is None or ts is None or ts < now - lookback or ts > now + timedelta(minutes=5):
            continue
        per.setdefault(str(ev["provider"]).lower(), []).append((ts, kind, ev))

    found: list[StallFinding] = []
    for provider, rows in sorted(per.items()):
        rows.sort(key=lambda r: r[0])
        consecutive = 0
        for _ts, kind, _ev in reversed(rows):
            if kind == "ok":
                break
            if kind == "stall":
                consecutive += 1
        trailing_ok = 0
        for _ts, kind, _ev in reversed(rows):
            if kind == "stall":
                break
            if kind == "ok":
                trailing_ok += 1
        in_window = [r for r in rows if r[0] >= now - window]
        window_stalls = sum(1 for r in in_window if r[1] == "stall")
        ratio_hit = len(in_window) >= int(pol["min_events_for_ratio"]) and (
            window_stalls / len(in_window) > float(pol["ratio_threshold"])
        )
        if consecutive < int(pol["consecutive_threshold"]) and not ratio_hit:
            continue
        stall_rows = [r for r in rows if r[1] == "stall"]
        classes: dict[str, int] = {}
        for _ts, _kind, ev in stall_rows:
            cls = str(ev.get("error_class") or "UNKNOWN").upper()
            classes[cls] = classes.get(cls, 0) + 1
        needed = int(pol["recovery_successes"])
        found.append(
            StallFinding(
                provider=provider,
                severity=STALL_DEGRADED,
                consecutive_stalls=consecutive,
                window_events=len(in_window),
                window_stalls=window_stalls,
                window_minutes=float(pol["window_minutes"]),
                error_classes=classes,
                processes=sorted({str(ev["source_process"]) for _t, _k, ev in stall_rows if ev.get("source_process")}),
                last_stall_at=stall_rows[-1][0].isoformat() if stall_rows else "",
                recovered=needed > 0 and trailing_ok >= needed,
            )
        )

    down = {f.provider for f in found if not f.recovered}
    for f in found:
        if f.recovered:
            continue
        f.all_lanes_down_processes = [
            p for p in f.processes if process_lane_providers(routing_doc, p, f.provider) <= down
        ]
        if f.all_lanes_down_processes:
            f.severity = STALL_CRITICAL
    found.sort(key=lambda f: (f.severity != STALL_CRITICAL, f.recovered, -f.window_stalls))
    return found


def format_stall_alert(findings: list[StallFinding]) -> str:
    """Operator text: which provider, how bad, and who has no lane left."""
    if not findings:
        return ""
    critical = any(f.severity == STALL_CRITICAL for f in findings)
    head = "🔴 LLM provider stalling — a process has no lane left" if critical else "⚠️ LLM provider stalling"
    lines = [head, ""]
    for f in findings:
        classes = ", ".join(f"{k}×{v}" for k, v in sorted(f.error_classes.items()))
        lines.append(
            f"• {f.provider}: {f.window_stalls}/{f.window_events} attempts stalled in the last "
            f"{f.window_minutes:g} min, {f.consecutive_stalls} in a row ({classes}) — {f.severity}"
        )
        if f.all_lanes_down_processes:
            shown = ", ".join(f.all_lanes_down_processes[:4])
            more = f" +{len(f.all_lanes_down_processes) - 4} more" if len(f.all_lanes_down_processes) > 4 else ""
            lines.append(f"  no lane left: {shown}{more}")
        elif f.processes:
            lines.append(f"  callers (another lane still open): {', '.join(f.processes[:4])}")
    lines += ["", "Timeouts and 503 overload are provider-side; retrying sooner only burns the deadline."]
    return "\n".join(lines)
