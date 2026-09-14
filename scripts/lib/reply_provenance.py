"""Reply provenance -- the ONE place a reply to the operator gets its Sources line.

Operator finding, verbatim, 2026-09-13 18:58 and 19:05:

    "it needs to quote the source ... whatever elements it returns it needs to
    give the elements like you're saying that it couldn't find it local so it
    went to DeepSeek -- but it should have been able to find it local"

    "the routing should be internal Command Center first and when it has to go
    out for other stuff it needs to let us know; this needs to be wired and
    fixed tight"

Two live replies that day said nothing about where their content came from: one
dumped the whole re-entry book for a one-symbol question, one answered a sector
question from DeepSeek's general knowledge and called cash/holdings empty while
the CIO snapshot carried them. The base fix (ffc795f3c) added a Sources footer
to the desk loop -- but the desk loop is only one of the reply paths.

THE CONTRACT. A reply to the operator is never sent without:

  (a) a ``Sources:`` line naming the Command Center stores it read (with the
      store's as_of / computed time when known) and, when a model wrote prose,
      the model id and its role ("wording only" | "general knowledge where
      labelled" | "intent classification only");
  (b) when the answer needed anything OUTSIDE the Command Center -- governed
      search, the Hermes queue, LLM curation, an on-demand provider pull,
      DeepSeek general knowledge -- an explicit ``Went outside: <what> -- <why>``
      line. Omitted entirely when nothing went outside;
  (c) the authority tail, last.

``finalize_operator_reply`` enforces all three and is the single chokepoint.
``cio_converse_core`` calls it immediately before ``_send`` for every operator
reply kind; ``cio_operator_desk_loop.try_fulfill_pending_replies`` calls the
same function for the follow-up / retraction sends that do not pass through the
converse core. Nothing else appends a Sources line to outbound text -- the desk
loop's ``_with_sources_footer`` is the evidence-aware label builder re-exported
from here, and the chokepoint recognises and keeps its line rather than adding
a second one.

The receipt: ``ReplyProvenance.to_dict()`` is written as ``reply_provenance`` on
the per-turn ``operator.message`` event payload and on the processor's result
dict, with these field names EXACTLY (the answer-quality monitor reads them):
``stores_read``, ``went_outside``, ``model``, ``sources_line_present``.

AUTHORITY: READ_ONLY_ADVISORY. Pure text and dict work. No I/O, no model call,
no broker reach. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA = "ReplyProvenance@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: The tail every reply ends with when the body did not bring its own wording.
DEFAULT_TAIL = "No orders/stops from chat · READ_ONLY_ADVISORY"

#: A line that IS an authority tail and nothing else. Wordings in use today:
#: "READ_ONLY_ADVISORY", "No orders/stops · READ_ONLY_ADVISORY",
#: "No orders/stops from chat · READ_ONLY_ADVISORY", "No orders or stops. READ_ONLY_ADVISORY."
#: A line that merely MENTIONS the authority ("• Authority: **READ_ONLY_ADVISORY** — no
#: orders / stops / 2FA from chat") is body text and is left alone.
AUTHORITY_TAIL_RE = re.compile(
    r"^\s*(?:[•\-–]\s*)?(?:No orders(?:\s*/\s*stops|\s+or\s+stops)?(?:\s+from\s+chat)?\s*[·.\-—:]?\s*)?"
    r"READ_ONLY_ADVISORY\.?\s*$"
)
SOURCES_PREFIX = "Sources: "
OUTSIDE_PREFIX = "Went outside: "
#: Between labels. NOT " · " -- that already appears INSIDE labels
#: ("re-entry desk · computed 2026-09-13 22:52"), so parsing a line back split one
#: store into two. Not ";" either: the model-role wording carries one.
SEP = " | "

#: Model-role wordings. Kept as constants so the receipt and the line agree.
ROLE_WORDING_ONLY = "wording only; every number from the stores above"
ROLE_GENERAL_KNOWLEDGE = "general knowledge where labelled; numbers from the stores above"
ROLE_INTENT_ONLY = "intent classification only; no facts"

_MODEL_LABEL_MARKERS = ("wording only", "general knowledge", "intent classification")


@dataclass
class ReplyProvenance:
    """What one outbound reply drew on. Field names are the monitor's contract."""

    kind: str
    stores_read: list[str] = field(default_factory=list)
    went_outside: list[str] = field(default_factory=list)
    model: Optional[str] = None
    model_role: Optional[str] = None
    sources_line_present: bool = False
    authority_tail_present: bool = False
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── label builders ───────────────────────────────────────────────────────────


def _dedupe_exact(items: list[str]) -> list[str]:
    """Order-preserving exact dedupe. For ``went_outside``: two egresses to the same
    model in different roles are two facts and must both survive."""
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        s = str(it or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _store_key(label: str) -> str:
    """The store a label names, without its detail: "re-entry desk · computed
    2026-09-13 23:02" and "re-entry desk" are ONE store; so are "CIO snapshot
    (cash, sectors)" and "CIO snapshot"."""
    key = str(label or "").strip()
    for sep in (" · ", " (", " — "):
        key = key.split(sep, 1)[0]
    return key.strip().lower()


def _dedupe(items: list[str]) -> list[str]:
    """Dedupe on STORE IDENTITY, not the rendered label, keeping the most detailed
    label for each store at the position the store first appeared.

    2026-09-13 (Agent D replaying the SCHG question): the base footer rendered
    "re-entry desk · computed 2026-09-13 23:02 · re-entry desk" because its seen-set
    was keyed on the full label, so the plain label added for the symbol card was
    not recognised as the same store."""
    order: list[str] = []
    best: dict[str, str] = {}
    for it in items:
        s = str(it or "").strip()
        if not s:
            continue
        k = _store_key(s)
        if k not in best:
            order.append(k)
            best[k] = s
        elif len(s) > len(best[k]):
            best[k] = s
    return [best[k] for k in order]


def _short_ts(raw: Any) -> str:
    return str(raw or "")[:16].replace("T", " ")


def labels_from_evidence(evidence: dict[str, Any], curated: dict[str, Any]) -> list[str]:
    """Store labels (and the model label) for a desk evidence dict.

    This is the base fix's ``_with_sources_footer`` logic, lifted so every path
    builds labels the same way. Stores first, model last.
    """
    avail = (evidence or {}).get("available") or {}
    labels: list[str] = []
    for src in (evidence or {}).get("sources") or []:
        src_s = str(src)
        if "reentry_decision_desk" in src_s:
            as_of = _short_ts(avail.get("reentry_as_of"))
            labels.append(f"re-entry desk{(' · computed ' + as_of) if as_of else ''}")
        elif src_s == "get_cio_snapshot":
            parts = [k for k in ("cash", "sector_exposure", "risk", "investment_policy", "portfolio")
                     if (avail.get("freeform_context") or {}).get(k)]
            labels.append("CIO snapshot" + (f" ({', '.join(parts)})" if parts else ""))
        elif src_s.endswith("holdings.json"):
            labels.append("holdings.json")
        elif "yahoo_analyst" in src_s:
            labels.append("yahoo_analyst_targets_history")
        elif src_s.startswith("/") and src_s.endswith(".json"):
            labels.append(src_s.rsplit("/", 1)[-1])
        else:
            labels.append(src_s)
    if avail.get("reentry_symbol_cards") or avail.get("reentry_card"):
        labels.append("re-entry desk")
    if avail.get("analyst_view"):
        labels.append("yahoo_analyst_targets_history")
    if avail.get("hermes_research"):
        labels.append("hermes_research_intelligence")
    csrc = str((curated or {}).get("source") or "")
    model = (curated or {}).get("model")
    if csrc == "deepseek_flash" and (avail.get("freeform_context") is not None):
        labels.append(f"{model or 'DeepSeek Flash'} — {ROLE_GENERAL_KNOWLEDGE}")
    elif csrc == "deepseek_flash":
        labels.append(f"{model or 'DeepSeek Flash'} — {ROLE_WORDING_ONLY}")
    elif csrc == "freeform_flash":
        labels.append(f"{model or 'DeepSeek Flash'} — {ROLE_GENERAL_KNOWLEDGE}")
    elif csrc.startswith("gap_resolver"):
        labels.append(csrc)
    return _dedupe(labels)


def with_sources_footer(text: str, evidence: dict[str, Any], curated: dict[str, Any]) -> str:
    """Append one ``Sources:`` line built from a desk evidence dict.

    Same behaviour as the base fix's ``_with_sources_footer``: silent when there
    is nothing to cite, and the line sits ABOVE a trailing authority tail. The
    desk loop re-exports this under its old name.
    """
    if not (text or "").strip():
        return text
    labels = labels_from_evidence(evidence, curated)
    if not labels:
        return text
    footer = SOURCES_PREFIX + SEP.join(labels[:6])
    body = text.rstrip()
    # Split off the WHOLE last line when it carries the authority token, and keep it
    # once. The base version stripped only the trailing "READ_ONLY_ADVISORY" token
    # and then re-appended the whole line, so a card ending "No orders/stops from
    # chat · READ_ONLY_ADVISORY" went out as "No orders/stops from chat ·" /
    # "Sources: ..." / "No orders/stops from chat · READ_ONLY_ADVISORY".
    head, _, last = body.rpartition("\n")
    if AUTHORITY in last:
        return f"{head}\n{footer}\n{last}" if head else f"{footer}\n{last}"
    return f"{body}\n{footer}"


def store_labels_from_raw(sources: list[Any], *, as_of: Any = None) -> list[str]:
    """Labels for a bare ``sources`` list (a desk result without its evidence dict)."""
    labels: list[str] = []
    for src in sources or []:
        s = str(src)
        if "reentry_decision_desk" in s:
            ts = _short_ts(as_of)
            labels.append(f"re-entry desk{(' · computed ' + ts) if ts else ''}")
        elif s == "get_cio_snapshot":
            labels.append("CIO snapshot")
        elif s.endswith("holdings.json"):
            labels.append("holdings.json")
        elif s == "cio_operator_attention":
            labels.append("office situation scan")
        elif s.startswith("/") and s.endswith(".json"):
            labels.append(s.rsplit("/", 1)[-1])
        else:
            labels.append(s)
    return _dedupe(labels)


def model_role_for(reply_source: Any, *, freeform: bool = False) -> Optional[str]:
    """Which role a model played, from the desk's ``reply_source`` marker."""
    src = str(reply_source or "")
    if src == "freeform_flash":
        return ROLE_GENERAL_KNOWLEDGE
    if src == "deepseek_flash":
        return ROLE_GENERAL_KNOWLEDGE if freeform else ROLE_WORDING_ONLY
    return None


def went_outside_from_desk(desk: dict[str, Any]) -> list[str]:
    """Everything a desk turn reached for beyond the Command Center's stores.

    Read from the desk result: the intent classifier's model, the Phase 7 gap
    resolver receipt (answered / queued vectors), the explicit ``went_outside``
    entries the desk records when it enqueues Hermes, the reply's own model
    when it wrote prose, and the freeform builder's research_status line when
    it says research was queued.
    """
    out: list[str] = []
    d = desk or {}
    intent = d.get("intent") if isinstance(d.get("intent"), dict) else {}
    if str(intent.get("source") or "") == "deepseek_flash":
        out.append(f"{intent.get('model') or 'deepseek-flash'} — {ROLE_INTENT_ONLY}")
    for item in d.get("went_outside") or []:
        out.append(str(item))
    receipt = d.get("gap_resolution") if isinstance(d.get("gap_resolution"), dict) else {}
    for entry in receipt.get("answered") or []:
        parts = str(entry).split(":")
        if len(parts) >= 3:
            out.append(f"{parts[2]} — {parts[0].replace('_', ' ')} for {parts[1]} had no house coverage (answered)")
        else:
            out.append(f"gap resolver — {entry} (answered)")
    for entry in receipt.get("queued") or []:
        parts = str(entry).split(":")
        eta = receipt.get("eta_seconds")
        eta_txt = f", ≈ {max(1, int(round(int(eta) / 60.0)))} min" if isinstance(eta, (int, float)) else ""
        if len(parts) >= 3:
            out.append(f"{parts[2]} — {parts[0].replace('_', ' ')} for {parts[1]} had no house coverage (queued{eta_txt})")
        else:
            out.append(f"gap resolver — {entry} (queued{eta_txt})")
    rs = str(d.get("reply_source") or "")
    if rs.startswith("gap_resolver:") and not receipt:
        vec = rs.split(":", 1)[1]
        if vec == "no_coverage":
            out.append("gap resolver — every declared vector denied or empty; nothing answered")
        else:
            out.append(f"{vec} — house store had no coverage (answered via gap resolver)")
    elif rs == "gap_resolver:no_coverage":
        out.append("gap resolver — every declared vector denied or empty; nothing answered")
    role = model_role_for(rs, freeform=str(intent.get("intent") or "") == "freeform")
    if role and d.get("model"):
        out.append(f"{d.get('model')} — {role}")
    elif role:
        out.append(f"DeepSeek Flash — {role}")
    txt = str(d.get("text") or "")
    if "research queued via" in txt:
        out.append("gap resolver — thematic research queued (house held no research on the topic)")
    return _dedupe_exact(out)


# ── the chokepoint ───────────────────────────────────────────────────────────


def _split_provenance_lines(text: str) -> tuple[list[str], Optional[str], Optional[str], Optional[str]]:
    """Body lines with every Sources / Went outside / authority-tail line pulled out.

    Returns (body_lines, existing_sources_line, existing_outside_line, tail_wording).
    The first tail wording seen is kept so a path's own phrasing survives; every
    whole-line tail is removed so the reply ends with exactly one.
    """
    body: list[str] = []
    sources_line: Optional[str] = None
    outside_line: Optional[str] = None
    tail: Optional[str] = None
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if s.startswith("Sources:"):
            if sources_line is None:
                sources_line = s
            continue
        if s.startswith("Went outside:"):
            if outside_line is None:
                outside_line = s
            continue
        if AUTHORITY_TAIL_RE.match(ln):
            if tail is None:
                tail = s
            continue
        body.append(ln)
    # trailing blank lines are noise once the footer moves
    while body and not body[-1].strip():
        body.pop()
    return body, sources_line, outside_line, tail


def _parse_sources_line(line: str) -> tuple[list[str], Optional[str]]:
    """Split an existing Sources line into store labels and a model label."""
    payload = line[len("Sources:"):].strip()
    stores: list[str] = []
    model_label: Optional[str] = None
    for part in payload.split(SEP):
        p = part.strip()
        if not p:
            continue
        if any(m in p for m in _MODEL_LABEL_MARKERS):
            model_label = model_label or p
        else:
            stores.append(p)
    return stores, model_label


def finalize_operator_reply(text: str, prov: ReplyProvenance) -> tuple[str, ReplyProvenance]:
    """Canonicalise one outbound reply: body / Sources / Went outside / tail.

    - A Sources line already in the body (the desk loop's, evidence-aware) is
      kept and its store labels are merged into the receipt; the model label is
      appended if the receipt names a model the line does not.
    - Otherwise the line is built from ``prov.stores_read`` and ``prov.model``.
      An empty ``stores_read`` is said out loud -- "none" -- never hidden.
    - ``Went outside:`` appears iff ``prov.went_outside`` is non-empty.
    - Exactly one authority tail, last. The body's own wording is kept when it
      had one; ``DEFAULT_TAIL`` otherwise.
    Returns the final text and the receipt with ``sources_line_present`` /
    ``authority_tail_present`` set from the text that will actually be sent.
    """
    body, existing_sources, _existing_outside, tail = _split_provenance_lines(text or "")

    stores = _dedupe(list(prov.stores_read or []))
    model_label: Optional[str] = None
    if existing_sources:
        parsed_stores, parsed_model = _parse_sources_line(existing_sources)
        stores = _dedupe(parsed_stores + stores)
        model_label = parsed_model
    if prov.model and not model_label:
        model_label = f"{prov.model} — {prov.model_role or ROLE_WORDING_ONLY}"
    if model_label and not prov.model:
        # the line already named a model; carry it into the receipt
        prov.model = model_label.split(" — ", 1)[0].strip() or None
        prov.model_role = model_label.split(" — ", 1)[1].strip() if " — " in model_label else prov.model_role
    prov.stores_read = stores

    parts = list(stores[:6]) if stores else ["none — no Command Center store was read for this reply"]
    if model_label:
        parts.append(model_label)
    sources_line = SOURCES_PREFIX + SEP.join(parts)

    outside = _dedupe_exact(list(prov.went_outside or []))
    prov.went_outside = outside
    lines = list(body)
    lines.append(sources_line)
    if outside:
        lines.append(OUTSIDE_PREFIX + "; ".join(outside[:6]))
    lines.append(tail or DEFAULT_TAIL)
    final = "\n".join(lines)
    prov.sources_line_present = any(ln.startswith("Sources:") for ln in final.split("\n"))
    prov.authority_tail_present = bool(AUTHORITY_TAIL_RE.match(final.split("\n")[-1]))
    return final, prov


def provenance_for_desk(desk: dict[str, Any], *, kind: str = "operator_desk") -> ReplyProvenance:
    """Receipt for a desk-loop result. Stores from the result's raw ``sources``;
    the evidence-aware Sources line in its text (if any) is merged at finalize."""
    d = desk or {}
    intent = d.get("intent") if isinstance(d.get("intent"), dict) else {}
    rs = d.get("reply_source")
    role = model_role_for(rs, freeform=str(intent.get("intent") or "") == "freeform")
    return ReplyProvenance(
        kind=kind,
        stores_read=store_labels_from_raw(list(d.get("sources") or [])),
        went_outside=went_outside_from_desk(d),
        model=d.get("model") if role else None,
        model_role=role,
    )


__all__ = [
    "AUTHORITY", "AUTHORITY_TAIL_RE", "DEFAULT_TAIL", "SCHEMA",
    "ROLE_GENERAL_KNOWLEDGE", "ROLE_INTENT_ONLY", "ROLE_WORDING_ONLY",
    "ReplyProvenance", "finalize_operator_reply", "labels_from_evidence",
    "model_role_for", "provenance_for_desk", "store_labels_from_raw",
    "went_outside_from_desk", "with_sources_footer",
]
