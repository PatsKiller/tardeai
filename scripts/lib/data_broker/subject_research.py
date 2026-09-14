"""Subject Research — read-only Data Broker projection over hermes_research_intelligence.

Registry domain ``research_thesis`` (32 writer modules today, consolidation target
scripts/lib/hermes_librarian/librarian.py; stale after 168h). Keyed by symbol or
by ``subject_guid`` (the UUIDv5 security_identity spine — see
reference_identity_memory_spine). Before Phase 4 scripts/api_v2.py read this table
directly in 31 places.

This projection READS ONLY. It does not queue research, call a lane, or touch a
provider; the registry's no_coverage rule (``say_so_queue_only_if_producer_exists``)
is for the caller to act on, with the envelope's gap as the evidence.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from lib.data_broker.envelope import envelope, newest
except ImportError:  # imported as scripts.lib.* (repo root on sys.path, scripts/ not)
    from scripts.lib.data_broker.envelope import envelope, newest

DOMAIN = "research_thesis"

_COLS = """id, created_at, updated_at, source, hermes_agent_name, research_type, symbol,
           subject_guid, issuer_guid, gics_sector, topic, summary, thesis, thesis_type,
           confidence_score, quality_score, freshness_date, research_expires_at, status,
           model_used, lane_used, tags, strategy_tags, category_sector"""

BY_SYMBOL_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                    WHERE upper(symbol)=%s ORDER BY created_at DESC LIMIT %s"""
BY_GUID_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                  WHERE subject_guid=%s::uuid ORDER BY created_at DESC LIMIT %s"""
BY_SECTOR_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                    WHERE (gics_sector=%s OR category_sector=%s)
                    ORDER BY created_at DESC LIMIT %s"""


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        elif type(v).__name__ in ("Decimal", "UUID"):
            v = float(v) if type(v).__name__ == "Decimal" else str(v)
        out[k] = v
    return out


def get_subject_research(db_query, *, symbol: str | None = None, subject_guid: str | None = None,
                         sector: str | None = None, limit: int = 20, now=None, registry=None) -> dict[str, Any]:
    """Research rows for one subject, newest first, wrapped in the read envelope.

    Exactly one of symbol / subject_guid / sector selects the rows. ``as_of`` is
    the newest row's created_at for THIS subject — a busy table does not make a
    stale thesis fresh.
    """
    rows: list[dict[str, Any]] = []
    error = None
    key: dict[str, Any] = {}
    try:
        lim = max(1, min(int(limit), 500))
        if subject_guid:
            key = {"subject_guid": str(subject_guid)}
            rows = db_query(BY_GUID_SQL, (str(subject_guid), lim), fetch="all") or []
        elif symbol:
            key = {"symbol": str(symbol).upper().strip()}
            rows = db_query(BY_SYMBOL_SQL, (key["symbol"], lim), fetch="all") or []
        elif sector:
            key = {"sector": str(sector)}
            rows = db_query(BY_SECTOR_SQL, (sector, sector, lim), fetch="all") or []
        else:
            error = "one of symbol / subject_guid / sector is required"
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    items = [_clean(r) for r in rows]
    env = envelope(DOMAIN, newest([r.get("created_at") for r in rows]), now=now, registry=registry)
    out = {"ok": error is None, "key": key, "items": items, "n": len(items),
           "read_only": True, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


# ── thematic search (no symbol) ──────────────────────────────────────────────
# 2026-09-13 18:56: "what sectors should I concentrate on into Q3/Q4 given
# September seasonality and the midterm cycle" was answered from the model's
# general knowledge while hermes_research_intelligence held 2,088 promoted rows.
# A question with no symbol had no read path at all: get_subject_research needs a
# symbol / guid / sector. This is that read path -- bounded, promoted-only, newest
# first, ranked by how many of the question's salient words a row matches.

_KEYWORD_STOP = frozenset("""
a an and are as at be been but by can could do does for from get going got had has have
how i if in into is it its just me my no not now of on or our should so some than that
the their them then there these they this those to too us was we were what when where
which who why will with would you your about after before over under again very more most
also any each other such only own same
market markets stock stocks portfolio book trade trades trading buy sell hold holding
holdings good bad time think thinking given normally usually perform performs performance
concentrate concentrating focus focusing look looking tell please thanks want need make
position positions weight weights cash
""".split())


def salient_keywords(question: str, *, max_keywords: int = 8) -> list[str]:
    """The nouns worth searching for, in order of appearance, plural-trimmed.

    Pure. ``"what sectors ... September ... Q3/Q4 ... seasonality and the midterm
    cycle"`` -> ``["sector", "september", "q3", "q4", "seasonality", "midterm",
    "cycle"]``. Words in the stop list (question glue, and desk words like
    "cash" or "holdings" that would match every row) are dropped.
    """
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9]+", (question or "").lower()):
        if tok in _KEYWORD_STOP:
            continue
        if not (len(tok) >= 4 or re.fullmatch(r"q[1-4]|h[12]|ai|[0-9]{4}", tok)):
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        if tok not in out:
            out.append(tok)
        if len(out) >= max_keywords:
            break
    return out


def _search_sql(n_keywords: int) -> str:
    hit = "(topic ILIKE %s OR summary ILIKE %s OR thesis ILIKE %s)"
    hits = " OR ".join([hit] * n_keywords)
    score = " + ".join([f"(CASE WHEN {hit} THEN 1 ELSE 0 END)"] * n_keywords)
    return (f"SELECT * FROM (SELECT {_COLS}, ({score}) AS keyword_hits FROM hermes_research_intelligence "
            f"WHERE status = 'promoted' AND ({hits})) matched "
            f"WHERE keyword_hits >= %s ORDER BY keyword_hits DESC, created_at DESC LIMIT %s")


def search_research(db_query, keywords: list[str], *, limit: int = 5, min_hits: int | None = None,
                    now=None, registry=None) -> dict[str, Any]:
    """Promoted research whose topic / summary / thesis mention the question's ``keywords``.

    READ ONLY; ``db_query(sql, params, fetch="all")`` is injected (tests pass a
    fake), so this module never opens a connection. Bounded: at most 8 keywords,
    at most 20 rows, ``ILIKE '%kw%'`` per column. Rows are ranked by how many
    keywords they hit, then newest first. ``min_hits`` (default: 1 for one or two
    keywords, else 2) keeps one generic word -- "sector", "cycle" -- from
    returning every row that mentions it. ``as_of`` is the newest matching row --
    the size of the table says nothing about coverage of THIS topic.
    """
    kws = [str(k).strip() for k in (keywords or []) if str(k).strip()][:8]
    rows: list[dict[str, Any]] = []
    error = None
    if not kws:
        env = envelope(DOMAIN, None, now=now, registry=registry)
        out = {"ok": True, "key": {"keywords": []}, "items": [], "n": 0,
               "read_only": True, "provider_calls": 0}
        out.update(env)
        return out
    try:
        lim = max(1, min(int(limit), 20))
        floor = int(min_hits) if min_hits is not None else (1 if len(kws) <= 2 else 2)
        floor = max(1, min(floor, len(kws)))
        like = [f"%{k}%" for k in kws]
        per_kw = [p for k in like for p in (k, k, k)]
        # psycopg2 binds positionally: SELECT-list score, inner WHERE, hit floor, LIMIT.
        params = tuple(per_kw + per_kw + [floor, lim])
        rows = db_query(_search_sql(len(kws)), params, fetch="all") or []
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    items = [_clean(r) for r in rows]
    env = envelope(DOMAIN, newest([r.get("created_at") for r in rows]), now=now, registry=registry)
    out = {"ok": error is None, "key": {"keywords": kws}, "items": items, "n": len(items),
           "read_only": True, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out
