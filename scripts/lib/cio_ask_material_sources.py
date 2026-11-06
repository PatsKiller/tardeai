"""Read-only material feeds shared by legacy and native Ask lifecycle callers."""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_query(sql, params):
    """Same bounded read-only DB connection as the established material reader.

    Kept independent of comms-editor's broad UI/renderer module graph. No provider
    or broker is available through this boundary; only SELECT from this module.
    """
    import psycopg2
    import psycopg2.extras

    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("MATERIAL_READ_ONLY")
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
        connect_timeout=2,
        options="-c statement_timeout=2000",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
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
            return out
        with self.path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                g = str(r.get("subject_guid") or "")
                at = _parse(r.get("filed_at") or r.get("observed_at"))
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
