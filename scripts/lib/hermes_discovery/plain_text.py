"""Plain-English wording for system-health discovery candidates (FQ-059).

The research desk's "Proposed topics" rail showed candidates whose whole text was the health checker's own
vocabulary: `System health: proposal_enrichment ERROR` / `cron_health check for proposal_enrichment is ERROR
(severity INFO, failure_count 1) — success_timestamp_in_future`. An operator reading the desk cannot tell what broke,
what it prevents, or whether it matters.

`plain_health_candidate()` turns that into what it means and what it costs, and returns the original text as
`technical` so nothing is lost. It is deliberately narrow: it only rewrites a candidate that matches the health-check
shape this repository's `system_ops` adapter writes, and returns None for anything else — a new producer's wording is
never guessed at.

Pure: strings in, dict out. No I/O.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_LABEL_RE = re.compile(r"^System health:\s*(?P<component>[A-Za-z0-9_.\-]+)\s+(?P<status>[A-Z_]+)\s*$")
_SUMMARY_RE = re.compile(
    r"^(?P<check>[A-Za-z0-9_.\-]+)\s+check for\s+(?P<component>[A-Za-z0-9_.\-]+)\s+is\s+(?P<status>[A-Z_]+)",
    re.IGNORECASE,
)

_STATUS_WORDS = {
    "ERROR": "an error",
    "FAILED": "a failure",
    "FAILURE": "a failure",
    "MISSING": "no recent run",
    "STALE": "stale results",
    "TIMEOUT": "a timeout",
    "CRASHED": "a crash",
    "UNKNOWN": "an unknown state",
}

_REASON_WORDS = (
    ("success_timestamp_in_future", "its last-success time is in the future, so its freshness cannot be trusted"),
    ("no_success_recorded", "no successful run is recorded"),
    ("never_ran", "it has not run yet"),
    ("timeout", "it ran out of time"),
    ("connection", "a data source could not be reached"),
    ("permission", "it was not allowed to read what it needed"),
)


def _task_name(component: str) -> str:
    text = re.sub(r"[_\-]+", " ", str(component or "")).strip()
    return text or "a scheduled task"


def _impact(status: str) -> str:
    s = str(status or "").upper()
    if s in ("MISSING", "NEVER_RAN"):
        return "It has not run recently, so any research it normally produces is not being produced."
    return "Until that clears, the research it feeds may be incomplete or out of date."


def plain_health_candidate(label: Any, summary: Any, meta: Optional[dict] = None) -> Optional[dict[str, str]]:
    """Return {"label", "summary", "technical"} for a health-check candidate, else None.

    Never raises and never invents a component: if neither the label nor the summary carries the shape this adapter
    writes, the caller keeps the candidate exactly as it is.
    """
    lab = str(label or "").strip()
    summ = str(summary or "").strip()
    m = _LABEL_RE.match(lab) or _SUMMARY_RE.match(summ) or _SUMMARY_RE.match(lab)
    if not m:
        return None
    component = str(m.group("component") or "").strip()
    status = str(m.group("status") or "").strip().upper()
    name = _task_name(component)
    status_word = _STATUS_WORDS.get(status, "a problem")

    reason = ""
    low = summ.lower()
    for needle, words in _REASON_WORDS:
        if needle in low:
            reason = words
            break
    if not reason:
        # The trailing "— <reason>" the adapter appends, when it is not one of the known shapes.
        tail = summ.split("—", 1)[1].strip() if "—" in summ else ""
        reason = f"the reported reason is {tail}" if tail else ""

    plain_label = f"Health check needs attention: {name}"
    plain_summary = f"The scheduled task {name} reported {status_word}."
    if reason:
        plain_summary += f" {reason[:1].upper()}{reason[1:]}."
    plain_summary += f" {_impact(status)}"

    technical = " · ".join(x for x in (lab, summ) if x)
    return {"label": plain_label, "summary": plain_summary, "technical": technical}
