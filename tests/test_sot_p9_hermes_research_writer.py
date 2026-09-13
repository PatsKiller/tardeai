"""One write module for hermes_research_intelligence (One Source of Truth, Phase 9).

On 2026-09-13 the authority gate counted 32 files carrying their own
``INSERT INTO`` / ``UPDATE hermes_research_intelligence`` SQL. Each chose its own
column list, coercions and defaults; none set ``subject_guid`` although the
registry declares it required. These tests pin three things:

1. GOLDEN EQUIVALENCE — for every legacy INSERT writer, the row the migrated
   producer now hands the module renders to the same column→value map the legacy
   SQL rendered (same columns, same values after coercion, same SQL-side
   defaults). For every legacy UPDATE writer, the module emits the same SET
   columns and the same predicate parameters.
2. RAILS + IDENTITY — a value off its CHECK rail is returned with a reason, not
   written; a registered symbol round-trips to the registry's GUID; a cik/company
   row derives an issuer-based GUID; a bare unregistered ticker is never minted.
3. THE REDUCTION — baseline ceiling 32 > 1, live count via the gate == 1.

Pure: fake cursors that record SQL and params; the identity registry is pinned to
a temp file by an autouse fixture so nothing here reads production state.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.writers import hermes_research_writer as W  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """No test here may read the production identity registry."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))
    from scripts.lib import identity_registry
    identity_registry._CACHE.clear()
    monkeypatch.setattr(W, "_IDENTITY_COLS_PRESENT", None)


# ── fakes ────────────────────────────────────────────────────────────────────


class FakeCursor:
    """Records SQL + params. Answers the identity-column probe when asked to."""

    def __init__(self, *, identity_columns: bool = True, next_id: int = 101):
        self.calls: list[tuple[str, tuple]] = []
        self.identity_columns = identity_columns
        self.next_id = next_id
        self.rowcount = 1
        self._last = ""

    def execute(self, sql, params=()):
        self._last = sql
        self.calls.append((sql, tuple(params or ())))

    def fetchone(self):
        return (self.next_id,)

    def fetchall(self):
        if "information_schema.columns" in self._last:
            return [(c,) for c in W.IDENTITY_COLUMNS] if self.identity_columns else []
        return []

    def close(self):
        return None

    @property
    def writes(self):
        return [(s, p) for s, p in self.calls if "information_schema" not in s]


class FakeConn:
    def __init__(self, cur: FakeCursor):
        self._cur = cur
        self.commits = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1


def _split_top(s: str) -> list[str]:
    """Split on commas at bracket/quote depth 0."""
    out, buf, depth, q = [], [], 0, None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def _norm(col: str, v):
    """Fold the rendering differences that carry no semantic difference."""
    if isinstance(v, str):
        s = v.strip()
        u = s.upper()
        if u in ("NOW()", "NOW()::DATE", "CURRENT_DATE"):
            ts_cols = ("created_at", "updated_at", "identity_tagged_at", "reviewed_at", "research_expires_at", "taxonomy_tagged_at")
            return "NOW()" if col in ts_cols else "CURRENT_DATE"
        if u == "NULL":
            return None
        if u in ("TRUE", "FALSE"):
            return u == "TRUE"
        m = re.fullmatch(r"'(.*)'(::jsonb)?", s, re.S)
        if m:
            s = m.group(1)
        m = re.fullmatch(r"ARRAY\[(.*)\]", s, re.S)
        if m:
            return [x.strip().strip("'") for x in _split_top(m.group(1))]
        try:
            return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else s
        except ValueError:
            return s
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return v


def render(sql: str, params) -> dict:
    """INSERT text + params → {column: normalized value} — legacy or new, same parser."""
    m = re.search(r"INSERT\s+INTO\s+hermes_research_intelligence\s*\((.*?)\)\s*VALUES\s*\((.*)\)", sql, re.S | re.I)
    assert m, sql
    cols = [c.strip() for c in m.group(1).split(",")]
    vals = _split_top(m.group(2))
    vals[-1] = re.sub(r"\)?\s*RETURNING.*$", "", vals[-1], flags=re.S | re.I).strip()
    assert len(cols) == len(vals), (cols, vals)
    it = iter(params)
    out = {}
    for c, v in zip(cols, vals):
        if "%s" in v:
            out[c] = _norm(c, next(it))
            if c in W.JSONB_COLUMNS and isinstance(out[c], str):
                out[c] = json.loads(out[c])
        else:
            out[c] = _norm(c, v)
            if c in W.JSONB_COLUMNS and isinstance(out[c], str):
                out[c] = json.loads(out[c])
    # Table defaults the legacy writers relied on and the module makes explicit.
    out.setdefault("status", "staged")
    out.setdefault("created_at", "NOW()")
    out.setdefault("source", "hermes")
    if isinstance(out.get("symbol"), str) and not out["symbol"]:
        out["symbol"] = None
    return {k: v for k, v in out.items() if v is not None}


def new_render(cur: FakeCursor) -> dict:
    assert len(cur.writes) == 1, cur.writes
    return render(*cur.writes[0])


# ── legacy INSERT golden records (verbatim SQL + params from origin/main) ─────

EVIDENCE = {"k": 1, "list": [1, 2]}
URLS = ["https://a/1", "https://b/2"]

LEGACY_INSERTS = {
    "catalyst_momentum_engine": (
        """INSERT INTO hermes_research_intelligence
                           (research_type, symbol, topic, summary, confidence_score, status, source, source_urls_json, hermes_agent_name, model_used, freshness_date, created_at)
                           VALUES ('momentum_catalyst', %s, %s, %s, %s, 'staged', 'hermes', %s, 'catalyst_momentum_engine', 'gemma3:4b', CURRENT_DATE, NOW())""",
        ("NOC", "earnings: NOC", "scalp momentum catalyst", 0.7, json.dumps(URLS)),
        {"research_type": "momentum_catalyst", "symbol": "NOC", "topic": "earnings: NOC",
         "summary": "scalp momentum catalyst", "confidence_score": 0.7, "status": "staged", "source": "hermes",
         "source_urls_json": URLS, "hermes_agent_name": "catalyst_momentum_engine", "model_used": "gemma3:4b"},
        "catalyst_momentum_engine",
    ),
    "hermes_youtube_discovery": (
        """INSERT INTO hermes_research_intelligence
                       (research_type, symbol, topic, summary, confidence_score, status, source,
                        source_urls_json, hermes_agent_name, model_used, freshness_date, created_at)
                       VALUES ('youtube_discovery', %s, %s, %s, %s, 'staged', 'hermes',
                               %s, 'hermes_youtube_discovery', 'gemma3:4b', CURRENT_DATE, NOW())""",
        ("NOC", "youtube_discovery: NOC", "2 videos", 0.6, json.dumps(URLS)),
        {"research_type": "youtube_discovery", "symbol": "NOC", "topic": "youtube_discovery: NOC",
         "summary": "2 videos", "confidence_score": 0.6, "status": "staged", "source": "hermes",
         "source_urls_json": URLS, "hermes_agent_name": "hermes_youtube_discovery", "model_used": "gemma3:4b"},
        "hermes_youtube_discovery",
    ),
    "hermes_topic_monitor_bridge": (
        """
                INSERT INTO hermes_research_intelligence
                    (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                     thesis_type, evidence_json, confidence_score, freshness_date, model_used, status)
                VALUES ('hermes','topic_monitor_bridge','topic_research', NULL, %s, %s, %s,
                        'neutral', %s::jsonb, 0.5, %s, 'topic_monitor_bridge', 'staged')
                RETURNING id
            """,
        ("Roth ladder", "Research topic 'Roth ladder'", "Investigate 'Roth ladder' for trading-relevant developments.",
         json.dumps(EVIDENCE), "2026-09-13"),
        {"source": "hermes", "hermes_agent_name": "topic_monitor_bridge", "research_type": "topic_research",
         "symbol": None, "topic": "Roth ladder", "summary": "Research topic 'Roth ladder'",
         "thesis": "Investigate 'Roth ladder' for trading-relevant developments.", "thesis_type": "neutral",
         "evidence_json": EVIDENCE, "confidence_score": 0.5, "freshness_date": "2026-09-13",
         "model_used": "topic_monitor_bridge", "status": "staged"},
        "topic_monitor_bridge",
    ),
    "holding_protection_advisor": (
        """INSERT INTO hermes_research_intelligence
                         (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                          thesis_type, evidence_json, confidence_score, model_used, prompt_hash,
                          freshness_date)
                       VALUES ('hermes','protection_advisor','protection_advisory',%s,
                          'stop/trailing-stop recommendation', %s, %s, 'neutral', %s, %s, %s, %s,
                          CURRENT_DATE)""",
        ("NOC", "rationale", "stop $500 (8% below) · no trail yet", json.dumps(EVIDENCE), 0.8, "grok-3-mini", "v7"),
        {"source": "hermes", "hermes_agent_name": "protection_advisor", "research_type": "protection_advisory",
         "symbol": "NOC", "topic": "stop/trailing-stop recommendation", "summary": "rationale",
         "thesis": "stop $500 (8% below) · no trail yet", "thesis_type": "neutral",
         "evidence_json": json.dumps(EVIDENCE), "confidence_score": 0.8, "model_used": "grok-3-mini", "prompt_hash": "v7"},
        "protection_advisor",
    ),
    "stop_health_check": (
        """INSERT INTO hermes_research_intelligence
            (source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
             evidence_json, confidence_score, model_used, status, category_lifecycle, freshness_date, created_at)
            VALUES (%s,%s,'stop_health',%s,%s,%s,%s,'neutral',%s::jsonb,%s,'stop_lifecycle_monitor',
                    'staged','stop', CURRENT_DATE, NOW())""",
        ("hermes", "StopHealthMonitor", "NOC", "Stop health: near_stop", "near_stop — NOC 1.2% from stop",
         "NOC 1.2% from stop", json.dumps(EVIDENCE), 0.95),
        {"source": "hermes", "hermes_agent_name": "StopHealthMonitor", "research_type": "stop_health",
         "symbol": "NOC", "topic": "Stop health: near_stop", "summary": "near_stop — NOC 1.2% from stop",
         "thesis": "NOC 1.2% from stop", "thesis_type": "neutral", "evidence_json": json.dumps(EVIDENCE),
         "confidence_score": 0.95, "model_used": "stop_lifecycle_monitor", "status": "staged",
         "category_lifecycle": "stop"},
        "StopHealthMonitor",
    ),
    "grok_stop_review": (
        """INSERT INTO hermes_research_intelligence
            (source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
             evidence_json, confidence_score, model_used, status, category_lifecycle, freshness_date, created_at)
            VALUES ('hermes','Grok','stop_curation',%s,'Grok stop R:R review',%s,%s,'neutral',%s::jsonb,%s,
                    'grok','staged','stop', CURRENT_DATE, NOW())""",
        ("NOC", "Grok stop curation [B]: keep — fine", "hold", json.dumps(EVIDENCE), 0.7),
        {"source": "hermes", "hermes_agent_name": "Grok", "research_type": "stop_curation", "symbol": "NOC",
         "topic": "Grok stop R:R review", "summary": "Grok stop curation [B]: keep — fine", "thesis": "hold",
         "thesis_type": "neutral", "evidence_json": json.dumps(EVIDENCE), "confidence_score": 0.7,
         "model_used": "grok", "status": "staged", "category_lifecycle": "stop"},
        "Grok",
    ),
    "gain_guardian_publish": (
        """INSERT INTO hermes_research_intelligence
               (topic, summary, symbol, research_type, source, status, confidence_score,
                evidence_json, created_at, freshness_date)
               VALUES (%s,%s,%s,'exit_intelligence','gain_guardian','staged',%s,%s::jsonb,NOW(),NOW())""",
        ("Exit intelligence: NOC TRIM (2026-09-13)", "parabolic", "NOC", 0.55, json.dumps(EVIDENCE)),
        {"topic": "Exit intelligence: NOC TRIM (2026-09-13)", "summary": "parabolic", "symbol": "NOC",
         "research_type": "exit_intelligence", "source": "gain_guardian", "status": "staged",
         "confidence_score": 0.55, "evidence_json": json.dumps(EVIDENCE)},
        "gain_guardian",
    ),
    "siem_to_hermes_backlog": (
        """
                INSERT INTO hermes_research_intelligence
                (symbol, research_type, hermes_agent_name, topic, summary, confidence_score,
                 source_urls_json, evidence_json, status, source, freshness_date, model_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'staged', 'hermes', CURRENT_DATE, 'siem_normalizer')
                RETURNING id
            """,
        (None, "security_backlog", "siem_agent", "SIEM: brute force", "5 events", 0.6, json.dumps(URLS), json.dumps(EVIDENCE)),
        {"symbol": None, "research_type": "security_backlog", "hermes_agent_name": "siem_agent",
         "topic": "SIEM: brute force", "summary": "5 events", "confidence_score": 0.6,
         "source_urls_json": json.dumps(URLS), "evidence_json": json.dumps(EVIDENCE), "status": "staged",
         "source": "hermes", "model_used": "siem_normalizer"},
        "siem_agent",
    ),
    "options_research_bridge": (
        """INSERT INTO hermes_research_intelligence
               (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                thesis_type, evidence_json, confidence_score, freshness_date, model_used, status)
               VALUES ('hermes','options_research_bridge','options_desk', %s, %s, %s, %s,
                       'neutral', %s::jsonb, %s, %s, 'options_engine', 'staged')""",
        ("NOC", "Options desk: NOC", "summary", "thesis", json.dumps(EVIDENCE), 0.62, "2026-09-13"),
        {"source": "hermes", "hermes_agent_name": "options_research_bridge", "research_type": "options_desk",
         "symbol": "NOC", "topic": "Options desk: NOC", "summary": "summary", "thesis": "thesis",
         "thesis_type": "neutral", "evidence_json": EVIDENCE, "confidence_score": 0.62,
         "freshness_date": "2026-09-13", "model_used": "options_engine", "status": "staged"},
        "options_research_bridge",
    ),
    "api_v2_operator_knowledge": (
        """INSERT INTO hermes_research_intelligence
                        (created_at, source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                         freshness_date, model_used, status)
                        VALUES (now(), 'hermes', 'operator', 'operator_knowledge', %s, %s, %s, %s,
                                now()::date, 'operator_telegram', 'staged') RETURNING id""",
        ("NOC", "operator note", "content", "content"),
        {"source": "hermes", "hermes_agent_name": "operator", "research_type": "operator_knowledge",
         "symbol": "NOC", "topic": "operator note", "summary": "content", "thesis": "content",
         "model_used": "operator_telegram", "status": "staged"},
        "operator",
    ),
    "hermes_autonomous_librarian_backlog_loop": (
        """
            INSERT INTO hermes_research_intelligence (
                source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
                evidence_json, confidence_score, freshness_date, source_urls_json, model_used,
                context_type_used, status, quality_score, tags
            ) VALUES (
                'hermes', 'autonomous_librarian_loop', 'research_backlog', NULL,
                %s, %s,
                'Autonomous Librarian finding — operator review required.',
                'neutral',
                %s::jsonb,
                0.30, %s, '[]'::jsonb,
                'librarian_loop', 'autonomous_librarian', 'staged', 0.30,
                ARRAY['research_backlog','autonomous_librarian','phase_49']
            ) RETURNING id
        """,
        ("backtest_weak_strategy: WR=30%", "Autonomous Librarian detected: WR=30%. Requires operator review.",
         json.dumps([EVIDENCE]), "2026-09-13"),
        {"source": "hermes", "hermes_agent_name": "autonomous_librarian_loop", "research_type": "research_backlog",
         "symbol": None, "topic": "backtest_weak_strategy: WR=30%",
         "summary": "Autonomous Librarian detected: WR=30%. Requires operator review.",
         "thesis": "Autonomous Librarian finding — operator review required.", "thesis_type": "neutral",
         "evidence_json": json.dumps([EVIDENCE]), "confidence_score": 0.30, "freshness_date": "2026-09-13",
         "source_urls_json": [], "model_used": "librarian_loop", "context_type_used": "autonomous_librarian",
         "status": "staged", "quality_score": 0.30, "tags": ["research_backlog", "autonomous_librarian", "phase_49"]},
        "autonomous_librarian_loop",
    ),
    "librarian_v2_backlog": (
        """
                INSERT INTO hermes_research_intelligence (
                    source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
                    evidence_json, confidence_score, freshness_date, source_urls_json, model_used,
                    context_type_used, status, quality_score, tags
                ) VALUES (
                    'hermes', 'librarian_v2', 'research_backlog', NULL,
                    %s, %s, 'Librarian v2 finding — operator review required.', 'neutral',
                    %s::jsonb, 0.30, %s, '[]'::jsonb, 'librarian_v2',
                    'librarian_v2', 'staged', 0.30,
                    ARRAY['research_backlog','librarian_v2']
                )
            """,
        ("screener_underfilled: 3 underfilled runs in 7d", "Librarian v2 detected: 3 underfilled runs in 7d",
         json.dumps([EVIDENCE]), "2026-09-13"),
        {"source": "hermes", "hermes_agent_name": "librarian_v2", "research_type": "research_backlog", "symbol": None,
         "topic": "screener_underfilled: 3 underfilled runs in 7d",
         "summary": "Librarian v2 detected: 3 underfilled runs in 7d",
         "thesis": "Librarian v2 finding — operator review required.", "thesis_type": "neutral",
         "evidence_json": [EVIDENCE], "confidence_score": 0.30, "freshness_date": "2026-09-13",
         "source_urls_json": [], "model_used": "librarian_v2", "context_type_used": "librarian_v2",
         "status": "staged", "quality_score": 0.30, "tags": ["research_backlog", "librarian_v2"]},
        "librarian_v2",
    ),
    "hermes_health_inspector_stage_finding": (
        """INSERT INTO hermes_research_intelligence
               (source, hermes_agent_name, research_type, topic, summary, thesis, evidence_json,
                confidence_score, status, tags, pattern_signature, freshness_date, model_used,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, %s, NOW(), NOW())
               RETURNING id""",
        ("hermes", "hermes_health_inspector", "agent_liveness", "agent_liveness_P1", "Agent Liveness: stale",
         "stale", json.dumps(EVIDENCE), 0.5, "staged", '{"agent_liveness","warning","P1"}',
         "agent_liveness::P1::alex", "watchdog"),
        {"source": "hermes", "hermes_agent_name": "hermes_health_inspector", "research_type": "agent_liveness",
         "topic": "agent_liveness_P1", "summary": "Agent Liveness: stale", "thesis": "stale",
         "evidence_json": json.dumps(EVIDENCE), "confidence_score": 0.5, "status": "staged",
         "tags": '{"agent_liveness","warning","P1"}', "pattern_signature": "agent_liveness::P1::alex",
         "model_used": "watchdog", "updated_at": W.SQL_NOW},
        "hermes_health_inspector",
    ),
    "health_learning_engine_threshold": (
        """
            INSERT INTO hermes_research_intelligence
                (source, hermes_agent_name, research_type, topic, summary, thesis,
                 confidence_score, status, tags, threshold_adjusted,
                 freshness_date, model_used, pattern_signature, evidence_json,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false,
                    CURRENT_DATE, %s, %s, %s::jsonb, NOW(), NOW())
        """,
        ("hermes", "hermes_health_inspector", "threshold_tuning", "threshold_tuning", "Threshold proposal: x",
         "Threshold proposal: x", 1.0, "staged", '{"health_inspection","threshold_tuning","P3"}',
         "learning_engine", "sig", json.dumps(EVIDENCE)),
        {"source": "hermes", "hermes_agent_name": "hermes_health_inspector", "research_type": "threshold_tuning",
         "topic": "threshold_tuning", "summary": "Threshold proposal: x", "thesis": "Threshold proposal: x",
         "confidence_score": 1.0, "status": "staged", "tags": '{"health_inspection","threshold_tuning","P3"}',
         "threshold_adjusted": False, "model_used": "learning_engine", "pattern_signature": "sig",
         "evidence_json": json.dumps(EVIDENCE), "updated_at": W.SQL_NOW},
        "hermes_health_inspector",
    ),
    "health_learning_engine_pattern": (
        """
            INSERT INTO hermes_research_intelligence
                (source, hermes_agent_name, research_type, topic, summary, thesis,
                 confidence_score, status, tags, new_pattern_discovered,
                 pattern_signature, freshness_date, model_used, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, CURRENT_DATE, %s, NOW(), NOW())
        """,
        ("hermes", "hermes_health_inspector", "pattern_discovery", "pattern_discovery", "hyp", "hyp", 0.5,
         "staged", '{"health_inspection","pattern_discovery","P3"}', "pat", "learning_engine"),
        {"source": "hermes", "hermes_agent_name": "hermes_health_inspector", "research_type": "pattern_discovery",
         "topic": "pattern_discovery", "summary": "hyp", "thesis": "hyp", "confidence_score": 0.5, "status": "staged",
         "tags": '{"health_inspection","pattern_discovery","P3"}', "new_pattern_discovered": True,
         "pattern_signature": "pat", "model_used": "learning_engine", "updated_at": W.SQL_NOW},
        "hermes_health_inspector",
    ),
}


@pytest.mark.parametrize("name", sorted(LEGACY_INSERTS))
def test_golden_insert_matches_legacy_writer(name):
    legacy_sql, legacy_params, new_row, producer = LEGACY_INSERTS[name]
    legacy = render(legacy_sql, legacy_params)

    cur = FakeCursor(identity_columns=False)
    rc = W.write_research_rows(cur, [new_row], producer=producer, source=legacy.get("source", "hermes"))
    assert rc.rows_written == 1 and rc.rows_rejected == [], rc.as_dict()
    new = new_render(cur)

    # gain_guardian's legacy INSERT omitted hermes_agent_name (NOT NULL in the DDL);
    # the module fills it from `producer`. That is the one deliberate addition.
    if name == "gain_guardian_publish":
        assert new.pop("hermes_agent_name") == "gain_guardian"
    assert new == legacy, f"\nlegacy={json.dumps(legacy, default=str, sort_keys=True)}\nnew={json.dumps(new, default=str, sort_keys=True)}"
    assert cur.writes[0][0].rstrip().endswith("RETURNING id")
    assert rc.ids == [101]


def test_backlog_drain_build_insert_equivalence():
    """hermes_backlog_drain used hermes_staging_ingest.build_insert (a second, dynamic write
    path). Same LLM output → same columns; unknown keys dropped the same way."""
    from hermes_staging_ingest import build_insert
    output = {"hermes_agent_name": "backlog_drain_agent", "research_type": "backlog_resolution",
              "topic": "Backlog resolution: x", "summary": "s", "thesis": "t", "thesis_type": "neutral",
              "confidence_score": 0.45, "freshness_date": "2026-09-13", "model_used": "deepseek",
              "evidence_json": {"backlog_id": 5}, "not_a_column": "dropped"}
    legacy_sql, legacy_vals = build_insert("hermes_research_intelligence", dict(output))
    legacy = render(legacy_sql, legacy_vals)
    legacy["created_at"] = "NOW()"  # build_insert stamps a Python timestamp; the module uses NOW()

    cur = FakeCursor(identity_columns=False)
    rc = W.write_research_rows(cur, [output], producer="backlog_drain_agent", drop_unknown=True)
    assert rc.dropped_columns == ["not_a_column"]
    assert new_render(cur) == legacy


# ── legacy UPDATE golden records ─────────────────────────────────────────────


def _set_cols(sql: str) -> set[str]:
    """Columns assigned in SET — stopping at the FROM/WHERE that sits at bracket depth 0,
    not at a FROM inside a sub-select (the tags-union repair has one)."""
    start = re.search(r"\bSET\b", sql, re.I).end()
    depth, q, i = 0, None, start
    while i < len(sql):
        ch = sql[i]
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and re.match(r"\b(FROM|WHERE)\b", sql[i:], re.I) and sql[i - 1].isspace():
            break
        i += 1
    return {p.split("=", 1)[0].strip() for p in _split_top(sql[start:i])}


def _where(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.split("WHERE", 1)[1]).strip().rstrip(";")


def test_update_coordinator_promote_and_rollback():
    cur = FakeCursor()
    W.set_status(cur, ids=[42], status="promoted")
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"status"} and params == ("promoted", [42])
    assert W.rollback_sql_for_status(42, "staged") == "UPDATE hermes_research_intelligence SET status='staged' WHERE id=42;"
    with pytest.raises(W.ResearchWriteError):
        W.rollback_sql_for_status(42, "bogus")


def test_update_outcome_learning_archive_stale_staged():
    legacy = """UPDATE hermes_research_intelligence SET status='archived'
                       WHERE status='staged'
                         AND created_at < NOW() - make_interval(days => %s)"""
    cur = FakeCursor()
    rc = W.archive_rows_where(cur, where="status = 'staged' AND created_at < NOW() - make_interval(days => %s)",
                              where_params=[45])
    sql, params = cur.writes[0]
    assert _set_cols(sql) == _set_cols(legacy) == {"status"}
    assert params == ("archived", 45) and rc.rows_written == 1


def test_update_freshness_and_retention_archive_with_tag():
    cur = FakeCursor()
    W.archive_rows_where(cur, where="freshness_date < CURRENT_DATE - INTERVAL '30 days' AND status NOT IN ('archived', 'rejected')",
                         add_tag="stale_freshness")
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"status", "tags"}
    assert "array_append(COALESCE(tags, ARRAY[]::text[]), %s)" in sql
    assert params == ("archived", "stale_freshness")

    cur = FakeCursor()
    W.archive_rows_where(cur, where="status = 'staged' AND created_at < CURRENT_DATE - %s::int", where_params=[90],
                         add_tag="auto_archived")
    assert cur.writes[0][1] == ("archived", "auto_archived", 90)


def test_update_backlog_drain_transition_if_staged():
    legacy = """UPDATE hermes_research_intelligence
                   SET status = CASE WHEN status='staged' THEN 'archived' ELSE status END,
                       tags = CASE WHEN 'drained' = ANY(tags) THEN tags
                                   ELSE array_append(tags, 'drained') END
                   WHERE id=%s"""
    cur = FakeCursor()
    W.transition_if_status(cur, ids=[7], from_status="staged", to_status="archived", add_tag_if_absent="drained")
    sql, params = cur.writes[0]
    assert _set_cols(sql) == _set_cols(legacy) == {"status", "tags"}
    assert "CASE WHEN status = %s THEN %s ELSE status END" in sql
    assert "CASE WHEN %s = ANY(tags) THEN tags ELSE array_append(tags, %s) END" in sql
    assert params == ("staged", "archived", "drained", "drained", [7])


def test_update_health_inspector_remediation_outcome():
    cur = FakeCursor()
    W.record_remediation_outcome(cur, finding_id=9, success=True, duration_ms=1200, pattern_signature="sig")
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"remediation_success", "remediation_duration_ms", "pattern_signature"}
    assert "pattern_signature = COALESCE(pattern_signature, %s)" in sql
    assert "remediation_success = true" in sql
    assert params == (1200, "sig", [9])
    # NULL stays NULL (legacy passed None straight through)
    cur = FakeCursor()
    W.record_remediation_outcome(cur, finding_id=9, success=None, duration_ms=None, pattern_signature=None)
    assert cur.writes[0][1] == (None, None, None, [9])


def test_update_tag_engine_strategy_tags_and_quality_blend():
    cur = FakeCursor()
    W.set_fields_by_id(cur, ids=[3], fields={"strategy_tags": ["swing", "earnings"]})
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"strategy_tags"} and params == (["swing", "earnings"], [3])

    legacy = """UPDATE hermes_research_intelligence
                           SET quality_score = ROUND((%s * COALESCE(quality_score, %s) + %s * %s)::numeric, 3)
                           WHERE COALESCE(research_type,'unknown') = %s"""
    cur = FakeCursor()
    W.blend_quality_score(cur, research_type="catalyst", blend_existing=0.7, neutral=0.5, blend_outcome_prior=0.3, prior=0.61)
    sql, params = cur.writes[0]
    assert _set_cols(sql) == _set_cols(legacy) == {"quality_score"}
    assert "ROUND((%s * COALESCE(quality_score, %s) + %s * %s)::numeric, 3)" in sql
    assert params == (0.7, 0.5, 0.3, 0.61, "catalyst")


def test_update_outcome_grader_and_trade_instances_join():
    cur = FakeCursor()
    W.link_from_join(cur, set_raw={"downstream_outcome": "l.actioned"}, from_clause="hermes_outcome_ledger l",
                     where="l.subject_type='research_row' AND l.subject_id = hri.id AND l.actioned IS NOT NULL AND hri.downstream_outcome IS NULL",
                     alias="hri")
    sql, params = cur.writes[0]
    assert sql.startswith("UPDATE hermes_research_intelligence AS hri")
    assert "FROM hermes_outcome_ledger l" in sql and _set_cols(sql) == {"downstream_outcome"} and params == ()

    cur = FakeCursor()
    W.link_from_join(cur, set_raw={"trade_instance_id": "ti.id"}, from_clause="trade_instances ti",
                     where="ti.source_table='paper_trades' AND ti.source_trade_id = h.related_trade_id::text AND h.related_trade_id IS NOT NULL AND h.trade_instance_id IS NULL",
                     alias="h")
    assert cur.writes[0][0].startswith("UPDATE hermes_research_intelligence AS h")


def test_update_trade_links_fill_if_null():
    legacy = """update hermes_research_intelligence
                           set related_trade_id=COALESCE(related_trade_id,%s),
                               related_proposal_id=COALESCE(related_proposal_id,%s), updated_at=now()
                           where id=%s"""
    cur = FakeCursor()
    W.fill_if_null(cur, ids=[11], fields={"related_trade_id": 5, "related_proposal_id": None}, touch_updated_at=True)
    sql, params = cur.writes[0]
    assert _set_cols(sql) == _set_cols(legacy) == {"related_trade_id", "related_proposal_id", "updated_at"}
    assert params == (5, None, [11])


def test_update_repairs_critique_refresh_synth_and_reground():
    # repair_health_threshold_tuning_noise
    cur = FakeCursor()
    W.archive_with_tags_union(cur, where="hermes_agent_name='hermes_health_inspector' AND research_type='threshold_tuning' AND status='staged'",
                              tags=["duplicate_collapsed", "proposal_only"], extra_set={"threshold_adjusted": False})
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"status", "tags", "threshold_adjusted", "updated_at"}
    assert "threshold_adjusted = false" in sql and params == ("archived", ["duplicate_collapsed", "proposal_only"])

    # repair_hermes_backlog_taxonomy (predicate-guarded evidence replace)
    cur = FakeCursor()
    W.set_fields_by_id(cur, ids=[2], fields={"evidence_json": [EVIDENCE]}, touch_updated_at=True,
                       extra_where="research_type='research_backlog' AND hermes_agent_name='autonomous_librarian_loop'")
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"evidence_json", "updated_at"} and params == (json.dumps([EVIDENCE]), [2])
    assert "AND research_type='research_backlog'" in _where(sql)

    # research_critique_pipeline archive + categories
    cur = FakeCursor()
    W.set_status(cur, ids=[4], status="archived", touch_updated_at=True)
    assert _set_cols(cur.writes[0][0]) == {"status", "updated_at"}
    cur = FakeCursor()
    W.set_fields_by_id(cur, ids=[4], fields={"category_content": "earnings", "category_sector": None,
                                             "category_lifecycle": "entry", "quality_score": 0.42})
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"category_content", "category_sector", "category_lifecycle", "quality_score"}
    # params follow the module's canonical COLUMNS order (quality_score, lifecycle, content, sector)
    assert params == (0.42, "entry", "earnings", None, [4])

    # research_intelligence_refresh (id = ANY + status IN)
    cur = FakeCursor()
    W.set_status(cur, ids=[1, 2], status="archived", only_from=["staged", "reviewed", "promoted"], touch_updated_at=True)
    sql, params = cur.writes[0]
    assert params == ("archived", [1, 2], ["staged", "reviewed", "promoted"]) and "status = ANY(%s)" in sql

    # topic_research_synthesizer
    cur = FakeCursor()
    W.set_fields_by_id(cur, ids=[8], fields={"summary": "s", "thesis": "t", "confidence_score": 0.5,
                                             "model_used": "synth:deepseek", "evidence_json": EVIDENCE}, touch_updated_at=True)
    assert _set_cols(cur.writes[0][0]) == {"summary", "thesis", "confidence_score", "model_used", "evidence_json", "updated_at"}

    # ingest_reground_retirement_gaps
    cur = FakeCursor()
    W.patch_evidence_json_path(cur, ids=[6], path=["grounded_count"], value=0)
    sql, params = cur.writes[0]
    assert "jsonb_set(COALESCE(evidence_json, '{}'::jsonb), %s::text[], %s::jsonb)" in sql
    assert params == (["grounded_count"], "0", [6])

    # health_learning_engine learning_cycle stamp
    cur = FakeCursor()
    W.stamp_learning_cycle(cur, cycle_number=3)
    sql, params = cur.writes[0]
    assert _set_cols(sql) == {"learning_cycle"} and params == (3,)
    assert "learning_cycle = 0 AND created_at > NOW() - INTERVAL '1 hour'" in sql


def test_callable_executor_shape_is_supported():
    """gain_guardian_publish / narrative_enrich / refresh / reground pass db_adapter._execute."""
    seen = []

    def fake_execute(sql, params, fetch=None):
        seen.append((sql, params, fetch))
        return {"id": 55} if fetch == "one" else ([] if fetch == "all" else True)

    rc = W.write_research_rows(fake_execute, [{"research_type": "x", "topic": "t", "summary": "s"}],
                               producer="p", identity_columns=False)
    assert rc.ids == [55] and seen[0][2] == "one"
    rc = W.set_status(fake_execute, ids=[1], status="archived")
    assert rc.rows_written == -1  # executor cannot report rowcount; receipt says so rather than guessing


# ── rails ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad,reason", [
    ({"confidence_score": 1.5}, "confidence_score_out_of_range"),
    ({"confidence_score": -0.1}, "confidence_score_out_of_range"),
    ({"thesis_type": "bull"}, "thesis_type_not_allowed"),
    ({"status": "live"}, "status_not_allowed"),
    ({"summary": ""}, "summary_required"),
    ({"topic": None}, "topic_required"),
    ({"evidence_json": "{not json"}, "evidence_json_invalid_json"),
    ({"quality_score": "high"}, "quality_score_not_numeric"),
])
def test_rejected_row_is_returned_not_written(bad, reason):
    row = {"research_type": "x", "topic": "t", "summary": "s", "hermes_agent_name": "a", "model_used": "m", **bad}
    cur = FakeCursor(identity_columns=False)
    rc = W.write_research_rows(cur, [row, {"research_type": "x", "topic": "ok", "summary": "ok"}], producer="p")
    assert cur.writes and len(cur.writes) == 1  # only the good row reached the cursor
    assert rc.rows_in == 2 and rc.rows_written == 1 and rc.rejected == 1
    assert rc.rows_rejected[0]["index"] == 0 and rc.rows_rejected[0]["reason"].startswith(reason)


def test_unknown_column_is_rejected_unless_dropping_is_explicit():
    cur = FakeCursor(identity_columns=False)
    rc = W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "bogus": 1}], producer="p")
    assert rc.rows_written == 0 and rc.rows_rejected[0]["reason"] == "unknown_columns:bogus"


def test_update_refuses_whole_table_and_unknown_columns():
    cur = FakeCursor()
    with pytest.raises(W.ResearchWriteError):
        W.update_research_rows(cur, where="", set_fields={"status": "archived"})
    with pytest.raises(W.ResearchWriteError):
        W.update_research_rows(cur, where="id = 1", set_fields={"nope": 1})
    with pytest.raises(W.ResearchWriteError):
        W.update_research_rows(cur, where="id = 1", set_fields={"status": "live"})
    with pytest.raises(W.ResearchWriteError):
        W.update_research_rows(cur, where="id = 1", set_fields={"created_at": W.SQL_NOW})
    assert cur.writes == []


# ── identity ─────────────────────────────────────────────────────────────────


def _register(symbol, **extra):
    from scripts.lib.identity_registry import load, lookup_symbol, register_all
    register_all([{"symbol": symbol, **extra}], apply=True)
    from scripts.lib import identity_registry
    identity_registry._CACHE.clear()
    return lookup_symbol(load(), symbol)["subject_guid"]


def test_symbol_only_row_round_trips_to_the_registry_guid():
    """Rule (c): ticker is an alias; the row lands on the GUID the registry already holds —
    the same one backfill_research_identity.py would write later."""
    guid = _register("NOC", company="Northrop Grumman")
    from scripts.lib.identity_registry import load, resolve_guid
    assert resolve_guid(load(), guid) == guid

    cur = FakeCursor(identity_columns=True)
    rc = W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "symbol": "noc "}], producer="p")
    new = new_render(cur)
    assert new["subject_guid"] == guid
    assert new["identity_status"] == "CANDIDATE" and new["identity_tagged_at"] == "NOW()"
    assert new["issuer_guid"]
    assert rc.identity == {"resolved": 1, "unresolved": 0, "explicit": 0, "columns_present": True, "lookups": {"REGISTRY": 1}}

    # research_identity.resolve — the backfill's resolver — agrees.
    from lib import research_identity as RI
    assert RI.resolve(RI.load_registry(), "NOC")["subject_guid"] == guid


def test_cik_company_row_derives_an_issuer_based_guid_without_minting():
    from scripts.lib.security_identity import issuer_guid, resolve_identity_spine, security_guid
    cur = FakeCursor(identity_columns=True)
    W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "symbol": "ZZZQ",
                                 "cik": "1133421", "company": "Northrop Grumman"}], producer="p")
    new = new_render(cur)
    expected_issuer = issuer_guid(cik="1133421")
    assert new["issuer_guid"] == expected_issuer
    assert new["subject_guid"] == security_guid(issuer=expected_issuer) == resolve_identity_spine(
        {"symbol": "ZZZQ", "cik": "1133421"})["security_guid"]
    assert new["identity_status"] == "CANDIDATE"
    assert "cik" not in new and "company" not in new  # hints are consumed, never written
    # The registry was not written to: identity is derived, not minted, on the write path.
    from scripts.lib.identity_registry import load
    assert load()["entities"] == {}


def test_bare_unregistered_ticker_gets_null_identity_never_a_ticker_guid():
    """Rule (a)/(d): never invent. NULL here is what the backfill leaves, so it is retried later."""
    cur = FakeCursor(identity_columns=True)
    rc = W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "symbol": "ZZZQ"}], producer="p")
    new = new_render(cur)
    assert "subject_guid" not in new and "issuer_guid" not in new and "identity_status" not in new
    assert rc.identity["unresolved"] == 1 and rc.identity["lookups"] == {"UNRESOLVED": 1}


def test_explicit_subject_guid_follows_the_supersede_chain():
    """A GUID written months ago must resolve to the current entity (identity upgrade rule)."""
    old = _register("ACME", company="Acme Corp")                 # CANDIDATE, company-derived
    new_guid = _register("ACME", identifiers={"cusip": "037833100"})  # CONFIRMED supersedes
    assert new_guid != old
    from scripts.lib.identity_registry import load, resolve_guid
    assert resolve_guid(load(), old) == new_guid

    cur = FakeCursor(identity_columns=True)
    W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "symbol": "ACME",
                                 "subject_guid": old}], producer="p")
    assert new_render(cur)["subject_guid"] == new_guid


def test_identity_columns_absent_means_no_identity_columns_in_the_insert():
    """The columns come from sql/research_identity_tags.sql; a table without them must still accept rows."""
    _register("NOC", company="Northrop Grumman")
    cur = FakeCursor(identity_columns=False)
    W.write_research_rows(cur, [{"research_type": "x", "topic": "t", "summary": "s", "symbol": "NOC"}], producer="p")
    assert not (set(W.IDENTITY_COLUMNS) & set(new_render(cur)))
    assert cur.calls[0][0].startswith("SELECT column_name FROM information_schema.columns")


def test_cash_rows_and_topic_rows_are_not_entities():
    cur = FakeCursor(identity_columns=True)
    rc = W.write_research_rows(cur, [
        {"research_type": "x", "topic": "t", "summary": "s", "symbol": "CASH"},
        {"research_type": "topic_research", "topic": "Roth ladder", "summary": "s", "symbol": None},
    ], producer="p")
    assert rc.identity["lookups"] == {"NOT_APPLICABLE": 2} and rc.identity["unresolved"] == 2


# ── the producers themselves, with a fake connection ─────────────────────────


def test_health_inspector_stage_findings_goes_through_the_module():
    import hermes_health_inspector as hhi
    cur = FakeCursor(identity_columns=False)
    conn = FakeConn(cur)
    staged, records = hhi._stage_findings(conn, [{"severity": "critical", "priority": "P0", "root_cause": "rc",
                                                 "linked_producers": ["a", "b"], "evidence": "e", "stale_count": 2}])
    assert staged == 1 and records[0]["id"] == 101 and conn.commits == 1
    new = new_render(cur)
    assert new["research_type"] == "health_inspection" and new["confidence_score"] == 0.8
    assert new["tags"] == '{"health_inspection","critical","P0","a","b"}'


def test_health_learning_engine_goes_through_the_module():
    from scripts.lib.health_learning_engine import HealthLearningEngine
    cur = FakeCursor(identity_columns=False)
    conn = FakeConn(cur)
    HealthLearningEngine(conn).stage_discovered_pattern({"name": "pat", "root_cause_hypothesis": "h", "severity": "P2", "confidence": 0.4})
    new = new_render(cur)
    assert new["new_pattern_discovered"] is True and new["pattern_signature"] == "pat"


def test_librarian_backlog_scope_goes_through_the_module_and_reexports():
    from lib.hermes_librarian import librarian
    assert librarian.write_research_rows is W.write_research_rows

    class Cur(FakeCursor):
        def fetchall(self):
            if "hermes_v_backtest_results_context" in self._last:
                return [("s1", 0.25, 0.8, 9)]
            return super().fetchall()

        def fetchone(self):
            if "hermes_v_catalyst_quality_context" in self._last:
                return (50,)
            if "hermes_v_screener_context" in self._last:
                return (0,)
            return super().fetchone()

    cur = Cur(identity_columns=False)
    out = librarian._run_backlog_scope(FakeConn(cur), cur, apply=True, max_rows=10)
    assert out["findings"] == 2 and out["written"] == 2
    inserts = [s for s, _ in cur.writes if s.startswith("INSERT INTO hermes_research_intelligence")]
    assert len(inserts) == 2


# ── the reduction, documented ────────────────────────────────────────────────


def test_negative_control_writer_count_fell_from_baseline_to_one():
    import check_data_source_authority as gate
    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    base = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
    before = base["writers"]["hermes_research_intelligence"]
    assert before > 1, "baseline must record the pre-consolidation plurality"
    now = gate.count_writers(auth, gate._files())["hermes_research_intelligence"]
    assert now == 1, f"exactly one file may write the store; found {now}"
    assert gate.compare_baseline("WRITER_COUNT_ROSE", {"hermes_research_intelligence": now},
                                 {"hermes_research_intelligence": before}) == []


def test_the_one_writer_is_this_module():
    import check_data_source_authority as gate
    pat = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+hermes_research_intelligence\b", re.I)
    hits = sorted(gate._rel(p) for p in gate._files() if pat.search(p.read_text(encoding="utf-8", errors="replace")))
    assert hits == ["scripts/lib/writers/hermes_research_writer.py"]
