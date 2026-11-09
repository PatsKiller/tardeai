"""Read-only material feeds shared by legacy and native Ask lifecycle callers."""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Stable, credential-free classes for a failed read-only DB source (LQ-20261107-1380). A receipt that says only
#: ``OperationalError`` cannot tell "the role rejected this process's password" (an operator action: re-render the
#: secret or restore the role) from "the statement timed out" (retry) or "the server is down". On 2026-11-08 a role
#: password was changed at 22:29:59 ET and the rendered secret did not agree with it until 22:47:06; every DB-backed
#: lane failed for those 17 minutes with the identical opaque code, and the breaker opened on it.
DB_AUTH_FAILED = "db_auth_failed"
DB_SLOTS_EXHAUSTED = "db_slots_exhausted"
DB_QUERY_TIMEOUT = "db_query_timeout"
DB_CONNECT_TIMEOUT = "db_connect_timeout"
DB_UNREACHABLE = "db_unreachable"
DB_ERROR = "db_error"
DB_FAILURE_REASONS = (
    DB_AUTH_FAILED, DB_SLOTS_EXHAUSTED, DB_QUERY_TIMEOUT, DB_CONNECT_TIMEOUT, DB_UNREACHABLE, DB_ERROR,
)


class SourceReadError(RuntimeError):
    """A bounded read of one source failed. ``reason`` is one of ``DB_FAILURE_REASONS`` (never the driver text,
    which can carry a host/user); ``cause`` keeps the original exception for a caller that wants its type."""

    def __init__(self, reason: str, *, cause: Optional[BaseException] = None):
        super().__init__(reason)
        self.reason = reason
        self.cause = cause


def _read_failure_reason(exc: BaseException) -> str:
    """Classify a psycopg2 connect/execute failure. SQLSTATE first (deterministic), then the driver's wording."""
    code = str(getattr(exc, "pgcode", None) or getattr(exc, "sqlstate", None) or "")
    msg = str(exc).lower()
    if code in ("28P01", "28000") or "password authentication failed" in msg or "no password supplied" in msg:
        return DB_AUTH_FAILED
    if code == "53300" or "too many connections" in msg or "connection slot" in msg:
        return DB_SLOTS_EXHAUSTED
    if code == "57014" or "statement timeout" in msg or "canceling statement" in msg:
        return DB_QUERY_TIMEOUT
    if "timeout expired" in msg and "statement" not in msg:
        return DB_CONNECT_TIMEOUT
    if code.startswith("08") or any(
        t in msg for t in ("could not connect", "connection refused", "server closed the connection",
                           "is the server running", "no route to host", "network is unreachable")
    ):
        return DB_UNREACHABLE
    return DB_ERROR


def _read_query(sql, params):
    """Same bounded read-only DB connection as the established material reader.

    Kept independent of comms-editor's broad UI/renderer module graph. No provider
    or broker is available through this boundary; only SELECT from this module.
    A driver failure is re-raised as :class:`SourceReadError` so the lane receipt names the cause
    (LQ-20261107-1380); a non-SELECT is still a programming error, not a source failure.
    """
    import psycopg2
    import psycopg2.extras

    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("MATERIAL_READ_ONLY")
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
            connect_timeout=2,
            options="-c statement_timeout=2000",
        )
    except psycopg2.Error as exc:
        raise SourceReadError(_read_failure_reason(exc), cause=exc) from exc
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as exc:
        raise SourceReadError(_read_failure_reason(exc), cause=exc) from exc
    finally:
        conn.close()


class EventSource(Protocol):
    name: str

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]: ...


def _parse(ts: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class SecFilingEventsFile:
    name = "sec_filing_events"

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else REPO_ROOT / "data" / "cio" / "sec_filing_events.jsonl"

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.path.exists():
            # A missing feed file is a broken producer, not "no filings": raising lets the caller record it in
            # source_errors (an empty-but-present file still returns [] below). LQ-20261107-183.
            raise FileNotFoundError(f"sec_filing_events input missing: {self.path.name}")
        with self.path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                g = str(r.get("subject_guid") or "")
                # ``filed_at`` is a bare date ("2026-11-06"), so reading it first stamped every filing at midnight
                # of its filing day: a cursor could not pass that day (the same filing was re-read on every poll) and
                # a filing the producer indexed late was unreachable. Track when it arrived, fall back to the date.
                at = _parse(r.get("observed_at") or r.get("filed_at"))
                if g not in guids or not at or at < since:
                    continue
                out.append(
                    {
                        "event_id": str(r.get("event_guid") or r.get("accession")),
                        "security_guid": g,
                        "symbol": r.get("symbol"),
                        "kind": f"sec_filing:{r.get('form')}",
                        "observed_at": at.isoformat(),
                        "summary": f"{r.get('symbol')} filed {r.get('form')}"
                        + (f" ({r.get('catalyst_type')})" if r.get("catalyst_type") else "")
                        + (f" — severity {r.get('severity')}" if r.get("severity") else ""),
                        "url": r.get("sec_url"),
                        "source": self.name,
                    }
                )
        return out


class MaterialChangesTable:
    name = "material_changes"
    SQL = (
        "SELECT change_guid::text AS change_guid, subject_guid::text AS subject_guid, symbol, kind, magnitude, "
        "observed_at FROM material_changes WHERE subject_guid = ANY(%s::uuid[]) AND observed_at > %s "
        "ORDER BY observed_at ASC LIMIT 200"
    )

    def __init__(self, db_query: Optional[Callable[..., list[dict]]] = None):
        self.db_query = db_query

    def fetch(self, guids: set[str], since: datetime) -> list[dict[str, Any]]:
        q = self.db_query
        if q is None:
            q = _read_query
        rows = q(self.SQL, (sorted(guids), since)) or []
        out = []
        for r in rows:
            at = r.get("observed_at")
            out.append(
                {
                    "event_id": str(r.get("change_guid")),
                    "security_guid": str(r.get("subject_guid")),
                    "symbol": r.get("symbol"),
                    "kind": f"material_change:{r.get('kind')}",
                    "observed_at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                    "summary": f"{r.get('symbol')} material change: {r.get('kind')}"
                    + (f" (magnitude {r.get('magnitude')})" if r.get("magnitude") is not None else ""),
                    "source": self.name,
                }
            )
        return out


def default_sources(cfg: dict) -> list[EventSource]:
    names = (cfg.get("reanswer") or {}).get("sources") or ["sec_filing_events", "material_changes"]
    out: list[EventSource] = []
    if "sec_filing_events" in names:
        out.append(SecFilingEventsFile())
    if "material_changes" in names:
        out.append(MaterialChangesTable())
    return out
