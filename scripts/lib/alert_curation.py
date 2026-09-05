"""alert_curation.py — turn a firing alert into something a human can act on.

READ_ONLY_ADVISORY. Pure functions plus one optional, guarded LLM call. Sends
nothing, writes nothing, and changes no system it describes.

THE DEFECT THIS EXISTS TO REMOVE
--------------------------------
The research-lane alert reached the operator looking like this:

    Firing:
      • chatgpt: error_streak:11>=5,zero_non_error_24h,error_rate_24h:100.0>=15
        streak=11  ok_24h=0 attempts_24h=11 (state held 2h)

    Fix:
      chatgpt: error_streak:11>=5 zero_non_error_24h error_rate_24h:100.0>=15

The `Fix:` section restates the trigger. `research_lane_health.fix_hint` ends
`if firing: return firing`, so any lane without a hand-written branch has its
symptom printed under a heading that promises a cause. A field whose NAME says
"what to do" and whose CONTENT says "what tripped" is worse than an empty field:
the operator reads it, learns nothing, and concludes there is nothing to learn.

The measured cause of that specific alert was not in the message at all. The
proxy pins `DEFAULT_MODEL = "gpt-5.4"` (chatgpt_oauth_proxy.py:27) and the
account rejects it with a 400. Two of the four slugs in its own `MODELS` list
still work. One environment variable fixes it. None of that is derivable from
`error_streak:11>=5`.

WHAT CURATION MAY AND MAY NOT DO
--------------------------------
It may reorder, group, name a known cause, and write plain English.

It may **not** invent a number, drop a firing lane, or soften a fault. Those are
enforced, not requested: `validate_curation` rejects prose containing any figure
absent from the evidence, and rejects any curation that fails to name a lane the
input said was firing. An LLM that violates either is discarded and the
deterministic rendering is used instead.

That asymmetry is deliberate. The failure mode of a curated alert is not ugly
prose — it is a confident sentence that is not true, or a quiet one that omits
the fault. Both are worse than the raw JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA = "AlertCuration@v1"

#: Numbers that appear in ordinary prose and must not be treated as claims.
_BENIGN_NUMBERS = {"0", "1", "2", "3", "4", "5", "24", "100"}

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class KnownCause:
    """A cause someone has actually diagnosed, with the action that follows."""

    lane: str
    matches: tuple[str, ...]          # firing tokens that select this cause
    cause: str
    action: str
    evidence: str = ""

    def applies(self, firing: str) -> bool:
        return all(m in firing for m in self.matches)


#: Causes diagnosed by measurement, not guessed. Each was confirmed against the
#: running system before being written here. A cause nobody has diagnosed does
#: NOT get an entry — the honest output is "cause not diagnosed", which at least
#: tells the operator the difference between a known and an unknown failure.
KNOWN_CAUSES: tuple[KnownCause, ...] = (
    KnownCause(
        lane="chatgpt",
        matches=("zero_non_error_24h",),
        cause=(
            "the local ChatGPT proxy is pinned to a model this account cannot use. "
            "chatgpt_oauth_proxy.py:27 sets DEFAULT_MODEL=gpt-5.4 and the backend "
            "returns 400 'not supported when using Codex with a ChatGPT account'. "
            "Every attempt fails the same way, which is why the error rate is total "
            "rather than intermittent."
        ),
        action=(
            "set CHATGPT_PROXY_MODEL=gpt-5.5 in the proxy's environment and restart "
            "it. gpt-5.5 and gpt-5.4-mini were both confirmed working against this "
            "account on 2026-09-05; gpt-5.4 and every *-codex slug were rejected."
        ),
        evidence="probed all six slugs in the proxy's MODELS list directly",
    ),
)


@dataclass
class CuratedAlert:
    """What the operator should see. Every field is derived, none invented."""

    headline: str
    urgency: str                                   # ACT_NOW / LOOK_TODAY / FYI
    lanes: list[str] = field(default_factory=list)
    plain_english: str = ""
    action: str = ""
    evidence: list[str] = field(default_factory=list)
    cause_known: bool = False
    curated_by: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "headline": self.headline,
            "urgency": self.urgency,
            "lanes": self.lanes,
            "plain_english": self.plain_english,
            "action": self.action,
            "evidence": self.evidence,
            "cause_known": self.cause_known,
            "curated_by": self.curated_by,
        }

    def render(self) -> str:
        """Telegram text. Short, and the action is above the evidence."""
        icon = {"ACT_NOW": "\U0001f534", "LOOK_TODAY": "\U0001f7e0"}.get(self.urgency, "\U0001f7e1")
        out = [f"{icon} {self.headline}", ""]
        if self.plain_english:
            out += [self.plain_english, ""]
        if self.action:
            out += ["*What to do*", self.action, ""]
        if not self.cause_known:
            out += ["_Cause not diagnosed — the evidence below is raw._", ""]
        if self.evidence:
            out += ["*Evidence*"] + [f"  • {e}" for e in self.evidence]
        return "\n".join(out).strip()


def _numbers(text: str) -> set[str]:
    return {n for n in _NUM_RE.findall(text or "") if n not in _BENIGN_NUMBERS}


def firing_lanes(report: dict) -> list[dict]:
    return [r for r in (report.get("lanes") or []) if not r.get("ok")]


def _urgency(rows: list[dict]) -> str:
    """How loudly to speak. Total failure of a lane outranks a rate."""
    for r in rows:
        firing = " ".join(str(x) for x in (r.get("firing") or []))
        if "zero_non_error_24h" in firing and int(r.get("attempts_24h") or 0) > 0:
            # Tried repeatedly, succeeded never. That is broken, not degraded.
            return "ACT_NOW"
    return "LOOK_TODAY" if rows else "FYI"


def deterministic_curation(report: dict) -> CuratedAlert:
    """Curation with no model involved. This is the floor, and the fallback."""
    rows = firing_lanes(report)
    if not rows:
        return CuratedAlert(headline="Research lanes healthy", urgency="FYI")

    lanes = [str(r.get("lane") or "?") for r in rows]
    causes: list[KnownCause] = []
    for r in rows:
        firing = " ".join(str(x) for x in (r.get("firing") or []))
        for kc in KNOWN_CAUSES:
            if kc.lane == r.get("lane") and kc.applies(firing):
                causes.append(kc)
                break

    evidence = []
    for r in rows:
        lane = r.get("lane")
        firing = ", ".join(str(x) for x in (r.get("firing") or [])) or "firing"
        # A lane that does not MEASURE attempts must not be rendered as though it
        # measured zero. drive-sync, lane-registry and search-providers carry
        # None here; printing "0 attempts in 24h, 0 succeeded" for them states a
        # measurement that was never taken — the same defect as an unmetered
        # provider window read as a ceiling of zero.
        if r.get("attempts_24h") is None and r.get("error_streak") is None:
            evidence.append(f"{lane}: {firing} (this lane reports no call counters)")
        else:
            evidence.append(
                f"{lane}: {int(r.get('attempts_24h') or 0)} attempts in 24h, "
                f"{int(r.get('non_error_24h') or 0)} succeeded, "
                f"error streak {int(r.get('error_streak') or 0)} — {firing}")

    if causes:
        plain = " ".join(
            f"The {c.lane} research lane is not working: {c.cause}" for c in causes)
        action = "\n".join(f"  • {c.action}" for c in causes)
        others = [x for x in lanes if x not in {c.lane for c in causes}]
        extra = f" (+{len(others)} more firing)" if others else ""
        headline = (f"{', '.join(sorted({c.lane for c in causes}))} lane is down "
                    f"— cause known{extra}")
    else:
        n = len(rows)
        plain = (
            f"{n} research lane{'s' if n != 1 else ''} "
            f"({', '.join(lanes)}) {'are' if n != 1 else 'is'} failing every attempt. "
            "Nobody has diagnosed why, so the raw counters are below rather than a "
            "guess at the cause.")
        action = ("  • run scripts/research_lane_health.py --json and read the "
                  "lane's RAW rows; the [ERROR] text carries the real reason")
        headline = f"{n} research lane{'s' if n != 1 else ''} failing"

    return CuratedAlert(
        headline=headline,
        urgency=_urgency(rows),
        lanes=lanes,
        plain_english=plain,
        action=action,
        evidence=evidence,
        cause_known=bool(causes),
        curated_by="deterministic",
    )


def validate_curation(curated: CuratedAlert, report: dict) -> list[str]:
    """Reasons this curation may not be sent. Empty list means it is safe.

    Two rules, both structural:

      * every lane the report says is firing must be named. A curated alert that
        quietly omits a fault is the failure this whole class of work exists to
        remove.
      * no number may appear in the prose that is not in the evidence. An LLM
        writing "the lane has been down for 3 days" when the input says two
        hours has produced a confident sentence that is not true, and the
        operator has no way to tell.
    """
    problems: list[str] = []

    expected = {str(r.get("lane") or "?") for r in firing_lanes(report)}
    named = " ".join([curated.headline, curated.plain_english, curated.action,
                      " ".join(curated.lanes), " ".join(curated.evidence)])
    missing = sorted(lane for lane in expected if lane not in named)
    if missing:
        problems.append(f"curation dropped firing lane(s): {', '.join(missing)}")

    # Trusted sources of figures: the report itself, the rendered evidence, and
    # the hand-diagnosed KNOWN_CAUSES text. The last one matters — a diagnosis
    # naming `gpt-5.4` or an HTTP 400 is the most useful thing in the message,
    # and a rule that forbade it would delete the only actionable content to
    # prevent a problem it does not have. This check exists to police MODEL
    # prose, so it only polices fields a model may author.
    trusted = " ".join([
        " ".join(curated.evidence),
        json.dumps(report, default=str),
        " ".join(kc.cause + " " + kc.action for kc in KNOWN_CAUSES),
    ])
    allowed = _numbers(trusted)
    model_authored = ("plain_english",) if curated.curated_by.startswith("llm") else ()
    for fld in model_authored:
        for n in _numbers(getattr(curated, fld)):
            if n not in allowed:
                problems.append(f"{fld} contains {n!r}, which is in no evidence")
    return problems


def llm_curation(report: dict, *, call_model, model: str = "gemma3:12b") -> CuratedAlert:
    """Ask a local model to write the plain-English half. Guarded, and optional.

    `call_model(prompt) -> str` is injected so this module never opens a socket
    and stays testable. Any failure — exception, empty answer, a validation
    problem — falls back to the deterministic rendering rather than sending
    something unverified.
    """
    base = deterministic_curation(report)
    rows = firing_lanes(report)
    if not rows:
        return base

    prompt = (
        "Rewrite this monitoring alert for a non-engineer in at most three "
        "sentences. State what is broken and what it stops from working.\n"
        "RULES: use only facts given below. Do not invent numbers, causes, "
        "times, or names. Do not omit any lane. Do not reassure.\n\n"
        f"FACTS:\n{json.dumps(base.to_dict(), indent=1)}\n"
    )
    try:
        answer = (call_model(prompt) or "").strip()
    except Exception:                                        # noqa: BLE001
        return base
    if not answer:
        return base

    candidate = CuratedAlert(
        headline=base.headline,
        urgency=base.urgency,
        lanes=base.lanes,
        plain_english=answer,
        action=base.action,               # never model-authored: it is the instruction
        evidence=base.evidence,
        cause_known=base.cause_known,
        curated_by=f"llm:{model}",
    )
    if validate_curation(candidate, report):
        # The model said something the evidence does not support. Discard the
        # prose, keep the facts. A rejected curation is not an error state.
        return base
    return candidate


def curate(report: dict, *, call_model: Optional[Any] = None,
           model: str = "gemma3:12b") -> CuratedAlert:
    """Entry point. Uses the model when one is supplied, and is safe without."""
    if call_model is None:
        return deterministic_curation(report)
    return llm_curation(report, call_model=call_model, model=model)
