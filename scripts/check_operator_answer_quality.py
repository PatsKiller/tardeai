#!/usr/bin/env python3
"""Measure the quality of the replies the operator actually received. Read-only.

WHY
---
On 2026-09-13 the operator asked three questions over Telegram and got:

    "Is now a good time to get back into schg"
        -> the WHOLE re-entry book (READY TO REVIEW / NEAR ENTRY), not SCHG's row
    "How does the market normally perform in September ... what sectors ..."
        -> DeepSeek general knowledge, plus "your holdings, weights and cash are
           not available ... all empty" while the CIO snapshot carried
           total_cash 710,933, sector weights and the investment policy
    "What's the outlook for SpaceX ..."
        -> a pending that could never close (SpaceX is private)

and not one reply said where its content came from. The operator's rule:
"routing should be internal Command Center first; when it has to go out for
other stuff it needs to let us know."

The desk was fixed the same evening. This measures every turn AFTER the fact,
against the ledgers the converse layer writes, so a regression is reported by a
monitor and not by the operator. It reads; it never replies, never edits a
ledger, never calls a model.

RULES (last 24h of operator turns)
----------------------------------
    NO_SOURCES_LINE              reply text without a "Sources:" line
    WENT_OUTSIDE_UNSTATED        provenance says went_outside is non-empty but
                                 the reply has no "Went outside:" line
    FALSE_EMPTY_CLAIM            reply says cash/holdings/sector/weights are
                                 not available / empty / DATA_UNAVAILABLE while
                                 the house had them. Which evidence decided it is
                                 named in the finding:
                                   provenance      stores_read has the CIO snapshot
                                   snapshot_health a persisted CIO snapshot from
                                                   within 24h of the turn said AVAILABLE
                                   store_health    holdings.json (store of record)
                                                   carried the domain at the time
    BOOK_DUMP_FOR_NAMED_SYMBOL   reply carries "READY TO REVIEW" or "NEAR ENTRY ("
                                 while the question names a known symbol
    PENDING_NEVER_CLOSED         a pending open > 2h with no expired/fulfilled row
    MODEL_UNLABELLED             a model wrote prose (provenance.model, or -- until
                                 Agent A's provenance lands -- reply_source names
                                 flash) and the reply never says "model knowledge"
                                 or "wording only"
    REPLY_TEXT_UNAVAILABLE       an operator turn whose reply text could not be
                                 read (the text rules above could not run for it)

WHERE THE TURNS LIVE
--------------------
    data/cio/cio_events.jsonl              operator.message events: question,
                                           reply_source, desk_kind, pending_id,
                                           and Agent A's reply_provenance
    operator_conversation_turns (DB)       the agent's reply text (role='agent',
                                           reply_to_message_id = the question).
                                           Read-only SELECT; degrades to
                                           REPLY_TEXT_UNAVAILABLE when unreachable.
    data/cio/cio_operator_pending_replies.jsonl   pending open/expired/fulfilled
    data/portfolios/state/holdings.json    store of record for the store_health rule

All data paths resolve through the served state tree (persistent-state), never
through this checkout: the monitor may run from a worktree that has no data/.

USAGE
-----
    python scripts/check_operator_answer_quality.py            # human-readable
    python scripts/check_operator_answer_quality.py --json
    python scripts/check_operator_answer_quality.py --dry-run  # print, never alert
    python scripts/check_operator_answer_quality.py --alert    # notify on change

EXIT CODES
----------
    0  nothing to report
    1  at least one finding
    2  could not run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "OperatorAnswerQualityReport@v1"
RECEIPT_NAME = "operator_answer_quality_last_run.json"
STATE_PATH = Path.home() / ".local/state/tradeai/operator_answer_quality_last_alert.json"
SENTINEL = "[DATA_INTEGRITY]"

WINDOW_HOURS = 24.0
PENDING_OPEN_HOURS = 2.0
SNAPSHOT_AT_THE_TIME_HOURS = 24.0

SCHEDULED_ENTRYPOINT = (
    "systemd: tradeai-operator-answer-quality.timer -- every 30 min at :22/:52 (proposed, not installed)"
)

RULES = (
    "NO_SOURCES_LINE",
    "WENT_OUTSIDE_UNSTATED",
    "FALSE_EMPTY_CLAIM",
    "BOOK_DUMP_FOR_NAMED_SYMBOL",
    "PENDING_NEVER_CLOSED",
    "RESEARCH_LANDED_UNSENT",
    "MODEL_UNLABELLED",
    "REPLY_TEXT_UNAVAILABLE",
)

#: Hermes finished the research a pending asked for, and the pending is still
#: open this long afterwards: the answer is on disk and the operator does not
#: have it. 2026-09-14 opr_74cc87d6ae62 (HPE) sat in exactly this state.
RESEARCH_LANDED_GRACE_MINUTES = 10.0

#: The canonical dev tree; the served state tree is reached through its data/ link.
DEV_TREE = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")

_EMPTY_CLAIM = re.compile(r"(?i)\b(not\s+available|unavailable|empty|DATA_UNAVAILABLE)\b")
_DOMAIN_WORD = re.compile(r"(?i)\b(cash|holdings?|sectors?|weights?)\b")
_BOOK_DUMP = re.compile(r"READY TO REVIEW|NEAR ENTRY \(")
_MODEL_LABEL = re.compile(r"(?i)model knowledge|wording only")
_FLASH_SOURCE = re.compile(r"(?i)flash|deepseek|llm_curation")
_SNAPSHOT_STORE = re.compile(r"(?i)cio[_ ]snapshot|get_cio_snapshot")


# ── small helpers ─────────────────────────────────────────────────────────────


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def data_root() -> Path:
    """The data/ directory of the served state tree.

    Order: TRADEAI_DATA_ROOT, CIO_STATE_ROOT/data, this checkout's data/ if it
    has a cio/ directory, the persistent-state root, then the canonical dev tree
    (whose data/ is linked to persistent-state). A worktree has no data/, so the
    checkout is never assumed.
    """
    env = (os.environ.get("TRADEAI_DATA_ROOT") or "").strip()
    if env:
        return Path(env)
    env = (os.environ.get("CIO_STATE_ROOT") or "").strip()
    if env:
        return Path(env) / "data"
    if (PROJECT_ROOT / "data" / "cio").is_dir():
        return PROJECT_ROOT / "data"
    try:
        from scripts.lib.persistent_state_root import good_persistent_root
        root = good_persistent_root() / "data"
        if (root / "cio").is_dir():
            return root
    except Exception:
        pass
    return DEV_TREE / "data"


# ── turn assembly ─────────────────────────────────────────────────────────────


def operator_turns_from_events(events: list[dict], *, now: datetime, window_hours: float = WINDOW_HOURS) -> list[dict]:
    """One row per operator.message event inside the window. Pure."""
    cutoff = now - timedelta(hours=window_hours)
    out: list[dict] = []
    for ev in events:
        if ev.get("event_type") != "operator.message":
            continue
        p = ev.get("payload") or {}
        ts = _parse_ts(p.get("ts") or ev.get("timestamp"))
        if ts is None or ts < cutoff or ts > now + timedelta(minutes=5):
            continue
        out.append({
            "ts": ts.isoformat(),
            "chat_id": str(p.get("chat_id") or ""),
            "message_id": str(p.get("message_id") or ""),
            "question": str(p.get("text") or ""),
            "reply_source": p.get("reply_source"),
            "desk_kind": p.get("desk_kind"),
            "pending_id": p.get("pending_id"),
            # Agent A's fields land here (reply_provenance: stores_read, went_outside,
            # model, sources_line_present). None until they do.
            "provenance": p.get("reply_provenance") if isinstance(p.get("reply_provenance"), dict) else None,
            # A reply body carried on the event itself, if the writer ever adds one.
            "reply": p.get("reply_text") or None,
            "event_id": ev.get("event_id"),
        })
    return out


def attach_replies(turns: list[dict], replies: dict[str, str]) -> list[dict]:
    """Join reply text by the question's message_id. Pure."""
    for t in turns:
        if not t.get("reply"):
            t["reply"] = replies.get(str(t.get("message_id") or "")) or None
    return turns


def _load_agent_replies_db(since: datetime) -> tuple[dict[str, str], Optional[str]]:
    """reply_to_message_id -> agent reply text, via a READ-ONLY session.

    operator_conversation_turns stores one row per (turn, resolved entity), so
    the same reply appears once per symbol it mentioned; the first row wins.
    Returns (replies, error). Never raises.
    """
    try:
        import psycopg2  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {}, f"psycopg2 unavailable: {type(exc).__name__}"
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
            connect_timeout=5,
        )
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute(
            """SELECT reply_to_message_id, text
                 FROM operator_conversation_turns
                WHERE role = 'agent' AND reply_to_message_id IS NOT NULL
                  AND occurred_at >= %s
                ORDER BY occurred_at ASC, id ASC""",
            (since,),
        )
        out: dict[str, str] = {}
        for rid, text in cur.fetchall():
            out.setdefault(str(rid), str(text or ""))
        return out, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ''}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_env_file(path: Path) -> None:
    """DB_* from the tree's .env into the environment (values never logged)."""
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            m = re.match(r"^(DB_HOST|DB_NAME|DB_USER|DB_PASSWORD|POSTGRES_PASSWORD)=(.*)$", line)
            if m and not os.environ.get(m.group(1)):
                os.environ[m.group(1)] = m.group(2).strip().strip("\"'")
    except OSError:
        pass


# ── the rules (pure) ──────────────────────────────────────────────────────────


def default_symbol_extractor() -> Callable[[str], list[str]]:
    """The desk's own extractor, so the monitor and the desk agree on what a symbol is."""
    try:
        from scripts.lib.cio_operator_desk_loop import _extract_symbols
        return _extract_symbols
    except Exception:
        return lambda text: re.findall(r"\b([A-Z]{2,5})\b", text or "")


def empty_claims(reply: str) -> list[dict]:
    """Sentences claiming cash/holdings/sector/weights are unavailable or empty. Pure."""
    out: list[dict] = []
    # Lines first, then sentences. Without the line split a "• Gaps
    # (DATA_UNAVAILABLE): book:topic" bullet fused with the next line's
    # "Sources: CIO snapshot (cash, ...)" and read as a claim that cash was
    # unavailable -- the monitor inventing the very defect it measures.
    for sentence in re.split(r"\n+|(?<=[.!?])\s+", reply or ""):
        if sentence.lstrip().startswith(("Sources:", "Went outside:")):
            continue  # the provenance footer names stores; it claims nothing about them
        if not _EMPTY_CLAIM.search(sentence):
            continue
        words = {w.lower().rstrip("s") for w in _DOMAIN_WORD.findall(sentence)}
        if not words:
            continue
        out.append({"domains": sorted(words), "sentence": sentence.strip()[:200]})
    return out


def _domain_available_in_snapshot(snapshot: dict, domain: str) -> Optional[bool]:
    d = (snapshot or {}).get("domains") or {}

    def _state(name: str) -> Optional[str]:
        v = d.get(name)
        if not isinstance(v, dict):
            return None
        return str(v.get("state") or v.get("quality_state") or "")

    if domain == "cash":
        v = d.get("cash_buying_power") if isinstance(d.get("cash_buying_power"), dict) else {}
        data = v.get("data") if isinstance(v.get("data"), dict) else v
        if data.get("total_cash") is not None:
            return True
        s = _state("cash_buying_power")
        return None if s is None else s in ("AVAILABLE", "PARTIAL")
    if domain == "holding":
        s = _state("holdings_detail")
        if s is not None:
            return s == "AVAILABLE"
        p = d.get("portfolio") if isinstance(d.get("portfolio"), dict) else {}
        return None if not p else bool(p.get("holdings_count"))
    if domain in ("sector", "weight"):
        s = _state("sectors")
        return None if s is None else s == "AVAILABLE"
    return None


def _domain_available_in_holdings(holdings: dict, domain: str) -> Optional[bool]:
    rows = (holdings or {}).get("holdings") or []
    if not isinstance(rows, list) or not rows:
        return None
    if domain == "cash":
        return any(str(r.get("symbol") or "").upper() == "CASH" and r.get("market_value") is not None for r in rows if isinstance(r, dict))
    return any(str(r.get("symbol") or "").upper() != "CASH" for r in rows if isinstance(r, dict))


def false_empty_claim(turn: dict, *, snapshot: Optional[dict] = None, holdings: Optional[dict] = None) -> Optional[dict]:
    """The reply called a house domain empty while the house had it. Pure.

    Evidence precedence -- provenance (Agent A's stores_read) when present, else
    a persisted snapshot from within 24h of the turn, else the store of record.
    The finding names which one decided it.
    """
    reply = turn.get("reply") or ""
    claims = empty_claims(reply)
    if not claims:
        return None
    prov = turn.get("provenance") or {}
    stores = [str(s) for s in (prov.get("stores_read") or [])] if isinstance(prov, dict) else []
    turn_ts = _parse_ts(turn.get("ts"))
    snap_at = _parse_ts((snapshot or {}).get("collected_at"))
    # "At that time" means collected BEFORE the turn and not more than a day
    # earlier. A snapshot collected after the reply proves nothing about what
    # the desk could have read when it answered.
    snap_at_the_time = bool(
        snapshot and snap_at and turn_ts
        and timedelta(0) <= (turn_ts - snap_at) <= timedelta(hours=SNAPSHOT_AT_THE_TIME_HOURS)
    )
    hold_at = _holdings_generated_at(holdings or {})
    for c in claims:
        for dom in c["domains"]:
            if stores:
                if any(_SNAPSHOT_STORE.search(s) for s in stores):
                    return {"rule": "provenance", "domain": dom, "sentence": c["sentence"],
                            "evidence": "reply_provenance.stores_read includes the CIO snapshot"}
                continue
            if snap_at_the_time:
                avail = _domain_available_in_snapshot(snapshot, dom)
                if avail:
                    return {"rule": "snapshot_health", "domain": dom, "sentence": c["sentence"],
                            "evidence": f"persisted CIO snapshot collected {snap_at.isoformat()} (before the turn) said AVAILABLE"}
                if avail is False:
                    continue
            if hold_at is not None and turn_ts is not None and hold_at > turn_ts:
                continue  # the store of record was rewritten after the turn; it cannot testify
            avail = _domain_available_in_holdings(holdings or {}, dom)
            if avail:
                when = hold_at.isoformat() if hold_at else "unparsed generated_at"
                return {"rule": "store_health", "domain": dom, "sentence": c["sentence"],
                        "evidence": f"holdings.json (store of record, generated {when}, before the turn) carried {dom}"}
    return None


def _holdings_generated_at(holdings: dict) -> Optional[datetime]:
    """holdings.json writes generated_at as '%Y-%m-%d %H:%M:%S ET'. Pure."""
    raw = str((holdings or {}).get("generated_at") or "").strip()
    if not raw:
        return None
    try:
        if raw.upper().endswith(" ET"):
            from zoneinfo import ZoneInfo
            naive = datetime.strptime(raw[:-3].strip(), "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=ZoneInfo("America/New_York"))
    except Exception:
        return None
    return _parse_ts(raw)


def no_sources_line(turn: dict) -> bool:
    reply = turn.get("reply") or ""
    return bool(reply.strip()) and "Sources:" not in reply


def went_outside_unstated(turn: dict) -> Optional[list]:
    prov = turn.get("provenance") or {}
    outside = prov.get("went_outside") if isinstance(prov, dict) else None
    if not outside:
        return None
    if "Went outside:" in (turn.get("reply") or ""):
        return None
    return list(outside)


def book_dump_for_named_symbol(turn: dict, extract: Callable[[str], list[str]]) -> Optional[list[str]]:
    reply = turn.get("reply") or ""
    if not _BOOK_DUMP.search(reply):
        return None
    try:
        named = list(extract(turn.get("question") or ""))
    except Exception:
        named = []
    return named or None


def model_unlabelled(turn: dict) -> Optional[dict]:
    """A model wrote prose and the reply never said so. Pure.

    provenance.model is the authority once Agent A's field lands; until then the
    event's reply_source (freeform_flash / deepseek_flash / gap_resolver:llm_curation)
    is the only evidence that a model wrote the prose, and the finding says so.
    """
    reply = turn.get("reply") or ""
    if not reply.strip() or _MODEL_LABEL.search(reply):
        return None
    prov = turn.get("provenance") or {}
    if isinstance(prov, dict) and prov.get("model"):
        return {"rule": "provenance", "model": str(prov["model"])}
    src = str(turn.get("reply_source") or "")
    if _FLASH_SOURCE.search(src):
        return {"rule": "reply_source", "model": src}
    return None


def pending_never_closed(pending_rows: list[dict], *, now: datetime, open_hours: float = PENDING_OPEN_HOURS) -> list[dict]:
    """Pendings whose latest row is still `open` after open_hours. Pure."""
    latest: dict[str, dict] = {}
    for r in pending_rows:
        pid = str(r.get("pending_id") or "")
        if pid:
            latest[pid] = r
    out: list[dict] = []
    cutoff = now - timedelta(hours=open_hours)
    for pid, r in latest.items():
        if str(r.get("status") or "open") != "open":
            continue
        ts = _parse_ts(r.get("ts"))
        if ts is None or ts > cutoff:
            continue
        out.append({"pending_id": pid, "question": str(r.get("operator_text") or "")[:60],
                    "age_hours": round((now - ts).total_seconds() / 3600, 1), "chat_id": r.get("chat_id")})
    return sorted(out, key=lambda x: x["pending_id"])


def research_landed_unsent(pending_rows: list[dict], gap_requests: list[dict], projection: dict, *,
                           now: datetime, grace_minutes: float = RESEARCH_LANDED_GRACE_MINUTES) -> list[dict]:
    """Open pendings whose Hermes research completed more than grace_minutes ago. Pure.

    The join is the one the desk uses: pending_id → (plan_id, research_id) in the
    gap-request ledger → the Hermes projection's request status and completion time.
    """
    latest: dict[str, dict] = {}
    for r in pending_rows:
        pid = str(r.get("pending_id") or "")
        if pid:
            latest[pid] = r
    open_ids = {pid for pid, r in latest.items() if str(r.get("status") or "open") == "open"}
    if not open_ids:
        return []
    by_rid = (projection or {}).get("by_research_id") or {}
    cutoff = now - timedelta(minutes=grace_minutes)
    out: dict[str, dict] = {}
    for ask in gap_requests:
        pid = str(ask.get("pending_id") or "")
        if pid not in open_ids or ask.get("kind") != "hermes_operator_forced":
            continue
        plan_id, rid_hint = str(ask.get("plan_id") or ""), str(ask.get("research_id") or "")
        for rid, meta in by_rid.items():
            if not isinstance(meta, dict) or not (rid == rid_hint or (plan_id and str(meta.get("plan_id")) == plan_id)):
                continue
            done = _parse_ts(meta.get("completed_ts"))
            if str(meta.get("status")) != "completed" or done is None or done > cutoff:
                continue
            row = latest[pid]
            out[pid] = {"pending_id": pid, "question": str(row.get("operator_text") or "")[:60],
                        "result_id": meta.get("latest_result_id"), "research_id": rid,
                        "landed_minutes_ago": round((now - done).total_seconds() / 60), "chat_id": row.get("chat_id")}
    return sorted(out.values(), key=lambda x: x["pending_id"])


def evaluate_turns(turns: list[dict], *, extract: Optional[Callable[[str], list[str]]] = None,
                   snapshot: Optional[dict] = None, holdings: Optional[dict] = None) -> dict[str, list[dict]]:
    """Run every per-turn rule. Pure given its inputs."""
    extract = extract or default_symbol_extractor()
    f: dict[str, list[dict]] = {r: [] for r in RULES}
    for t in turns:
        base = {"message_id": t.get("message_id"), "ts": t.get("ts"), "question": (t.get("question") or "")[:60],
                "reply_source": t.get("reply_source"), "desk_kind": t.get("desk_kind")}
        if not (t.get("reply") or "").strip():
            f["REPLY_TEXT_UNAVAILABLE"].append(base)
            # Text rules cannot run; provenance-only rules still can.
            outside = went_outside_unstated({**t, "reply": ""})
            if outside:
                f["WENT_OUTSIDE_UNSTATED"].append({**base, "went_outside": outside})
            continue
        if no_sources_line(t):
            f["NO_SOURCES_LINE"].append(base)
        outside = went_outside_unstated(t)
        if outside:
            f["WENT_OUTSIDE_UNSTATED"].append({**base, "went_outside": outside})
        fec = false_empty_claim(t, snapshot=snapshot, holdings=holdings)
        if fec:
            f["FALSE_EMPTY_CLAIM"].append({**base, **fec})
        named = book_dump_for_named_symbol(t, extract)
        if named:
            f["BOOK_DUMP_FOR_NAMED_SYMBOL"].append({**base, "symbols": named})
        mu = model_unlabelled(t)
        if mu:
            f["MODEL_UNLABELLED"].append({**base, **mu})
    return f


# ── collect ───────────────────────────────────────────────────────────────────


def _load_snapshot_for_rule(root: Path) -> Optional[dict]:
    """A persisted CIO snapshot, if one exists. Read-only; never rebuilds one."""
    for p in (
        # cio_portfolio.SNAPSHOT_PATH: data/portfolios/state/data_broker/cio_snapshot.json
        root / "portfolios" / "state" / "data_broker" / "cio_snapshot.json",
        root / "runtime" / "cio_snapshot.json",
        root.parent / "state" / "data_broker" / "cio_snapshot.json",
        DEV_TREE / "state" / "data_broker" / "cio_snapshot.json",
    ):
        try:
            if p.is_file():
                doc = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and doc.get("domains"):
                    return doc
        except Exception:
            continue
    return None


def collect(*, now: Optional[datetime] = None, root: Optional[Path] = None,
            events_path: Optional[Path] = None, pending_path: Optional[Path] = None,
            holdings_path: Optional[Path] = None, snapshot: Optional[dict] = None,
            replies: Optional[dict[str, str]] = None, extract: Optional[Callable[[str], list[str]]] = None,
            reply_loader: Optional[Callable[[datetime], tuple[dict[str, str], Optional[str]]]] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = root or data_root()
    events = _jsonl(events_path or (root / "cio" / "cio_events.jsonl"))
    pending = _jsonl(pending_path or (root / "cio" / "cio_operator_pending_replies.jsonl"))
    holdings: dict = {}
    hp = holdings_path or (root / "portfolios" / "state" / "holdings.json")
    try:
        if hp.is_file():
            holdings = json.loads(hp.read_text(encoding="utf-8"))
    except Exception:
        holdings = {}
    if snapshot is None:
        snapshot = _load_snapshot_for_rule(root)

    turns = operator_turns_from_events(events, now=now)
    reply_error: Optional[str] = None
    if replies is None:
        since = now - timedelta(hours=WINDOW_HOURS + 1)
        loader = reply_loader or _load_agent_replies_db
        if reply_loader is None:
            _load_env_file(DEV_TREE / ".env")
        replies, reply_error = loader(since)
    attach_replies(turns, replies)

    findings = evaluate_turns(turns, extract=extract, snapshot=snapshot, holdings=holdings)
    findings["PENDING_NEVER_CLOSED"] = pending_never_closed(pending, now=now)
    projection: dict = {}
    try:
        pp = root / "cio" / "hermes_research_projection.json"
        if pp.is_file():
            projection = json.loads(pp.read_text(encoding="utf-8"))
    except Exception:
        projection = {}
    findings["RESEARCH_LANDED_UNSENT"] = research_landed_unsent(
        pending, _jsonl(root / "cio" / "cio_operator_gap_requests.jsonl"), projection, now=now)
    return {
        "schema": SCHEMA,
        "ran_at": now.isoformat(),
        "window_hours": WINDOW_HOURS,
        "data_root": str(root),
        "turns": len(turns),
        "turns_with_reply": sum(1 for t in turns if (t.get("reply") or "").strip()),
        "turns_with_provenance": sum(1 for t in turns if t.get("provenance")),
        "reply_source_error": reply_error,
        "pending_rows": len(pending),
        "findings": findings,
        "finding_count": sum(len(v) for v in findings.values()),
        "turn_index": [{"message_id": t["message_id"], "ts": t["ts"], "question": t["question"][:60],
                        "reply_source": t["reply_source"], "desk_kind": t["desk_kind"],
                        "has_reply": bool((t.get("reply") or "").strip()), "has_provenance": bool(t.get("provenance"))}
                       for t in turns],
    }


# ── receipt / fingerprint / alert ─────────────────────────────────────────────


def _write_run_receipt(report: dict, *, receipt_path: Optional[Path] = None) -> None:
    """Prove this ran, every run. The alert state only changes on change."""
    path = receipt_path or (data_root() / "runtime" / RECEIPT_NAME)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def fingerprint(report: dict) -> dict[str, str]:
    fp: dict[str, str] = {}
    for rule, rows in (report.get("findings") or {}).items():
        for r in rows:
            key = r.get("pending_id") or r.get("message_id") or r.get("question")
            fp[f"{rule}:{key}"] = rule
    return fp


_WHAT_WILL_BE_DONE = {
    "NO_SOURCES_LINE": "the desk appends 'Sources:' to every answer; replay this turn with scripts/replay_operator_question.py",
    "WENT_OUTSIDE_UNSTATED": "a reply that left the Command Center must say 'Went outside:'; replay and fix the branch",
    "FALSE_EMPTY_CLAIM": "the freeform builder must read the house payload it called empty; replay with the litmus snapshot fixture",
    "BOOK_DUMP_FOR_NAMED_SYMBOL": "a named symbol gets ITS row (format_reentry_symbol_reply), never the book; replay with the desk fixture",
    "PENDING_NEVER_CLOSED": "try_fulfill_pending_replies must expire it at 2h; check the poller is running",
    "RESEARCH_LANDED_UNSENT": "Hermes finished this pending's research but the operator has no follow-up; check the CIO bot's fulfilment loop joins the result (hermes_result_for_pending) and is running",
    "MODEL_UNLABELLED": "model prose must be labelled 'model knowledge' or 'wording only'; check the Flash prompt and footer",
    "REPLY_TEXT_UNAVAILABLE": "the monitor could not read the reply (operator_conversation_turns); text rules did not run for this turn",
}


def format_alert(report: dict, previous: dict[str, str]) -> str:
    """Operator-facing: what happened, the question, the rule, what will be done."""
    f = report["findings"]
    fp = fingerprint(report)
    if not fp:
        return f"{SENTINEL} ✅ Operator answers: every reply in the last 24h named its sources, answered the symbol asked, and called nothing empty that the house had."
    lines = [f"{SENTINEL} 🚨 Operator answer quality: {report['finding_count']} finding(s) in the last 24h", ""]
    for rule in RULES:
        rows = f.get(rule) or []
        for r in rows[:6]:
            q = (r.get("question") or "")[:60]
            detail = ""
            if rule == "FALSE_EMPTY_CLAIM":
                detail = f" — called {r.get('domain')} empty; decided by {r.get('rule')} ({r.get('evidence')})"
            elif rule == "BOOK_DUMP_FOR_NAMED_SYMBOL":
                detail = f" — asked about {', '.join(r.get('symbols') or [])}, got the book"
            elif rule == "MODEL_UNLABELLED":
                detail = f" — {r.get('model')} wrote prose (evidence: {r.get('rule')})"
            elif rule == "WENT_OUTSIDE_UNSTATED":
                detail = f" — went outside to {', '.join(map(str, r.get('went_outside') or []))}"
            elif rule == "PENDING_NEVER_CLOSED":
                detail = f" — {r.get('pending_id')} open {r.get('age_hours')}h"
            elif rule == "RESEARCH_LANDED_UNSENT":
                detail = (f" — {r.get('pending_id')}: Hermes result {r.get('result_id')} landed "
                          f"{r.get('landed_minutes_ago')} min ago, not delivered")
            lines.append(f"• [{rule}] \"{q}\"{detail}")
        if len(rows) > 6:
            lines.append(f"  … and {len(rows) - 6} more {rule}")
    lines.append("")
    lines.append("What will be done:")
    for rule in RULES:
        if f.get(rule):
            lines.append(f"• {rule}: {_WHAT_WILL_BE_DONE[rule]}")
    newly = [k for k in fp if k not in previous]
    if newly:
        lines += ["", f"NEW since the last run: {len(newly)}"]
    cleared = [k for k in previous if k not in fp]
    if cleared:
        lines += ["", f"Cleared: {len(cleared)}"]
    lines += ["", f"Receipt: data/runtime/{RECEIPT_NAME} · scripts/check_operator_answer_quality.py"]
    return "\n".join(lines)


def _alert(report: dict) -> None:
    """Notify only when the finding-set changes. Never raises."""
    fp = fingerprint(report)
    previous: dict = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError):
        pass
    if fp == previous:
        print("\n  alert: suppressed — unchanged since the last run.")
        return

    body = format_alert(report, previous)
    try:
        from telegram_alert import send_telegram

        ok = send_telegram(body, message_class="operator_alert")
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fp}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}).", file=sys.stderr)


def print_report(report: dict) -> None:
    f = report["findings"]
    print("Operator answer quality — what did the operator actually get back?")
    print("=" * 74)
    print(f"  data_root={report['data_root']}")
    print(f"  turns={report['turns']}  with_reply={report['turns_with_reply']}  "
          f"with_provenance={report['turns_with_provenance']}  pending_rows={report['pending_rows']}")
    if report.get("reply_source_error"):
        print(f"  reply text source: {report['reply_source_error']}")
    for t in report.get("turn_index") or []:
        print(f"    {t['ts'][:16]} #{t['message_id']} [{t['desk_kind']}/{t['reply_source']}] "
              f"reply={'yes' if t['has_reply'] else 'NO'} prov={'yes' if t['has_provenance'] else 'no'}  \"{t['question']}\"")
    print("-" * 74)
    for rule in RULES:
        for r in f.get(rule) or []:
            extra = ""
            if rule == "FALSE_EMPTY_CLAIM":
                extra = f" domain={r.get('domain')} decided_by={r.get('rule')} :: {r.get('sentence')}"
            elif rule == "BOOK_DUMP_FOR_NAMED_SYMBOL":
                extra = f" symbols={r.get('symbols')}"
            elif rule == "MODEL_UNLABELLED":
                extra = f" model={r.get('model')} evidence={r.get('rule')}"
            elif rule == "WENT_OUTSIDE_UNSTATED":
                extra = f" went_outside={r.get('went_outside')}"
            elif rule == "PENDING_NEVER_CLOSED":
                extra = f" {r.get('pending_id')} open {r.get('age_hours')}h"
            print(f"  [{rule:<26}] \"{r.get('question')}\"{extra}")
    if not report["finding_count"]:
        print("  nothing to report.")
    print("-" * 74)
    print("  " + "  ".join(f"{rule}={len(f.get(rule) or [])}" for rule in RULES))
    print(f"  findings={report['finding_count']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the finding-set changes")
    ap.add_argument("--dry-run", action="store_true", help="print the report and the alert body; send nothing, record no state")
    ap.add_argument("--receipt", default=None, help="write the run receipt here instead of data/runtime/")
    args = ap.parse_args()

    try:
        report = collect()
    except Exception as exc:  # noqa: BLE001 -- cannot-run is exit 2, never a green 0
        print(f"ERROR: could not collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)

    # A dry run is a manual look, not a scheduled run: it writes the receipt only
    # where --receipt says, so it never advances the lane's output signal on the
    # served tree and never writes host data/ from a worktree.
    if args.receipt or not args.dry_run:
        _write_run_receipt(report, receipt_path=Path(args.receipt) if args.receipt else None)
    if args.dry_run:
        print("\n  dry-run: alert body that WOULD be sent (nothing sent, no state recorded):")
        print("  " + format_alert(report, {}).replace("\n", "\n  "))
    elif args.alert:
        _alert(report)
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
