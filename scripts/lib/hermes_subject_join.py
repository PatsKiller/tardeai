"""Join CIO desk Hermes products for one subject before claiming Hub empty.

STAGE 3 shared helper — CIO desk and Maria skill both import this.
Hub ``hermes_research_intelligence`` / symbol-journey alone is NEVER enough to
say "0 findings" or "queued".

Join order (mandatory):
  1. cio_operator_gap_requests / pending ledger (opr_*), plus the Postgres
     ``data_gap_registry`` rows the desk files for each opr_ when a
     ``db_query`` is supplied (optional -- JSONL stays a source; no driver
     needed)
  2. hermes research projection / requests (res_*)
  3. hermes_research_results.jsonl completed rows
  4. Hub intelligence only after the three above (caller-supplied probe)

Vocabulary — do not collapse these:
  ANALYZED_THIN   desk result completed with INSUFFICIENT_DATA / thin packet
  QUEUED          opr_ and/or res_ in flight; not yet a completed result
  HUB_PROMOTED_0  Hub has no promoted row (≠ desk empty; ≠ analyzed-thin)
  DESK_COMPLETED  completed desk result with usable answers/findings
  NONE            nothing on desk or Hub for this subject

Never report Hub backlog ``total: 500`` (api LIMIT page) as FIFO queue depth.

Keying (M5 2026-09-23): rows are matched on ``subject_guid`` when both the
subject and the row carry one (the identity registry resolves the GUID when the
caller passes only a symbol); a single-subject row whose GUID differs is a
different security even when the ticker string matches. Legacy rows without a
GUID fall back to the symbol.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker writes.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "HermesSubjectJoin@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

STATUS_ANALYZED_THIN = "ANALYZED_THIN"
STATUS_QUEUED = "QUEUED"
STATUS_HUB_PROMOTED_0 = "HUB_PROMOTED_0"
STATUS_DESK_COMPLETED = "DESK_COMPLETED"
STATUS_NONE = "NONE"

_INSUFFICIENT_RE = re.compile(
    r"INSUFFICIENT_DATA|insufficient\s+data|analyzed[\s_-]?thin|"
    r"not\s+enough\s+(?:data|evidence)",
    re.I,
)
_ZERO_FINDINGS_LIE = re.compile(
    r"(?:0|zero)\s+(?:recent\s+)?(?:hermes\s+)?findings|"
    r"queued\s+(?:not|but\s+not)\s+analyzed|"
    r"500\s+(?:deep|backlog)|backlog\s+(?:of\s+)?500|"
    r"no\s+hermes\s+(?:research|findings)",
    re.I,
)


def _repo_root() -> Path:
    env = os.environ.get("TRADEAI_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _cio_dir(root: Optional[Path] = None) -> Path:
    env = os.environ.get("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    base = Path(root) if root is not None else _repo_root()
    cwd = Path("data/cio")
    if cwd.is_dir():
        return cwd.resolve()
    return (base / "data" / "cio").resolve()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


_OPR_ID = re.compile(r"\bopr_[0-9a-f]{6,}\b")
#: data_gap_registry statuses that mean the desk's opr_ request is still in flight.
_DB_OPEN_STATUSES = frozenset({"open", "dispatched", "in_progress", "queued", "retrying"})
_DEFAULT_DB_GAP_LIMIT = 20


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(str(os.environ.get(name) or "").strip() or default))
    except ValueError:
        return default


def _row_guids(row: dict[str, Any]) -> set[str]:
    """Every subject_guid a ledger row carries: top level, its request, its gaps."""
    out: set[str] = set()
    for src in (row, row.get("request"), row.get("intent")):
        if isinstance(src, dict) and src.get("subject_guid"):
            out.add(str(src["subject_guid"]).lower())
    for g in row.get("gaps") or []:
        if isinstance(g, dict) and g.get("subject_guid"):
            out.add(str(g["subject_guid"]).lower())
    return out


def _row_symbols(row: dict[str, Any]) -> set[str]:
    syms = {str(row.get("symbol") or "").upper()} - {""}
    for s in row.get("symbols") or []:
        if s:
            syms.add(str(s).upper())
    return syms


def _subject_match(row: dict[str, Any], symbol: str, guid: Optional[str]) -> bool:
    """GUID-keyed match with a symbol fallback for legacy (GUID-less) rows.

    A row naming ONE subject whose GUID differs from ours is another security
    that happens to share the ticker string, so it does not match. A
    multi-subject row may carry only some GUIDs, so there the symbol still counts.
    """
    g = str(guid or "").lower()
    guids = _row_guids(row)
    if g and g in guids:
        return True
    if not _sym_match(row, symbol):
        return False
    if g and guids and len(_row_symbols(row)) <= 1:
        return False
    return True


def resolve_subject_guid(symbol: str) -> Optional[str]:
    """Registry subject_guid for ``symbol``, or None -- never raises.

    Disabled with ``TRADEAI_HERMES_JOIN_RESOLVE_GUID=0``.
    """
    if str(os.environ.get("TRADEAI_HERMES_JOIN_RESOLVE_GUID", "1")).strip() == "0":
        return None
    try:
        try:
            from scripts.lib import cio_hermes_research as hr  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            from lib import cio_hermes_research as hr  # type: ignore  # noqa: PLC0415
        ident = hr._subject_identity(symbol) or {}
    except Exception:  # noqa: BLE001
        return None
    return str(ident.get("subject_guid") or "") or None


def house_db_query() -> Optional[Callable[..., list[dict]]]:
    """The read-only house DB reader for the join, or None when disabled.

    ``TRADEAI_HERMES_JOIN_DB=0`` turns the Postgres legs off (tests set it so a
    unit run never reads live gap rows or Hub counts). Import failure -> None.
    """
    if str(os.environ.get("TRADEAI_HERMES_JOIN_DB", "1")).strip() == "0":
        return None
    try:
        try:
            from scripts.lib.comms_editor import default_db_query  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            from lib.comms_editor import default_db_query  # type: ignore  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    return default_db_query


_HUB_PROMOTED_SQL = (
    "SELECT count(*) AS n FROM hermes_research_intelligence "
    "WHERE upper(symbol) = %s AND status = 'promoted'"
)


def hub_promoted_count_finder(db_query: Callable[..., list[dict]]) -> Callable[[str], int]:
    """``hub_finder`` over the Hub table: PROMOTED rows for one symbol.

    Per-ticker and exact -- never the api_v2 page total (500 is a LIMIT).
    Raises on DB failure; ``join_subject_hermes`` then leaves ``hub_count`` None.
    """

    def _finder(symbol: str) -> int:
        rows = db_query(_HUB_PROMOTED_SQL, (str(symbol or "").upper(),))
        return int((rows[0] or {}).get("n") or 0) if rows else 0

    return _finder


_DB_GAP_SQL = (
    "SELECT id, symbol, gap_type, gap_detail, status, detected_at, resolution_data "
    "FROM data_gap_registry WHERE detected_by = 'cio_operator_desk' AND upper(symbol) = %s "
    "ORDER BY detected_at DESC LIMIT %s"
)


def _db_gap_requests(sym: str, db_query: Callable[..., list[dict]]) -> list[dict[str, Any]]:
    """The desk's opr_ gap requests as filed in Postgres (data_gap_registry)."""
    limit = _env_int("TRADEAI_HERMES_JOIN_DB_GAP_LIMIT", _DEFAULT_DB_GAP_LIMIT)
    out: list[dict[str, Any]] = []
    for r in db_query(_DB_GAP_SQL, (sym, limit)) or []:
        m = _OPR_ID.search(str(r.get("gap_detail") or ""))
        if not m:
            continue
        res = r.get("resolution_data") if isinstance(r.get("resolution_data"), dict) else {}
        out.append({
            "pending_id": m.group(0),
            "gap_registry_id": r.get("id"),
            "gap_type": r.get("gap_type"),
            "status": str(r.get("status") or "").lower(),
            "detected_at": str(r.get("detected_at") or ""),
            "job_id": res.get("job_id"),
            "result_ref": res.get("result_id"),
        })
    return out


def _sym_match(row: dict[str, Any], symbol: str) -> bool:
    up = symbol.upper()
    if str(row.get("symbol") or "").upper() == up:
        return True
    syms = row.get("symbols") or []
    if isinstance(syms, list) and any(str(s).upper() == up for s in syms):
        return True
    return False


def _is_thin_result(result: dict[str, Any]) -> bool:
    """True when a completed desk result is analyzed-thin / INSUFFICIENT_DATA."""
    for key in ("thesis_stance", "summary", "status_detail", "coverage_state"):
        if _INSUFFICIENT_RE.search(str(result.get(key) or "")):
            return True
    for f in result.get("findings") or []:
        if isinstance(f, dict) and _INSUFFICIENT_RE.search(str(f.get("text") or "")):
            return True
        if isinstance(f, str) and _INSUFFICIENT_RE.search(f):
            return True
    for a in result.get("answers") or []:
        if isinstance(a, dict):
            blob = " ".join(str(a.get(k) or "") for k in ("summary", "detail", "status"))
            if _INSUFFICIENT_RE.search(blob):
                return True
    answers = [
        a for a in (result.get("answers") or [])
        if isinstance(a, dict) and a.get("summary")
    ]
    findings = [
        f for f in (result.get("findings") or [])
        if (isinstance(f, dict) and f.get("text")) or isinstance(f, str)
    ]
    if not answers and not findings and not (result.get("summary") or "").strip():
        return True
    return False


@dataclass
class HermesJoinResult:
    """One subject's Hermes timeline across desk stores (and optional Hub)."""

    schema: str = SCHEMA
    authority: str = AUTHORITY
    symbol: str = ""
    subject_guid: Optional[str] = None
    status: str = STATUS_NONE
    pending_ids: list[str] = field(default_factory=list)
    research_ids: list[str] = field(default_factory=list)
    result_ids: list[str] = field(default_factory=list)
    latest_result: Optional[dict[str, Any]] = None
    gap_requests: list[dict[str, Any]] = field(default_factory=list)
    projection_metas: list[dict[str, Any]] = field(default_factory=list)
    hub_count: Optional[int] = None
    honesty_line: str = ""
    sources: list[str] = field(default_factory=list)
    db_gap_requests: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def citations(self) -> list[dict[str, str]]:
        """Citable evidence ids from this join, newest desk product first.

        Each entry is ``{"id", "label"}``; a reply renders ``[n]`` only where the
        id itself appears in its text (``reply_provenance``), so nothing here can
        become a citation the reply does not actually show.
        """
        out: list[dict[str, str]] = []
        for rid in reversed(self.result_ids):
            out.append({"id": rid, "label": f"hermes_research_results · {rid}"})
        for rid in self.research_ids:
            out.append({"id": rid, "label": f"hermes research · {rid}"})
        for pid in self.pending_ids:
            out.append({"id": pid, "label": f"operator gap request · {pid}"})
        return out

    @property
    def has_desk_completion(self) -> bool:
        return self.status in (STATUS_DESK_COMPLETED, STATUS_ANALYZED_THIN)


def honesty_line_for(
    status: str,
    *,
    symbol: str,
    result_id: Optional[str] = None,
    research_ids: Optional[list[str]] = None,
    pending_ids: Optional[list[str]] = None,
    hub_count: Optional[int] = None,
) -> str:
    """Operator-facing one-liner; never collapses analyzed-thin into Hub 0."""
    sym = (symbol or "?").upper()
    if status == STATUS_DESK_COMPLETED:
        rid = result_id or (research_ids or ["res_?"])[0]
        return f"Hermes desk research on {sym} completed ({rid})."
    if status == STATUS_ANALYZED_THIN:
        rid = result_id or (research_ids or ["res_?"])[0]
        return (
            f"Hermes desk research on {sym} completed as analyzed-thin / "
            f"INSUFFICIENT_DATA ({rid}) — not the same as Hub promoted 0."
        )
    if status == STATUS_QUEUED:
        bits = []
        if pending_ids:
            bits.append("pending " + ", ".join(pending_ids[:3]))
        if research_ids:
            bits.append("research " + ", ".join(research_ids[:3]))
        detail = "; ".join(bits) or "in flight"
        return f"Hermes desk research on {sym} is queued ({detail})."
    if status == STATUS_HUB_PROMOTED_0:
        return (
            f"Hub hermes_research_intelligence has 0 promoted rows for {sym}; "
            f"desk opr_/res_/results were also empty — not a 500-deep backlog claim."
        )
    if hub_count is not None and hub_count == 0:
        return (
            f"No desk Hermes (opr_/res_/results) for {sym}; Hub promoted count is 0."
        )
    return f"No desk Hermes join for {sym} yet."


def claim_contradicts_join(claim_text: str, join: HermesJoinResult) -> bool:
    """True when prose claims '0 findings' beside a desk completion."""
    if not join.has_desk_completion:
        return False
    return bool(_ZERO_FINDINGS_LIE.search(claim_text or ""))


def join_subject_hermes(
    symbol: str,
    *,
    root: Optional[Path] = None,
    subject_guid: Optional[str] = None,
    hub_finder: Optional[Callable[[str], int]] = None,
    cio_dir: Optional[Path] = None,
    db_query: Optional[Callable[..., list[dict]]] = None,
) -> HermesJoinResult:
    """Join desk Hermes for ``symbol``; optionally consult Hub last.

    ``hub_finder(symbol) -> int`` returns Hub promoted row count when the caller
    has a Hub probe (``hub_promoted_count_finder(db_query)`` is the house one).
    Absence of a finder leaves ``hub_count`` None (unknown), never silently 0.

    ``subject_guid`` keys the join; when omitted it is resolved from the
    identity registry. ``db_query`` (optional) adds the desk's opr_ rows from
    Postgres ``data_gap_registry``; any DB failure degrades to the JSONL stores.
    """
    sym = str(symbol or "").strip().upper()
    guid = subject_guid or (resolve_subject_guid(sym) if sym else None)
    out = HermesJoinResult(symbol=sym, subject_guid=guid)
    if not sym:
        out.honesty_line = honesty_line_for(STATUS_NONE, symbol="?")
        return out

    d = Path(cio_dir) if cio_dir is not None else _cio_dir(root)
    gap_path = d / "cio_operator_gap_requests.jsonl"
    pending_path = d / "cio_operator_pending_replies.jsonl"
    result_path = d / "hermes_research_results.jsonl"

    # 1) gap requests / pending (opr_*)
    for row in _read_jsonl(gap_path):
        if not _subject_match(row, sym, guid):
            continue
        out.gap_requests.append(row)
        pid = str(row.get("pending_id") or "")
        if pid.startswith("opr_") and pid not in out.pending_ids:
            out.pending_ids.append(pid)
        rid = str(row.get("research_id") or "")
        if rid.startswith("res_") and rid not in out.research_ids:
            out.research_ids.append(rid)
        out.sources.append(f"cio_operator_gap_requests · {pid or rid or 'row'}")

    for row in _read_jsonl(pending_path):
        if str(row.get("status") or "") not in ("open", "", "queued"):
            continue
        intent = row.get("intent") if isinstance(row.get("intent"), dict) else {}
        symbols = list(intent.get("symbols") or [])
        if sym not in {str(s).upper() for s in symbols} and not _subject_match(row, sym, guid):
            continue
        pid = str(row.get("pending_id") or "")
        if pid.startswith("opr_") and pid not in out.pending_ids:
            out.pending_ids.append(pid)
            out.sources.append(f"cio_operator_pending_replies · {pid}")

    # 1b) the same opr_ requests as filed in Postgres (optional)
    if db_query is not None:
        try:
            db_rows = _db_gap_requests(sym, db_query)
        except Exception:  # noqa: BLE001 -- no driver / DB down: JSONL stands alone
            db_rows = []
        for r in db_rows:
            out.db_gap_requests.append(r)
            pid = r["pending_id"]
            if r["status"] in _DB_OPEN_STATUSES and pid not in out.pending_ids:
                out.pending_ids.append(pid)
            out.sources.append(f"data_gap_registry · {pid} ({r['status'] or '?'})")

    # 2) projection (res_*)
    try:
        try:
            from scripts.lib import cio_hermes_research as hr  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            from lib import cio_hermes_research as hr  # type: ignore  # noqa: PLC0415
        proj = hr._load_projection() or {}
        by_rid = proj.get("by_research_id") or {}
        for rid, meta in by_rid.items():
            if not isinstance(meta, dict):
                continue
            req = meta.get("request") if isinstance(meta.get("request"), dict) else {}
            if not _subject_match(meta, sym, guid) and not _subject_match(req, sym, guid):
                continue
            out.projection_metas.append(dict(meta, research_id=rid))
            rid_s = str(rid)
            if rid_s.startswith("res_") and rid_s not in out.research_ids:
                out.research_ids.append(rid_s)
            out.sources.append(f"hermes_research_projection · {rid_s}")
    except Exception:  # noqa: BLE001
        pass

    # 3) results jsonl (newest last)
    results = [r for r in _read_jsonl(result_path) if _subject_match(r, sym, guid)]
    completed = [
        r for r in results
        if str(r.get("status") or "").lower() in ("completed", "complete", "")
        or str(r.get("event") or "") == "HERMES_RESEARCH_COMPLETED"
        or r.get("result_id")
    ]
    if completed:
        latest = completed[-1]
        out.latest_result = latest
        rr = str(latest.get("result_id") or "")
        if rr and rr not in out.result_ids:
            out.result_ids.append(rr)
        rid = str(latest.get("research_id") or "")
        if rid.startswith("res_") and rid not in out.research_ids:
            out.research_ids.append(rid)
        out.sources.append(f"hermes_research_results · {rr or rid}")
        if _is_thin_result(latest):
            out.status = STATUS_ANALYZED_THIN
        else:
            out.status = STATUS_DESK_COMPLETED
    elif out.pending_ids or any(
        str(m.get("status") or "").lower() in ("queued", "in_flight", "claimed", "running")
        for m in out.projection_metas
    ) or out.research_ids:
        if out.status == STATUS_NONE:
            out.status = STATUS_QUEUED

    # 4) Hub last
    if hub_finder is not None:
        try:
            out.hub_count = int(hub_finder(sym))
        except Exception:  # noqa: BLE001
            out.hub_count = None
        if out.status == STATUS_NONE and out.hub_count == 0:
            out.status = STATUS_HUB_PROMOTED_0

    if out.status == STATUS_NONE and (out.pending_ids or out.research_ids):
        out.status = STATUS_QUEUED

    out.honesty_line = honesty_line_for(
        out.status,
        symbol=sym,
        result_id=(out.result_ids[-1] if out.result_ids else None),
        research_ids=out.research_ids,
        pending_ids=out.pending_ids,
        hub_count=out.hub_count,
    )
    return out


__all__ = [
    "AUTHORITY",
    "SCHEMA",
    "STATUS_ANALYZED_THIN",
    "STATUS_DESK_COMPLETED",
    "STATUS_HUB_PROMOTED_0",
    "STATUS_NONE",
    "STATUS_QUEUED",
    "HermesJoinResult",
    "claim_contradicts_join",
    "honesty_line_for",
    "house_db_query",
    "hub_promoted_count_finder",
    "join_subject_hermes",
    "resolve_subject_guid",
]
