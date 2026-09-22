"""Communications Editor -- the one function that owns what reaches the operator.

Operator, 2026-09-14, after reading five Telegram exports end to end:

    "I need something that's accurate ... formatted in HTML where I can actually
    see and hyperlink back to the fully qualified tail scale if it's in command
    center. If you're giving me something from FinViz or Yahoo, go back to the
    alternative source ... Intelligence to me is not giving me the same daily
    morning dump. It should contain new stuff ... I need a function on agent
    that's totally responsible for these communication messages that go out,
    formatted, and accuracy. This should be polished like it's coming from your
    broker at Goldman Sachs or Citadel."

    "make sure all these messages have guid nothing redundant CIO agrees"

What the exports showed (2026-08-25 .. 09-14): the same MORNING CIO BRIEF 50
times in 16 days, word for word; 299 messages with literal Markdown asterisks
(Telegram rejected the Markdown and the transport resent plain text); links on
about one message in five; content-free "CIO Run Complete -- <uuid>" notices;
decisions shipped while marked OPERATOR_PRODUCT_INVALID; a brief saying
"AVOID AXTI" while the CIO's own decision row said RESEARCH_MORE.

THE EDITOR, applied to every message at ``telegram_transport.deliver_text``:

  1. HTML. Telegram Markdown is converted to escaped HTML (bold, italic, code,
     links); identifiers like READ_ONLY_ADVISORY are never mangled.
  2. GUIDs. Every message gets a message GUID; every company it names gets its
     registry subject GUID. Both go on a compact footer.
  3. Nothing redundant. A fingerprint of the message with times, ages and ids
     removed is kept per chat; the same content inside the window is not sent
     again (the transport reports it as a suppressed duplicate).
  4. CIO agrees. Each named symbol's stance in the message is compared with the
     CIO's latest decision. In ``live`` mode a disagreement **holds** the send
     (2026-09-18 Telegram↔CIO audit: 225 disagreed messages were still
     delivered when this only annotated). Bullish investment-shaped messages
     with **no** ``cio_decisions`` row are also held (fail closed).
     OPERATOR_PRODUCT_INVALID products are held. Index/macro tickers
     (SPY/QQQ/…) are excluded from stance matching so a market-header
     "Bullish" line cannot suppress the desk.
  4b. Soft-block rewrite (2026-09-20 audit C2). When the message is bullish/GO
     and CIO is RESEARCH_MORE / HUMAN_REVIEW / HOLD (etc.), demote GO/BUY
     headlines to WATCH/RESEARCH and re-check stance so the operator gets a
     watch alert instead of silence. Hard-bear CIO (AVOID/SELL/TRIM/…) still
     holds — never soft-deliver a watch over an avoid.
  4c. Publish packet (2026-09-20 audit C3). Recommendation-shaped sends
     (GO/BUY/WATCH-from-rewrite) get a structured footer: thesis, CIO
     action+as_of, risks, evidence, portfolio fit (best-effort from body +
     CIO row; thin fields marked n/a).
  5. Links. Each named symbol gets its Command Center page on the fully
     qualified Tailscale host, and Finviz plus Yahoo as alternate sources.
  6. Pills. 🟢 Trade-AI · 🔵 Outside · 🟣 DeepSeek, from what the message says.

MODES (``COMMS_EDITOR_MODE``): ``off`` (default) · ``shadow`` -- decide and
write a receipt, send the original unchanged · ``live`` -- send the edited
message and hold duplicates, invalid products, CIO stance disagreements, and
missing CIO decisions on bullish investment-shaped text.

AUTHORITY: READ_ONLY_ADVISORY. Formatting, reads and one local ledger file.
Never places, sizes or cancels anything. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import contextvars
import hashlib
import html
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CommsEditorDecision@v1"
ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = PROJECT_ROOT / "data" / "runtime" / "comms_editor_ledger.json"
DEFAULT_RECEIPTS = PROJECT_ROOT / "data" / "runtime" / "comms_editor_receipts.jsonl"
DEFAULT_CC_HOST = "ms01-openclaw.tail163d14.ts.net"
MSG_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tradeai:operator-message")

#: Active-turn primary symbols for footer links. Set by the desk before send so
#: residual names in the body (prior-turn memory) do not bleed into chrome tags.
_PRIMARY_SYMBOLS_CV: contextvars.ContextVar[Optional[tuple[str, ...]]] = contextvars.ContextVar(
    "comms_editor_primary_symbols", default=None,
)

PILL_HOUSE = "🟢 Trade-AI"
PILL_OUTSIDE = "🔵 Outside"
PILL_MODEL = "🟣 DeepSeek"

#: Same content to the same chat inside this window is a duplicate.
DUPLICATE_WINDOW_HOURS = 20
#: Telegram's hard limit is 4096; leave room for the footer.
MAX_BODY_FOR_FOOTER = 3500

_HTML_TAG = re.compile(r"</?(?:b|strong|i|em|u|s|code|pre|a|blockquote|tg-spoiler)(?:\s[^>]*)?>", re.I)
_STANCE_BULL = re.compile(r"\b(GO|A\+|BUY|STRONG\s+BUY|ADD(?:_ON_PULLBACK)?|ACCUMULATE|BULLISH)\b")
_STANCE_BEAR = re.compile(r"\b(AVOID|SELL|EXIT|TRIM|REDUCE|DO NOT BUY|BEARISH|HOLD)\b")
# BUY_READY / ENTRY_NEAR are bullish-lean CIO actions (2026-09-18 audit: omitting
# them labeled 202 GO alerts as "neutral" and flooded false disagreements).
_CIO_BULL = {
    "BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE", "INITIATE", "REENTER", "RE_ENTER",
    "BUY_READY", "ENTRY_NEAR",
}
_CIO_BEAR = {"AVOID", "SELL", "EXIT", "TRIM", "REDUCE", "HOLD_REDUCE"}
# Soft non-bull CIO actions: allow GO/BUY → WATCH rewrite then re-check (C2).
_CIO_SOFT_BLOCK = frozenset({
    "RESEARCH_MORE", "HUMAN_REVIEW", "HOLD", "WAIT", "NEUTRAL", "NO_GO", "NOGO", "WATCH",
})
# Broad market / macro symbols: regime words near these are not investment recs.
_STANCE_EXCLUDE_SYMBOLS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "IEF", "HYG", "LQD", "USO", "GLD", "SLV",
})
_CIO_DECISION_HEADER = re.compile(r"^\[CIO DECISION\]", re.M)
_REC_SHAPED = re.compile(
    r"\bNEW\s+GO\b|\b\[GO\]\b|\b\[WATCH\]\b|\bSTRONG\s+BUY\b|"
    r"\b(?:GO|BUY|ACCUMULATE|WATCH)\b.{0,40}\bRVOL\b|"
    r"\bRVOL\b.{0,40}\b(?:GO|WATCH)\b",
    re.I | re.S,
)
_THESIS_LINE = re.compile(
    r"(?:Finviz[^\n]*\n\s*)?_([^_\n]{12,160})_|Finviz[^\n]*\n\s*([^\n]{12,160})",
    re.I,
)
_RISK_LINE = re.compile(
    r"(Critic:[^\n]{0,160}|MICRO_FLOAT[^\n]{0,120}|DOWNGRADE[^\n]{0,120}|⚠️[^\n]{0,160})",
    re.I,
)


def _holds_invalid_product(body: str) -> bool:
    """True only for a standalone invalid operator product — never a digest.

    The morning/EOD brief renders the whole-product completeness grade
    (``OPERATOR_PRODUCT_INVALID``) on EVERY decision's "Completeness" line, so a
    bare substring match held the digest — the one message the operator reads
    every day — and two of its three chunks never reached the phone
    (2026-09-16 07:30 ET) while the semantic-state file still recorded the brief
    as published. A digest carries many ``[CIO DECISION]`` blocks; a standalone
    invalid product is exactly one. Hold the latter, ship the former.
    """
    if "OPERATOR_PRODUCT_INVALID" not in body:
        return False
    return len(_CIO_DECISION_HEADER.findall(body)) == 1


#: Host-level switch, one line: off | shadow | live. Most Telegram senders are cron
#: jobs that never load an env file, so an environment variable alone would put
#: only some processes in shadow mode -- and "shadow for one trading day" would
#: review a partial sample. The file reaches every sender on the host.
MODE_FILE_DEFAULT = Path.home() / ".config" / "tradeai" / "comms_editor_mode"


def mode() -> str:
    """COMMS_EDITOR_MODE from the environment, else the host mode file, else off."""
    m = (os.environ.get("COMMS_EDITOR_MODE") or "").strip().lower()
    if not m:
        path = Path(os.environ.get("COMMS_EDITOR_MODE_FILE") or MODE_FILE_DEFAULT)
        try:
            m = path.read_text(encoding="utf-8").strip().splitlines()[0].strip().lower()
        except (OSError, IndexError):
            m = ""
    return m if m in ("off", "shadow", "live") else "off"


# ── 1. HTML ──────────────────────────────────────────────────────────────────


def looks_like_html(text: str) -> bool:
    return bool(_HTML_TAG.search(text or ""))


def markdown_to_html(text: str) -> str:
    """Telegram Markdown (v1) -> escaped Telegram HTML. HTML input is returned unchanged.

    ``*bold*`` / ``**bold**`` -> <b>, ``_italic_`` only between non-word
    characters (so READ_ONLY_ADVISORY and snake_case ids stay intact),
    ```code``` -> <code>, ``[label](https://url)`` -> <a>. Everything else is
    escaped, so a stray ``<`` or ``&`` can never break the parse again.
    """
    if not text:
        return ""
    if looks_like_html(text):
        return text
    stash: list[str] = []

    def keep(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    t = re.sub(r"`([^`\n]+)`", lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)",
               lambda m: keep(f'<a href="{html.escape(m.group(2), quote=True)}">{html.escape(m.group(1))}</a>'), t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w])_([^_\n]+?)_(?![\w])", r"<i>\1</i>", t)
    t = t.replace("\\_", "_").replace("\\*", "*").replace("\\[", "[").replace("\\`", "`")
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], t)


# ── 2. GUIDs and 3. duplicates ───────────────────────────────────────────────

_VOLATILE = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:?\d{2}|Z)?\b"), "<ts>"),
    (re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|ET|EDT|EST|UTC|Z)?\b", re.I), "<time>"),
    (re.compile(r"\(\s*\d+(\.\d+)?\s*[hmd]\s*old\s*\)", re.I), "<age>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<hex>"),
    (re.compile(r"🆔[^\n]*"), ""),
]


def fingerprint(text: str) -> str:
    """Content identity: tags, times, ages, ids and whitespace removed."""
    t = re.sub(r"<[^>]+>", "", text or "")
    for rx, rep in _VOLATILE:
        t = rx.sub(rep, t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:20]


def message_guid(chat_id: str, fp: str, now: datetime) -> str:
    return str(uuid.uuid5(MSG_NAMESPACE, f"{chat_id}:{fp}:{now.isoformat()}"))


def _chat_key(chat_id: Any) -> str:
    return hashlib.sha256(str(chat_id).encode()).hexdigest()[:12]


class DuplicateLedger:
    """Per chat: fingerprint -> first GUID, first/last seen, count. JSON on disk."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or os.environ.get("COMMS_EDITOR_LEDGER") or DEFAULT_LEDGER)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"schema": "CommsEditorLedger@v1", "chats": {}}

    def check(self, chat_id: Any, fp: str, now: datetime, window_hours: float = DUPLICATE_WINDOW_HOURS) -> Optional[dict]:
        rec = (self._load().get("chats") or {}).get(_chat_key(chat_id), {}).get(fp)
        if not rec:
            return None
        try:
            last = datetime.fromisoformat(rec["last_seen"])
        except (KeyError, ValueError):
            return None
        return rec if now - last < timedelta(hours=window_hours) else None

    def record(self, chat_id: Any, fp: str, guid: str, now: datetime) -> None:
        doc = self._load()
        chats = doc.setdefault("chats", {})
        chat = chats.setdefault(_chat_key(chat_id), {})
        rec = chat.get(fp) or {"guid": guid, "first_seen": now.isoformat(), "count": 0}
        rec["last_seen"] = now.isoformat()
        rec["count"] = int(rec.get("count") or 0) + 1
        chat[fp] = rec
        cutoff = now - timedelta(hours=48)
        for key in list(chats):
            chats[key] = {k: v for k, v in chats[key].items()
                          if str(v.get("last_seen") or "") >= cutoff.isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        tmp.replace(self.path)


# ── subjects, CIO agreement, links, pills ────────────────────────────────────


def subjects(text: str, *, resolve: Optional[Callable[[str], list[dict]]] = None) -> list[dict[str, str]]:
    """Registry-backed companies the message names: [{symbol, guid}]. Never a guessed ticker."""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    try:
        if resolve is None:
            from scripts.lib.operator_subject_resolver import resolve_subjects  # noqa: PLC0415

            def resolve(t: str) -> list[dict]:
                return resolve_subjects(t, book=[])
        rows = resolve(plain) or []
    except Exception:  # noqa: BLE001
        rows = []
    out: list[dict[str, str]] = []
    for r in rows:
        if r.get("symbol") and r.get("guid") and r["symbol"] not in [o["symbol"] for o in out]:
            out.append({"symbol": str(r["symbol"]).upper(), "guid": str(r["guid"])})
    return out[:6]


def set_primary_symbols(symbols: Optional[Iterable[str]]) -> contextvars.Token:
    """Bind turn-scoped primary tickers for the next ``edit`` / deliver_text call."""
    try:
        from scripts.lib.telegram_rich import scope_primary_symbols  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from lib.telegram_rich import scope_primary_symbols  # type: ignore  # noqa: PLC0415
    if symbols is None:
        return _PRIMARY_SYMBOLS_CV.set(None)
    return _PRIMARY_SYMBOLS_CV.set(tuple(scope_primary_symbols(symbols)))


def reset_primary_symbols(token: contextvars.Token) -> None:
    _PRIMARY_SYMBOLS_CV.reset(token)


def _resolve_primary_symbols(explicit: Optional[Iterable[str]]) -> Optional[list[str]]:
    try:
        from scripts.lib.telegram_rich import scope_primary_symbols  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from lib.telegram_rich import scope_primary_symbols  # type: ignore  # noqa: PLC0415
    if explicit is not None:
        return scope_primary_symbols(explicit)
    cv = _PRIMARY_SYMBOLS_CV.get()
    if cv is None:
        return None
    return scope_primary_symbols(cv)


def cio_views(symbols: list[str], db_query: Optional[Callable[..., list[dict]]]) -> dict[str, dict[str, Any]]:
    """The CIO's latest decision per symbol in the last 3 days."""
    if not symbols or db_query is None:
        return {}
    try:
        rows = db_query(
            "SELECT DISTINCT ON (symbol) symbol, action, status, created_at FROM cio_decisions"
            " WHERE symbol = ANY(%s) AND created_at > now() - interval '3 days'"
            " ORDER BY symbol, created_at DESC", (list(symbols),)) or []
    except Exception:  # noqa: BLE001
        return {}
    return {str(r["symbol"]).upper(): r for r in rows if r.get("symbol")}


def _stance_near(text: str, symbol: str) -> Optional[str]:
    sym = (symbol or "").upper()
    if sym in _STANCE_EXCLUDE_SYMBOLS:
        return None
    plain = re.sub(r"<[^>]+>", " ", text or "")
    for m in re.finditer(rf"(?<![A-Z]){re.escape(sym)}(?![A-Z])", plain):
        window = plain[max(0, m.start() - 60): m.end() + 60].upper()
        bull, bear = _STANCE_BULL.search(window), _STANCE_BEAR.search(window)
        if bull and not bear:
            return "bullish"
        if bear and not bull:
            return "bearish"
    return None


def cio_disagreements(text: str, views: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for sym, v in views.items():
        action = str(v.get("action") or "").upper()
        cio = "bullish" if action in _CIO_BULL else ("bearish" if action in _CIO_BEAR else "neutral")
        said = _stance_near(text, sym)
        if said and said != cio:
            out.append({"symbol": sym, "message": said, "cio_action": action,
                        "cio_as_of": str(v.get("created_at") or "")[:16]})
    return out


def cio_missing_decisions(
    text: str,
    symbols: list[str],
    views: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bullish investment-shaped symbols with no ``cio_decisions`` row — fail closed.

    Only bullish (Buy/GO/Accumulate) messages are held when the CIO row is
    missing. Bearish CIO digests that *are* the decision product must still
    ship (2026-09-16 morning-brief hold regression).
    """
    out = []
    for sym in symbols:
        s = str(sym or "").upper()
        if not s or s in _STANCE_EXCLUDE_SYMBOLS or s in views:
            continue
        said = _stance_near(text, s)
        if said == "bullish":
            out.append({"symbol": s, "message": said, "cio_action": None, "cio_as_of": ""})
    return out


def rewrite_bullish_to_watch(text: str, symbols: list[str]) -> tuple[str, list[str]]:
    """Demote GO/BUY lexicon near soft-block conflict symbols to WATCH/RESEARCH.

    Used when Telegram is bullish but CIO is RESEARCH_MORE / HUMAN_REVIEW / HOLD
    (etc.): ban the GO headline, keep a watch-shaped alert for the operator.
    Hard-bear CIO actions must not call this path — those stay held.
    """
    out = text or ""
    changes: list[str] = []
    for sym in symbols:
        s = str(sym or "").upper()
        if not s or s in _STANCE_EXCLUDE_SYMBOLS:
            continue
        before = out
        # NEW GO — SYM  /  *NEW GO* — *SYM*
        out = re.sub(
            rf"\*?NEW\s+GO\*?\s*[—\-:-]\s*\*?{re.escape(s)}\*?",
            f"WATCH — *{s}*",
            out,
            flags=re.I,
        )
        # [GO] near SYM / SYM … [GO]
        out = re.sub(
            rf"\[GO\](?=[^\n]{{0,50}}\b{re.escape(s)}\b)",
            "[WATCH]",
            out,
            flags=re.I,
        )
        out = re.sub(
            rf"(\b{re.escape(s)}\b[^\n]{{0,50}})\[GO\]",
            r"\1[WATCH]",
            out,
            flags=re.I,
        )
        # Bare GO token immediately before SYM (✅ GO *SYM*)
        out = re.sub(
            rf"\bGO\b(\s+\*?{re.escape(s)}\*?)",
            r"WATCH\1",
            out,
            flags=re.I,
        )
        # BUY / STRONG BUY / ACCUMULATE / BULLISH near SYM (either side)
        out = re.sub(
            rf"\b(STRONG\s+BUY|BUY|ACCUMULATE|ADD(?:_ON_PULLBACK)?|BULLISH)\b"
            rf"([^\n]{{0,50}}\b{re.escape(s)}\b)",
            rf"WATCH\2",
            out,
            flags=re.I,
        )
        out = re.sub(
            rf"(\b{re.escape(s)}\b[^\n]{{0,50}})\b(STRONG\s+BUY|BUY|ACCUMULATE|BULLISH)\b",
            rf"\1WATCH",
            out,
            flags=re.I,
        )
        if out != before:
            changes.append(f"rewrote:go_to_watch:{s}")
    return out, changes


def _recommendation_shaped(text: str) -> bool:
    return bool(_REC_SHAPED.search(text or ""))


def _publish_packet_lines(
    text: str,
    views: dict[str, dict[str, Any]],
    symbols: list[str],
) -> list[str]:
    """Best-effort thesis / CIO / risks / evidence / portfolio-fit lines for the footer."""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    thesis = "n/a · not stated"
    m = _THESIS_LINE.search(text or "")
    if m:
        thesis = (m.group(1) or m.group(2) or "").strip().rstrip("_")[:140] or thesis
    elif re.search(r"\bRVOL\b", plain, re.I):
        thesis = "scanner catalyst (RVOL/score) — see body"
    risk = "n/a · not stated"
    rm = _RISK_LINE.search(text or "")
    if rm:
        risk = re.sub(r"\s+", " ", rm.group(1)).strip()[:140]
    evidence = "n/a · not stated"
    if re.search(r"\bFinviz\b", plain, re.I):
        evidence = "Finviz headline/blurb"
    elif re.search(r"\b(RVOL|SEC|Form\s*4|earnings|ATR)\b", plain, re.I):
        evidence = "in-body scanner/market fields"
    lines = ["📋 <b>Publish packet</b>"]
    lines.append(f"• Thesis: {html.escape(thesis)}")
    for sym in symbols[:4]:
        v = views.get(sym) or {}
        action = str(v.get("action") or "UNKNOWN")
        as_of = str(v.get("created_at") or "")[:16] or "n/a"
        lines.append(f"• CIO {html.escape(sym)}: {html.escape(action)} as_of {html.escape(as_of)}")
    if not symbols:
        lines.append("• CIO: n/a · no subject symbols")
    lines.append(f"• Risks: {html.escape(risk)}")
    lines.append(f"• Evidence: {html.escape(evidence)}")
    lines.append("• Portfolio fit: n/a · scanner-watch (not book-checked)")
    return lines


def soft_block_rewrite_symbols(disagree: list[dict[str, Any]]) -> list[str]:
    """Symbols eligible for GO→WATCH rewrite (bullish msg + soft-block CIO)."""
    out: list[str] = []
    for d in disagree:
        action = str(d.get("cio_action") or "").upper()
        if d.get("message") == "bullish" and action in _CIO_SOFT_BLOCK:
            sym = str(d.get("symbol") or "").upper()
            if sym and sym not in out:
                out.append(sym)
    return out


def _hold_reason(
    body: str,
    disagree: list[dict[str, Any]],
    missing: Optional[list[dict[str, Any]]] = None,
) -> Optional[str]:
    """Live hold policy: invalid product, stance conflict, then missing CIO decision."""
    if _holds_invalid_product(body):
        return "operator_product_invalid"
    if disagree:
        # Alias kept as cio_disagreement for receipts that already key on it;
        # publishers use cio_stance_conflict via cio_telegram_stance_gate.
        return "cio_disagreement"
    if missing:
        return "cio_decision_missing"
    return None


def cc_base() -> str:
    for key in ("COMMAND_CENTER_BASE_URL", "TRADEAI_CC_BASE_URL", "NOTIFICATION_PUBLIC_BASE_URL"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v.startswith("https://") and not re.search(r"192\.168\.|127\.0\.0\.1|localhost|0\.0\.0\.0|10\.0\.", v):
            return v
    return f"https://{(os.environ.get('TAILSCALE_HOSTNAME') or DEFAULT_CC_HOST).strip()}"


def symbol_links(symbol: str) -> str:
    # Canonical dossier deep-link (same as telegram_rich.cc_symbol_url) — not portfolio.
    try:
        from scripts.lib.telegram_rich import symbol_links as _rich_links  # noqa: PLC0415
        return _rich_links(symbol, surface="intelligence")
    except ImportError:  # pragma: no cover
        s = quote(symbol.upper())
        return (f'<a href="{cc_base()}/v3/watch/intelligence/{s}">{html.escape(symbol.upper())} in Command Center</a>'
                f' · <a href="https://finviz.com/quote.ashx?t={s}">Finviz</a>'
                f' · <a href="https://finance.yahoo.com/quote/{s}">Yahoo</a>')


def build_outbound_links(symbols: Optional[Iterable[str]]) -> str:
    """Footer chrome for the active turn's primary symbols only."""
    try:
        from scripts.lib.telegram_rich import build_outbound_links as _build  # noqa: PLC0415
        return _build(symbols, surface="intelligence")
    except ImportError:  # pragma: no cover
        from scripts.lib.telegram_rich import scope_primary_symbols  # noqa: PLC0415
        return " · ".join(symbol_links(s) for s in scope_primary_symbols(symbols)[:3])


def pills_for(text: str) -> list[str]:
    t = text or ""
    out = [PILL_HOUSE]
    if re.search(r"(?i)went outside|governed[_ ]search|brave|searxng|web search|looked up outside", t) and \
            not re.search(r"(?i)nothing (was )?looked up outside", t):
        out.append(PILL_OUTSIDE)
    if re.search(r"(?i)deepseek|model knowledge|flash|grok|chatgpt|llm", t):
        out.append(PILL_MODEL)
    return out


def default_db_query(sql: str, params: Any = None, fetch: str = "all") -> list[dict[str, Any]]:
    """Read-only, 2 s statement timeout, dict rows. Raises on failure (callers degrade)."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"), dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=2, options="-c statement_timeout=2000",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── the decision ─────────────────────────────────────────────────────────────


@dataclass
class EditorDecision:
    mode: str
    chat: str
    guid: str
    fingerprint: str
    text: str
    parse_mode: str
    duplicate_of: Optional[str] = None
    held_reason: Optional[str] = None
    subjects: list[dict[str, str]] = field(default_factory=list)
    cio_disagreements: list[dict[str, Any]] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    schema: str = SCHEMA
    authority: str = AUTHORITY

    @property
    def send(self) -> bool:
        return not (self.duplicate_of or self.held_reason)

    def receipt(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("text", None)
        d["send"] = self.send
        return d


def edit(text: str, *, chat_id: Any, parse_mode: Optional[str] = None, now: Optional[datetime] = None,
         ledger: Optional[DuplicateLedger] = None, db_query: Optional[Callable[..., list[dict]]] = None,
         resolve: Optional[Callable[[str], list[dict]]] = None, editor_mode: Optional[str] = None,
         primary_symbols: Optional[Iterable[str]] = None) -> EditorDecision:
    """Decide what one message becomes. Pure apart from reads; ``commit`` records it.

    ``primary_symbols`` scopes footer links to the active turn only. When set
    (or via ``set_primary_symbols``), residual tickers in the body — e.g. TROW
    from prior-turn memory — do not get secondary Finviz/Yahoo chrome.
    """
    now = now or datetime.now(timezone.utc)
    ledger = ledger or DuplicateLedger()
    m = editor_mode or mode()
    changes: list[str] = []

    body = text or ""
    was_html = parse_mode == "HTML" or looks_like_html(body)

    primary = _resolve_primary_symbols(primary_symbols)
    subs = subjects(body, resolve=resolve)
    if primary is not None:
        allow = set(primary)
        # Keep GUID rows for primary only; never invent links for body bleed.
        by_sym = {s["symbol"]: s for s in subs}
        scoped: list[dict[str, str]] = []
        for sym in primary:
            if sym in by_sym:
                scoped.append(by_sym[sym])
            else:
                scoped.append({"symbol": sym, "guid": ""})
        subs = scoped
        changes.append("primary_symbols_scoped")
    syms = [s["symbol"] for s in subs if s.get("symbol")]
    views = cio_views(syms, db_query)
    disagree = cio_disagreements(body, views)
    missing = cio_missing_decisions(body, syms, views)

    # C2: soft-block GO/BUY → WATCH rewrite, then re-check stance.
    rewrite_syms = soft_block_rewrite_symbols(disagree)
    if rewrite_syms:
        new_body, rw_changes = rewrite_bullish_to_watch(body, rewrite_syms)
        if rw_changes and new_body != body:
            body = new_body
            changes.extend(rw_changes)
            # Subjects may still resolve; refresh disagreements on demoted text.
            disagree = cio_disagreements(body, views)
            missing = cio_missing_decisions(body, syms, views)

    # Fingerprint the body that will ship (post-rewrite) so WATCH dupes collapse.
    fp = fingerprint(body)
    guid = message_guid(str(chat_id), fp, now)

    if was_html:
        html_body = body
    else:
        html_body = markdown_to_html(body)
        if html_body != body:
            changes.append("markdown_to_html")

    held = _hold_reason(body, disagree, missing)
    prior = ledger.check(chat_id, fp, now)

    footer: list[str] = []
    if syms and len(html_body) < MAX_BODY_FOR_FOOTER:
        link_line = build_outbound_links(syms[:3] if primary is None else primary)
        if link_line:
            footer.append(link_line)
            changes.append("links")
    for d in disagree:
        footer.append(f"⚠️ <b>CIO disagrees on {html.escape(d['symbol'])}</b>: message reads {d['message']}, "
                      f"CIO decision is {html.escape(d['cio_action'] or 'UNKNOWN')} ({html.escape(d['cio_as_of'])})"
                      f" — <b>held</b>")
        changes.append(f"cio_disagreement:{d['symbol']}")
    for d in missing:
        footer.append(f"⚠️ <b>CIO decision missing for {html.escape(d['symbol'])}</b>: message reads "
                      f"{d['message']} — <b>held</b> (fail closed)")
        changes.append(f"cio_decision_missing:{d['symbol']}")
    if held == "cio_disagreement":
        changes.append("held:cio_disagreement")
    if held == "cio_decision_missing":
        changes.append("held:cio_decision_missing")

    # C3: structured publish packet on recommendation-shaped sends (and on holds
    # that were recommendation-shaped, so receipts/operators see the packet).
    if _recommendation_shaped(body) and len(html_body) < MAX_BODY_FOR_FOOTER:
        footer.extend(_publish_packet_lines(body, views, syms))
        changes.append("publish_packet")

    if len(html_body) < MAX_BODY_FOR_FOOTER:
        ids = " ".join(f"{s['symbol']}:{s['guid'][:8]}" for s in subs[:4] if s.get("guid"))
        footer.append(f"<i>{' · '.join(pills_for(body))} · 🆔 {guid[:8]}{(' · ' + ids) if ids else ''}</i>")
        changes.append("guid_footer")
    final = html_body.rstrip() + ("\n\n" + "\n".join(footer) if footer else "")
    return EditorDecision(mode=m, chat=str(_chat_key(chat_id)), guid=guid, fingerprint=fp, text=final,
                          parse_mode="HTML", duplicate_of=(prior or {}).get("guid"), held_reason=held,
                          subjects=[s for s in subs if s.get("guid")], cio_disagreements=disagree, changes=changes)


def commit(decision: EditorDecision, *, chat_id: Any, now: Optional[datetime] = None,
           ledger: Optional[DuplicateLedger] = None, receipts: Optional[Path] = None) -> None:
    """Record a sent message in the ledger and append the receipt."""
    now = now or datetime.now(timezone.utc)
    if decision.send and decision.mode == "live":
        (ledger or DuplicateLedger()).record(chat_id, decision.fingerprint, decision.guid, now)
    receipts = Path(receipts or os.environ.get("COMMS_EDITOR_RECEIPTS") or DEFAULT_RECEIPTS)
    try:
        receipts.parent.mkdir(parents=True, exist_ok=True)
        with receipts.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now.isoformat(), **decision.receipt()}, default=str) + "\n")
    except OSError:
        pass


__all__ = ["DuplicateLedger", "EditorDecision", "PILL_HOUSE", "PILL_MODEL", "PILL_OUTSIDE", "build_outbound_links",
           "cc_base", "cio_disagreements", "cio_missing_decisions", "commit", "default_db_query", "edit",
           "fingerprint", "markdown_to_html", "message_guid", "mode", "reset_primary_symbols",
           "rewrite_bullish_to_watch", "set_primary_symbols", "soft_block_rewrite_symbols", "subjects",
           "symbol_links"]
