"""cio_notification_signal.py — CIO Telegram signal-over-spam notification gate.

READ_ONLY_ADVISORY. This is the canonical production notification decision for
the CIO material scanner. It separates four identities so that raw evidence
churn (quote refreshes, READY/NEAR list ordering, tiny cash drift, a timer tick)
cannot produce fresh operator pages:

  1. decision lineage identity   — stable while the operator question is the
                                   same (cash posture, re-entry book, a specific
                                   position's concentration/lifecycle).
  2. evidence generation identity — raw evidence evolution; changes often; lives
                                   in trace/Command Center, never implies a page.
  3. material generation identity — changes ONLY when operator meaning changes
                                   (HOLD_CASH→DEPLOY_CASH, WAIT→RE_ENTER,
                                   blocked→unblocked ACT_NOW, a governed delta
                                   move, a real risk transition).
  4. notification identity        — whether the operator has already been told
                                   THIS material generation on THIS lineage.

A single ``decide_notification`` produces a ``NotificationDecision@v1`` and a
delivery class (IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY / SUPPRESSED). Durable
per-lineage state survives process restarts, is bounded and corruption-safe,
and suppresses prior-operator-REJECT recommendations unless the semantic
material generation genuinely changes (reopen with WHAT CHANGED SINCE YOUR
REJECT).

This module never sends Telegram itself and never mutates financial truth.
Memory behavior influence is NOT enabled here.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from scripts.lib.cio_decision_semantics import (
    actionability_blocking_state,
    canonical_act_now,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "cio" / "cio_notification_state.jsonl"
DEFAULT_AUDIT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_notification_audit.jsonl"
DEFAULT_METRICS_PATH = PROJECT_ROOT / "data" / "cio" / "cio_notification_metrics.jsonl"

# ── Delivery classes ───────────────────────────────────────────────────────
DELIVERY_IMMEDIATE = "IMMEDIATE"
DELIVERY_DIGEST = "DIGEST"
DELIVERY_COMMAND_CENTER_ONLY = "COMMAND_CENTER_ONLY"
DELIVERY_SUPPRESSED = "SUPPRESSED"

# ── Lineage classes (stable semantic identity) ────────────────────────────
LINEAGE_CASH = "cash_posture:CASH"
LINEAGE_REENTRY = "reentry:BOOK"
LINEAGE_FRESHNESS = "freshness:BOOK"

# ── Standing recommendations that are operator-actionable ─────────────────
ACTIONABLE_STANCES = frozenset({
    "ADD", "TRIM", "EXIT", "RE_ENTER", "ROTATE", "DEPLOY_CASH", "RAISE_CASH",
})

# Dispositions that suppress an unchanged recommendation.
SUPPRESSING_DISPOSITIONS = frozenset({"REJECT", "ACK", "DONE"})

# A governed material threshold for concentration/position delta changes. A
# $50 drift never opens a new generation; a move >= threshold does.
MATERIAL_DELTA_THRESHOLD_USD = 5000.0

# Bounded per-lineage state cardinality + audit retention.
MAX_LINEAGES = 2048
MAX_AUDIT_LINES = 20000
MAX_METRICS_LINES = 20000


# ── Machine tokens that must never appear in operator phone copy ──────────
# (They belong in evidence/Command Center, not the headline.)
MACHINE_TOKENS = (
    "ACT_NOW=",
    "READY=",
    "NEAR=",
    "WAIT=",
    "STALE_REFRESH_REQUIRED",
    "DATA_UNAVAILABLE",
    "operator_challenge_status=",
    "challenge_review=",
    "decision_input_digest=",
    "decision_evidence_digest=",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(*parts: Any, length: int = 24) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:length]


def _num(v: Any) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _str(v: Any) -> str:
    return str(v or "").strip()


def _upper(v: Any) -> str:
    return _str(v).upper()


def _disposition(decision: dict[str, Any]) -> str:
    raw = decision.get("operator_disposition")
    if isinstance(raw, dict):
        return _upper(raw.get("disposition"))
    if raw:
        return _upper(raw)
    return _upper(decision.get("disposition"))


# ─────────────────────────────────────────────────────────────────────────────
# Identity 1 — decision lineage (stable across evidence churn)
# ─────────────────────────────────────────────────────────────────────────────

def decision_lineage_id(decision: dict[str, Any]) -> str:
    """Stable lineage for the operator question, independent of raw churn.

    * cash -> ``cash_posture:CASH`` (does not change for $50 of cash drift)
    * re-entry -> ``reentry:BOOK`` (does not change for READY list ordering)
    * freshness -> ``freshness:BOOK``
    * otherwise -> ``position:{SYM}:{CLASS}`` where CLASS is CONCENTRATION for a
      TRIM with a weight, otherwise the standing stance.
    """
    d = decision if isinstance(decision, dict) else {}
    sym = _upper(d.get("symbol")) or "BOOK"
    if sym == "CASH":
        return LINEAGE_CASH
    if sym in ("REENTRY", "RE-ENTRY"):
        return LINEAGE_REENTRY
    if sym == "BOOK":
        return LINEAGE_FRESHNESS
    standing = _upper(d.get("standing_recommendation") or d.get("stance_code") or d.get("action"))
    klass = standing
    if standing == "TRIM":
        weight = d.get("weight_pct", d.get("current_weight_pct"))
        if weight is not None:
            klass = "CONCENTRATION"
    return f"position:{sym}:{klass}"


# ─────────────────────────────────────────────────────────────────────────────
# Identity 2 — evidence generation (raw evolution)
# ─────────────────────────────────────────────────────────────────────────────

def evidence_generation_id(decision: dict[str, Any]) -> str:
    """Raw evidence identity. Changes often; never implies a Telegram page."""
    d = decision if isinstance(decision, dict) else {}
    return _digest(
        d.get("decision_evidence_digest"),
        d.get("decision_input_digest"),
        d.get("evidence_digest"),
        length=32,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Identity 3 — material generation (operator-meaning change only)
# ─────────────────────────────────────────────────────────────────────────────

def _blocking(decision: dict[str, Any]) -> Optional[str]:
    b = actionability_blocking_state(decision)
    if b:
        return _upper(b)
    ability = _upper(decision.get("actionability"))
    if ability in {"DATA_CONFLICT", "STALE_REFRESH_REQUIRED", "REVALIDATE", "STALE", "EXPIRED"}:
        return ability
    return None


def _delta_bucket(delta_usd: float) -> int:
    return int(round(abs(delta_usd) / MATERIAL_DELTA_THRESHOLD_USD))


def material_generation_id(decision: dict[str, Any]) -> str:
    """Semantic generation — changes ONLY when operator meaning changes.

    Cash:      (posture status, action, deploy_now>0)
    Re-entry:  (action)            — WAIT stays WAIT across list churn
    Position:  (standing, current_action, act_now, blocking, delta bucket)
    """
    d = decision if isinstance(decision, dict) else {}
    lineage = decision_lineage_id(d)
    standing = _upper(d.get("standing_recommendation") or d.get("stance_code") or d.get("action"))
    current = _upper(d.get("current_action"))
    act_now = bool(d.get("act_now"))
    blocking = _blocking(d)
    delta = _num(d.get("delta_usd") if d.get("delta_usd") is not None else d.get("recommended_delta_usd"))

    if lineage == LINEAGE_CASH:
        posture = _upper((d.get("cash_posture") or {}).get("cash_posture_status")
                         or d.get("cash_posture_status"))
        deploy_now = _num((d.get("capital") or {}).get("deploy_now")
                          if d.get("deploy_now") is None else d.get("deploy_now"))
        return _digest("cash", posture, standing, deploy_now > 0)
    if lineage == LINEAGE_REENTRY:
        return _digest("reentry", standing, act_now)
    if lineage == LINEAGE_FRESHNESS:
        counts = d.get("freshness_counts") or {}
        return _digest("freshness", counts)
    return _digest("position", standing, current, act_now, blocking or "none", _delta_bucket(delta))


# ─────────────────────────────────────────────────────────────────────────────
# Semantic materiality (does this generation need operator attention now?)
# ─────────────────────────────────────────────────────────────────────────────

def semantic_materiality(decision: dict[str, Any]) -> tuple[bool, str]:
    """Whether this decision's *current meaning* is operator-actionable.

    A recurring WAIT / HOLD_CASH / blocked TRIM is NOT material for delivery,
    even though it is economically important state.
    """
    d = decision if isinstance(decision, dict) else {}
    standing = _upper(d.get("standing_recommendation") or d.get("stance_code") or d.get("action"))
    current = _upper(d.get("current_action"))
    act_now = bool(d.get("act_now"))
    blocking = _blocking(d)

    if act_now and not blocking:
        return True, "act_now_advisory"
    if standing in ACTIONABLE_STANCES and not blocking and current not in {"WAIT", "NO_ACTION", "REVALIDATE"}:
        return True, "material_standing_action"
    if blocking:
        return False, f"blocked:{blocking}"
    if standing in {"HOLD_CASH", "WAIT", "NO_ACTION", "HOLD", "RESEARCH"}:
        return False, "non_action_state"
    return False, "not_material"


# ─────────────────────────────────────────────────────────────────────────────
# Durable per-lineage notification state (bounded, atomic, corruption-safe)
# ─────────────────────────────────────────────────────────────────────────────

class NotificationStateStore:
    """Durable per-lineage notification state.

    * index file: one line per lineage (latest record), rewritten atomically.
    * audit file: append-only history (bounded), for traceability/metrics.
    * fail-closed: a malformed index line is skipped (treated as unknown).
    * bounded: MAX_LINEAGES cap; audit/metrics capped at MAX_*_LINES.
    * concurrency-safe: an advisory ``fcntl`` lock serializes the read-modify-
      write of the index so two concurrent scanner runs cannot double-send.
    """

    _tls = threading.local()

    def __init__(
        self,
        state_path: Optional[Path | str] = None,
        audit_path: Optional[Path | str] = None,
        metrics_path: Optional[Path | str] = None,
    ) -> None:
        self.state_path = Path(state_path or DEFAULT_STATE_PATH)
        self.audit_path = Path(audit_path or DEFAULT_AUDIT_PATH)
        self.metrics_path = Path(metrics_path or DEFAULT_METRICS_PATH)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Acquire the per-store process lock (reentrant within this thread).

        Two independent scanner processes that share ``state_path`` serialize
        their read-modify-write through this lock, preventing a race where both
        decide IMMEDIATE before either persists its notification state.
        """
        if getattr(self._tls, "locked", False):
            yield
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            self._tls.locked = True
            try:
                yield
            finally:
                self._tls.locked = False
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # -- index (compact latest-per-lineage) ----------------------------------
    def _read_index(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.is_file():
            return {}
        out: dict[str, dict[str, Any]] = {}
        try:
            for line in self.state_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # corruption-safe: skip malformed
                if isinstance(rec, dict) and rec.get("decision_lineage_id"):
                    out[str(rec["decision_lineage_id"])] = rec
        except OSError:
            return {}
        return out

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        # Bounded lineage cardinality: keep the most-recently-seen lineages.
        ordered = sorted(index.values(), key=lambda r: r.get("updated_at") or "", reverse=True)
        ordered = ordered[:MAX_LINEAGES]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in ordered:
                fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.state_path)

    def _append(self, path: Path, rec: dict[str, Any], limit: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        # Bounded retention: truncate to the last `limit` lines.
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if len(lines) > limit:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines[-limit:])
        except OSError:
            pass

    def latest(self, lineage: str) -> Optional[dict[str, Any]]:
        with self.locked():
            return self._read_index().get(lineage)

    def record(self, nd: dict[str, Any]) -> dict[str, Any]:
        """Persist a NotificationDecision as the latest state for its lineage."""
        lineage = str(nd.get("decision_lineage_id") or "")
        if not lineage:
            return nd
        with self.locked():
            row = dict(nd)
            row["updated_at"] = _now_iso()
            index = self._read_index()
            index[lineage] = row
            self._write_index(index)
            self._append(self.audit_path, row, MAX_AUDIT_LINES)
        return nd

    def record_metrics(self, counters: dict[str, Any]) -> None:
        rec = {"ts": _now_iso(), **{k: int(v) for k, v in (counters or {}).items()}}
        self._append(self.metrics_path, rec, MAX_METRICS_LINES)

    def all_lineages(self) -> dict[str, dict[str, Any]]:
        return self._read_index()


# ─────────────────────────────────────────────────────────────────────────────
# Identity 4 + delivery decision — NotificationDecision@v1
# ─────────────────────────────────────────────────────────────────────────────

def decide_notification(
    decision: dict[str, Any],
    *,
    store: Optional[NotificationStateStore] = None,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Produce a NotificationDecision@v1 + delivery class for one decision.

    FAIL-CLOSED: unknown/absent state is treated as "never told" (so a genuine
    first material generation may page once), but a REJECT persists across
    restarts and suppresses unchanged repeats.
    """
    d = decision if isinstance(decision, dict) else {}
    store = store or NotificationStateStore()

    lineage = decision_lineage_id(d)
    evidence_gen = evidence_generation_id(d)
    material_gen = material_generation_id(d)
    standing = _upper(d.get("standing_recommendation") or d.get("stance_code") or d.get("action"))
    current = _upper(d.get("current_action"))
    act_now = bool(d.get("act_now"))
    blocking = _blocking(d)
    disposition = _disposition(d)

    prev = store.latest(lineage)
    gen_changed = prev is None or prev.get("material_generation_id") != material_gen
    standing_changed = prev is not None and prev.get("standing_recommendation") != standing
    blocking_changed = prev is not None and prev.get("blocking_state") != (blocking or None)

    from scripts.lib.cio_production_eligibility import is_forbidden_from_production

    material, material_reason = semantic_materiality(d)
    prior_reject = bool(prev) and (prev.get("operator_disposition") or "").upper() in SUPPRESSING_DISPOSITIONS
    if is_forbidden_from_production(d):
        return {
            "notification_id": "ntf_" + _digest("ntf", lineage, material_gen, _now_iso(), length=24),
            "decision_id": _str(d.get("decision_id")),
            "decision_lineage_id": lineage,
            "material_generation_id": material_gen,
            "evidence_generation_id": evidence_gen,
            "wake_id": _str(wake_id),
            "trace_id": _str(trace_id),
            "notification_class": DELIVERY_SUPPRESSED,
            "materiality_reason": material_reason,
            "suppressed_reason": "not_production_advisory_eligible",
            "standing_recommendation": standing,
            "current_action": current,
            "act_now": act_now,
            "blocking_state": blocking,
            "operator_disposition": disposition,
            "reopen": False,
            "reopen_reason": None,
            "previous_notification_id": (prev or {}).get("notification_id"),
            "previous_material_generation_id": (prev or {}).get("material_generation_id"),
            "next_review": d.get("next_review"),
            "evidence_digest": evidence_gen,
            "created_at": _now_iso(),
        }

    notification_class = DELIVERY_COMMAND_CENTER_ONLY
    suppressed_reason: Optional[str] = None
    reopen = False
    reopen_reason: Optional[str] = None

    if not gen_changed:
        # Sticky ACT_NOW on a concentration lineage must not go fully silent —
        # DIGEST keeps the operator aware of over-fire without re-paging IMMEDIATE
        # every scan (signal-over-spam preserved for non-ACT_NOW replays).
        if (
            act_now
            and not blocking
            and not prior_reject
            and "CONCENTRATION" in str(lineage).upper()
        ):
            notification_class = DELIVERY_DIGEST
            suppressed_reason = None
        else:
            notification_class = DELIVERY_SUPPRESSED
            suppressed_reason = (
                "prior_operator_reject_unchanged" if prior_reject else "unchanged_replay"
            )
    elif prior_reject:
        # Prior REJECT: reopen ONLY on a genuine semantic change (standing moved,
        # blocking changed, or now actionable), never on a raw hash alone.
        if material or standing_changed or blocking_changed:
            notification_class = DELIVERY_IMMEDIATE
            reopen = True
            reopen_reason = _reopen_reason(d, prev, standing_changed, blocking_changed)
        else:
            notification_class = DELIVERY_SUPPRESSED
            suppressed_reason = "post_reject_unchanged_semantically"
    elif material:
        notification_class = DELIVERY_IMMEDIATE
    elif blocking_changed:
        # A genuine blocking-state transition (clean↔blocked) pages once.
        notification_class = DELIVERY_IMMEDIATE
    else:
        # Non-action state changed but not actionable → digest candidate (only
        # meaningful non-action transitions), otherwise Command-Center-only.
        notification_class = DELIVERY_DIGEST

    nd = {
        "notification_id": "ntf_" + _digest("ntf", lineage, material_gen, _now_iso(), length=24),
        "decision_id": _str(d.get("decision_id")),
        "decision_lineage_id": lineage,
        "material_generation_id": material_gen,
        "evidence_generation_id": evidence_gen,
        "wake_id": _str(wake_id),
        "trace_id": _str(trace_id),
        "notification_class": notification_class,
        "materiality_reason": material_reason,
        "suppressed_reason": suppressed_reason,
        "standing_recommendation": standing,
        "current_action": current,
        "act_now": act_now,
        "blocking_state": blocking,
        "operator_disposition": disposition,
        "reopen": reopen,
        "reopen_reason": reopen_reason,
        "previous_notification_id": (prev or {}).get("notification_id"),
        "previous_material_generation_id": (prev or {}).get("material_generation_id"),
        "next_review": d.get("next_review"),
        "evidence_digest": evidence_gen,
        "created_at": _now_iso(),
    }
    return nd


def _reopen_reason(
    decision: dict[str, Any],
    prev: dict[str, Any],
    standing_changed: bool,
    blocking_changed: bool,
) -> str:
    d = decision if isinstance(decision, dict) else {}
    if standing_changed:
        return f"standing recommendation changed {prev.get('standing_recommendation')} → {_upper(d.get('standing_recommendation') or d.get('action'))}"
    if blocking_changed:
        return f"blocking state changed {prev.get('blocking_state')} → {_blocking(d) or 'none'}"
    if bool(d.get("act_now")):
        return "current action became genuinely actionable"
    return "material evidence change since REJECT"


# ─────────────────────────────────────────────────────────────────────────────
# Human CIO Telegram renderer
# ─────────────────────────────────────────────────────────────────────────────

def _sentence_truncate(text: str, limit: int) -> str:
    """Sentence-safe truncation: cut at a word boundary, never mid-word."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def render_cio_card(decision: dict[str, Any], nd: dict[str, Any]) -> str:
    """Decision-first, human CIO card. No machine enums in the headline."""
    d = decision if isinstance(decision, dict) else {}
    sym = _str(d.get("symbol")) or "—"
    standing = nd.get("standing_recommendation") or _upper(d.get("action"))
    current = nd.get("current_action") or "REVIEW"
    act_now = bool(nd.get("act_now"))
    blocking = nd.get("blocking_state")
    reopen = bool(nd.get("reopen"))
    disposition = nd.get("operator_disposition")

    # Symbol display: REENTRY/BOOK/CASH are desk rows, not tickers.
    display = sym
    if sym == "REENTRY":
        display = "Re-entry"
    elif sym == "CASH":
        display = "Cash"
    elif sym == "BOOK":
        display = "Book"

    # Why / counter / change, sentence-safe.
    why = _sentence_truncate(_str(d.get("why_now")), 400) or "See CIO for evidence."
    change = _sentence_truncate(_str(d.get("what_changes_call")), 300)

    lines = ["Alex · CIO"]

    if reopen:
        lines += [
            "",
            f"{display} — {standing} / {current}",
            "",
            "WHAT CHANGED SINCE YOUR REJECT",
            _sentence_truncate(_str(nd.get("reopen_reason")) or why, 400),
        ]
        if act_now and not blocking:
            lines += ["", "This is now actionable:", why]
        else:
            lines += ["", "Since your REJECT:", "This is a genuine material change, so I am reopening the case."]
    elif act_now and not blocking:
        lines += ["", f"{display} — {standing}", "", why]
    elif blocking:
        lines += [
            "",
            f"{display} — {standing} / {current}",
            "",
            why,
            "",
            "I am not asking you to act now.",
        ]
    else:
        lines += [
            "",
            f"{display} — {standing}",
            "",
            why,
        ]

    # Capital only when it is the operator decision.
    cash = d.get("capital") if isinstance(d.get("capital"), dict) else {}
    if cash:
        free = cash.get("free_investable")
        deploy = cash.get("deploy_now")
        if free is not None:
            lines.append(f"Free investable: ${_num(free):,.0f}")
        if deploy is not None:
            lines.append(f"Deploy now: ${_num(deploy):,.0f}")

    lines += ["", "What would change the call:", change]

    if disposition and disposition in SUPPRESSING_DISPOSITIONS and not reopen:
        lines.append(f"(Your {disposition} is on this case.)")

    if nd.get("next_review"):
        lines.append(f"Next review: {_str(nd.get('next_review'))}")

    return "\n".join(lines)


def _digest_label(lineage: str) -> str:
    """Human label for a lineage key in a digest line."""
    if lineage == LINEAGE_CASH:
        return "Cash: hold"
    if lineage == LINEAGE_REENTRY:
        return "Re-entry: wait"
    if lineage == LINEAGE_FRESHNESS:
        return "Book freshness"
    # position:SYM:CLASS → "SYM — CLASS"
    if lineage.startswith("position:"):
        _, sym, klass = lineage.split(":", 2)
        return f"{sym} — {klass.replace('_', ' ').title()}"
    return lineage


def render_digest(nds: list[dict[str, Any]]) -> str:
    """One concise digest for a set of non-action DIGEST decisions."""
    if not nds:
        return ""
    lines = ["Alex · CIO", "", "No governed action is required right now."]
    seen: set[str] = set()
    for nd in nds:
        lineage = nd.get("decision_lineage_id", "")
        if lineage in seen:
            continue
        seen.add(lineage)
        lines.append(f"• {_digest_label(lineage)}")
    return "\n".join(lines[:24])


# ─────────────────────────────────────────────────────────────────────────────
# Action-button discipline
# ─────────────────────────────────────────────────────────────────────────────

def build_cio_keyboard(decision: dict[str, Any], nd: dict[str, Any]) -> dict[str, Any]:
    """Buttons only when there is an actual operator decision.

    Non-action / informational cards: OPEN CIO + EVIDENCE only (no ACK/DEFER/
    REJECT wall). Actionable cards keep the disposition controls.
    """
    did = _str(decision.get("decision_id"))
    from scripts.lib.cio_action_links import (
        build_cio_evidence_url,
        build_cio_hub_url,
    )

    open_row = [{"text": "OPEN CIO", "url": build_cio_hub_url()}]
    rows: list[list[dict[str, Any]]] = [open_row]
    if did:
        rows.append([{"text": "EVIDENCE", "url": build_cio_evidence_url(did)}])
    if bool(nd.get("act_now")) and not nd.get("blocking_state"):
        # Actual operator decision → disposition controls.
        try:
            from scripts.lib.cio_telegram_keyboard import build_decision_inline_keyboard
            return build_decision_inline_keyboard(decision)
        except Exception:
            pass
    return {"inline_keyboard": rows, "authority": "READ_ONLY_ADVISORY", "decision_id": did}


# ─────────────────────────────────────────────────────────────────────────────
# Text linter
# ─────────────────────────────────────────────────────────────────────────────

def lint_cio_text(text: str) -> dict[str, Any]:
    """Deterministic linter for outbound CIO text. Fail/fallback on violations."""
    issues: list[str] = []
    t = text or ""

    # Machine tokens in operator copy.
    for tok in MACHINE_TOKENS:
        if tok in t:
            issues.append(f"machine_token:{tok}")

    # Mid-word/mid-sentence truncation heuristics: a trailing open paren + short
    # token, or a trailing dash, indicates a cut mid-token.
    if re.search(r"\([A-Za-z]{1,3}$", t):
        issues.append("mid_word_truncation")
    if re.search(r"[A-Za-z]-$", t):
        issues.append("mid_word_truncation")

    # Broken underscore italics (Markdown) in plain text.
    if re.search(r"[A-Za-z]_[A-Za-z]", t):
        issues.append("underscore_italics_risk")

    # Repeated section content (WHAT CHANGED == WHY).
    low = t.lower()
    if "what changed" in low and "why" in low:
        why_idx = low.find("why")
        wc_idx = low.find("what changed")
        if 0 <= wc_idx < why_idx:
            seg_why = t[why_idx:why_idx + 200].strip()
            seg_wc = t[wc_idx:wc_idx + 200].strip()
            if seg_why and seg_why.split("\n", 1)[0].strip() == seg_wc.split("\n", 1)[0].strip():
                issues.append("duplicate_section_content")

    # Body must not exceed a safe Telegram limit.
    if len(t.encode("utf-8")) > 4000:
        issues.append("body_too_long")

    return {"ok": not issues, "issues": issues, "text": t}


# ─────────────────────────────────────────────────────────────────────────────
# Replay / metrics
# ─────────────────────────────────────────────────────────────────────────────

def replay_decisions(
    decisions: list[dict[str, Any]],
    *,
    store: Optional[NotificationStateStore] = None,
) -> dict[str, Any]:
    """Run a deterministic replay of historical decisions through the gate.

    Returns raw_evaluations, per-class counts, and suppression reasons.
    """
    store = store or NotificationStateStore()
    counters: dict[str, int] = {}
    immediate = digest = cc = suppressed = 0
    reopens = 0
    for d in decisions:
        nd = decide_notification(d, store=store)
        store.record(nd)
        cls = nd["notification_class"]
        counters[cls] = counters.get(cls, 0) + 1
        if cls == DELIVERY_IMMEDIATE:
            immediate += 1
        elif cls == DELIVERY_DIGEST:
            digest += 1
        elif cls == DELIVERY_COMMAND_CENTER_ONLY:
            cc += 1
        else:
            suppressed += 1
        if nd.get("reopen"):
            reopens += 1
    return {
        "raw_evaluations": len(decisions),
        "immediate_notifications": immediate,
        "digest_notifications": digest,
        "command_center_only": cc,
        "suppressed": suppressed,
        "reopens": reopens,
        "counters": counters,
    }
