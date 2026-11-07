"""tests/test_document_mentions_purge_20261107.py — LQ-20261107-358.

Three defects measured on the live `document_mentions` table on 2026-11-07:

1. The 16:25 ET run — written AFTER the stoplist shipped — still bound prose to issuers:
   "Shell-company" -> SHEL (the legal-suffix stripper turned the compound into the name "Shell") and
   "Cross-reference XLV" -> CRT (progressive prefix narrowed three words to "CROSS"). Neither name is
   on any list; the shape is what gives them away — a proper name hyphenates two capitals
   ("T-Mobile", "Bio-Rad"), prose glues a lower-case word on ("Shell-company", "Cross-reference").
2. 1,599 (document, role) groups carry duplicate rows. The unique index is on issuer_guid, and
   PostgreSQL treats every NULL as distinct, so an unresolved mention never conflicted. Every
   duplicate group is in the NULL-issuer rows; none is in the resolved ones.
3. Nothing removes the rows the rule already refuses, and 90k of them are still served.

Hermetic: no database, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import document_mentions as DM  # noqa: E402
import purge_document_mentions_false_positives as purge  # noqa: E402


# ── 1. the prose-compound rule ────────────────────────────────────────────


def test_shell_company_is_not_shell_plc():
    """The exact row written at 16:25 ET (id 665319): a hyphenated compound, no SHEL in the text."""
    text = "- Shell-company structure with market_cap_b 172.92 but avg_vol_m only 57.6 and rvol 0.0."
    assert DM.false_positive_reason("Shell-company", "SHEL", "company_name",
                                    text=text, own_symbol="CTAA") == "prose_compound_without_context"


def test_cross_reference_is_not_cross_timbers():
    """The exact row written at 16:25 ET (id 665330): three words narrowed to CRT's first token."""
    text = "- Cross-reference XLV relative strength and sector leadership claims against primary index data."
    assert DM.false_positive_reason("Cross-reference XLV", "CRT", "company_name",
                                    text=text, own_symbol="PFE") == "prose_compound_without_context"


def test_a_proper_hyphenated_issuer_name_is_untouched():
    """A PROPER name hyphenates two capitals. Every one of these is a real issuer and must survive."""
    for name, symbol in (("T-Mobile", "TMUS"), ("Bio-Rad", "BIO"), ("Kimberly-Clark", "KMB"),
                         ("O-I Glass", "OI"), ("Asia-Pacific", "APWC")):
        text = f"The filing from {name} was reviewed."
        assert DM.false_positive_reason(name, symbol, "company_name", text=text) is None, name


def test_context_still_allows_a_prose_shaped_name():
    """Ambiguity only ever asks for context; the row's own symbol, or "(SHEL)", satisfies it."""
    text = "Shell-company structure flagged; see (SHEL) filings."
    assert DM.false_positive_reason("Shell-company", "SHEL", "company_name", text=text) is None
    assert DM.false_positive_reason("Shell-company", "SHEL", "company_name",
                                    text="Shell-company structure.", own_symbol="SHEL") is None


def test_a_ticker_match_is_a_different_claim():
    assert DM.false_positive_reason("Shell-company", "SHEL", "ticker", text="Shell-company.") is None


def test_the_rule_still_refuses_what_it_refused_before():
    """No regression in the stoplist/phrase/ordinary-word paths the 2026-11-07 fix added."""
    assert DM.false_positive_reason("GLOBE NEWSWIRE", "GL", "company_name",
                                    text="GLOBE NEWSWIRE — today") == "ambiguous_name_without_context"
    assert DM.false_positive_reason("Moving Average", "MA", "company_name",
                                    text="Moving Average crossed") == "prose_phrase_without_context"
    assert DM.false_positive_reason("Here", "HERE", "ticker_alias",
                                    text="mid Here peers") == "ordinary_word_alias_without_context"


# ── 2. the purge selection ────────────────────────────────────────────────


class _Cur:
    def __init__(self, script, connection=None):
        self.script = list(script)
        self.connection = connection          # psycopg2 exposes it; the clause memo lives there
        self.sql: list[tuple] = []
        self.rowcount = 0
        self._rows: list = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        for match, result in self.script:
            if match in sql:
                self._rows = result(params) if callable(result) else result
                if isinstance(self._rows, int):
                    self.rowcount = self._rows
                    self._rows = []
                return
        self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_null_duplicates_keep_the_earliest_row_of_each_group():
    rows = [(11, "news_articles", 1, "mentioned", 10),
            (12, "news_articles", 1, "mentioned", 10),
            (10, "news_articles", 1, "mentioned", 10),
            (21, "catalyst_events", 2, "mentioned", 20),
            (20, "catalyst_events", 2, "mentioned", 20)]
    cur = _Cur([("first_value(id) OVER", rows)])
    assert sorted(r[0] for r in purge.select_null_duplicates(cur)) == [11, 12, 21]


def test_false_positive_selection_uses_the_rule_on_the_document_text():
    mentions = [
        (1, "news_articles", 7, "SHEL", "company_name", "Shell-company", "mentioned"),
        (2, "news_articles", 7, "TMUS", "company_name", "T-Mobile", "mentioned"),
    ]
    texts = [(7, "A Shell-company structure; T-Mobile is the peer.", "CTAA")]
    cur = _Cur([("FROM document_mentions WHERE matched_via", mentions),
                ("FROM news_articles", texts)])
    picked = purge.select_false_positives(cur)
    assert [p[0] for p in picked] == [1]
    assert picked[0][6] == "prose_compound_without_context"


# ── 3. archive before delete ──────────────────────────────────────────────


def _apply_scripts(archived: int, deleted: int):
    return [
        ("CREATE TABLE IF NOT EXISTS document_mentions_purged", []),
        ("ALTER TABLE document_mentions_purged", []),
        ("CREATE UNIQUE INDEX IF NOT EXISTS uq_dm_purged_batch", []),
        ("CREATE TEMP TABLE _purge_plan", []),
        ("INSERT INTO _purge_plan", []),
        ("INSERT INTO document_mentions_purged", archived),
        ("DELETE FROM document_mentions", deleted),
    ]


def test_apply_archives_then_deletes():
    cur = _Cur(_apply_scripts(archived=3, deleted=3))
    conn = _Conn(cur)
    archived, deleted = purge.apply_batch(conn, {1: "x", 2: "y", 3: "z"}, "B1")
    sqls = [s for s, _ in cur.sql]
    assert archived == 3 and deleted == 3 and conn.committed
    assert next(i for i, s in enumerate(sqls) if "INSERT INTO document_mentions_purged" in s) < \
           next(i for i, s in enumerate(sqls) if s.startswith("DELETE FROM document_mentions"))


def test_a_short_archive_rolls_back_and_deletes_nothing():
    cur = _Cur(_apply_scripts(archived=2, deleted=0))
    conn = _Conn(cur)
    try:
        purge.apply_batch(conn, {1: "x", 2: "y", 3: "z"}, "B2")
    except RuntimeError as exc:
        assert "archived 2 of 3" in str(exc)
    else:                                              # pragma: no cover
        raise AssertionError("a short archive must raise")
    assert conn.rolled_back and not conn.committed
    assert not any(s.startswith("DELETE FROM document_mentions") for s, _ in cur.sql)


def test_the_plan_table_is_idempotent_by_primary_key():
    """Re-selecting a row that is already gone cannot happen; a repeated id inside one plan cannot either."""
    cur = _Cur([("CREATE TEMP TABLE _purge_plan", [])] + [("INSERT INTO _purge_plan", [])])
    purge._stage_plan(cur, {1: "x", 2: "y"})
    assert "PRIMARY KEY" in cur.sql[0][0]
    assert cur.sql[1][1] == [1, "x", 2, "y"]


# ── 4. the coalesced index and the writer's matching ON CONFLICT ──────────


class _MemoConn:
    """A connection object that accepts attributes, like psycopg2's."""
    pass


def test_the_clause_follows_what_the_database_has():
    plain = _Cur([("pg_indexes", [])], connection=_MemoConn())
    assert DM._conflict_target(plain) == DM._CONFLICT_PLAIN
    coalesced = _Cur([("pg_indexes", [(1,)])], connection=_MemoConn())
    assert DM._conflict_target(coalesced) == DM._CONFLICT_EXPR
    assert "COALESCE(issuer_guid" in DM._CONFLICT_EXPR


def test_the_clause_is_probed_once_per_connection():
    conn = _MemoConn()
    cur = _Cur([("pg_indexes", [(1,)])], connection=conn)
    DM._conflict_target(cur)
    DM._conflict_target(cur)                     # same connection: the memo answers, no second probe
    assert sum(1 for s, _ in cur.sql if "pg_indexes" in s) == 1


def test_a_cursor_without_a_connection_still_gets_a_correct_clause():
    """A driver that hides `.connection` re-probes; the answer stays right."""
    assert DM._conflict_target(_Cur([("pg_indexes", [(1,)])])) == DM._CONFLICT_EXPR


def test_the_migration_is_idempotent_and_guards_the_duplicates():
    sql = (ROOT / "migrations" / "2026_11_07_document_mentions_issuer_coalesce.sql").read_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_docmentions_issuer_coalesce" in sql
    assert "COALESCE(issuer_guid, '00000000-0000-0000-0000-000000000000'::uuid)" in sql
    assert "RAISE EXCEPTION" in sql and "purge_document_mentions_false_positives.py" in sql
    down = (ROOT / "migrations" / "2026_11_07_document_mentions_issuer_coalesce.down.sql").read_text()
    assert "DROP INDEX IF EXISTS uq_docmentions_issuer_coalesce" in down


def test_the_canonical_schema_carries_both_indexes():
    sql = (ROOT / "sql" / "document_mentions.sql").read_text()
    assert "uq_docmentions_issuer_coalesce" in sql
    assert "uq_docmentions\n" in sql              # the old one is kept: existing writers target it


def test_persist_writes_with_the_coalesced_target_once_the_index_exists():
    cur = _Cur([("pg_indexes", [(1,)])])
    conn = _Conn(cur)
    row = {"symbol": "SHEL", "subject_guid": None, "issuer_guid": None, "identity_status": "UNRESOLVED",
           "matched_via": "company_name", "matched_text": "Shell", "role": "mentioned",
           "role_source": "deterministic", "role_confidence": None}
    DM.persist(conn, source_table="news_articles", source_id=7, rows=[row])
    inserts = [s for s, _ in cur.sql if "INSERT INTO document_mentions" in s]
    assert inserts and "COALESCE(issuer_guid" in inserts[0]
    assert DM._ISSUER_SENTINEL in DM._CONFLICT_EXPR
