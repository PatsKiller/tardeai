"""Maria outbound gate — the OpenClaw gateway's ``message_sending`` bridge.

Operator decision 2026-09-23: "hook Maria through the gateway". Maria (OpenClaw,
chat 8797974247) never called the shared reply chokepoint — SOUL.md prose asked
her to, and her session logs show zero calls. The 12:26Z S reply told the
operator "0 recent findings" beside a completed desk result, invented
"🔍 Iris" / "🎯 Alex" sections with agentToAgent forbidden, and carried no
Sources / LEGEND / 🆔 footer. This module is what the gateway plugin
(``~/.openclaw/extensions/tradeai-maria-gate``) runs on EVERY Maria outbound
message, so parity is enforced in code, not in a prompt.

It composes the existing house pieces — it re-implements none of them:

  1. ``maria_parity_hook.scrub_maria_outbound`` — strip unauthorized
     Iris/Alex/CIO labels; inject the 🔒 policy notice once.
  2. ``hermes_subject_join`` — a line claiming "0 findings / queued not
     analyzed" is replaced by the join's honesty line when the desk has a
     completed (or analyzed-thin) result for that subject.
  3. ``cio_telegram_stance_gate.check_investment_send`` — per resolved subject,
     on the text window around it. Bearish-CIO conflict or a missing CIO row
     (fail closed) → the reply is HELD (replaced by a held notice, never a
     silent drop). A neutral-CIO conflict is demoted with
     ``comms_editor.rewrite_bullish_to_watch`` and re-checked. Every stance
     decision gets a ``[CIO Stance: …]`` stamp.
  4. 🆔 footer in the comms editor's format (``pills · 🆔 msg · SYM:guid``).
  5. ``reply_provenance.finalize_operator_reply`` + ``LEGEND`` — Origin /
     Sources / authority tail, last.

The gate is pure apart from reads (join stores, ``cio_decisions``) and the
receipt append. Mode (observe | live) is the plugin's decision; the receipt
records which one applied.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker reach.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib import comms_editor as CE
from scripts.lib import cio_telegram_stance_gate as SG
from scripts.lib.hermes_subject_join import (
    claim_contradicts_join,
    house_db_query,
    hub_promoted_count_finder,
    join_subject_hermes,
)
from scripts.lib.maria_parity_hook import scrub_maria_outbound
from scripts.lib.reply_provenance import (
    LEGEND,
    ROLE_GENERAL_KNOWLEDGE,
    ReplyProvenance,
    finalize_operator_reply,
)

SCHEMA = "MariaOutboundGate@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Hold source recorded in cio_telegram_stance_holds.jsonl — not an organic
#: publisher caller, so it never counts toward the publisher observe receipt.
STANCE_SOURCE = "maria_outbound_gate"

MODE_OBSERVE = "observe"
MODE_LIVE = "live"

_DEF_MAX_SUBJECTS = 4
_DEF_STANCE_WINDOW = 80
_DEF_MODEL_LABEL = "Maria · OpenClaw agent model"

#: A line that asserts Hermes has nothing. Mirrors the join module's own
#: contradiction check, which is what decides whether to correct it.
_ZERO_CLAIM_HINT = re.compile(r"(?i)finding|hermes|research|backlog|queued")
#: Sizing advice has no house detector yet (MBI_BEHAVIOR = 0: memory and chat
#: must not size). Flag-only on the receipt; the text is left alone.
_SIZING_HINT = re.compile(
    r"(?i)\b(?:starter|small|half|full|initial|pilot)\s+(?:size|position|stake)\b|"
    r"\bposition[\s-]siz(?:e|ing)\b|\b\d+(?:\.\d+)?\s*%\s+(?:of\s+(?:the\s+)?)?(?:book|portfolio)\b"
)
_GUID_FOOTER = re.compile(r"🆔")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def max_subjects() -> int:
    return max(1, _env_int("MARIA_GATE_MAX_SUBJECTS", _DEF_MAX_SUBJECTS))


def stance_window() -> int:
    return max(20, _env_int("MARIA_GATE_STANCE_WINDOW_CHARS", _DEF_STANCE_WINDOW))


def model_label() -> str:
    return str(os.environ.get("MARIA_GATE_MODEL_LABEL") or _DEF_MODEL_LABEL).strip()


def receipts_path() -> Optional[Path]:
    """Receipt jsonl. ``MARIA_GATE_RECEIPTS`` redirects or disables (``off``).

    Under pytest nothing is written unless the env var names a path, so a test
    run can never append to the production ledger.
    """
    raw = str(os.environ.get("MARIA_GATE_RECEIPTS") or "").strip()
    if raw.lower() in {"0", "off", "false", "no", "disable"}:
        return None
    if raw:
        return Path(raw)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    state = os.environ.get("TRADEAI_STATE_DIR") or str(Path.home() / ".local" / "state" / "tradeai")
    return Path(state) / "maria_outbound_gate_receipts.jsonl"


@dataclass
class GateResult:
    content: str
    changed: bool = False
    cancel: bool = False
    cancel_reason: Optional[str] = None
    held: bool = False
    held_reason: Optional[str] = None
    stripped_claims: list[str] = field(default_factory=list)
    honesty_corrections: list[dict[str, Any]] = field(default_factory=list)
    stance: list[dict[str, Any]] = field(default_factory=list)
    subjects: list[dict[str, str]] = field(default_factory=list)
    sizing_flags: list[str] = field(default_factory=list)
    message_guid: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    schema: str = SCHEMA
    authority: str = AUTHORITY

    def receipt(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("content", None)
        return d


def _resolve(text: str, resolve: Optional[Callable[[str], list[dict]]]) -> list[dict[str, str]]:
    return CE.subjects(text, resolve=resolve)


def _correct_zero_claims(
    text: str,
    *,
    resolve: Optional[Callable[[str], list[dict]]],
    cio_dir: Optional[Path],
    stores: list[str],
    out: GateResult,
) -> str:
    """Replace a "0 findings / queued" line when the desk join contradicts it."""
    lines = text.split("\n")
    joins: dict[str, Any] = {}
    for i, line in enumerate(lines):
        if not _ZERO_CLAIM_HINT.search(line):
            continue
        for subj in _resolve(line, resolve):
            sym = subj["symbol"]
            if sym not in joins:
                join_db = house_db_query()
                joins[sym] = join_subject_hermes(
                    sym,
                    subject_guid=subj.get("guid"),
                    cio_dir=cio_dir,
                    db_query=join_db,
                    hub_finder=hub_promoted_count_finder(join_db) if join_db else None,
                )
            join = joins[sym]
            if not claim_contradicts_join(line, join):
                continue
            research = [r for r in join.research_ids if r.startswith("res_")]
            if join.latest_result and str(join.latest_result.get("research_id") or "").startswith("res_"):
                rid = str(join.latest_result["research_id"])
                research = [rid] + [r for r in research if r != rid]
            indent = re.match(r"^\s*(?:[-*•]\s*)?", line).group(0)
            fix = f"{indent}🟢 Correction — {join.honesty_line}"
            if research:
                fix += f" Research: {', '.join(research[:3])}."
            out.honesty_corrections.append(
                {
                    "symbol": sym,
                    "status": join.status,
                    "replaced": line.strip()[:300],
                    "result_ids": join.result_ids,
                    "research_ids": research[:5],
                    "citations": join.citations(),
                }
            )
            lines[i] = fix
            stores.append("hermes_subject_join (opr_/res_/results)")
            break
    return "\n".join(lines)


#: "up-sell", "buy-side", "sell-through": a hyphenated compound is not a stance.
_HYPHEN_COMPOUND = re.compile(r"(?<=\w)-(?=\w)")


def _window(text: str, symbol: str, width: int) -> str:
    """Text around each case-exact mention of ``symbol``, compounds neutralised."""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    parts = [
        plain[max(0, m.start() - width) : m.end() + width]
        for m in re.finditer(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", plain)
    ]
    return _HYPHEN_COMPOUND.sub("_", "\n…\n".join(parts))


def _stance_stamp(sym: str, verdict: SG.StanceGateVerdict, note: str = "") -> str:
    action = verdict.cio_action or ("MISSING" if verdict.held_reason == SG.HELD_MISSING else "UNSTATED")
    return f"[CIO Stance: {sym} {action}{(' — ' + note) if note else ''}]"


def _apply_stance(
    text: str,
    subjects: list[dict[str, str]],
    *,
    db_query: Optional[Callable[..., list[dict]]],
    out: GateResult,
    stores: list[str],
    request_review: bool = True,
) -> tuple[str, list[str]]:
    """Gate each subject's window. Returns (text, stamp lines)."""
    width = stance_window()
    stamps: list[str] = []
    for subj in subjects:
        sym = subj["symbol"]
        window = _window(text, sym, width)
        if not window:
            continue
        said = SG.infer_message_stance(window, sym)
        if said not in ("bullish", "bearish"):
            continue
        stores.append("cio_decisions (stance gate)")
        if said == "bearish":
            # Hard suppression is for bullish text only (spec + comms editor's
            # missing-decision policy). A bearish read is stamped, never held,
            # and never written to the hold ledger.
            view = SG.load_cio_view(sym, db_query) or {}
            action = str(view.get("action") or "").upper() or None
            side = SG.cio_side(action) if action else None
            v = SG.StanceGateVerdict(allow=True, symbol=sym, message_stance=said, cio_action=action, cio_side=side)
            note = "reply reads bearish" + ("; CIO disagrees" if side == "bullish" else "")
            stamps.append(_stance_stamp(sym, v, note))
            out.stance.append({"symbol": sym, **v.as_dict(), "outcome": "stamped_bearish"})
            continue
        verdict = SG.check_investment_send(
            symbol=sym,
            message_text=window,
            asserted_stance=said,
            db_query=db_query,
            source=STANCE_SOURCE,
            request_review=request_review,
        )
        row = {"symbol": sym, **verdict.as_dict()}
        if verdict.allow and getattr(verdict, "effective_action", None) == "WATCH":
            # Soft-rewrite stance (HOLD / epistemic gap): the gate allows the
            # send on condition that the bullish verb is demoted to WATCH.
            new_text, changes = CE.rewrite_bullish_to_watch(text, [sym])
            rewritten = bool(changes) and new_text != text
            text = new_text if rewritten else text
            stamps.append(_stance_stamp(sym, verdict, "Action rewritten to WATCH" if rewritten else ""))
            row["outcome"] = "rewritten_to_watch" if rewritten else "allowed"
            out.stance.append(row)
            continue
        if verdict.allow:
            stamps.append(_stance_stamp(sym, verdict))
            row["outcome"] = "allowed"
            out.stance.append(row)
            continue
        if verdict.held_reason == SG.HELD_DISAGREEMENT and verdict.cio_side == "neutral":
            new_text, changes = CE.rewrite_bullish_to_watch(text, [sym])
            if changes:
                # Re-read the stance only (no second gate call, so no second hold row).
                again = SG.infer_message_stance(_window(new_text, sym, width), sym)
                if again != "bullish":
                    text = new_text
                    stamps.append(_stance_stamp(sym, verdict, "Action rewritten to WATCH"))
                    row["outcome"] = "rewritten_to_watch"
                    out.stance.append(row)
                    continue
        row["outcome"] = "held"
        out.stance.append(row)
        out.held = True
        out.held_reason = out.held_reason or verdict.held_reason
    return text, stamps


def _held_body(out: GateResult) -> str:
    lines = ["⛔ Held by the CIO stance gate — this reply was not sent."]
    for s in out.stance:
        if s.get("outcome") != "held":
            continue
        cio = s.get("cio_action") or "no CIO decision on file (fail closed)"
        lines.append(f"• {s['symbol']}: reply read {s.get('message_stance')}; CIO: {cio} ({s.get('held_reason')}).")
    lines.append("Ask the CIO desk for the current decision on these names.")
    return "\n".join(lines)


def _footer(body: str, subjects: list[dict[str, str]], chat: str, now: datetime) -> tuple[str, str]:
    fp = CE.fingerprint(body)
    guid = CE.message_guid(chat, fp, now)
    ids = " ".join(f"{s['symbol']}:{s['guid'][:8]}" for s in subjects if s.get("guid"))
    return f"{' · '.join(CE.pills_for(body))} · 🆔 {guid[:8]}{(' · ' + ids) if ids else ''}", guid


def gate(
    content: str,
    *,
    session_key: str = "",
    channel: str = "",
    to: str = "",
    now: Optional[datetime] = None,
    db_query: Optional[Callable[..., list[dict]]] = None,
    resolve: Optional[Callable[[str], list[dict]]] = None,
    cio_dir: Optional[Path] = None,
    request_review: bool = True,
) -> GateResult:
    """Decide what one Maria outbound message becomes.

    ``request_review=False`` (observe mode) keeps the gate side-effect free: a
    missing-stance hold is computed but no paid CIO review is queued.
    """
    now = now or datetime.now(timezone.utc)
    raw = content or ""
    out = GateResult(content=raw)
    if not raw.strip():
        return out

    stores: list[str] = []

    # 1. specialist honesty (A2A is off unless evidence ever says otherwise)
    text, decision = scrub_maria_outbound(raw, a2a_enabled=False)
    out.stripped_claims = list(decision.stripped_claims)

    # 2. Hermes join before any "0 findings" claim survives
    try:
        text = _correct_zero_claims(text, resolve=resolve, cio_dir=cio_dir, stores=stores, out=out)
    except Exception as exc:  # noqa: BLE001 — a join failure must not drop the reply
        out.errors.append(f"hermes_join:{type(exc).__name__}")

    # 3. stance gate per subject
    subjects = _resolve(text, resolve)[: max_subjects()]
    out.subjects = subjects
    stamps: list[str] = []
    try:
        text, stamps = _apply_stance(
            text, subjects, db_query=db_query, out=out, stores=stores, request_review=request_review
        )
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"stance_gate:{type(exc).__name__}")

    out.sizing_flags = sorted({m.group(0) for m in _SIZING_HINT.finditer(text)})

    body = _held_body(out) if out.held else text
    if out.held:
        stamps = [s for s in stamps if s] + [
            f"[CIO Stance: {s['symbol']} {s.get('cio_action') or 'MISSING'} — held]"
            for s in out.stance
            if s.get("outcome") == "held"
        ]

    # 4. stamps + 🆔 footer (pills read the reply itself, not the LEGEND),
    #    LEGEND on top, then 5. Origin / Sources / tail last.
    tail_lines = list(stamps)
    if not _GUID_FOOTER.search(body):
        line, guid = _footer(body, subjects, str(to or session_key), now)
        out.message_guid = guid
        tail_lines.append(line)
    if not body.lstrip().startswith("Key:"):
        body = LEGEND + "\n" + body
    if tail_lines:
        body = body.rstrip() + "\n\n" + "\n".join(tail_lines)
    prov = ReplyProvenance(
        kind="maria_outbound",
        stores_read=sorted(set(stores)),
        model=model_label(),
        model_role=ROLE_GENERAL_KNOWLEDGE,
        # A correction names the desk's res_/rr_ ids; cite them where they appear.
        citations=[c for hc in out.honesty_corrections for c in hc.get("citations") or []],
    )
    final, prov = finalize_operator_reply(body, prov)
    out.provenance = prov.to_dict()
    out.content = final
    out.changed = final != raw
    return out


def write_receipt(
    result: GateResult, *, mode: str, session_key: str, channel: str, to: str, now: Optional[datetime] = None
) -> Optional[Path]:
    path = receipts_path()
    if path is None:
        return None
    now = now or datetime.now(timezone.utc)
    row = {
        "ts": now.isoformat(),
        "mode": mode,
        "session_key": session_key,
        "channel": channel,
        "to": to,
        "applied": mode == MODE_LIVE,
        **result.receipt(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        return None
    return path


def handle(
    payload: dict[str, Any],
    *,
    db_query: Optional[Callable[..., list[dict]]] = None,
    resolve: Optional[Callable[[str], list[dict]]] = None,
    cio_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Bridge contract: {content, sessionKey, channel, to, mode} → {content, cancel, cancel_reason, receipt}."""
    content = str(payload.get("content") or "")
    session_key = str(payload.get("sessionKey") or "")
    channel = str(payload.get("channel") or "")
    to = str(payload.get("to") or "")
    mode = str(payload.get("mode") or MODE_OBSERVE).strip().lower()
    if mode not in (MODE_OBSERVE, MODE_LIVE):
        mode = MODE_OBSERVE
    result = gate(
        content,
        session_key=session_key,
        channel=channel,
        to=to,
        db_query=db_query,
        resolve=resolve,
        cio_dir=cio_dir,
        request_review=mode == MODE_LIVE,
    )
    write_receipt(result, mode=mode, session_key=session_key, channel=channel, to=to)
    return {
        "content": result.content,
        # Holds replace the text with a held notice; the channel is never silent.
        "cancel": False,
        "cancel_reason": None,
        "changed": result.changed,
        "mode": mode,
        "receipt": result.receipt(),
    }


__all__ = [
    "AUTHORITY",
    "MODE_LIVE",
    "MODE_OBSERVE",
    "SCHEMA",
    "STANCE_SOURCE",
    "GateResult",
    "gate",
    "handle",
    "receipts_path",
    "write_receipt",
]
