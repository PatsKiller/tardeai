"""numbers_truth_strikes.py — the three-strike ladder for the hourly numbers-truth audit (LQ-20261107-1702).

DSN-20261109 (REV 2 sections D/E, REV 3 sections G/H) splits the audit in three: the core (LQ-1701) produces a
findings list M in its receipt, this module turns that list into the strike ladder, and the lane wiring (LQ-1703)
schedules it. This module owns only the ladder:

  strike 1-2   recorded in the state; shown on the receipt; no alert (a single stale run is not a defect)
  strike 3     one SELF-FIX from config/numbers_truth_heal.json — a request for ONE run of the PRODUCER lane through
               the sanctioned host path (scripts/lib/n8n_cc_wave_c.enqueue_host_run -> the gateway's coordination/run),
               rate-limited to one per lane per hour. Only ACTIVE n8n lanes are healable (REV 2 D); a KEEP_ON_CRON
               producer, an unmapped figure, or an authority finding tickets here instead (REV 3 G: a source change is
               operator-only, AGENTS.md section 17).
  strike 4     (or strike 3 with nothing to heal) a TICKET: one LQ-AUTO-<fp> per fingerprint (dedup), a FINDING file
               for inbox/claude-lead, one ESCALATION through the existing host comms intent route
               (config/host_comms_intent_routes.json), and — because the operator's contract (REV 3 H) is a prompt
               page, not a digest — an immediate CRITICAL event through the D34 hub
               (scripts/lib/critical_channels.deliver: Critical Telegram chat + email + Google Fi email-to-text).
               The hub is reused, never rebuilt: this module owns no sender. The intent is still queued as the
               durable incident record (its P2 copy is mirrored to email by config/comms_email_mirror.json), but the
               page does not wait for it and is never quiet-held. A repeated fingerprint never re-pages: one ticket
               id per fingerprint, and the text primitive dedupes by that id.
  PASS         a fingerprint that was failing and is now measured and agreeing clears with ONE "cleared" line — an
               intent only (Telegram + email, never the text channel).

Verdict vocabulary is the whole point of the module, so it is stated once here:

  FAIL           the figure and its truth were both read and disagree beyond tolerance. Strikes.
  NOT_MEASURED   the truth (or the served figure) could not be read. It NEVER strikes and NEVER clears: the counter
                 holds, so an intermittent store does not silently reset an escalation, and an unreadable truth is
                 never reported as a pass (AGENTS.md section 0 rule 5; design section 1).
  PASS           the figure was measured and agrees. Absence from M is the normal pass signal; a `PASS` row is also
                 accepted. If the caller passes `audited` (the fingerprints the run actually covered), a fingerprint
                 absent from BOTH holds instead of clearing — an audit that stopped looking at a figure must not look
                 like a fix. A malformed row holds the rows it could have described (its page; every page when the
                 row is too broken to name one): a producer error is never a measured pass.

State is data/runtime/numbers_truth_state.json, keyed by the figure fingerprint `page|figure_id|account|symbol`
(lowercase; an absent component is the empty string). Rows older than KEEP_DAYS are pruned: the file is bounded by
design (REV 2 F), and no per-run files are written.

AUTHORITY: READ_ONLY_ADVISORY. Never a broker, an order, a stop write, a DB write, a code edit, a cron or systemd
edit. The one write path this module owns is the state file; heals, tickets and escalations go through injected
callables whose production defaults are the sanctioned routes named above — the page is a call into the D34 critical-
alert hub, which owns the senders, the operator's allowlist and the per-channel receipts. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

SCHEMA = "NumbersTruthStrikes@v1"
STATE_SCHEMA = "NumbersTruthState@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
#: Dark-contract declaration: a library with no scheduled entrypoint of its own — the audit lane (LQ-1703) calls it.
SCHEDULED_ENTRYPOINT = (
    "NONE — library, unscheduled by design; its caller is the numbers-truth-audit lane (n8n, hourly :07, 24x7). "
    "Scheduling is operator-only (AGENTS.md section 17)."
)

STATE_REL = "data/runtime/numbers_truth_state.json"
CONFIG_REL = "config/numbers_truth_heal.json"
KEEP_DAYS = 7
HEAL_STRIKE = 3
TICKET_STRIKE = 4
SEVERITIES = ("P0", "P1", "P2", "P3")
FAIL, NOT_MEASURED, PASS = "FAIL", "NOT_MEASURED", "PASS"
VERDICTS = (FAIL, NOT_MEASURED, PASS)
#: The core (LQ-1701) spells a failure `MISMATCH`; it is the same strike. Accept both, never translate silently.
_VERDICT_ALIASES = {"MISMATCH": FAIL}
ACTION_RECORD, ACTION_HEAL, ACTION_TICKET, ACTION_CLEAR = "record", "heal", "ticket", "clear"
#: A measured FAIL the operator has accepted as a known source disagreement: no strike, no heal, no clear, no page,
#: and never counted as a pass. The entry that matched, with its reason, travels on the decision so it stays visible.
ACTION_KNOWN = "known_disagreement"
#: The audit's reason for a mismatch whose SHOWN side is a producer artifact older than the truth read. It heals
#: the producer and tickets; it never pages (LQ-20261107-1739 — the XAR false positive).
STALE_ARTIFACT = "stale_artifact"
_FP_RE = re.compile(r"^[^|]*\|[^|]*\|[^|]*\|[^|]*$")


class StrikesError(ValueError):
    """A caller-supplied finding, config or state value that cannot be acted on."""


# ── fingerprints and findings ───────────────────────────────────────────────────────────────────────────────────


def fingerprint(page: Any, figure_id: Any, account: Any = None, symbol: Any = None) -> str:
    """`page|figure_id|account|symbol`, lowercase, absent component = empty string."""
    parts = [str(p or "").strip().lower() for p in (page, figure_id, account, symbol)]
    if any("|" in p for p in parts):
        raise StrikesError("a fingerprint component may not contain a pipe")
    if not parts[0] or not parts[1]:
        raise StrikesError("page and figure_id are required")
    return "|".join(parts)


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _side(value: Any) -> Optional[dict[str, Any]]:
    """One side of a finding: `{value, source, as_of}` plus the evidence that makes it actionable.

    ``qty``/``status``/``order_id`` travel with the broker side of an expired stop: the phone sentence names the
    order that lapsed and the shares it no longer protects (LQ-20261107-1739). Anything else is None (malformed).
    """
    if not isinstance(value, Mapping):
        return None
    out = {k: value.get(k) for k in ("value", "source", "provider", "as_of", "qty", "status", "order_id")}
    return out if any(v is not None for v in out.values()) else None


def normalise(row: Mapping[str, Any]) -> dict[str, Any]:
    """One finding from the core's list M, validated. Raises StrikesError naming the defect.

    The core (LQ-1701) emits `status: MISMATCH|NOT_MEASURED`, the displayed side as `shown` and the truth side as
    `truth`, with the check named by `code`. This module's own vocabulary is FAIL / NOT_MEASURED / PASS and
    `served`; both spellings are accepted (a mismatch IS a failure, `shown` IS what was served) so neither side of
    the interface has to change to suit the other.
    """
    if not isinstance(row, Mapping):
        raise StrikesError("finding is not an object")
    verdict = str(row.get("verdict") or row.get("status") or "").strip().upper()
    verdict = _VERDICT_ALIASES.get(verdict, verdict)
    if verdict not in VERDICTS:
        raise StrikesError(f"verdict must be one of {VERDICTS} (or MISMATCH), got "
                           f"{row.get('verdict') or row.get('status')!r}")
    severity = str(row.get("severity") or "").strip().upper()
    if severity not in SEVERITIES:
        raise StrikesError(f"severity must be one of {SEVERITIES}, got {row.get('severity')!r}")
    fp = row.get("fingerprint")
    computed = fingerprint(row.get("page"), row.get("figure_id"), row.get("account"), row.get("symbol"))
    if fp is not None:
        fp = str(fp).strip().lower()
        if not _FP_RE.match(fp):
            raise StrikesError(f"fingerprint must be page|figure_id|account|symbol, got {fp!r}")
        if fp != computed:
            raise StrikesError(f"fingerprint {fp!r} does not match its own fields ({computed!r})")
    served = _side(row["served"] if "served" in row else row.get("shown"))
    truth = _side(row.get("truth"))
    missing_as_of = False
    if verdict == FAIL:
        # design section 1: a finding carries BOTH sides and their timestamps.
        if served is None or truth is None:
            raise StrikesError("a FAIL needs both the served side (served/shown) and the truth side")
        missing_as_of = any(side.get("as_of") is None for side in (served, truth))
    if verdict == NOT_MEASURED and served is None and truth is None:
        # The core (LQ-1701) records "nothing was readable here" as ``shown: {}``/``truth: {}`` plus a TYPED reason
        # (``no_such_field``, ``source_unreadable``). The reason is that row's whole evidence: refusing it graded
        # every healthy NOT_MEASURED finding of the audit malformed, which reads as a wiring fault and drops the hold
        # from the counts. A row that names neither a side nor a reason is still refused.
        if not str(row.get("reason") or "").strip():
            raise StrikesError("NOT_MEASURED needs the side that could not be read")
    return {
        "fingerprint": computed,
        "page": str(row.get("page") or "").strip().lower(),
        "figure_id": str(row.get("figure_id") or "").strip().lower(),
        "account": _clean(row.get("account")),
        "symbol": _clean(row.get("symbol")),
        "verdict": verdict,
        "severity": severity,
        "check": str(row.get("check") or row.get("code") or "").strip() or None,
        "family": str(row.get("family") or row.get("check_family") or "").strip().lower() or None,
        "served": served,
        "truth": truth,
        "tolerance": row.get("tolerance"),
        "detail": str(row.get("detail") or "").strip() or None,
        # The producer's own reason travels: ``stale_artifact`` is the audit's statement that the shown side is an
        # artifact older than the truth, and the ladder must see it to heal-first and never page.
        "reason": str(row.get("reason") or "").strip() or None,
        "missing_as_of": missing_as_of,
    }


def split_findings(findings: Iterable[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Validate the list. Returns (most-severe row per fingerprint, malformed rows with the reason).

    A duplicate fingerprint inside one run is one strike: the most severe row wins (design section 3).
    """
    good: dict[str, dict[str, Any]] = {}
    bad: list[dict[str, Any]] = []
    for raw in findings or ():
        try:
            row = normalise(raw)
        except StrikesError as exc:
            bad.append({"reason": str(exc), "row": dict(raw) if isinstance(raw, Mapping) else raw})
            continue
        prior = good.get(row["fingerprint"])
        if prior is None or SEVERITIES.index(row["severity"]) < SEVERITIES.index(prior["severity"]):
            good[row["fingerprint"]] = row
    return good, bad


# ── state ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _now(now: Optional[datetime]) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def empty_state() -> dict[str, Any]:
    return {"schema": STATE_SCHEMA, "updated_at": None, "figures": {}}


def load_state(path: Optional[Path] = None) -> dict[str, Any]:
    """Read the state. A missing file is an empty state; an unreadable one raises (it must never read as "no fails",
    which would silently restart every escalation)."""
    p = Path(path) if path is not None else state_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_state()
    except OSError as exc:
        raise StrikesError(f"state unreadable: {p}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StrikesError(f"state is not JSON: {p}: {exc}") from exc
    if not isinstance(doc, Mapping) or not isinstance(doc.get("figures"), Mapping):
        raise StrikesError(f"state is not a {STATE_SCHEMA} document: {p}")
    return {"schema": STATE_SCHEMA, "updated_at": doc.get("updated_at"), "figures": dict(doc["figures"])}


def save_state(state: Mapping[str, Any], path: Optional[Path] = None, *, now: Optional[datetime] = None) -> Path:
    """Write the state atomically (tmp in the same directory, then replace). Returns the path."""
    p = Path(path) if path is not None else state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": STATE_SCHEMA, "updated_at": _iso(_now(now)), "figures": dict(state.get("figures") or {})}
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, p)
    except BaseException:
        try:  # nosemgrep: tq-py-except-pass -- the write failure is re-raised below; a cleanup failure must not replace it
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def prune(state: dict[str, Any], *, now: Optional[datetime] = None, keep_days: int = KEEP_DAYS) -> list[str]:
    """Drop rows whose last observation is older than `keep_days` AND that are not mid-escalation. A row with a
    ticket or a pending heal is kept until that settles: dropping it would re-ticket the same fingerprint as new."""
    cut = _now(now) - timedelta(days=keep_days)
    dropped = []
    for fp, row in list(state.get("figures", {}).items()):
        seen = _parse(row.get("last_seen_at")) or _parse(row.get("first_seen_at"))
        if row.get("ticket") or (row.get("heal") or {}).get("requested_at"):
            continue
        if seen is None or seen < cut:
            dropped.append(fp)
            del state["figures"][fp]
    return dropped


def state_path(root: Optional[Path] = None) -> Path:
    return (Path(root) if root is not None else _root()) / STATE_REL


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def root_for(state_path_: Optional[Path]) -> Optional[Path]:
    """The state root an explicit state path implies: ``<root>/data/runtime/numbers_truth_state.json`` -> ``<root>``.

    ``None`` when the caller named no state path (the live default stands). Every default writer in ``run()``
    resolves under this root: a replay or a test against a throwaway state must never write a FINDING, an escalation
    intent or a heal request into the live tree (LQ-20261107-1739 leak note: a replay wrote 26 FINDING files into the
    live lead inbox because the FINDING writer fell back to the live resolver).
    """
    if state_path_ is None:
        return None
    p = Path(state_path_).resolve()
    parts = Path(STATE_REL).parts
    if len(p.parts) > len(parts) and p.parts[-len(parts):] == parts:
        return p.parents[len(parts) - 1]
    return p.parent


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    p = Path(path) if path is not None else _root() / CONFIG_REL
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StrikesError(f"heal config unreadable: {p}: {exc}") from exc
    if not isinstance(doc, Mapping):
        raise StrikesError(f"heal config is not an object: {p}")
    return dict(doc)


def page_codes(config: Mapping[str, Any]) -> frozenset[str]:
    """The codes allowed to reach the D34 page. Everything else is record/ticket/FINDING only.

    Read from the config (never hardcoded), because turning a page on or off is the operator's call. An absent key is
    the safe direction: no code pages. A malformed list is refused rather than guessed at.
    """
    raw = config.get("page_codes")
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or any(not isinstance(c, str) or not c.strip() for c in raw):
        raise StrikesError("page_codes must be a list of non-empty code strings")
    return frozenset(c.strip().upper() for c in raw)


def known_disagreements(config: Mapping[str, Any], now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """The validated known-disagreement table. An entry is a measured FAIL the operator has accepted.

    Every entry carries the operator's name, a stated reason and an expiry; a malformed entry refuses the whole
    table (fail-closed: a suppression list that cannot be read must not run). The list ships empty.
    """
    raw = config.get("known_disagreement")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StrikesError("known_disagreement must be a list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise StrikesError(f"known_disagreement[{i}] is not an object")
        check = str(row.get("check") or "").strip().upper()
        reason = str(row.get("reason") or "").strip()
        approved_by = str(row.get("approved_by") or "").strip()
        if not check:
            raise StrikesError(f"known_disagreement[{i}] has no check code")
        if not reason:
            # A suppression with no written reason is exactly the silent failure the table must not become.
            raise StrikesError(f"known_disagreement[{i}] ({check}) has no reason")
        if not approved_by:
            raise StrikesError(f"known_disagreement[{i}] ({check}) has no approved_by")
        try:
            expires = datetime.strptime(str(row.get("expires")), "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise StrikesError(f"known_disagreement[{i}] ({check}) needs expires as YYYY-MM-DD") from exc
        symbol = row.get("symbol")
        account = row.get("account")
        out.append({
            "check": check,
            "symbol": str(symbol).strip().upper() if symbol not in (None, "") else None,
            "account": _clean(account),
            "reason": reason,
            "approved_by": approved_by,
            "approved_at": row.get("approved_at"),
            "expires": expires,
        })
    return out


def match_known_disagreement(finding: Mapping[str, Any], entries: Iterable[Mapping[str, Any]],
                             now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """The entry this measured FAIL is accepted by, or None. An expired entry matches nothing (fail-closed)."""
    moment = _now(now)
    check = str(finding.get("check") or "").strip().upper()
    symbol = str(finding.get("symbol") or "").strip().upper()
    account = _clean(finding.get("account"))
    for entry in entries:
        if moment.date() > entry["expires"]:
            continue
        if check != entry["check"]:
            continue
        if entry.get("symbol") is not None and symbol != entry["symbol"]:
            continue
        if entry.get("account") is not None and account != entry["account"]:
            continue
        return dict(entry)
    return None


def heal_lane(finding: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[Optional[str], str]:
    """The producer lane that owns this figure. Returns (lane, reason-when-no-lane)."""
    if finding.get("family") == "authority":
        return None, "authority_finding"
    by_figure = config.get("by_figure_id") or {}
    by_page = config.get("by_page") or {}
    # The catalog's pages are routes ("/cio") and the config's by_page keys are bare ("cio"). Without both
    # spellings every page-mapped figure was "no_heal_mapped" and strike 3 ticketed instead of healing.
    page = str(finding.get("page") or "")
    lane = (by_figure.get(finding.get("figure_id"))
            or by_page.get(page) or by_page.get(page.lstrip("/")))
    lane = lane or config.get("default_lane")
    if not lane:
        return None, "no_heal_mapped"
    healable = config.get("healable") or {}
    if lane not in healable:
        # REV 2 D: a KEEP_ON_CRON producer is named so the ticket says why it was not re-run.
        return None, f"not_healable:{lane}"
    return lane, ""


def _strikes(row: Mapping[str, Any]) -> int:
    """The row's consecutive-fail counter. A row with no counter is zero strikes: the counter starts at zero when a
    fingerprint is first seen, so a missing key is the ladder's defined start, not an unknown served number."""
    return int(row.get("consecutive_fails") or 0)  # nosemgrep: tq-py-missing-as-zero -- a counter's start is 0 by definition; no figure or number is defaulted


def _heals_this_hour(state: Mapping[str, Any], lane: str, now: datetime) -> int:
    n = 0
    for row in (state.get("figures") or {}).values():
        # a settled heal (the figure cleared after it) still used the lane's budget, so it counts too
        for heal in (row.get("heal"), row.get("last_heal")):
            heal = heal or {}
            if heal.get("lane") != lane:
                continue
            at = _parse(heal.get("requested_at"))
            if at is not None and now - at < timedelta(hours=1):
                n += 1
    return n


def _settle(row: dict[str, Any], *, now: datetime) -> None:
    """Close out a cleared figure. Its ticket id moves to `last_ticket`: leaving `ticket` set would make every
    later recurrence record `ticket_open` forever and never escalate again. Its heal moves to `last_heal` with the
    outcome, which keeps the per-lane hourly budget honest while `prune` stops retaining the row as mid-escalation."""
    ticket = row.pop("ticket", None)
    if ticket:
        row["last_ticket"] = ticket
    heal = row.pop("heal", None)
    if heal:
        row["last_heal"] = {**heal, "state": "cleared", "settled_at": _iso(now)}
    row["status"] = "cleared"


# ── the ladder (pure: findings + state + config + clock in, decisions out) ──────────────────────────────────────


def plan(
    *,
    findings: Iterable[Mapping[str, Any]],
    state: Mapping[str, Any],
    config: Mapping[str, Any],
    now: Optional[datetime] = None,
    audited: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Decide what this run does. Pure: it does not write the state, request a heal, open a ticket or queue anything.

    Returns {"decisions": [...], "malformed": [...], "counts": {...}} where each decision is one of
    record / heal / ticket / clear, carrying both sides so every surfaced line can quote them.
    """
    moment = _now(now)
    figures = {fp: dict(row) for fp, row in (state.get("figures") or {}).items()}
    observed, malformed = split_findings(findings)
    audited_set = {str(x).strip().lower() for x in audited} if audited is not None else None
    pages_for = page_codes(config)
    accepted = known_disagreements(config, now=moment)
    decisions: list[dict[str, Any]] = []

    for fp in sorted(observed):
        finding = observed[fp]
        row = dict(figures.get(fp) or {})
        fails = _strikes(row)
        row.update({"page": finding["page"], "figure_id": finding["figure_id"],
                    "account": finding["account"], "symbol": finding["symbol"],
                    "check": finding["check"], "severity": finding["severity"],
                    "last_verdict": finding["verdict"]})
        verdict = finding["verdict"]
        if verdict == NOT_MEASURED:
            # hold: no increment, no clear, no last_seen_at move (an unreadable truth is not evidence of anything).
            row["last_not_measured_at"] = _iso(moment)
            decisions.append({**finding, "action": "hold", "fails": fails, "reason": "not_measured"})
            row["consecutive_fails"] = fails
            figures[fp] = row
            continue

        if verdict == PASS:
            decisions.append({**finding, "action": ACTION_RECORD, "fails": 0, "reason": "pass"})
            if fails:
                decisions[-1] = {**finding, "action": ACTION_CLEAR, "fails": 0,
                                 "fails_before": fails, "ticket": row.get("ticket")}
                row.update({"consecutive_fails": 0, "cleared_at": _iso(moment)})
                _settle(row, now=moment)
            row["last_seen_at"] = _iso(moment)
            row.setdefault("first_seen_at", row["last_seen_at"])
            figures[fp] = row
            continue

        # FAIL — unless the operator has accepted this exact measured disagreement for this figure. The entry must be
        # unexpired, and it changes nothing else: no strike, no heal, no clear, no page, no "pass". Expiry is
        # fail-closed — an expired entry matches nothing, so the row is an ordinary strike again the same run.
        accepted_entry = match_known_disagreement(finding, accepted, now=moment)
        if accepted_entry is not None:
            row["last_seen_at"] = _iso(moment)
            row.setdefault("first_seen_at", row["last_seen_at"])
            row["status"] = ACTION_KNOWN
            decisions.append({**finding, "action": ACTION_KNOWN, "fails": fails,
                              "reason": f"known_disagreement:{accepted_entry['reason']}",
                              "known_disagreement": accepted_entry})
            figures[fp] = row
            continue

        # FAIL
        fails += 1
        stale_artifact = str(finding.get("reason") or "").startswith(STALE_ARTIFACT)
        # A stale-artifact mismatch is drift between an old producer artifact and today's broker book: it can never
        # page, whatever its code (LQ-20261107-1739). The actionable variant is broker truth, a separate finding.
        paged = finding["check"].strip().upper() in pages_for and not stale_artifact
        row["consecutive_fails"] = fails
        row["last_seen_at"] = _iso(moment)
        row.setdefault("first_seen_at", row["last_seen_at"])
        already_ticketed = bool(row.get("ticket"))
        if already_ticketed:
            decisions.append({**finding, "action": ACTION_RECORD, "fails": fails,
                              "reason": "ticket_open", "ticket": row.get("ticket")})
            row["status"] = "ticketed"
            figures[fp] = row
            continue
        if stale_artifact:
            # The producer artifact predates the broker change it is graded against. The FIRST action is the heal of
            # that producer (once), then the figure is a stale_artifact ticket. Never a page: the operator cannot act
            # on a page that is merely old, and the broker truth is reported by the audit's own broker-side check.
            lane, why = heal_lane(finding, config)
            limit = int((config.get("rate_limit") or {}).get("per_lane_per_hour") or 1)
            used = _heals_this_hour({"figures": figures}, lane, moment) if lane else 0
            if lane and not row.get("heal") and used < limit:
                mode = ((config.get("healable") or {}).get(lane) or {}).get("mode") or "live"
                decisions.append({**finding, "action": ACTION_HEAL, "fails": fails, "lane": lane, "mode": mode,
                                  "reason": "stale_artifact_heal", "paged": False})
                row.update({"status": "healing",
                            "heal": {"lane": lane, "mode": mode, "requested_at": _iso(moment), "strike": fails,
                                     "state": "REQUESTED"}})
                figures[fp] = row
                continue
            decisions.append({**finding, "action": ACTION_TICKET, "fails": fails, "lane": lane or None,
                              "reason": STALE_ARTIFACT if not why else f"{STALE_ARTIFACT}:{why}",
                              "paged": False})
            row.update({"status": "ticketed", "ticket": {"id": ticket_id(fp), "at": _iso(moment), "paged": False}})
            figures[fp] = row
            continue

        if fails < HEAL_STRIKE:
            decisions.append({**finding, "action": ACTION_RECORD, "fails": fails, "reason": "strike_recorded"})
            row["status"] = "striking"
            figures[fp] = row
            continue

        lane, why = heal_lane(finding, config)
        if fails == HEAL_STRIKE and lane:
            limit = int((config.get("rate_limit") or {}).get("per_lane_per_hour") or 1)
            used = _heals_this_hour({"figures": figures}, lane, moment)
            if used >= limit:
                decisions.append({**finding, "action": ACTION_TICKET, "fails": fails,
                                  "reason": f"heal_rate_limited:{lane}", "lane": lane,
                                  "mode": (config["healable"][lane] or {}).get("mode", "live"),
                                  "paged": paged})
                row.update({"status": "ticketed", "ticket": {"id": ticket_id(fp), "at": _iso(moment),
                                                             "paged": paged}})
                figures[fp] = row
                continue
            mode = ((config.get("healable") or {}).get(lane) or {}).get("mode") or "live"
            # paged travels on the heal too: a REFUSED heal becomes a ticket in the same run, and that ticket is the
            # operator's first word about the figure — a page code must page on it.
            decision = {**finding, "action": ACTION_HEAL, "fails": fails, "lane": lane, "mode": mode,
                        "reason": "strike_3_self_fix", "paged": paged}
            decisions.append(decision)
            row.update({"status": "healing",
                        "heal": {"lane": lane, "mode": mode, "requested_at": _iso(moment), "strike": fails,
                                 "state": "REQUESTED"}})
            figures[fp] = row
            continue

        # strike 4, or strike 3 with nothing to heal: ticket (REV 2 D, REV 3 G)
        reason = why or "strike_4"
        if fails == HEAL_STRIKE and not lane:
            reason = why or "no_heal_mapped"
        decisions.append({**finding, "action": ACTION_TICKET, "fails": fails, "reason": reason, "lane": lane,
                          "paged": paged})
        row.update({"status": "ticketed", "ticket": {"id": ticket_id(fp), "at": _iso(moment), "paged": paged}})
        figures[fp] = row

    # PASS by absence: a fingerprint that was failing and is no longer in M cleared — unless the caller told us which
    # fingerprints the run covered and this one is not among them (an audit that stopped looking is not a fix).
    # A malformed row is a producer error about a fingerprint we cannot name, so it is never a measured pass for the
    # rows it could have described: its page holds (and a row too broken to name a page holds every page).
    malformed_pages: set[str] = set()
    for bad in malformed:
        bad_row = bad.get("row")
        malformed_pages.add(str(bad_row.get("page") or "").strip().lower() if isinstance(bad_row, Mapping) else "")
    for fp, row in list(figures.items()):
        if fp in observed or not _strikes(row):
            continue
        if malformed_pages and ("" in malformed_pages
                                or str(row.get("page") or "").strip().lower() in malformed_pages):
            decisions.append({"fingerprint": fp, "action": "hold", "fails": _strikes(row),
                              "reason": "malformed_findings", "page": row.get("page"),
                              "figure_id": row.get("figure_id")})
            continue
        if audited_set is not None and fp not in audited_set:
            decisions.append({"fingerprint": fp, "action": "hold", "fails": _strikes(row),
                              "reason": "not_audited", "page": row.get("page"), "figure_id": row.get("figure_id")})
            continue
        decisions.append({"fingerprint": fp, "action": ACTION_CLEAR, "fails": 0,
                          "fails_before": _strikes(row),
                          "page": row.get("page"), "figure_id": row.get("figure_id"),
                          "account": row.get("account"), "symbol": row.get("symbol"),
                          "check": row.get("check"), "severity": row.get("severity"),
                          "ticket": row.get("ticket"), "reason": "measured_pass"})
        row.update({"consecutive_fails": 0, "cleared_at": _iso(moment), "last_seen_at": _iso(moment)})
        _settle(row, now=moment)

    counts = {
        "checked": len(observed),
        "fail": sum(1 for f in observed.values() if f["verdict"] == FAIL),
        "not_measured": sum(1 for f in observed.values() if f["verdict"] == NOT_MEASURED),
        "pass": sum(1 for f in observed.values() if f["verdict"] == PASS),
        "malformed": len(malformed),
        "strike_1_2": sum(1 for d in decisions if d["action"] == ACTION_RECORD and d.get("reason") == "strike_recorded"),
        "heals": sum(1 for d in decisions if d["action"] == ACTION_HEAL),
        "tickets": sum(1 for d in decisions if d["action"] == ACTION_TICKET),
        "cleared": sum(1 for d in decisions if d["action"] == ACTION_CLEAR),
        # Visible every run; an accepted disagreement is never folded into "pass" or into silence.
        "known_disagreement": sum(1 for d in decisions if d["action"] == ACTION_KNOWN),
    }
    return {"decisions": decisions, "malformed": malformed, "counts": counts, "figures": figures}


def ticket_id(fp: str) -> str:
    """The dedup key AND the ticket name the FINDING carries. The lead's ledger row is allocated by the lead
    (REV 2 E); this id is stable per fingerprint so the same defect never opens twice."""
    return "LQ-AUTO-" + re.sub(r"[^a-z0-9]+", "-", fp).strip("-")


# ── escalation text (both sides + timestamps, AGENTS.md section 0 rule 5) ────────────────────────────────────────


def _fmt(side: Optional[Mapping[str, Any]]) -> str:
    if not side:
        return "unreadable"
    value = side.get("value")
    source = side.get("source") or side.get("provider") or "source?"
    return f"{value if value is not None else '—'} ({source} @ {side.get('as_of') or 'as_of?'})"


def ticket_subject(decision: Mapping[str, Any]) -> str:
    return f"numbers-truth {decision.get('severity', 'P')}: {ticket_id(decision['fingerprint'])}"


def ticket_summary(decision: Mapping[str, Any]) -> str:
    """One plain line for the operator: what disagrees, both sides with timestamps, and what was tried."""
    page, figure = decision.get("page"), decision.get("figure_id")
    where = page + ("/" + str(decision["symbol"]).upper() if decision.get("symbol") else "")
    if decision.get("account"):
        where += " " + str(decision["account"])
    tried = str(decision.get("reason") or "unmapped")
    if decision.get("action") == ACTION_HEAL:
        return f"{where}: {figure} FAIL {decision['fails']}x — heal {decision.get('lane')} requested"
    heal_note = f"heal tried: {decision['lane']}" if decision.get("lane") else f"no heal: {tried}"
    return (f"{where}: {figure} FAIL {decision['fails']}x — served {_fmt(decision.get('served'))} vs truth "
            f"{_fmt(decision.get('truth'))}; {heal_note}. {decision.get('detail') or ''}").strip()


def cleared_line(decision: Mapping[str, Any]) -> str:
    where = str(decision.get("page") or "?") + ("/" + str(decision["symbol"]).upper() if decision.get("symbol") else "")
    runs = "run" if decision.get("fails_before") == 1 else "runs"
    return (f"cleared: {where} {decision.get('figure_id')} measures true again after "
            f"{decision.get('fails_before', '?')} failing {runs}")


# ── production defaults for the four injected actions ───────────────────────────────────────────────────────────


def request_heal(*, lane: str, mode: str, run_id: Optional[str] = None, now: Optional[datetime] = None,
                 ledger: Optional[Path] = None) -> dict[str, Any]:
    """Ask for ONE run of the producer lane through the sanctioned host path. Never a broker, never a send.

    scripts/lib/n8n_cc_wave_c.enqueue_host_run applies the gateway's own coordination/run validation (allowlist,
    mode availability, run-id shape) and writes one REQUESTED row the executor drains. A refusal is returned, never
    raised: a heal that cannot be requested is a ticket reason, not an audit failure.
    """
    from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415 — keeps this module import-free for the audit's unit tests

    stamp = _now(now).strftime("%Y%m%dT%H%M%S")
    rid = run_id or f"nta:{lane}:{stamp}"
    try:
        out = W.enqueue_host_run(lane_id=lane, mode=mode, run_id=rid,
                                 requested_by="host:numbers-truth-audit", caller_id="tradeai-cc-wave-c",
                                 ledger=ledger, now=_now(now).timestamp())
    except Exception as exc:  # a heal request must never take the audit down; the reason is recorded
        return {"ok": False, "accepted": False, "state": "ERROR", "reason": type(exc).__name__, "run_id": rid}
    return {**({"ok": True} if out.get("accepted") else {"ok": False}), **out}


def queue_escalation(*, domain: str, kind: str, subject: str, summary: str, fingerprint_: str,
                     now: Optional[datetime] = None, ledger_path: Optional[Path] = None,
                     root: Optional[Path] = None) -> dict[str, Any]:
    """Queue ONE host comms intent (never a send). The existing route table names this module as the producer.

    ``root`` names the state root a caller already resolved (run() hands it the root implied by an explicit
    ``state_path_``). An intent raised by a replay against a throwaway root must land in that root's ledger, never in
    the live one (LQ-20261107-1739 leak note).
    """
    from scripts.check_registry_runtime_truth import IntentRefused, queue_host_intent  # noqa: PLC0415

    if ledger_path is None:
        from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415

        ledger_path = W.ledger_path(root)
    try:
        rec = queue_host_intent(producer=PRODUCER, domain=domain, kind=kind, subject=subject, summary=summary,
                                execution_id="nta:" + ticket_id(fingerprint_), node="numbers-truth-strikes",
                                ledger_path=ledger_path, now=_now(now).timestamp())
    except IntentRefused as exc:
        return {"ok": False, "queued": False, "reason": f"intent_{exc.reason}"}
    except Exception as exc:  # the store being down must surface as a reason, not as a crash
        return {"ok": False, "queued": False, "reason": f"intent_{type(exc).__name__}"}
    return {"ok": True, "queued": True, "intent_id": (rec or {}).get("intent_id")}


PRODUCER = "numbers_truth_strikes"

#: The class the operator's critical-text allowlist turns on for a NEW ticket (config/critical_text_classes.json).
CRITICAL_CLASS = "numbers_truth_ticket"


def _bare(side: Optional[Mapping[str, Any]]) -> str:
    """Just the value. The text sentence has 160 characters, and the sources and timestamps belong where there is room
    for them: the email body, the FINDING and the state row all carry the full `_fmt` form."""
    if not isinstance(side, Mapping):
        return "unreadable"
    value = side.get("value")
    return "unreadable" if value is None else str(value)


def _account_name(account: Any) -> str:
    """The one short human name for an account key (`config/account_display_names.json`); never the raw key.

    The page is read on a phone: ``schwab_taxable`` is an internal key, ``Schwab Individual`` is what the operator
    calls the account. A missing label falls back to a title-cased key and never costs the page.
    """
    key = str(account or "").strip()
    if not key:
        return ""
    try:
        from scripts.lib.account_display import account_label  # noqa: PLC0415 — a config read, not a transport
        return str(account_label(key) or "")
    except Exception:  # noqa: BLE001 — a missing name must not cost the page
        return " ".join(w.capitalize() for w in key.replace("-", "_").split("_") if w)


def _expired_stop_line(decision: Mapping[str, Any], *, name_symbol: bool = True) -> Optional[str]:
    """The operator sentence for a stop that expired at the close (LQ-20261107-1739): the actionable fact, named.

    Built from the audit's broker-side evidence (the expired order's own price and quantity), so the phone says
    what happened and what is no longer protected — never a comparison of two page numbers, a fingerprint or a path.
    ``name_symbol=False`` is the TRIGGER form: ``format_text`` already puts the symbol and the account name in its
    head, so repeating them would spend the 160 characters twice.
    """
    if str(decision.get("check") or "").upper() != "NT_STOP_EXPIRED":
        return None
    served = decision.get("served") or {}
    price, qty = served.get("value"), served.get("qty")
    fact = ("no working stop; "
            + (f"your {price:g} Day stop expired at the close" if isinstance(price, (int, float))
               else "your Day stop expired at the close"))
    if not name_symbol:
        return fact
    bits = [str(decision.get("symbol") or "").upper()]
    if isinstance(qty, (int, float)):
        bits.append(f"{qty:g} sh")
    label = _account_name(decision.get("account"))
    if label:
        bits.append(label)
    who = " ".join(x for x in bits if x)
    return f"{who}: {fact}" if who else fact


def critical_event(decision: Mapping[str, Any]) -> dict[str, Any]:
    """The one CRITICAL event a NEW ticket raises, in the shape `critical_producers` builds for its own classes.

    Built here rather than through `critical_producers.produce`: its ``PRODUCERS`` map is the D35 ten and its own test
    pins that set exactly. A non-D35 producer builds its event in place — the same thing
    ``scripts/llm_paid_spend_watch.py`` does — so this page adds no row to another module's pinned map.

    ``what`` is the full both-sides line (the email subject and body). ``trigger`` is the short form the phone gets:
    the hub's text primitive shortens the TRIGGER and never the action, so the numbers go first and the timestamps —
    which the phone sentence has no room for and the email already carries — are left out of it.

    ``event_id`` is the ticket id: the key `critical_texts` dedupes on for 12 hours, so a re-run inside that window
    cannot text the operator twice about the same fingerprint.
    """
    where = f"{decision.get('page')}/{decision.get('figure_id')}"
    expired = _expired_stop_line(decision)                                   # "SPCX 200 sh Schwab Individual: ..."
    expired_trigger = _expired_stop_line(decision, name_symbol=False)        # "...; the phone head names both"
    action = "place a new stop before the next open"
    return {
        "alert_class": CRITICAL_CLASS,
        "event_id": ticket_id(decision["fingerprint"]),
        "symbol": str(decision.get("symbol") or "PORTFOLIO").upper(),
        # the account NAME, not the internal key: `format_text` renders it as "(Schwab Individual)"
        "account": _account_name(decision.get("account")),
        # a broker-truth page is the operator's sentence in every channel; the technical both-sides line lives in the
        # FINDING and the decision, never on the phone (LQ-20261107-1739 acceptance: readable, no paths/fingerprints)
        "what": f"{expired}. {action[0].upper()}{action[1:]}." if expired else ticket_summary(decision),
        "trigger": expired_trigger or (f"served {_bare(decision.get('served'))} vs truth "
                                       f"{_bare(decision.get('truth'))} on {where}"),
        "action": action if expired else "check the figure's source",
        "evidence": {"fingerprint": decision["fingerprint"], "page": decision.get("page"),
                     "figure_id": decision.get("figure_id")},
    }


def deliver_critical(decision: Mapping[str, Any], *, now: Optional[datetime] = None,
                     hub: Any = None, **hub_kwargs: Any) -> dict[str, Any]:
    """Page the operator about ONE new ticket through the D34 critical-alert hub. Never raises.

    `scripts/lib/critical_channels.deliver` is the existing three-channel P1 route — the Critical Telegram chat
    (priority P1 through ``telegram_alert``, never quiet-held), the operator's email, and every Google Fi
    email-to-text line — and it decides everything about the send: the allowlist, the 160-character sentence, the
    dedupe window, the hourly cap and the per-channel receipts. Nothing here re-implements any of it, and no sender
    lives in this module.

    Imported lazily inside the call, the same pattern ``scripts/llm_paid_spend_watch.py`` uses, so a dry run and the
    unit tests never import a transport. A hub that cannot be reached at all (the class removed from the operator's
    allowlist, a broken contact file) comes back as a named outcome rather than taking the audit down — the audit's
    job is to run every hour, and the escalation's failure is a receipt, not a crash.
    """
    try:
        if hub is None:
            from scripts.lib import critical_channels as hub  # noqa: PLC0415 — the sender import stays off the load path
        delivery = hub.deliver(critical_event(decision), now=now, **hub_kwargs)
        out = delivery.as_dict() if hasattr(delivery, "as_dict") else dict(delivery or {})
        return {"ok": bool(out.get("delivered")), **out}
    except Exception as exc:  # noqa: BLE001 — an unreachable hub is a recorded outcome; the reason is the class name
        # never str(exc): a third-party message can embed a recipient address, and no receipt may carry one
        return {"ok": False, "delivered": False, "reason": f"critical_hub_error:{type(exc).__name__}"}


def write_finding(*, decision: Mapping[str, Any], inbox: Path, now: Optional[datetime] = None) -> dict[str, Any]:
    """Write the FINDING file the lead reads (REV 2 E). One file per ticket, named by the ticket id."""
    t_id = ticket_id(decision["fingerprint"])
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"FINDING-{t_id}.md"
    if path.exists():
        return {"ok": True, "written": False, "path": str(path), "reason": "already_there"}
    body = [
        f"# FINDING {t_id} — numbers truth (numbers-truth-audit)",
        "",
        f"- fingerprint: `{decision['fingerprint']}`",
        f"- page / figure: `{decision.get('page')}` / `{decision.get('figure_id')}`"
        + (f" · symbol `{decision['symbol']}`" if decision.get("symbol") else "")
        + (f" · account `{decision['account']}`" if decision.get("account") else ""),
        f"- severity: {decision.get('severity')} · check: `{decision.get('check')}` · failing run: {decision.get('fails')}",
        f"- served: {_fmt(decision.get('served'))}",
        f"- truth:  {_fmt(decision.get('truth'))}",
        f"- tolerance: {decision.get('tolerance')}",
        f"- self-fix: {('requested ' + str(decision.get('lane'))) if decision.get('action') == ACTION_HEAL else (decision.get('lane') or 'none')} ({decision.get('reason')})",
        f"- observation: {decision.get('detail') or '—'}",
        f"- raised: {_iso(_now(now))}",
        "",
        "Raised by `scripts/lib/numbers_truth_strikes.py` (LQ-20261107-1702). Both sides and their timestamps are above;",
        "the audit never repairs, never writes a store and never sends from this module: the operator was paged by the",
        "D34 critical-alert hub (`scripts/lib/critical_channels.deliver`), which owns the senders and the receipts.",
        "Ticket the lead's ledger row against this id.",
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")
    return {"ok": True, "written": True, "path": str(path)}


# ── the run ────────────────────────────────────────────────────────────────────────────────────────────────────


def run(
    *,
    findings: Iterable[Mapping[str, Any]],
    state_path_: Optional[Path] = None,
    config_path: Optional[Path] = None,
    audited: Optional[Iterable[str]] = None,
    apply: bool = False,
    now: Optional[datetime] = None,
    heal: Optional[Callable[..., dict[str, Any]]] = None,
    escalate: Optional[Callable[..., dict[str, Any]]] = None,
    critical: Optional[Callable[..., dict[str, Any]]] = None,
    ticket: Optional[Callable[..., dict[str, Any]]] = None,
    inbox: Optional[Path] = None,
) -> dict[str, Any]:
    """Plan, and under `apply` write the state and take the heal / ticket / escalation / page actions.

    Returns the audit's receipt body: counts, every decision with both sides, and the outcome of each action taken.
    A dry run (`apply=False`) writes nothing and calls nothing — it is the only way to read today's ladder first.
    """
    moment = _now(now)
    config = load_config(config_path)
    state = load_state(state_path_)
    plan_ = plan(findings=findings, state=state, config=config, now=moment, audited=audited)
    figures = plan_["figures"]
    state = {"schema": STATE_SCHEMA, "figures": figures}
    pruned = prune(state, now=moment)

    actions: list[dict[str, Any]] = []
    heal_fn = heal or request_heal
    escalate_fn = escalate or queue_escalation
    critical_fn = critical or deliver_critical
    ticket_fn = ticket
    esc_cfg = config.get("escalation") or {}
    # Every default writer resolves under the root an explicit state path implies; an injected callable is the
    # caller's own and is handed no extra keyword (LQ-20261107-1739 leak note).
    derived = root_for(state_path_)

    def _default_ledger() -> Optional[Path]:
        if derived is None:
            return None
        from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415 — the state root resolver, not this module's own

        return W.ledger_path(derived)

    for decision in plan_["decisions"]:
        action = decision["action"]
        taken: dict[str, Any] = {}
        if action == ACTION_HEAL and apply:
            heal_kw = {"ledger": _default_ledger()} if heal is None else {}
            healed = dict(heal_fn(lane=decision["lane"], mode=decision.get("mode") or "live",
                                  now=moment, **heal_kw) or {})
            taken = {"heal": healed}
            row = figures.get(decision["fingerprint"]) or {}
            heal_row = dict(row.get("heal") or {})
            heal_row.update({"state": "ACCEPTED" if healed.get("accepted") else "REFUSED",
                             "reason": healed.get("reason"), "run_id": healed.get("run_id")})
            row["heal"] = heal_row
            figures[decision["fingerprint"]] = row
            if not healed.get("accepted"):
                # a refused heal is strike 3 with nothing healed: ticket now, not after another failing run
                decision = {**decision, "action": ACTION_TICKET, "reason": f"heal_refused:{healed.get('reason')}"}
                row.update({"status": "ticketed", "ticket": {"id": ticket_id(decision["fingerprint"]),
                                                             "at": _iso(moment),
                                                             "paged": bool(decision.get("paged"))}})
                figures[decision["fingerprint"]] = row
                action = ACTION_TICKET
        if action == ACTION_TICKET and apply:
            decision = {**decision, "ticket_id": ticket_id(decision["fingerprint"])}
            if ticket_fn is not None:
                taken = {**taken, "ticket": dict(ticket_fn(decision=decision, now=moment) or {})}
            elif inbox is not None or esc_cfg:
                taken = {**taken, "ticket": write_finding(
                    decision=decision,
                    inbox=Path(inbox) if inbox is not None else default_inbox(derived), now=moment)}
            # The operator's page is turned on for the config's page_codes and NOTHING else (LQ-20261107-1726):
            # a code outside that list is a ticket + FINDING + state record, with no Telegram, no text and no email.
            # The escalation intent is itself a Telegram delivery, so it is gated with the page.
            if not decision.get("paged"):
                taken["page_suppressed"] = "code_not_in_page_codes"
            else:
                esc_extra = {"root": derived} if escalate is None and derived is not None else {}
                esc = dict(escalate_fn(domain=esc_cfg.get("domain") or "data",
                                       kind=esc_cfg.get("kind_ticket") or "numbers_truth_ticket",
                                       subject=ticket_subject(decision), summary=ticket_summary(decision),
                                       fingerprint_=decision["fingerprint"], now=moment, **esc_extra) or {})
                taken["escalation"] = esc
                # the operator's contract is a PROMPT page (REV 3 H), not a digest slot: the intent above is the
                # durable record, and this is the three-channel delivery that does not wait for a batch or 07:00.
                # Guarded here as well as inside deliver_critical: a page that raises must not abort the run before
                # the state is saved, because the next hourly run would open the same ticket and page again.
                try:
                    taken["critical"] = dict(critical_fn(decision=decision, now=moment) or {})
                except Exception as exc:  # noqa: BLE001 — a failed page is a recorded outcome, never a lost audit run
                    taken["critical"] = {"ok": False, "delivered": False,
                                         "reason": f"critical_call_error:{type(exc).__name__}"}
        if action == ACTION_CLEAR and apply and decision.get("ticket"):
            # recovery is ONE line (REV 3 H) and only for a fingerprint the operator was told about. A ticket that
            # was never paged gets no Telegram clear either — the intent is a Telegram route (LQ-20261107-1726).
            if not (decision.get("ticket") or {}).get("paged"):
                taken["clear_suppressed"] = "ticket_was_not_paged"
            else:
                esc_extra = {"root": derived} if escalate is None and derived is not None else {}
                taken = dict(escalate_fn(domain=esc_cfg.get("domain") or "data",
                                         kind=esc_cfg.get("kind_cleared") or "numbers_truth_cleared",
                                         subject=f"numbers-truth cleared: {ticket_id(decision['fingerprint'])}",
                                         summary=cleared_line(decision),
                                         fingerprint_=decision["fingerprint"], now=moment, **esc_extra) or {})
            action = ACTION_CLEAR
        if apply:
            actions.append({"fingerprint": decision["fingerprint"], "action": action, "taken": taken})
        else:
            actions.append({"fingerprint": decision["fingerprint"], "action": action, "would": True})

    if apply:
        save_state(state, state_path_, now=moment)

    counts = dict(plan_["counts"])
    counts["tickets"] = sum(1 for a in actions if a["action"] == ACTION_TICKET)
    counts["heals"] = sum(1 for a in actions if a["action"] == ACTION_HEAL)
    counts["cleared"] = sum(1 for a in actions if a["action"] == ACTION_CLEAR)
    counts["applied"] = apply
    # A page that reached no channel is not a failed audit, but it is the failure the operator cares about: it gets a
    # count of its own so a lane (or a reader) sees "3 tickets, 0 paged" without unpacking every action.
    counts["paged"] = sum(1 for a in actions if (a.get("taken") or {}).get("critical", {}).get("ok") is True)
    counts["page_failed"] = sum(1 for a in actions if "critical" in (a.get("taken") or {})
                                and (a["taken"]["critical"] or {}).get("ok") is not True)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": _iso(moment),
        "ok": True,
        "counts": counts,
        "decisions": plan_["decisions"],
        "actions": actions,
        "malformed": plan_["malformed"],
        "pruned": pruned,
        "state_path": str(state_path_) if state_path_ else str(state_path()),
        "heals": [d for d in plan_["decisions"] if d["action"] == ACTION_HEAL],
        "tickets": [d for d in plan_["decisions"] if d["action"] == ACTION_TICKET],
        "cleared": [cleared_line(d) for d in plan_["decisions"] if d["action"] == ACTION_CLEAR],
        "not_measured": [d["fingerprint"] for d in plan_["decisions"] if d["action"] == "hold"],
        # The accepted disagreements of this run, with the operator's reason — never a silent drop.
        "known_disagreements": [{"fingerprint": d["fingerprint"], "check": d.get("check"),
                                 "reason": (d.get("known_disagreement") or {}).get("reason"),
                                 "expires": str((d.get("known_disagreement") or {}).get("expires")),
                                 "approved_by": (d.get("known_disagreement") or {}).get("approved_by")}
                                for d in plan_["decisions"] if d["action"] == ACTION_KNOWN],
    }


def default_inbox(root: Optional[Path] = None) -> Path:
    """The lead's coordinator inbox under the state root (never a literal path in this file). Overridable, because
    the lane passes its own when it runs against a different root."""
    if root is None:
        from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415 — the state root resolver, not this module's own

        root = W.state_root()
    return Path(root) / "data" / "coordination" / "coordinator" / "inbox" / "claude-lead"
