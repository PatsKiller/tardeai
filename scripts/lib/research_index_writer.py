"""research_index_writer.py — the deterministic + citation index (Wave 2 item 8; 03 §3 steps 1 and 5).

Writes ``intelligence.research_index`` rows for every accepted research delta:

* one row per structured question class the delta answered (thesis / catalysts / invalidation /
  bear_case), ``answer_ref`` = the delta id, ``answer_store`` = ``research_thesis_deltas``;
* one row per cited URL per day: ``question_class = "citation"``, ``horizon = <canonical_url_sha16>``,
  ``answer_ref = <canonical url>`` — the per-URL/day index that stops the same page being re-read
  (the AUUD 180-pages-in-72-h finding). Only the canonical URL and the extraction reference are stored;
  never page bodies.

Reads: ``latest(subject_guid, question_class, horizon)`` and ``cited_urls(subject_guid, since_hours)``
feed the retrieval ladder. Every call is fail-soft: no DSN, no schema, or FORCE RLS without the tenant
setting → ``{"pg": "absent"|"error"}`` and the caller continues. Kill switch ``TRADEAI_RESEARCH_INDEX=0``.
Authority: READ_ONLY_ADVISORY (a projection; the canonical stores keep their writers).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TENANT = "tradeai:tenant:primary"
STORE = "research_thesis_deltas"
QUESTION_CLASSES = ("thesis", "catalysts", "invalidation", "bear_case")
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref$|ref_|igshid|_hs)", re.I)


def enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("TRADEAI_RESEARCH_INDEX", "1")).lower() not in ("0", "false", "off")


def canonical_url(url: str) -> str:
    """Lower-case host, drop fragment / tracking params / default ports / trailing slash."""
    try:
        s = urlsplit(str(url).strip())
    except ValueError:
        return str(url).strip()
    if not s.scheme or not s.netloc:
        return str(url).strip()
    host = s.netloc.lower()
    for port in (":80", ":443"):
        if host.endswith(port):
            host = host[: -len(port)]
    if host.startswith("www."):
        host = host[4:]
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=False) if not _TRACKING.match(k)]
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower() if s.scheme.lower() != "http" else "https", host, path, urlencode(sorted(q)), ""))


def url_key(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def _conn(env: dict):
    try:
        import db_adapter  # type: ignore
        c = db_adapter._get_conn()
        with c.cursor() as cur:
            cur.execute("SET app.tenant_id = %s", (TENANT,))
        return c
    except Exception:  # noqa: BLE001
        return None


def _urls_from(delta: dict) -> list[str]:
    urls: list[str] = []
    for key in ("source_refs", "sources", "citations", "evidence", "evidence_json"):
        v = delta.get(key)
        items = v if isinstance(v, list) else ([v] if v else [])
        for it in items:
            if isinstance(it, str) and it.startswith(("http://", "https://")):
                urls.append(it)
            elif isinstance(it, dict):
                u = it.get("source_url_canonical") or it.get("url") or it.get("source_url") or it.get("href")
                if isinstance(u, str) and u.startswith(("http://", "https://")):
                    urls.append(u)
    return sorted({canonical_url(u) for u in urls})


def rows_for(delta: dict, *, subject_guid: str, answered_at: _dt.datetime | None = None,
             next_due_hours: float | None = 168.0) -> list[dict]:
    """Pure: the index rows one accepted delta implies (no DB). Empty when the subject is unresolved."""
    if not subject_guid:
        return []
    now = answered_at or _dt.datetime.now(_dt.timezone.utc)
    ref = str(delta.get("delta_id") or delta.get("research_result_id") or delta.get("research_id") or "")
    if not ref:
        return []
    nd = (now + _dt.timedelta(hours=float(next_due_hours))) if next_due_hours else None
    out: list[dict] = []
    answered = delta.get("structured_answers") if isinstance(delta.get("structured_answers"), dict) else {}
    for qc in QUESTION_CLASSES:
        if qc == "thesis" or answered.get(qc) or delta.get(f"q_{qc}"):
            out.append({"subject_guid": subject_guid, "question_class": qc, "horizon": "default", "tenant_id": TENANT,
                        "answer_ref": ref, "answer_store": STORE, "answered_at": now, "next_due": nd})
    day = now.strftime("%Y-%m-%d")
    for u in _urls_from(delta):
        out.append({"subject_guid": subject_guid, "question_class": "citation", "horizon": f"{url_key(u)}:{day}",
                    "tenant_id": TENANT, "answer_ref": u, "answer_store": STORE + ":" + ref, "answered_at": now,
                    "next_due": now + _dt.timedelta(days=1)})
    return out


_UPSERT = """
INSERT INTO intelligence.research_index (subject_guid, question_class, horizon, tenant_id, answer_ref, answer_store, answered_at, next_due, version)
VALUES (%(subject_guid)s, %(question_class)s, %(horizon)s, %(tenant_id)s, %(answer_ref)s, %(answer_store)s, %(answered_at)s, %(next_due)s,
        COALESCE((SELECT max(version) + 1 FROM intelligence.research_index r
                   WHERE r.subject_guid = %(subject_guid)s AND r.question_class = %(question_class)s AND r.horizon = %(horizon)s
                     AND r.answer_ref <> %(answer_ref)s), 1))
ON CONFLICT (subject_guid, question_class, horizon, version) DO NOTHING
"""


def index_delta(delta: dict, *, subject_guid: str, env: dict | None = None, conn: Any = None) -> dict:
    """Write the rows for one accepted delta. Fail-soft. Returns {pg, rows, written}."""
    env = os.environ if env is None else env
    rows = rows_for(delta, subject_guid=subject_guid)
    if not enabled(env) or not rows:
        return {"pg": "skipped", "rows": len(rows), "written": 0}
    c = conn or _conn(env)
    if c is None:
        return {"pg": "absent", "rows": len(rows), "written": 0}
    written = 0
    try:
        with c.cursor() as cur:
            for r in rows:
                # A repeat of the same answer for the same key is a no-op (existing row with that ref).
                cur.execute("SELECT 1 FROM intelligence.research_index WHERE subject_guid=%s AND question_class=%s AND horizon=%s AND answer_ref=%s LIMIT 1",
                            (r["subject_guid"], r["question_class"], r["horizon"], r["answer_ref"]))
                if cur.fetchone():
                    continue
                cur.execute(_UPSERT, r)
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        c.commit()
        return {"pg": "written", "rows": len(rows), "written": written}
    except Exception as exc:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"pg": "error", "rows": len(rows), "written": written, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def latest(subject_guid: str, question_class: str, horizon: str = "default", *, env: dict | None = None, conn: Any = None) -> dict | None:
    env = os.environ if env is None else env
    if not enabled(env) or not subject_guid:
        return None
    c = conn or _conn(env)
    if c is None:
        return None
    try:
        with c.cursor() as cur:
            cur.execute("SELECT answer_ref, answer_store, answered_at, next_due, version FROM intelligence.research_index "
                        "WHERE subject_guid=%s AND question_class=%s AND horizon=%s ORDER BY answered_at DESC LIMIT 1",
                        (subject_guid, question_class, horizon))
            row = cur.fetchone()
        c.rollback()
        if not row:
            return None
        return {"answer_ref": row[0], "answer_store": row[1], "answered_at": row[2], "next_due": row[3], "version": row[4]}
    except Exception:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def cited_urls(subject_guid: str, *, since_hours: float = 24.0, env: dict | None = None, conn: Any = None) -> list[str]:
    """URLs already read for the subject inside the window — ladder step 5's deterministic source."""
    env = os.environ if env is None else env
    if not enabled(env) or not subject_guid:
        return []
    c = conn or _conn(env)
    if c is None:
        return []
    try:
        with c.cursor() as cur:
            cur.execute("SELECT DISTINCT answer_ref FROM intelligence.research_index WHERE subject_guid=%s AND question_class='citation' "
                        "AND answered_at > now() - (%s || ' hours')::interval", (subject_guid, str(float(since_hours))))
            rows = cur.fetchall()
        c.rollback()
        return sorted(str(r[0]) for r in rows)
    except Exception:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return []
