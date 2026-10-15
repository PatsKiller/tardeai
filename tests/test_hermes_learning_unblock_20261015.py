"""Hermes learning unblock (2026-10-15; AGENTS.md §23.23, §24.1, §6): three blocked steps of the n8n fabric process
hermes-learning become dry-run shadow lanes.

  tag_engine              --dry-run makes NO model call (generate_cloud never reached; the rows the live run would
                          classify are counted), uses a read-only DB session and runs no DDL. --apply is unchanged.
  outcome_feedback_agent  every send is a declared notification intent through the host chokepoint
                          (send_telegram priority P2/P3, producer hermes_outcome_feedback_agent; no bypass_router);
                          --dry-run never reaches the notifier; --notify record calls no sender at all.
  autonomous_self_tune    --learn is non-destructive: self_purge is never called and every purge helper refuses in
                          learn-only mode. The historical flag combinations (the cron line runs --apply) execute the
                          byte-identical statement sequence.
  score_history_retention unchanged: destructive retention, an operator decision, stays on cron (EXCLUDED).

Hermetic: every DB connection is a recording fake, the Telegram chokepoint is a stub module in sys.modules (the real
telegram_alert is never imported here), retention_archive.managed_purge and the research writer are stubs, and all
files live in tmp_path. Nothing reaches a database, a model or Telegram.
"""

from __future__ import annotations

import ast
import copy
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_notification_intents as CNI  # noqa: E402
import hermes_autonomous_self_tune as ST  # noqa: E402
import hermes_tag_engine as TE  # noqa: E402
from lib.hermes_outcome_bus import alert_notifications as AN  # noqa: E402
from scripts import n8n_workflow_templates as T  # noqa: E402

SPEC = json.loads((ROOT / "config" / "n8n_fabric_processes.json").read_text(encoding="utf-8"))["processes"][
    "hermes-learning"
]
MANIFEST = json.loads((ROOT / SPEC["manifest"]).read_text(encoding="utf-8"))
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
BLOCKED_REASONS = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["blocked_reasons"]
UNBLOCKED = ("tag_engine", "outcome_feedback_agent", "autonomous_self_tune")
WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP", "MERGE")


# ── recording DB fakes ───────────────────────────────────────────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, conn: "FakeConn"):
        self.conn = conn
        self.connection = conn
        self._last = ""
        self.rowcount = 0

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.conn.log.append((text, params))
        self._last = text
        if self.conn.readonly and text.split(" ", 1)[0].upper() in WRITE_VERBS:
            raise RuntimeError(f"cannot execute {text.split(' ', 1)[0]} in a read-only transaction")
        self.rowcount = 4 if text.upper().startswith("UPDATE") else 0

    def _answer(self):
        for needle, value in self.conn.answers:
            if needle in self._last:
                return value
        return None

    def fetchone(self):
        v = self._answer()
        return v if v is not None else (0,)

    def fetchall(self):
        v = self._answer()
        return v if v is not None else []

    def close(self):
        pass


class FakeConn:
    def __init__(self, answers, log):
        self.answers = answers
        self.log = log
        self.readonly = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def set_session(self, readonly=False, **_kw):
        self.readonly = bool(readonly)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        if self.readonly:
            raise RuntimeError("commit on a read-only dry-run session")
        self.commits += 1

    def close(self):
        pass


def _writes(log) -> list[str]:
    return [sql for sql, _ in log if sql.split(" ", 1)[0].upper() in WRITE_VERBS]


# ── 1. tag_engine: --dry-run makes no model call ─────────────────────────────────────────────────────────────────

TAG_CFG = {
    "retag": {"backlog_batch": 50, "llm_batch": 5, "llm_timeout_s": 1, "llm_wall_clock_s": 60},
    "fallback_tag": "general_research",
    "max_tags": 2,
    "synonyms": {},
    "quality": {"shrink_k": 5, "neutral": 0.5, "blend_existing": 0.5, "blend_outcome_prior": 0.5},
    "efficacy": {"min_samples_per_tag": 5},
}
TAG_ANSWERS = [
    ("FROM strategy_registry", [("momentum",), ("breakout",)]),
    ("ORDER BY created_at DESC LIMIT", [(1, "AAPL", "quiet text"), (2, "MSFT", "a momentum setup"),
                                        (3, None, "no symbol"), (4, "NVDA", "unrelated words")]),
    ("count(*) FILTER (WHERE strategy_tags", (2, 10)),
    ("COALESCE(hri.research_type,'unknown')", [("news", 3, 10)]),
    ("round(stddev(quality_score)", (0.1, 5)),
    ("unnest(hri.strategy_tags) tag, count(*)", [("momentum", 3, 10)]),
    ("SELECT tag, count(*) trade_n", []),
]


@pytest.fixture
def tag_env(monkeypatch, tmp_path):
    log: list = []
    conns: list[FakeConn] = []

    def _conn():
        c = FakeConn(TAG_ANSWERS, log)
        conns.append(c)
        return c

    llm_calls: list = []

    def _no_model(*a, **k):
        llm_calls.append((a, k))
        raise AssertionError("generate_cloud reached")

    gcg = types.ModuleType("lib.governed_cloud_generation")
    gcg.generate_cloud = _no_model
    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation", gcg)
    writes: list = []
    writer = types.ModuleType("lib.writers.hermes_research_writer")
    writer.set_fields_by_id = lambda cur, **k: writes.append(("set_fields_by_id", k))
    writer.blend_quality_score = lambda cur, **k: writes.append(("blend", k)) or types.SimpleNamespace(rows_written=1)
    monkeypatch.setitem(sys.modules, "lib.writers.hermes_research_writer", writer)
    monkeypatch.setattr(TE, "_conn", _conn)
    monkeypatch.setattr(TE, "_cfg", lambda: copy.deepcopy(TAG_CFG))
    monkeypatch.setattr(TE, "KILL_SWITCH", tmp_path / "HERMES_DISABLED")
    return types.SimpleNamespace(log=log, conns=conns, llm_calls=llm_calls, writes=writes)


def test_tag_engine_dry_run_makes_no_model_call_and_writes_nothing(tag_env, monkeypatch, capsys):
    monkeypatch.setattr(TE, "_llm_tags", lambda *a, **k: pytest.fail("dry run reached _llm_tags"))
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--dry-run", "--apply"])  # --dry-run wins
    TE.main()
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["apply"] is False
    assert tag_env.llm_calls == []  # generate_cloud never called
    # rows 1 (AAPL) and 4 (NVDA) have no rule tag and a symbol: the live run would classify them; row 3 has no symbol
    assert out["retag"]["llm_would_call"] == 2 and out["retag"]["llm_called"] == 0
    assert out["retag"]["llm_tagged"] == 0 and out["retag"]["rule_tagged"] == 1 and out["retag"]["fallback"] == 3
    assert _writes(tag_env.log) == [] and tag_env.writes == []  # no CREATE/ALTER, no upsert, no writer call
    assert tag_env.conns and all(c.readonly for c in tag_env.conns)  # every session read-only at the server
    assert all(c.commits == 0 for c in tag_env.conns)


def test_tag_engine_dry_run_respects_the_live_llm_budget(tag_env, monkeypatch):
    monkeypatch.setattr(TE, "_llm_tags", lambda *a, **k: pytest.fail("dry run reached _llm_tags"))
    cfg = copy.deepcopy(TAG_CFG)
    cfg["retag"]["llm_batch"] = 1
    assert TE.retag(cfg, True, dry_run=True)["llm_would_call"] == 1  # same cap as the live run; apply ignored
    assert tag_env.writes == [] and tag_env.llm_calls == []


def test_tag_engine_apply_path_is_unchanged(tag_env, monkeypatch, capsys):
    called: list = []
    monkeypatch.setattr(TE, "_llm_tags", lambda txt, vocab, timeout, mx: called.append(txt) or ["breakout"])
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--apply"])
    TE.main()
    out = json.loads(capsys.readouterr().out)
    assert "mode" not in out and out["apply"] is True
    assert "llm_would_call" not in out["retag"] and "llm_called" not in out["retag"]
    assert called == ["quiet text", "unrelated words"] and out["retag"]["llm_tagged"] == 2
    assert [w[0] for w in tag_env.writes].count("set_fields_by_id") == 4
    ddl = [s for s in _writes(tag_env.log) if s.startswith(("CREATE", "ALTER"))]
    assert len(ddl) == 3 and any(s.startswith("INSERT INTO hermes_tag_efficacy") for s in _writes(tag_env.log))
    assert not any(c.readonly for c in tag_env.conns) and sum(c.commits for c in tag_env.conns) == 2


def test_tag_engine_bare_preview_is_unchanged(tag_env, monkeypatch, capsys):
    """The bare preview (no flag) keeps its historical shape: it still refines through _llm_tags (here a stub)."""
    called: list = []
    monkeypatch.setattr(TE, "_llm_tags", lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py"])
    TE.main()
    out = json.loads(capsys.readouterr().out)
    assert out["apply"] is False and "mode" not in out and len(called) == 2 and tag_env.writes == []


# ── 2. outcome_feedback_agent: declared chokepoint intents; dry run and record mode send nothing ───────────────


@pytest.fixture
def chokepoint(monkeypatch, tmp_path):
    """A stub telegram_alert module: the real chokepoint (and its env bootstrap) is never imported here."""
    sent: list = []
    fake = types.ModuleType("telegram_alert")

    def send_telegram(message, bypass_router=False, **kw):
        sent.append({"message": message, "bypass_router": bypass_router, **kw})
        return True

    fake.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(AN, "STATE_PATH", tmp_path / "notify_state.json")
    monkeypatch.setattr(AN, "AUDIT_PATH", tmp_path / "notify_audit.jsonl")
    monkeypatch.setattr(AN, "_panel_url", lambda cfg: "/v3/hermes")
    return types.SimpleNamespace(sent=sent, tmp=tmp_path)


NOTIFY_CFG = {
    "enabled": True,
    "min_severity": "info",
    "cooldown_hours": 8,
    "alert_types": {},
    "channels": {"telegram": {"enabled": True, "bypass_router": True}},
}
ALERTS = {
    "active_count": 3,
    "active": [
        {"id": "hit_rate_declining", "severity": "critical", "label": "Hit rate", "detail": "down"},
        {"id": "efficiency_declining", "severity": "warning", "label": "Efficiency", "detail": "low"},
        {"id": "scope_creep", "severity": "info", "label": "Scope", "detail": "wide"},
    ],
}


def test_sends_are_declared_intents_through_the_chokepoint(chokepoint):
    r = AN.dispatch_alert_notifications(copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG))
    assert r["sent"] == 3 and r["notify"] == "chokepoint"
    assert [(s["priority"], s["producer"]) for s in chokepoint.sent] == [
        ("P2", AN.PRODUCER), ("P2", AN.PRODUCER), ("P3", AN.PRODUCER)]
    assert all(s["bypass_router"] is False for s in chokepoint.sent)  # the config's bypass_router is ignored
    assert set(json.loads(AN.STATE_PATH.read_text())["last_sent"]) == {a["id"] for a in ALERTS["active"]}


def test_record_mode_calls_no_sender_and_returns_the_intents(chokepoint):
    r = AN.dispatch_alert_notifications(copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG), notify="record")
    assert chokepoint.sent == [] and r["sent"] == 0
    intents = [x["intent"] for x in r["results"]]
    assert [i["priority"] for i in intents] == ["P2", "P2", "P3"]
    assert all(i["producer"] == AN.PRODUCER and i["dedupe_key"].startswith("hermes_closed_loop:") for i in intents)
    assert not AN.STATE_PATH.exists()  # nothing delivered: no cooldown written
    with pytest.raises(ValueError):
        AN.dispatch_alert_notifications(ALERTS, cfg=NOTIFY_CFG, notify="telegram")


def test_dispatch_dry_run_sends_nothing(chokepoint):
    r = AN.dispatch_alert_notifications(copy.deepcopy(ALERTS), cfg=copy.deepcopy(NOTIFY_CFG), dry_run=True)
    assert chokepoint.sent == [] and {x["status"] for x in r["results"]} == {"dry_run"}


@pytest.fixture
def feedback_agent(monkeypatch, tmp_path, chokepoint):
    import hermes_outcome_feedback_agent as FA

    log: list = []
    conns: list[FakeConn] = []

    def _conn():
        c = FakeConn([], log)
        conns.append(c)
        return c

    bus = {"global": {}, "by_symbol": {}, "by_tag": {}, "alerts": copy.deepcopy(ALERTS), "maturity": {}}
    monkeypatch.setattr(FA, "_conn", _conn)
    monkeypatch.setattr(FA, "KILL_SWITCH", tmp_path / "HERMES_DISABLED")
    monkeypatch.setattr(FA, "_cfg", lambda: {"notifications": copy.deepcopy(NOTIFY_CFG)})
    monkeypatch.setattr(FA, "build_bus", lambda cur, cfg, run_id: copy.deepcopy(bus))
    files: list = []
    monkeypatch.setattr(FA, "write_outcome_bus", lambda b, apply: files.append("bus") or tmp_path / "bus.json")
    monkeypatch.setattr(FA, "write_maturity_snapshot", lambda m, apply: files.append("snap") or None)
    monkeypatch.setattr(FA, "_write_heartbeat", lambda s: files.append("heartbeat"))
    return types.SimpleNamespace(FA=FA, conns=conns, files=files, sent=chokepoint.sent)


def test_feedback_dry_run_is_read_only_and_never_notifies(feedback_agent, monkeypatch, capsys):
    FA = feedback_agent.FA
    monkeypatch.setattr(FA, "dispatch_alert_notifications", lambda *a, **k: pytest.fail("dry run notified"))
    monkeypatch.setattr(sys, "argv", ["hermes_outcome_feedback_agent.py", "--dry-run", "--apply"])  # --dry-run wins
    FA.main()
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["apply"] is False and out["notifications"]["skipped"] == "dry_run"
    assert feedback_agent.sent == [] and feedback_agent.files == []
    assert feedback_agent.conns and all(c.readonly for c in feedback_agent.conns)


def test_feedback_apply_routes_through_the_chokepoint_with_declared_priorities(feedback_agent, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hermes_outcome_feedback_agent.py", "--apply"])
    feedback_agent.FA.main()
    out = json.loads(capsys.readouterr().out)
    assert out["apply"] is True and out["notifications"]["sent"] == 3
    assert {s["priority"] for s in feedback_agent.sent} == {"P2", "P3"}
    assert feedback_agent.files == ["bus", "snap", "heartbeat"]


def test_feedback_apply_record_mode_sends_nothing(feedback_agent, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hermes_outcome_feedback_agent.py", "--apply", "--notify", "record"])
    feedback_agent.FA.main()
    out = json.loads(capsys.readouterr().out)
    assert feedback_agent.sent == [] and out["notifications"]["notify"] == "record"
    assert [x["status"] for x in out["notifications"]["results"]] == ["intent"] * 3


def _declared_priorities(tree: ast.AST) -> set[str]:
    exprs = [k.value for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "priority"]
    return {c.value for e in exprs for c in ast.walk(e)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value in ("P1", "P2", "P3")}


@pytest.mark.parametrize("rel", ["scripts/lib/hermes_outcome_bus/alert_notifications.py",
                                 "scripts/hermes_outcome_feedback_agent.py"])
def test_every_send_declares_its_priority_and_none_bypasses(rel):
    """Wave-2 style (tests/test_notification_intents_wave2_20261011.py): declared P2/P3, no bypass_router site."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = CNI.notifier_calls(tree)
    assert all(declared and not bypass for _, _, declared, bypass in calls), calls
    if calls:
        assert _declared_priorities(tree) == {"P2", "P3"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "bypass_router"]


# ── 3. autonomous_self_tune: --learn is non-destructive; historical flags are byte-identical ───────────────────

TUNE_ANSWERS = [
    ("count(DISTINCT created_at::date)", (6,)),
    ("jsonb_array_elements(detail->'changes')", (0, 0)),
    ("DISTINCT ON (factor)", [("momentum", 0.40, 0.3), ("value", 0.10, 0.1)]),
    ("to_regclass('hermes_autotune_audit')", ("hermes_autotune_audit",)),
    ("SELECT to_regclass(%s)", ("t",)),
]


@pytest.fixture
def tune_env(monkeypatch, tmp_path):
    log: list = []
    conns: list[FakeConn] = []
    purges: list = []

    def _conn():
        c = FakeConn(TUNE_ANSWERS, log)
        conns.append(c)
        return c

    ra = types.ModuleType("lib.retention_archive")

    def managed_purge(conn, *, table, where_sql, params, label, writer, apply):
        purges.append({"table": table, "label": label, "apply": apply})
        if apply:
            conn.cursor().execute(f"DELETE FROM {table} t WHERE {where_sql}", params)
        return {"deleted": 2 if apply else 0, "eligible": 2}

    ra.managed_purge = managed_purge
    monkeypatch.setitem(sys.modules, "lib.retention_archive", ra)
    weights = tmp_path / "hermes_score_weights.yaml"
    weights.write_text("version: 3\nweights:\n  momentum: 0.5\n  value: 0.5\n", encoding="utf-8")
    monkeypatch.setattr(ST, "WEIGHTS_FILE", weights)
    monkeypatch.setattr(ST, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    monkeypatch.setattr(ST, "_conn", _conn)
    monkeypatch.setattr(ST, "_LEARN_ONLY", False)
    return types.SimpleNamespace(log=log, conns=conns, purges=purges, weights=weights, tmp=tmp_path)


def _json_tail(text: str) -> dict:
    return json.loads(text[text.index("{"):])


def test_learn_never_deletes_even_with_apply(tune_env, capsys):
    assert ST.main(["--learn", "--apply"]) == 0
    out = _json_tail(capsys.readouterr().out)
    assert "self_purge" not in out and out["auto_graft"]["status"] == "applied"
    assert tune_env.purges == []
    writes = _writes(tune_env.log)
    assert not [s for s in writes if s.startswith(("DELETE", "UPDATE", "TRUNCATE", "DROP"))], writes
    assert [s.split(" (")[0] for s in writes] == ["CREATE TABLE IF NOT EXISTS hermes_autotune_audit",
                                                  "INSERT INTO hermes_autotune_audit"]
    assert "version: 4" in tune_env.weights.read_text()  # the graft (a learn-class write) still happens


def test_purge_helpers_refuse_in_learn_only_mode(tune_env):
    cur = FakeConn(TUNE_ANSWERS, tune_env.log).cursor()
    ST._LEARN_ONLY = True
    try:
        for call in (lambda: ST.self_purge(cur, True),
                     lambda: ST._purge(cur, "x", "UPDATE t SET a=1", (), True),
                     lambda: ST._archived_purge(cur, "x", "t", "TRUE", (), True)):
            with pytest.raises(ST.LearnOnlyViolation):
                call()
    finally:
        ST._LEARN_ONLY = False
    assert tune_env.purges == [] and _writes(tune_env.log) == []


def test_learn_dry_run_is_read_only_no_ddl_no_file_write(tune_env, capsys):
    before = tune_env.weights.read_bytes()
    assert ST.main(["--learn", "--dry-run", "--apply"]) == 0  # --dry-run wins
    out = _json_tail(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["apply"] is False and "self_purge" not in out
    assert out["auto_graft"]["status"] == "dry" and out["auto_graft"]["changes"]
    assert _writes(tune_env.log) == [] and tune_env.purges == []
    assert all(c.readonly and c.commits == 0 for c in tune_env.conns)
    assert tune_env.weights.read_bytes() == before and not (tune_env.tmp / "grafts").exists()


def test_dry_run_on_a_database_without_the_audit_table(tune_env, capsys, monkeypatch):
    answers = [a for a in TUNE_ANSWERS if "hermes_autotune_audit'" not in a[0]]
    answers.insert(0, ("to_regclass('hermes_autotune_audit')", (None,)))
    monkeypatch.setattr(ST, "_conn", lambda: FakeConn(answers, tune_env.log))
    assert ST.main(["--learn", "--dry-run"]) == 0
    assert not [s for s, _ in tune_env.log if "FROM hermes_autotune_audit" in s]
    assert _json_tail(capsys.readouterr().out)["auto_graft"]["status"] == "dry"


#: The statement sequence (verb + first table) each historical flag combination executes, measured on the
#: pre-split script (origin/main 57d8fc3ff, the code the cron line runs today) against these fakes. The split
#: must reproduce it exactly: the cron line (--apply) and every other existing combination are unchanged.
HISTORICAL = {
    ("--apply",): [
        "CREATE hermes_autotune_audit", "SELECT hermes_weight_calibration", "SELECT hermes_autotune_audit",
        "SELECT hermes_weight_calibration", "INSERT hermes_autotune_audit", "UPDATE hermes_advisory_events",
        "UPDATE hermes_embedding_queue", "DELETE hermes_embedding_queue", "DELETE hermes_score_history",
        "DELETE hermes_research_intelligence", "DELETE hermes_external_research", "SELECT to_regclass",
        "DELETE watchlist_research_results", "SELECT to_regclass", "DELETE watchlist_research_queue",
        "SELECT to_regclass", "DELETE proposal_research_packets", "INSERT hermes_autotune_audit",
    ],
    (): [
        "CREATE hermes_autotune_audit", "SELECT hermes_weight_calibration", "SELECT hermes_autotune_audit",
        "SELECT hermes_weight_calibration", "SELECT to_regclass", "SELECT to_regclass", "SELECT to_regclass",
    ],
    ("--purge", "--apply"): [
        "CREATE hermes_autotune_audit", "UPDATE hermes_advisory_events", "UPDATE hermes_embedding_queue",
        "DELETE hermes_embedding_queue", "DELETE hermes_score_history", "DELETE hermes_research_intelligence",
        "DELETE hermes_external_research", "SELECT to_regclass", "DELETE watchlist_research_results",
        "SELECT to_regclass", "DELETE watchlist_research_queue", "SELECT to_regclass",
        "DELETE proposal_research_packets", "INSERT hermes_autotune_audit",
    ],
}
HISTORICAL[("--learn", "--purge", "--apply")] = HISTORICAL[("--apply",)]
HISTORICAL[("--learn", "--apply")] = [
    "CREATE hermes_autotune_audit", "SELECT hermes_weight_calibration", "SELECT hermes_autotune_audit",
    "SELECT hermes_weight_calibration", "INSERT hermes_autotune_audit",
]


def _shape(log) -> list[str]:
    out = []
    for sql, _ in log:
        words = sql.replace("(", " ").replace(",", " ").split()
        verb = words[0].upper()
        if verb == "CREATE":
            table = words[5]
        elif verb in ("INSERT", "DELETE"):
            table = words[2]
        elif verb == "UPDATE":
            table = words[1]
        else:
            table = "to_regclass" if "to_regclass" in sql else words[words.index("FROM") + 1]
        out.append(f"{verb} {table}")
    return out


@pytest.mark.parametrize("argv", sorted(HISTORICAL), ids=lambda a: " ".join(a) or "bare")
def test_historical_flag_combinations_are_byte_identical(tune_env, capsys, argv):
    assert ST.main(list(argv)) == 0
    out = _json_tail(capsys.readouterr().out)
    assert _shape(tune_env.log) == HISTORICAL[argv]
    assert "mode" not in out and out["apply"] is ("--apply" in argv)
    assert ("self_purge" in out) is ("--purge" in argv or "--learn" not in argv)
    assert ("auto_graft" in out) is ("--learn" in argv or "--purge" not in argv)
    assert sum(c.commits for c in tune_env.conns) == (1 if "--apply" in argv else 0)
    assert not any(c.readonly for c in tune_env.conns)


def test_cron_line_and_manifest_step_are_unchanged():
    step = next(s for s in MANIFEST["stages"]["tune"]["steps"] if s["id"] == "autonomous_self_tune")
    assert step["command"].endswith("scripts/hermes_autonomous_self_tune.py --apply")  # both halves, as before
    retention = next(s for s in MANIFEST["stages"]["learn"]["steps"] if s["id"] == "score_history_retention")
    assert retention["command"].endswith("scripts/hermes_score_history_retention.py --apply --days 21")


# ── 4. the fabric spec, allowlist and plan ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sid", UNBLOCKED)
def test_unblocked_step_is_a_dry_run_shadow_lane(sid):
    s = SPEC["steps"][sid]
    assert s["blocked"] is None and s["dry_run"]
    e = ALLOW[s["lane_id"]]
    assert e["live_arg"] is None and e["dry_run_arg"] == ["--dry-run"] and "--apply" not in e["command"]
    assert s["lane_id"] not in BLOCKED_REASONS


def test_self_tune_lane_runs_only_the_learn_half():
    e = ALLOW[SPEC["steps"]["autonomous_self_tune"]["lane_id"]]
    assert e["command"][-1] == "--learn" and "--purge" not in e["command"] + e["dry_run_arg"]
    assert SPEC["steps"]["autonomous_self_tune"]["lane_extra_args"] == ["--learn"]


def test_score_history_retention_stays_excluded_on_cron():
    s = SPEC["steps"]["score_history_retention"]
    assert "OPERATOR DECISION" in s["blocked"] and "stays on cron" in s["blocked"]
    assert s["lane_id"] not in ALLOW and s["lane_id"] in BLOCKED_REASONS


def test_plan_fits_the_execution_timeout_and_honours_the_wait_cap():
    plan = T.process_plan("hermes-learning", SPEC, MANIFEST)
    assert plan["worst_case_s"] <= T.PROCESS_EXECUTION_TIMEOUT_S
    steps = {s["id"]: s for st in plan["stages"] for s in st["steps"]}
    assert steps["autonomous_self_tune"]["outcome_timeout_s"] == 600
    assert all(s["max_attempts"] == 1 for s in steps.values())
    assert sum(s["worst_case_s"] for s in steps.values()) == plan["worst_case_s"] == 3580


@pytest.mark.parametrize("cap", [10_000, 30, True, "600"])
def test_outcome_timeout_cap_can_only_lower_the_wait(cap):
    spec = copy.deepcopy(SPEC)
    spec["steps"]["autonomous_self_tune"]["outcome_timeout_s"] = cap
    with pytest.raises(ValueError, match="outcome_timeout_s"):
        T.process_plan("hermes-learning", spec, MANIFEST)


def test_every_runnable_step_without_the_cap_would_not_fit():
    spec = copy.deepcopy(SPEC)
    spec["steps"]["autonomous_self_tune"].pop("outcome_timeout_s")
    with pytest.raises(ValueError, match="exceeds"):
        T.process_plan("hermes-learning", spec, MANIFEST)
