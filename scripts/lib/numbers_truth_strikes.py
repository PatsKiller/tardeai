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
               for inbox/claude-lead, and one ESCALATION through the existing host comms intent route
               (config/host_comms_intent_routes.json -> the comms-intent consumer -> the incident notifier, whose D34
               delivery is email + Telegram + Google Fi email-to-text). This module queues an intent; it never sends.
  PASS         a fingerprint that was failing and is now measured and agreeing clears with ONE "cleared" line.

Verdict vocabulary is the whole point of the module, so it is stated once here:

  FAIL           the figure and its truth were both read and disagree beyond tolerance. Strikes.
  NOT_MEASURED   the truth (or the served figure) could not be read. It NEVER strikes and NEVER clears: the counter
                 holds, so an intermittent store does not silently reset an escalation, and an unreadable truth is
                 never reported as a pass (AGENTS.md section 0 rule 5; design section 1).
  PASS           the figure was measured and agrees. Absence from M is the normal pass signal; a `PASS` row is also
                 accepted. If the caller passes `audited` (the fingerprints the run actually covered), a fingerprint
                 absent from BOTH holds instead of clearing — an audit that stopped looking at a figure must not look
                 like a fix.

State is data/runtime/numbers_truth_state.json, keyed by the figure fingerprint `page|figure_id|account|symbol`
(lowercase; an absent component is the empty string). Rows older than KEEP_DAYS are pruned: the file is bounded by
design (REV 2 F), and no per-run files are written.

AUTHORITY: READ_ONLY_ADVISORY. Never a broker, an order, a stop write, a DB write, a code edit, a cron or systemd
edit. The one write path this module owns is the state file; heals, tickets and escalations go through injected
callables whose production defaults are the sanctioned routes named above. MBI_BEHAVIOR = 0.
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
    """One side of a finding: `{value, source, as_of}`. Anything else is None (malformed)."""
    if not isinstance(value, Mapping):
        return None
    out = {k: value.get(k) for k in ("value", "source", "provider", "as_of")}
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


def heal_lane(finding: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[Optional[str], str]:
    """The producer lane that owns this figure. Returns (lane, reason-when-no-lane)."""
    if finding.get("family") == "authority":
        return None, "authority_finding"
    by_figure = config.get("by_figure_id") or {}
    lane = by_figure.get(finding.get("figure_id")) or (config.get("by_page") or {}).get(finding.get("page"))
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

        # FAIL
        fails += 1
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
                                  "mode": (config["healable"][lane] or {}).get("mode", "live")})
                row.update({"status": "ticketed", "ticket": {"id": ticket_id(fp), "at": _iso(moment)}})
                figures[fp] = row
                continue
            mode = ((config.get("healable") or {}).get(lane) or {}).get("mode") or "live"
            decision = {**finding, "action": ACTION_HEAL, "fails": fails, "lane": lane, "mode": mode,
                        "reason": "strike_3_self_fix"}
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
        decisions.append({**finding, "action": ACTION_TICKET, "fails": fails, "reason": reason, "lane": lane})
        row.update({"status": "ticketed", "ticket": {"id": ticket_id(fp), "at": _iso(moment)}})
        figures[fp] = row

    # PASS by absence: a fingerprint that was failing and is no longer in M cleared — unless the caller told us which
    # fingerprints the run covered and this one is not among them (an audit that stopped looking is not a fix).
    for fp, row in list(figures.items()):
        if fp in observed or not _strikes(row):
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
    return f"cleared: {where} {decision.get('figure_id')} measures true again after {decision.get('fails_before', '?')} failing runs"


# ── production defaults for the three injected actions ───────────────────────────────────────────────────────────


def request_heal(*, lane: str, mode: str, run_id: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
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
                                 now=_now(now).timestamp())
    except Exception as exc:  # a heal request must never take the audit down; the reason is recorded
        return {"ok": False, "accepted": False, "state": "ERROR", "reason": type(exc).__name__, "run_id": rid}
    return {**({"ok": True} if out.get("accepted") else {"ok": False}), **out}


def queue_escalation(*, domain: str, kind: str, subject: str, summary: str, fingerprint_: str,
                     now: Optional[datetime] = None, ledger_path: Optional[Path] = None) -> dict[str, Any]:
    """Queue ONE host comms intent (never a send). The existing route table names this module as the producer."""
    from scripts.check_registry_runtime_truth import IntentRefused, queue_host_intent  # noqa: PLC0415

    if ledger_path is None:
        from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415

        ledger_path = W.ledger_path()
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
        "the audit never repairs, never sends and never writes a store. Ticket the lead's ledger row against this id.",
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
    ticket: Optional[Callable[..., dict[str, Any]]] = None,
    inbox: Optional[Path] = None,
) -> dict[str, Any]:
    """Plan, and under `apply` write the state and take the heal / ticket / escalation actions.

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
    ticket_fn = ticket
    esc_cfg = config.get("escalation") or {}

    for decision in plan_["decisions"]:
        action = decision["action"]
        taken: dict[str, Any] = {}
        if action == ACTION_HEAL and apply:
            healed = dict(heal_fn(lane=decision["lane"], mode=decision.get("mode") or "live",
                                  now=moment) or {})
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
                row.update({"status": "ticketed", "ticket": {"id": ticket_id(decision["fingerprint"]), "at": _iso(moment)}})
                figures[decision["fingerprint"]] = row
                action = ACTION_TICKET
        if action == ACTION_TICKET and apply:
            decision = {**decision, "ticket_id": ticket_id(decision["fingerprint"])}
            if ticket_fn is not None:
                taken = {**taken, "ticket": dict(ticket_fn(decision=decision, now=moment) or {})}
            elif inbox is not None or esc_cfg:
                taken = {**taken, "ticket": write_finding(
                    decision=decision, inbox=Path(inbox) if inbox is not None else default_inbox(), now=moment)}
            esc = dict(escalate_fn(domain=esc_cfg.get("domain") or "data",
                                   kind=esc_cfg.get("kind_ticket") or "numbers_truth_ticket",
                                   subject=ticket_subject(decision), summary=ticket_summary(decision),
                                   fingerprint_=decision["fingerprint"], now=moment) or {})
            taken["escalation"] = esc
        if action == ACTION_CLEAR and apply and decision.get("ticket"):
            # recovery is ONE line (REV 3 H) and only for a fingerprint the operator was told about.
            taken = dict(escalate_fn(domain=esc_cfg.get("domain") or "data",
                                     kind=esc_cfg.get("kind_cleared") or "numbers_truth_cleared",
                                     subject=f"numbers-truth cleared: {ticket_id(decision['fingerprint'])}",
                                     summary=cleared_line(decision),
                                     fingerprint_=decision["fingerprint"], now=moment) or {})
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
    }


def default_inbox(root: Optional[Path] = None) -> Path:
    """The lead's coordinator inbox under the state root (never a literal path in this file). Overridable, because
    the lane passes its own when it runs against a different root."""
    if root is None:
        from scripts.lib import n8n_cc_wave_c as W  # noqa: PLC0415 — the state root resolver, not this module's own

        root = W.state_root()
    return Path(root) / "data" / "coordination" / "coordinator" / "inbox" / "claude-lead"
