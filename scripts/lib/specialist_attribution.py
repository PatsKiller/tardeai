"""Specialist attribution honesty — Stage 2 (desk ∧ Maria parity).

Operator lock 2026-09-23 (plan-openclaw-internal-first-integrity):
  Iris / Alex / CIO labels only when a real specialist run happened
  (OpenClaw A2A session, Trade-AI agent-job row, or desk synthesis id).
  If OpenClaw agentToAgent is off: say so once, then house + Hermes only —
  no roleplay.

AUTHORITY: READ_ONLY_ADVISORY. Pure text / dict. No I/O, no model call,
no broker reach. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Optional, Sequence

SCHEMA = "SpecialistAttribution@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

Surface = Literal["desk", "maria"]

#: OpenClaw A2A specialist agent ids (not the CIO desk product voice).
OPENCLAW_A2A_SPECIALISTS = frozenset({"iris", "alex", "aegis", "steph"})

#: Evidence sources that may authorize a specialist / CIO label.
SOURCE_OPENCLAW_A2A = "openclaw_a2a"
SOURCE_DESK_AGENT_JOB = "desk_agent_job"
SOURCE_DESK_SYNTHESIS = "desk_synthesis"
ALLOWED_SOURCES = frozenset(
    {SOURCE_OPENCLAW_A2A, SOURCE_DESK_AGENT_JOB, SOURCE_DESK_SYNTHESIS}
)

#: One-shot notice when A2A is off (Maria). Say once; do not invent specialists after.
A2A_DENY_NOTICE = (
    "agentToAgent is off — no Iris/Alex (or other specialist) session ran. "
    "House + Hermes join only; specialist labels withheld."
)

#: Desk / Maria refuse line when a label was requested without evidence.
REFUSE_LABEL_NOTICE = (
    "Specialist label withheld — no real Iris/Alex/CIO run id on this turn "
    "(need A2A session, desk agent-job, or desk synthesis)."
)

# ── claim detectors ──────────────────────────────────────────────────────────

#: Line-start specialist attribution (the morning Maria failure shape).
_LINE_CLAIM_RE = re.compile(
    r"(?im)^(?P<prefix>\s*[-*•]?\s*)"
    r"(?:"
    r"(?P<agent>iris|alex|aegis|steph)\s*(?:['’]s)?\s*"
    r"(?:cio\s+)?(?:take|found|view|says|notes?|thinks?)\b"
    r"|"
    r"(?P<pair>iris\s*/\s*alex|alex\s*/\s*iris)\b[^\n]{0,40}?"
    r"(?:cio\s+)?(?:take|found|view)?\b"
    r"|"
    r"(?P<cio>cio\s+take)\s*[:—\-]"
    r")"
)

#: Inline roleplay phrases that must not survive without evidence.
_INLINE_CLAIM_RE = re.compile(
    r"\b(?P<agent>iris|alex|aegis|steph)\s+"
    r"(?:cio\s+)?(?:take|found|says|notes?|thinks?)\b"
    r"|"
    r"\b(?P<pair>iris\s*/\s*alex|alex\s*/\s*iris)\b",
    re.IGNORECASE,
)

#: Desk product chrome — Alex IS the CIO Telegram desk voice. Not an A2A claim.
_DESK_PRODUCT_VOICE_RE = re.compile(
    r"(?im)^(?:\s*🧠\s*)?\*?Alex\s*·"
)

#: Honesty language that mentions specialists without attributing a take.
_HONEST_NO_SPECIALIST_RE = re.compile(
    r"(?i)\bno specialist\b|\bspecialist agent has (?:not )?reviewed\b|"
    r"specialist labels? withheld|agentToAgent is off"
)


@dataclass(frozen=True)
class SpecialistRunEvidence:
    """One real specialist / synthesis run that may authorize a label."""

    agent_id: str
    run_or_session_id: str
    source: str  # openclaw_a2a | desk_agent_job | desk_synthesis

    def ok(self) -> bool:
        aid = (self.agent_id or "").strip()
        rid = (self.run_or_session_id or "").strip()
        src = (self.source or "").strip()
        return bool(aid and rid and src in ALLOWED_SOURCES)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttributionDecision:
    """Result of scrubbing / evaluating specialist attribution on one reply."""

    schema: str = SCHEMA
    authority: str = AUTHORITY
    allowed_labels: list[str] = field(default_factory=list)
    stripped_claims: list[str] = field(default_factory=list)
    notice_injected: Optional[str] = None
    a2a_enabled: bool = False
    surface: str = "desk"
    text_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence_allows(agent_id: str, evidence: Sequence[SpecialistRunEvidence] | None) -> bool:
    """True iff a non-empty run/session id exists for this agent_id."""
    want = (agent_id or "").strip().lower()
    if not want:
        return False
    for row in evidence or ():
        if not row.ok():
            continue
        if row.agent_id.strip().lower() == want:
            return True
        # desk synthesis authorizes a generic "CIO take" label
        if want in {"cio", "cio_take", "cio_council"} and row.source == SOURCE_DESK_SYNTHESIS:
            return True
    return False


def cio_take_allowed(evidence: Sequence[SpecialistRunEvidence] | None) -> bool:
    """CIO take requires desk synthesis or a named desk agent-job — never invented."""
    for row in evidence or ():
        if not row.ok():
            continue
        if row.source == SOURCE_DESK_SYNTHESIS:
            return True
        if row.source == SOURCE_DESK_AGENT_JOB:
            return True
    return False


def a2a_specialist_allowed(
    agent_id: str,
    evidence: Sequence[SpecialistRunEvidence] | None,
    *,
    a2a_enabled: bool,
) -> bool:
    """OpenClaw Iris/Alex/… labels require A2A on + a real session/job id."""
    aid = (agent_id or "").strip().lower()
    if aid not in OPENCLAW_A2A_SPECIALISTS:
        return False
    if not a2a_enabled:
        return False
    for row in evidence or ():
        if not row.ok():
            continue
        if row.source != SOURCE_OPENCLAW_A2A:
            continue
        if row.agent_id.strip().lower() == aid:
            return True
    return False


def _claim_authorized(
    *,
    agent: Optional[str],
    is_cio_take: bool,
    is_pair: bool,
    surface: Surface,
    a2a_enabled: bool,
    evidence: Sequence[SpecialistRunEvidence] | None,
) -> bool:
    if is_cio_take:
        # Maria never invents CIO take; desk needs synthesis / agent-job evidence.
        if surface == "maria":
            # Only if a real desk synthesis id was joined into Maria's evidence.
            return cio_take_allowed(evidence)
        return cio_take_allowed(evidence)
    if is_pair:
        # "Iris / Alex" needs both (or refuse the pair label).
        if surface == "maria":
            return a2a_specialist_allowed("iris", evidence, a2a_enabled=a2a_enabled) and (
                a2a_specialist_allowed("alex", evidence, a2a_enabled=a2a_enabled)
            )
        # Desk: both need desk agent-job / synthesis evidence — not fake A2A.
        return evidence_allows("iris", evidence) and evidence_allows("alex", evidence)
    if not agent:
        return False
    aid = agent.lower()
    if surface == "maria":
        return a2a_specialist_allowed(aid, evidence, a2a_enabled=a2a_enabled)
    # Desk: Trade-AI agent-job / synthesis only (not OpenClaw A2A cosplay).
    if aid == "alex":
        # Bare "Alex take/found" on desk still needs a real job/synthesis id —
        # product chrome ("Alex · …") is handled separately and never reaches here
        # when the line matches _DESK_PRODUCT_VOICE_RE.
        return evidence_allows("alex", evidence) or cio_take_allowed(evidence)
    return evidence_allows(aid, evidence)


def _strip_unauthorized_inline(line: str, stripped: list[str]) -> str:
    """Remove inline unauthorized claim phrases; keep surrounding prose when possible."""

    def _repl(m: re.Match[str]) -> str:
        stripped.append(m.group(0).strip())
        return ""

    out = _INLINE_CLAIM_RE.sub(_repl, line)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def scrub_operator_specialist_claims(
    text: str,
    *,
    surface: Surface,
    a2a_enabled: bool = False,
    evidence: Sequence[SpecialistRunEvidence] | None = None,
    inject_a2a_notice: bool = True,
) -> tuple[str, AttributionDecision]:
    """Fail closed: strip pseudo Iris/Alex/CIO attribution without real run evidence.

    Desk product voice headers (``Alex · …``) are preserved. Honesty lines that
    already refuse specialists are preserved. When Maria has A2A off and the
    body had (or would have) specialist claims, inject ``A2A_DENY_NOTICE`` once
    at the top if ``inject_a2a_notice``.
    """
    decision = AttributionDecision(a2a_enabled=a2a_enabled, surface=surface)
    raw = text or ""
    if not raw.strip():
        return raw, decision

    out_lines: list[str] = []
    had_unauthorized = False

    for line in raw.split("\n"):
        if _DESK_PRODUCT_VOICE_RE.match(line) and surface == "desk":
            out_lines.append(line)
            continue
        if _HONEST_NO_SPECIALIST_RE.search(line):
            out_lines.append(line)
            continue

        m = _LINE_CLAIM_RE.match(line)
        if m:
            agent = (m.group("agent") or "").lower() or None
            is_cio = bool(m.group("cio"))
            is_pair = bool(m.group("pair"))
            if _claim_authorized(
                agent=agent,
                is_cio_take=is_cio,
                is_pair=is_pair,
                surface=surface,
                a2a_enabled=a2a_enabled,
                evidence=evidence,
            ):
                label = agent or ("cio_take" if is_cio else "iris/alex")
                if label not in decision.allowed_labels:
                    decision.allowed_labels.append(label)
                out_lines.append(line)
            else:
                had_unauthorized = True
                decision.stripped_claims.append(line.strip())
                # Drop the claim line entirely (fail closed).
            continue

        # Inline claims on otherwise normal lines
        if _INLINE_CLAIM_RE.search(line):
            # Check each match; if any unauthorized, strip those phrases.
            unauthorized = False
            for im in _INLINE_CLAIM_RE.finditer(line):
                agent = (im.group("agent") or "").lower() or None
                is_pair = bool(im.group("pair"))
                if not _claim_authorized(
                    agent=agent,
                    is_cio_take=False,
                    is_pair=is_pair,
                    surface=surface,
                    a2a_enabled=a2a_enabled,
                    evidence=evidence,
                ):
                    unauthorized = True
                    break
            if unauthorized:
                had_unauthorized = True
                cleaned = _strip_unauthorized_inline(line, decision.stripped_claims)
                if cleaned:
                    out_lines.append(cleaned)
                continue

        out_lines.append(line)

    notice: Optional[str] = None
    if had_unauthorized:
        if surface == "maria" and not a2a_enabled and inject_a2a_notice:
            notice = A2A_DENY_NOTICE
        else:
            notice = REFUSE_LABEL_NOTICE

    if notice:
        # Inject once at top if not already present.
        joined = "\n".join(out_lines)
        if notice not in joined:
            out_lines = [notice, ""] + out_lines
            decision.notice_injected = notice
        else:
            decision.notice_injected = notice

    final = "\n".join(out_lines)
    # Collapse accidental triple blanks from dropped lines
    final = re.sub(r"\n{3,}", "\n\n", final).strip("\n")
    if final and not final.endswith("\n") and text.endswith("\n"):
        final += "\n"
    decision.text_changed = final != raw
    return final, decision


def evidence_from_dicts(rows: Iterable[dict[str, Any]] | None) -> list[SpecialistRunEvidence]:
    """Build evidence rows from dicts (desk result / Maria bridge payload)."""
    out: list[SpecialistRunEvidence] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        try:
            ev = SpecialistRunEvidence(
                agent_id=str(row.get("agent_id") or ""),
                run_or_session_id=str(
                    row.get("run_or_session_id")
                    or row.get("session_id")
                    or row.get("job_id")
                    or row.get("run_id")
                    or ""
                ),
                source=str(row.get("source") or ""),
            )
        except Exception:
            continue
        if ev.ok():
            out.append(ev)
    return out


__all__ = [
    "A2A_DENY_NOTICE",
    "ALLOWED_SOURCES",
    "AUTHORITY",
    "AttributionDecision",
    "OPENCLAW_A2A_SPECIALISTS",
    "REFUSE_LABEL_NOTICE",
    "SCHEMA",
    "SOURCE_DESK_AGENT_JOB",
    "SOURCE_DESK_SYNTHESIS",
    "SOURCE_OPENCLAW_A2A",
    "SpecialistRunEvidence",
    "a2a_specialist_allowed",
    "cio_take_allowed",
    "evidence_allows",
    "evidence_from_dicts",
    "scrub_operator_specialist_claims",
]
