"""Useful-output proof for the 5 lanes #1831 dropped from "proven" (2026-10-16), and the bounded watchlist sweep.

The refreshed cutover measurement (#1831) counts a lane as proven only with a useful-output verdict. These five ran
live (RUN_DONE) with no output verdict, because none wrote LaneRunReceipt@v2 ``produced_count``:
crontab-snapshot-for-health-agent, n8n-incident-fanin, n8n-pilot-dispatch, n8n-research-intake-consumer,
research-insight-extractor. Each now writes the output fields and opts in (allowlist ``output_receipt: "v2"``).

As in the CW batches (#1808-#1812), every test runs the lane's REAL entry point in a fake n8n attempt (gateway, DB and
``crontab -l`` stubbed; TRADEAI_STATE_ROOT = tmp), reads the immutable per-attempt receipt and applies the executor's
``apply_output_verdict`` with the COMMITTED contract and allowlist entry. A dry run writes no receipt and prints one
``LANE_OUTPUT`` line instead.

watchlist-enrichment-sweep: the 15:30 ET 2026-10-16 live run was killed at timeout_s 900 mid-batch (RUN_TIMEOUT,
effect UNKNOWN). The sweep now starts no new batch after a wall-clock budget below the lane timeout; the symbols it
did not reach are ``deadline_deferred`` and stay stalest-first for the next run.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from tests.support import lane_produced_count as H

ROOT = Path(__file__).resolve().parents[1]
LANES = (
    "crontab-snapshot-for-health-agent",
    "n8n-incident-fanin",
    "n8n-pilot-dispatch",
    "n8n-research-intake-consumer",
    "research-insight-extractor",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


@pytest.mark.parametrize("lane", LANES)
def test_contract_evidence_names_the_lane_receipt(lane):
    """The receipt_field evidence points at <lane>_last.json, the file write_lane_receipt actually writes."""
    raw = (ROOT / "config" / "n8n_health_contracts.json").read_text()
    assert f"data/runtime/{lane}_last.json produced_count" in raw, lane


def _no_attempt_receipt(tmp_path: Path, lane: str) -> bool:
    return not (tmp_path / "data" / "runtime" / "lane_attempts" / lane).exists()


def _lane_output_line(err: str) -> dict:
    lines = [ln for ln in err.splitlines() if ln.startswith("LANE_OUTPUT ")]
    assert len(lines) == 1, err
    return json.loads(lines[0][len("LANE_OUTPUT "):])


# ── crontab-snapshot-for-health-agent ─────────────────────────────────────────────────────────────────────────────
def _crontab(text: str | None, rc: int = 0):
    def runner(argv, **_k):
        assert argv == ["crontab", "-l"]
        return types.SimpleNamespace(returncode=rc, stdout=text, stderr="" if rc == 0 else "no crontab")

    return runner


def test_crontab_snapshot_entry_runs_the_receipt_writer_with_the_same_targets():
    e = H.ALLOW["crontab-snapshot-for-health-agent"]
    assert e["command"] == ["$PY", "scripts/crontab_snapshot_lane.py"]
    assert e["live_arg"] == ["$STATE_ROOT/data/runtime/crontab_snapshot.txt"]
    assert e["dry_run_arg"] == ["--dry-run", "$STATE_ROOT/data/runtime/n8n_runs/shadow/crontab_snapshot.txt"]
    assert e["output_signal"] == "data/runtime/crontab_snapshot.txt" and e["timeout_s"] == 30


def test_crontab_snapshot_live_rewrites_the_file_and_is_produced(monkeypatch, tmp_path):
    import crontab_snapshot_lane as m

    lane = "crontab-snapshot-for-health-agent"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    target = tmp_path / "data" / "runtime" / "crontab_snapshot.txt"
    assert m.main([str(target)], runner=_crontab("*/5 * * * * true\n# note\n0 1 * * * x\n")) == 0
    assert target.read_text().startswith("*/5") and not target.with_name("crontab_snapshot.txt.tmp").exists()
    out = H.check(tmp_path, lane, run_id, produced=1, expect="produced")
    doc = H.attempt_receipt(tmp_path, lane, run_id)
    assert doc["attempted_count"] == 1 and doc["output_evidence"][0]["lines"] == 2
    assert out["output_verdict"]["produced_count"] == 1


@pytest.mark.parametrize("text,rc,reason", [(None, 1, "dependency_unavailable"), ("", 0, "no_input_unexpected")])
def test_crontab_snapshot_failure_keeps_the_last_good_file_and_fails_the_run(monkeypatch, tmp_path, text, rc, reason):
    import crontab_snapshot_lane as m

    lane = "crontab-snapshot-for-health-agent"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    target = tmp_path / "data" / "runtime" / "crontab_snapshot.txt"
    target.parent.mkdir(parents=True)
    target.write_text("last good\n")
    assert m.main([str(target)], runner=_crontab(text, rc)) == 1
    assert target.read_text() == "last good\n"
    H.check(tmp_path, lane, run_id, produced=0, expect="empty_output")
    assert H.attempt_receipt(tmp_path, lane, run_id)["skipped_reasons"] == {reason: 1}


def test_crontab_snapshot_dry_run_writes_only_the_shadow_copy_and_no_receipt(monkeypatch, tmp_path, capsys):
    import crontab_snapshot_lane as m

    lane = "crontab-snapshot-for-health-agent"
    H.attempt_env(monkeypatch, tmp_path, lane)
    shadow = tmp_path / "shadow" / "crontab_snapshot.txt"
    assert m.main(["--dry-run", str(shadow)], runner=_crontab("0 1 * * * x\n")) == 0
    assert shadow.read_text() == "0 1 * * * x\n"
    assert _no_attempt_receipt(tmp_path, lane)
    assert not (tmp_path / "data" / "runtime" / f"{lane}_last.json").exists()
    assert _lane_output_line(capsys.readouterr().err)["produced_count"] == 1


# ── shared fake gateway ───────────────────────────────────────────────────────────────────────────────────────────
class FakeGateway:
    def __init__(self, *, has_key=True, status="new", accept="ACCEPTED", items=None, list_state="OK"):
        self.url, self.has_key = "http://127.0.0.1:0", has_key
        self._status, self._accept, self._items, self._list_state = status, accept, items or [], list_state
        self.calls: list[tuple] = []

    def healthz(self):
        return {"ok": True}

    def status(self, key):
        self.calls.append(("status", key))
        if self._status == "new":
            return {"state": "REFUSED", "reason": "unknown_event"}
        return {"state": self._status}

    def accept_event(self, ev):
        self.calls.append(("accept_event", ev["idempotency_key"]))
        return {"state": self._accept}

    def transition(self, op, key, **_k):
        self.calls.append((op, key))
        return {"state": "CONSUMED" if op == "consumer_ack" else "REFUSED"}

    def call(self, op, **_k):
        return {"state": self._list_state, "items": list(self._items)}


def _walked(_client, _key, _ref):
    return [{"op": "artifact", "state": "ARTIFACT_WRITTEN"}]


# ── n8n-incident-fanin ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fanin(monkeypatch, tmp_path):
    from scripts import n8n_incident_fanin as m

    monkeypatch.setenv("TRADEAI_SERVED_SHA", "a" * 40)
    monkeypatch.setattr(m, "_flood_policy", lambda root, findings: {"applied": False, "mode": "report_only"})
    monkeypatch.setattr(m, "write_lane_registry_receipt", lambda *a, **k: None)
    monkeypatch.setattr(m, "walk_to_artifact", _walked)
    return m


def _findings(n):
    return [{"source": "breach_detector", "item": f"lane-{i}:NO_OUTPUT", "severity": "P2", "detail": "d",
             "detected_at": "2026-10-16T19:00:00+00:00", "store": "data/runtime",
             "artifact_rel": "data/runtime/x_last.json"} for i in range(n)]


@pytest.mark.parametrize("n,gateway,rc,produced,expect", [
    (2, {}, 0, 2, "produced"),
    (0, {}, 0, 0, "empty_allowed"),
    (2, {"status": "UNREACHABLE"}, 1, 0, "empty_output"),
    (0, {"has_key": False}, 0, 0, "empty_output"),
])
def test_incident_fanin(fanin, monkeypatch, tmp_path, n, gateway, rc, produced, expect):
    lane = "n8n-incident-fanin"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    gw = FakeGateway(**gateway)
    monkeypatch.setattr(fanin, "GatewayClient", lambda **_k: gw)
    monkeypatch.setattr(fanin, "collect", lambda root, now: _findings(n))
    assert fanin.main(["--apply"]) == rc
    out = H.check(tmp_path, lane, run_id, produced=produced, expect=expect)
    doc = H.attempt_receipt(tmp_path, lane, run_id)
    assert doc["attempted_count"] == n
    if expect == "empty_allowed":
        assert out["output_verdict"]["empty_reason"] == "no_new_input"
    if not gateway.get("has_key", True):
        assert out["output_verdict"]["fatal"] == ["no_credentials"]
    # the notifier's own N8nIncidentFanin@v1 receipt is unchanged in place
    assert json.loads((tmp_path / fanin.RECEIPT_REL).read_text())["schema"] == fanin.SCHEMA


def test_incident_fanin_dry_run_prints_the_fields_and_writes_nothing(fanin, monkeypatch, tmp_path, capsys):
    lane = "n8n-incident-fanin"
    H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(fanin, "GatewayClient", lambda **_k: pytest.fail("dry run built a gateway client"))
    monkeypatch.setattr(fanin, "collect", lambda root, now: _findings(3))
    assert fanin.main(["--dry-run"]) == 0
    assert _no_attempt_receipt(tmp_path, lane) and not (tmp_path / fanin.RECEIPT_REL).exists()
    got = _lane_output_line(capsys.readouterr().err)
    assert got["produced_count"] == 0 and got["attempted_count"] == 3 and got["skipped_reasons"] == {"dry_run": 3}


# ── n8n-pilot-dispatch ────────────────────────────────────────────────────────────────────────────────────────────
def _pilot_row(outcome, *, fired=True, duplicate=False):
    return {"lane_id": "morning-brief-0730", "fired": fired, "outcome": outcome,
            "ops": [{"op": "accept_event", "state": "ACCEPTED", "duplicate": duplicate}] if fired else []}


@pytest.mark.parametrize("row,rc,produced,expect,skip", [
    (_pilot_row("ARTIFACT_WRITTEN"), 0, 1, "produced", {}),
    (_pilot_row("ARTIFACT_WRITTEN", duplicate=True), 0, 0, "empty_allowed", {"duplicate_in_ledger": 1}),
    (_pilot_row("NO_FIRE", fired=False), 0, 0, "empty_allowed", {"no_fire": 1}),
    (_pilot_row("GATEWAY_UNREACHABLE"), 1, 0, "empty_output", {"dependency_unavailable": 1}),
])
def test_pilot_dispatch(monkeypatch, tmp_path, row, rc, produced, expect, skip):
    from scripts import n8n_pilot_dispatch as m

    lane = "n8n-pilot-dispatch"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setenv("TRADEAI_APPROVAL_BOARD", "0")
    monkeypatch.setenv("TRADEAI_SERVED_SHA", "a" * 40)
    monkeypatch.setattr(m, "GatewayClient", lambda **_k: FakeGateway())
    monkeypatch.setattr(m, "_db_query_factory", lambda: None)
    monkeypatch.setattr(m, "dispatch_lane", lambda lane_id, **_k: dict(row))
    assert m.main(["--apply", "--lane", "morning-brief-0730"]) == rc
    H.check(tmp_path, lane, run_id, produced=produced, expect=expect)
    assert H.attempt_receipt(tmp_path, lane, run_id)["skipped_reasons"] == skip


def test_pilot_dispatch_dry_run_prints_the_fields_and_writes_nothing(monkeypatch, tmp_path, capsys):
    from scripts import n8n_pilot_dispatch as m

    lane = "n8n-pilot-dispatch"
    H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setenv("TRADEAI_APPROVAL_BOARD", "0")
    monkeypatch.setattr(m, "_db_query_factory", lambda: None)
    monkeypatch.setattr(m, "dispatch_lane", lambda lane_id, **_k: _pilot_row("DRY_RUN"))
    assert m.main(["--dry-run", "--lane", "morning-brief-0730"]) == 0
    assert _no_attempt_receipt(tmp_path, lane)
    got = _lane_output_line(capsys.readouterr().err)
    assert got["attempted_count"] == 1 and got["skipped_reasons"] == {"dry_run": 1}


# ── n8n-research-intake-consumer ──────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def intake(monkeypatch):
    from scripts import n8n_research_intake_consumer as m

    monkeypatch.setenv("TRADEAI_SERVED_SHA", "a" * 40)
    monkeypatch.setattr(m, "walk_to_artifact", _walked)
    monkeypatch.setattr(m, "load_request", lambda root, key: {"key": key})
    return m


def _plan_rows(actions):
    def plan(items, *, already, cap, requests):
        return [{"idempotency_key": f"k{i}", "action": a, "subject": "ai-infra", "requested_by": "operator",
                 "request_type": "topic", **({"reason": "typed_refusal:unknown_topic"} if a == "refuse" else {})}
                for i, a in enumerate(actions)]

    return plan


@pytest.mark.parametrize("actions,enq,produced,expect,skip", [
    (["enqueue", "refuse"], {"ok": True, "queued": True, "queue_id": 7}, 1, "produced", {"refused_unknown_topic": 1}),
    ([], None, 0, "empty_allowed", {}),
    (["enqueue"], {"ok": True, "queued": False, "already": True, "queue_id": 7}, 0, "empty_allowed",
     {"already_queued": 1}),
])
def test_research_intake_consumer(intake, monkeypatch, tmp_path, actions, enq, produced, expect, skip):
    lane = "n8n-research-intake-consumer"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(intake, "plan", _plan_rows(actions))
    gw = FakeGateway(items=[{"idempotency_key": f"k{i}", "state": "ACCEPTED"} for i in range(len(actions))])
    assert intake.main(["--apply"], client=gw, enqueue=lambda topic, by: dict(enq or {})) == 0
    H.check(tmp_path, lane, run_id, produced=produced, expect=expect)
    doc = H.attempt_receipt(tmp_path, lane, run_id)
    assert doc["skipped_reasons"] == skip and doc["attempted_count"] == len(actions)


def test_research_intake_consumer_apply_without_a_gateway_key_is_a_fatal_skip(intake, monkeypatch, tmp_path):
    lane = "n8n-research-intake-consumer"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(intake, "GatewayClient", lambda **_k: FakeGateway(has_key=False))
    assert intake.main(["--apply"], enqueue=lambda *a: pytest.fail("enqueued without a gateway")) == 0
    out = H.check(tmp_path, lane, run_id, produced=0, expect="empty_output")
    assert out["output_verdict"]["fatal"] == ["no_credentials"]


def test_research_intake_consumer_dry_run_prints_the_fields_and_writes_nothing(intake, monkeypatch, tmp_path, capsys):
    lane = "n8n-research-intake-consumer"
    H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(intake, "plan", _plan_rows(["enqueue"]))
    gw = FakeGateway(items=[{"idempotency_key": "k0", "state": "ACCEPTED"}])
    assert intake.main(["--dry-run"], client=gw, enqueue=lambda *a: pytest.fail("dry run enqueued")) == 0
    assert _no_attempt_receipt(tmp_path, lane) and not (tmp_path / intake.RECEIPT_REL).exists()
    got = _lane_output_line(capsys.readouterr().err)
    assert got["attempted_count"] == 1 and got["skipped_reasons"] == {"dry_run": 1}


# ── research-insight-extractor ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def rie(monkeypatch):
    import research_insight_extractor as m

    return m


def _extract(n, *, short=0, failed=0, dry=False):
    def fn(dry_run=False, errors=None, skips=None, limit=100):
        if skips is not None and short:
            skips["text_too_short"] = skips.get("text_too_short", 0) + short
        if errors is not None:
            errors.extend(f"news:{i}: RuntimeError" for i in range(failed))
        return [{"id": None if dry_run else 100 + i} for i in range(n)]

    return fn


@pytest.mark.parametrize("news,cats,short,failed,rc,produced,expect", [
    (3, 2, 1, 0, 0, 5, "produced"),
    (0, 0, 2, 0, 0, 0, "empty_allowed"),
    (0, 0, 0, 2, 1, 0, "empty_output"),
])
def test_research_insight_extractor(rie, monkeypatch, tmp_path, news, cats, short, failed, rc, produced, expect):
    lane = "research-insight-extractor"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(rie, "extract_from_news", _extract(news, short=short, failed=failed))
    monkeypatch.setattr(rie, "extract_from_catalysts", _extract(cats))
    assert rie.run_default(dry_run=False) == rc
    H.check(tmp_path, lane, run_id, produced=produced, expect=expect)
    doc = H.attempt_receipt(tmp_path, lane, run_id)
    assert doc["attempted_count"] == news + cats + failed
    if short:
        assert doc["skipped_reasons"]["text_too_short"] == short


def test_research_insight_extractor_crash_is_a_fatal_skip(rie, monkeypatch, tmp_path):
    lane = "research-insight-extractor"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)

    def boom(**_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rie, "extract_from_news", boom)
    with pytest.raises(RuntimeError):
        rie.run_default(dry_run=False)
    out = H.check(tmp_path, lane, run_id, produced=0, expect="empty_output")
    assert out["output_verdict"]["why"] == "receipt_status_failed"
    assert out["output_verdict"]["skipped_reasons"] == {"dependency_unavailable": 1}


def test_research_insight_extractor_dry_run_prints_the_fields_and_writes_nothing(rie, monkeypatch, tmp_path, capsys):
    lane = "research-insight-extractor"
    H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(rie, "extract_from_news", _extract(4))
    monkeypatch.setattr(rie, "extract_from_catalysts", _extract(1))
    assert rie.run_default(dry_run=True) == 0
    assert _no_attempt_receipt(tmp_path, lane)
    got = _lane_output_line(capsys.readouterr().err)
    assert got == {"produced_count": 0, "attempted_count": 5, "skipped_reasons": {"dry_run": 5}, "empty_reason": None}


def test_research_insight_extractor_without_an_env_file_lets_libpq_find_the_password(rie, monkeypatch, tmp_path):
    """A checkout with no .env no longer crashes before connecting; no password argument is passed."""
    seen = {}
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setattr(rie, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **k: seen.update(k) or "conn"))
    assert rie._get_conn() == "conn"
    assert "password" not in seen and seen["user"] == "trade_ai"


# ── watchlist-enrichment-sweep: bounded run ───────────────────────────────────────────────────────────────────────
class _Cur:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 0

    def execute(self, sql, params=None):
        self.rowcount = 1 if sql.lstrip().startswith("UPDATE") else 0
        if self.rowcount:
            self.conn.updated.append(params[-1])

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.updated: list[str] = []
        self.commits = 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def sweep(monkeypatch):
    import watchlist_enrichment_sweep as m

    conn = _Conn()
    synced: list[list[str]] = []
    monkeypatch.setattr(m, "_conn", lambda: conn)
    monkeypatch.setitem(sys.modules, "finviz_enrichment", types.SimpleNamespace(
        enrich_tickers=lambda batch, project_root=None: None,
        get_enriched=lambda s, project_root=None: {"rsi": "50", "sma50_pct": "1", "sma200_pct": "2"}))
    monkeypatch.setitem(sys.modules, "open_trades_intelligence", types.SimpleNamespace(_trend_label=lambda a, b: "up"))
    monkeypatch.setitem(sys.modules, "setup_quality_prior", types.SimpleNamespace(rsi_band=lambda r: "mid"))
    monkeypatch.setitem(sys.modules, "directive_promotion", types.SimpleNamespace(classify_tradeable=lambda s, t: []))
    monkeypatch.setitem(sys.modules, "price_db_sync",
                        types.SimpleNamespace(sync_quotes_to_ticker_prices=lambda syms: synced.append(list(syms))))
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(
        Ticker=lambda s: types.SimpleNamespace(info={})))
    return types.SimpleNamespace(m=m, conn=conn, synced=synced)


def _ticking(step):
    t = [0.0]

    def clock():
        t[0] += step
        return t[0]

    return clock


def test_sweep_starts_no_batch_after_the_deadline_and_defers_the_rest(sweep):
    syms = [f"S{i:02d}" for i in range(40)]  # 3 batches of 15
    res = sweep.m.enrich_symbols(syms, deadline=2.5, clock=_ticking(2.0))
    # batch 1 always runs; the clock reads 2.0 before batch 2 (< 2.5) and 4.0 before batch 3 (>= 2.5)
    assert res["enriched"] == 30 and res["deferred"] == 10
    assert sweep.conn.updated == syms[:30] and sweep.conn.commits == 2  # each finished batch is committed
    assert sweep.synced == [syms[:30]]  # ticker_prices sync covers only the symbols reached


def test_sweep_without_a_deadline_is_unchanged(sweep):
    syms = [f"S{i:02d}" for i in range(40)]
    res = sweep.m.enrich_symbols(syms)
    assert res["enriched"] == 40 and res["deferred"] == 0 and sweep.synced == [syms]


def test_deferred_symbols_are_a_typed_non_fatal_skip_and_the_run_is_produced(sweep, monkeypatch, tmp_path):
    lane = "watchlist-enrichment-sweep"
    run_id = H.attempt_env(monkeypatch, tmp_path, lane)
    monkeypatch.setattr(sweep.m, "sweep", lambda limit=None, dry=False, budget_s=None: {
        "total": 165, "enriched": 120, "deferred": 45})
    assert sweep.m.main(["--once"]) == 0
    H.check(tmp_path, lane, run_id, produced=120, expect="produced")
    doc = H.attempt_receipt(tmp_path, lane, run_id)
    assert doc["skipped_reasons"] == {"deadline_deferred": 45, "not_enriched": 0}
    assert doc["summary"]["deferred"] == 45


def test_sweep_budget_fits_inside_the_lane_timeout():
    """600 s budget + the worst measured single batch (186 s, logs/watchlist_sweep.log 2026-10-14..16) + margin must
    end before the executor's `timeout -k 30 <timeout_s>` kill."""
    import watchlist_enrichment_sweep as m

    timeout_s = H.ALLOW["watchlist-enrichment-sweep"]["timeout_s"]
    assert m.DEFAULT_BUDGET_S + 186 + 60 <= timeout_s
    assert "--budget-s" not in H.ALLOW["watchlist-enrichment-sweep"]["command"]  # same argv as the cron line


def test_sweep_main_passes_the_budget_through(sweep, monkeypatch, tmp_path):
    H.attempt_env(monkeypatch, tmp_path, "watchlist-enrichment-sweep")
    seen = {}

    def fake(limit=None, dry=False, budget_s=None):
        seen["budget_s"] = budget_s
        return {"total": 1, "enriched": 1, "deferred": 0}

    monkeypatch.setattr(sweep.m, "sweep", fake)
    assert sweep.m.main(["--once"]) == 0 and seen["budget_s"] == sweep.m.DEFAULT_BUDGET_S
    assert sweep.m.main(["--once", "--budget-s", "0"]) == 0 and seen["budget_s"] == 0
