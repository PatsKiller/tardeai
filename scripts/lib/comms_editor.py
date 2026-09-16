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
     CIO's latest decision; a disagreement is stated on the message, and a
     product the CIO marked OPERATOR_PRODUCT_INVALID is held.
  5. Links. Each named symbol gets its Command Center page on the fully
     qualified Tailscale host, and Finviz plus Yahoo as alternate sources.
  6. Pills. 🟢 Trade-AI · 🔵 Outside · 🟣 DeepSeek, from what the message says.

MODES (``COMMS_EDITOR_MODE``): ``off`` (default) · ``shadow`` -- decide and
write a receipt, send the original unchanged · ``live`` -- send the edited
message and hold duplicates and invalid products.

AUTHORITY: READ_ONLY_ADVISORY. Formatting, reads and one local ledger file.
Never places, sizes or cancels anything. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
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

PILL_HOUSE = "🟢 Trade-AI"
PILL_OUTSIDE = "🔵 Outside"
PILL_MODEL = "🟣 DeepSeek"

#: Same content to the same chat inside this window is a duplicate.
DUPLICATE_WINDOW_HOURS = 20
#: Telegram's hard limit is 4096; leave room for the footer.
MAX_BODY_FOR_FOOTER = 3500

_HTML_TAG = re.compile(r"</?(?:b|strong|i|em|u|s|code|pre|a|blockquote|tg-spoiler)(?:\s[^>]*)?>", re.I)
_STANCE_BULL = re.compile(r"\b(GO|A\+|BUY|ADD(?:_ON_PULLBACK)?|ACCUMULATE|STRONG BUY)\b")
_STANCE_BEAR = re.compile(r"\b(AVOID|SELL|EXIT|TRIM|REDUCE|DO NOT BUY)\b")
_CIO_BULL = {"BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE", "INITIATE", "REENTER", "RE_ENTER"}
_CIO_BEAR = {"AVOID", "SELL", "EXIT", "TRIM", "REDUCE", "HOLD_REDUCE"}


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
    plain = re.sub(r"<[^>]+>", " ", text or "")
    for m in re.finditer(rf"(?<![A-Z]){re.escape(symbol)}(?![A-Z])", plain):
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


def cc_base() -> str:
    for key in ("COMMAND_CENTER_BASE_URL", "TRADEAI_CC_BASE_URL", "NOTIFICATION_PUBLIC_BASE_URL"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v.startswith("https://") and not re.search(r"192\.168\.|127\.0\.0\.1|localhost|0\.0\.0\.0|10\.0\.", v):
            return v
    return f"https://{(os.environ.get('TAILSCALE_HOSTNAME') or DEFAULT_CC_HOST).strip()}"


def symbol_links(symbol: str) -> str:
    # Canonical dossier deep-link (same as telegram_rich.cc_symbol_url) — not portfolio.
    s = quote(symbol.upper())
    return (f'<a href="{cc_base()}/v3/watch/intelligence/{s}">{html.escape(symbol.upper())} in Command Center</a>'
            f' · <a href="https://finviz.com/quote.ashx?t={s}">Finviz</a>'
            f' · <a href="https://finance.yahoo.com/quote/{s}">Yahoo</a>')


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
         resolve: Optional[Callable[[str], list[dict]]] = None, editor_mode: Optional[str] = None) -> EditorDecision:
    """Decide what one message becomes. Pure apart from reads; ``commit`` records it."""
    now = now or datetime.now(timezone.utc)
    ledger = ledger or DuplicateLedger()
    m = editor_mode or mode()
    fp = fingerprint(text)
    guid = message_guid(str(chat_id), fp, now)
    changes: list[str] = []

    body = text or ""
    if parse_mode == "HTML" or looks_like_html(body):
        html_body = body
    else:
        html_body = markdown_to_html(body)
        if html_body != body:
            changes.append("markdown_to_html")

    subs = subjects(body, resolve=resolve)
    views = cio_views([s["symbol"] for s in subs], db_query)
    disagree = cio_disagreements(body, views)
    held = "operator_product_invalid" if "OPERATOR_PRODUCT_INVALID" in body else None
    prior = ledger.check(chat_id, fp, now)

    footer: list[str] = []
    if subs and len(html_body) < MAX_BODY_FOR_FOOTER:
        footer.append(" · ".join(symbol_links(s["symbol"]) for s in subs[:3]))
        changes.append("links")
    for d in disagree:
        footer.append(f"⚠️ <b>CIO disagrees on {html.escape(d['symbol'])}</b>: message reads {d['message']}, "
                      f"CIO decision is {html.escape(d['cio_action'])} ({html.escape(d['cio_as_of'])})")
        changes.append(f"cio_disagreement:{d['symbol']}")
    if len(html_body) < MAX_BODY_FOR_FOOTER:
        ids = " ".join(f"{s['symbol']}:{s['guid'][:8]}" for s in subs[:4])
        footer.append(f"<i>{' · '.join(pills_for(body))} · 🆔 {guid[:8]}{(' · ' + ids) if ids else ''}</i>")
        changes.append("guid_footer")
    final = html_body.rstrip() + ("\n\n" + "\n".join(footer) if footer else "")
    return EditorDecision(mode=m, chat=_chat_key(chat_id), guid=guid, fingerprint=fp, text=final,
                          parse_mode="HTML", duplicate_of=(prior or {}).get("guid"), held_reason=held,
                          subjects=subs, cio_disagreements=disagree, changes=changes)


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


__all__ = ["DuplicateLedger", "EditorDecision", "PILL_HOUSE", "PILL_MODEL", "PILL_OUTSIDE", "cc_base",
           "cio_disagreements", "commit", "default_db_query", "edit", "fingerprint", "markdown_to_html", "message_guid", "mode",
           "subjects", "symbol_links"]
