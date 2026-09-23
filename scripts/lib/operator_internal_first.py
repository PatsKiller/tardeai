"""Shared internal-first operator reply entry (Stage 1).

CIO desk and Maria skill call the SAME path for ticker perspective / buy /
research intents:

  1. Resolve subject (ticker or company name → identity)
  2. House evidence gather
  3. Hermes join (``hermes_subject_join``) before any "0 findings" claim
  4. Build body (house + Hermes honesty; no fake specialist labels)
  5. ``finalize_operator_reply`` — LEGEND / Sources / Origin / authority

LIVE_LOOKUP / MODEL_GENERAL only as labelled Went outside — never as house
research. This module does not invent a second provenance dialect.

Stable Maria API (import these names; do not re-implement footers):

  - ``answer_internal_first``
  - ``join_subject_hermes`` (re-export)
  - ``finalize_operator_reply`` / ``ReplyProvenance`` / ``LEGEND`` (re-export)
  - ``InternalFirstResult``

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA = "OperatorInternalFirst@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

try:
    from scripts.lib.reply_provenance import (  # noqa: E402
        LEGEND,
        ReplyProvenance,
        finalize_operator_reply,
    )
except ImportError:  # pragma: no cover
    from lib.reply_provenance import (  # type: ignore  # noqa: E402
        LEGEND,
        ReplyProvenance,
        finalize_operator_reply,
    )

try:
    from scripts.lib.hermes_subject_join import (  # noqa: E402
        HermesJoinResult,
        claim_contradicts_join,
        join_subject_hermes,
    )
except ImportError:  # pragma: no cover
    from lib.hermes_subject_join import (  # type: ignore  # noqa: E402
        HermesJoinResult,
        claim_contradicts_join,
        join_subject_hermes,
    )


@dataclass
class InternalFirstResult:
    """Return shape for desk and Maria skill consumers."""

    schema: str = SCHEMA
    authority: str = AUTHORITY
    text: str = ""
    kind: str = "internal_first"
    symbols: list[str] = field(default_factory=list)
    subject_guid: Optional[str] = None
    issuer_guid: Optional[str] = None
    hermes_join: Optional[dict[str, Any]] = None
    provenance: Optional[dict[str, Any]] = None
    sources: list[str] = field(default_factory=list)
    went_outside: list[str] = field(default_factory=list)
    desk: Optional[dict[str, Any]] = None
    unresolved: bool = False
    unresolved_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_primary(text: str) -> dict[str, Any]:
    """Best subject from the shared resolver; GUID from registry when present."""
    try:
        from scripts.lib.operator_subject_resolver import resolve_subjects  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from lib.operator_subject_resolver import resolve_subjects  # type: ignore  # noqa: PLC0415
    subjects = resolve_subjects(text or "")
    for s in subjects:
        if s.get("symbol") and s.get("kind") in ("ticker", "company", "etf"):
            return s
    for s in subjects:
        if s.get("kind") == "company" and not s.get("symbol"):
            return s
    return {}


def _ensure_legend(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return LEGEND
    if text.startswith("Key:") or LEGEND.split(" · ", 1)[0] in text.split("\n", 1)[0]:
        return text
    return LEGEND + "\n" + text


def _guid_chrome(symbol: Optional[str], subject_guid: Optional[str]) -> str:
    if symbol and subject_guid:
        short = str(subject_guid)[:8]
        return f"Subject: `{str(symbol).upper()}:{short}…`"
    if symbol:
        return f"Subject: `{str(symbol).upper()}` (identity unresolved)"
    return "Subject: unresolved — no tradable instrument bound"


def answer_internal_first(
    text: str,
    *,
    chat_id: str = "",
    message_id: str = "",
    channel: str = "skill",
    surface: str = "maria",
    use_desk: bool = True,
    hub_finder=None,
    dry_run: bool = False,
) -> InternalFirstResult:
    """Internal-first reply ending in ``finalize_operator_reply``.

    Parameters
    ----------
    surface:
        ``"maria"`` or ``"desk"`` — recorded on the receipt; same code path.
    use_desk:
        When True (default), runs ``handle_operator_desk_question`` for house
        facts / enqueue. When False, builds a join-only honesty reply (tests /
        thin skill probes).
    hub_finder:
        Optional ``callable(symbol) -> int`` Hub count probe.
    dry_run:
        When True, desk still gathers house facts but must not enqueue gap or
        Hermes research rows (no durable queue writes).
    """
    primary = _resolve_primary(text)
    symbol = str(primary.get("symbol") or "").upper() or None
    subject_guid = primary.get("guid") or primary.get("subject_guid")
    issuer_guid = primary.get("issuer_guid")

    out = InternalFirstResult(
        symbols=[symbol] if symbol else [],
        subject_guid=str(subject_guid) if subject_guid else None,
        issuer_guid=str(issuer_guid) if issuer_guid else None,
    )

    if primary.get("kind") == "company" and not symbol:
        out.unresolved = True
        out.unresolved_reason = str(
            primary.get("reason") or "name_not_in_instrument_feed_or_ambiguous"
        )
        body = (
            f"{_guid_chrome(None, None)}\n"
            f"I can't bind that company name to a house identity yet "
            f"({out.unresolved_reason}). Send the ticker if you have it."
        )
        prov = ReplyProvenance(
            kind="internal_first_unresolved",
            stores_read=["operator_subject_resolver", "company_name_index"],
        )
        final, receipt = finalize_operator_reply(_ensure_legend(body), prov)
        out.text = final
        out.provenance = receipt.to_dict() if hasattr(receipt, "to_dict") else asdict(receipt)
        out.sources = list(receipt.stores_read or [])
        return out

    hermes: Optional[HermesJoinResult] = None
    if symbol:
        hermes = join_subject_hermes(
            symbol,
            subject_guid=out.subject_guid,
            hub_finder=hub_finder,
        )
        out.hermes_join = hermes.to_dict()

    desk_result: Optional[dict[str, Any]] = None
    if use_desk:
        try:
            from scripts.lib.cio_operator_desk_loop import (  # noqa: PLC0415
                handle_operator_desk_question,
            )
        except ImportError:  # pragma: no cover
            from lib.cio_operator_desk_loop import (  # type: ignore  # noqa: PLC0415
                handle_operator_desk_question,
            )
        desk_result = handle_operator_desk_question(
            text,
            chat_id=chat_id,
            message_id=message_id,
            channel=channel if channel != "skill" else "telegram",
            dry_run=dry_run,
        )
        out.desk = desk_result if isinstance(desk_result, dict) else None
        # Prefer desk-resolved identity when the desk bound a symbol.
        intent = (desk_result or {}).get("intent") if isinstance((desk_result or {}).get("intent"), dict) else {}
        desk_syms = [str(s).upper() for s in (intent.get("symbols") or []) if s]
        if desk_syms and not symbol:
            symbol = desk_syms[0]
            out.symbols = desk_syms[:4]
            hermes = join_subject_hermes(
                symbol,
                subject_guid=out.subject_guid,
                hub_finder=hub_finder,
            )
            out.hermes_join = hermes.to_dict()
        # Desk may have resolved GUID via intent subjects — prefer those.
        for subj in (intent.get("subjects") or []):
            if isinstance(subj, dict) and subj.get("guid") and not out.subject_guid:
                out.subject_guid = str(subj["guid"])
                break
        if not out.subject_guid and symbol:
            try:
                try:
                    from scripts.lib import research_identity as RI  # noqa: PLC0415
                except ImportError:  # pragma: no cover
                    from lib import research_identity as RI  # type: ignore  # noqa: PLC0415
                tag = RI.resolve(RI.load_registry(), symbol)
                if tag and tag.get("subject_guid"):
                    out.subject_guid = str(tag["subject_guid"])
                    out.issuer_guid = str(tag.get("issuer_guid") or "") or out.issuer_guid
            except Exception:  # noqa: BLE001
                pass

    # Re-join after desk may have enqueued, so honesty reflects current state.
    if symbol and use_desk:
        hermes = join_subject_hermes(
            symbol,
            subject_guid=out.subject_guid,
            hub_finder=hub_finder,
        )
        out.hermes_join = hermes.to_dict()

    body_bits: list[str] = [_guid_chrome(symbol, out.subject_guid)]
    if hermes is not None:
        body_bits.append(hermes.honesty_line)

    desk_text = ""
    if desk_result:
        desk_text = (desk_result.get("text") or desk_result.get("reply_preview") or "").strip()
        if desk_text and hermes and claim_contradicts_join(desk_text, hermes):
            # Fail closed: strip the lie; keep house facts above the honesty line.
            desk_text = (
                "(Hermes honesty override) Desk/Hub prose claimed empty or "
                "queued-not-analyzed while a desk completion exists — using "
                "join status instead."
            )
        if desk_text:
            body_bits.append(desk_text)
    elif hermes is not None and hermes.latest_result:
        summary = ""
        for a in hermes.latest_result.get("answers") or []:
            if isinstance(a, dict) and a.get("summary"):
                summary = str(a["summary"])[:400]
                break
        if not summary:
            summary = str(hermes.latest_result.get("summary") or "")[:400]
        if summary:
            body_bits.append(summary)

    if not any(b for b in body_bits[1:] if b):
        body_bits.append(
            "No house perspective assembled yet. Hermes join status is above; "
            "no MODEL_GENERAL filler from this path."
        )

    stores: list[str] = []
    went: list[str] = []
    if desk_result:
        stores.extend(str(s) for s in (desk_result.get("sources") or []) if s)
        went.extend(str(w) for w in (desk_result.get("went_outside") or []) if w)
    if hermes:
        stores.extend(hermes.sources)
    stores = list(dict.fromkeys(stores))  # stable dedupe
    stores = stores or ["operator_internal_first"]

    model = (desk_result or {}).get("model")
    role = None
    if model:
        role = "wording only; every number from the stores above"

    body = _ensure_legend("\n\n".join(b for b in body_bits if b))
    # Refuse to leave without Sources when stores were read (Stage 1 contract).
    prov = ReplyProvenance(
        kind=f"internal_first:{surface}",
        stores_read=stores[:16],
        went_outside=went[:6],
        model=model,
        model_role=role,
    )
    final, receipt = finalize_operator_reply(body, prov)

    if "Sources:" not in final and stores:
        # finalize always adds Sources; this is a hard contract for consumers.
        raise RuntimeError("internal_first_missing_sources_line")

    out.text = final
    out.provenance = receipt.to_dict() if hasattr(receipt, "to_dict") else asdict(receipt)
    out.sources = list(receipt.stores_read or [])
    out.went_outside = list(receipt.went_outside or [])
    out.kind = str((desk_result or {}).get("kind") or "internal_first")
    if dry_run and isinstance(out.desk, dict):
        out.desk = {**out.desk, "dry_run": True, "research_queued": False}
    return out


__all__ = [
    "AUTHORITY",
    "SCHEMA",
    "LEGEND",
    "ReplyProvenance",
    "InternalFirstResult",
    "HermesJoinResult",
    "answer_internal_first",
    "claim_contradicts_join",
    "finalize_operator_reply",
    "join_subject_hermes",
]
