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

    @property
    def fail_rate(self) -> float:
        return (self.failures / self.calls) if self.calls else 0.0


def evaluate(
    rows: Iterable[dict[str, Any]],
    *,
    min_calls: int = DEFAULT_MIN_CALLS,
    fail_rate: float = DEFAULT_FAIL_RATE,
) -> list[Finding]:
    """Findings for lanes that are failing hard enough to be someone's problem.

    Each row is one ledger call: model_name, process_id, success, error_message.
    A lane is reported when its failure rate meets the threshold over enough calls.
    Billing and auth failures are reported at ANY volume — one 402 is already the
    whole account, and waiting for five of them wastes five more calls.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        lane = str(row.get("model_name") or row.get("model_lane") or "unknown")
        b = buckets.setdefault(
            lane,
            {"calls": 0, "failures": 0, "kinds": {}, "processes": set(), "sample": ""},
        )
        b["calls"] += 1
        if row.get("success"):
            continue
        b["failures"] += 1
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
            )
        )
    # Loudest first, so a truncated alert still carries the billing line.
    findings.sort(key=lambda f: (f.severity != "CRITICAL", -f.failures))
    return findings


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
        lines.append(
            f"• {f.lane}: {f.failures}/{f.calls} calls failed ({f.fail_rate:.0%}) — {f.kind}"
        )
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
