"""Rebuild of closed PR #1417 (operator 2026-10-21: "yes rebuild 1417"). Cron freeze: no crontab line.

1. Plan expiry: the premarket pipeline step ``cio_draft_plan_hygiene`` runs ``--apply --expire-stale``; the sweep
   appends ``expired`` status events (never deletes) and its dry run writes nothing.
2. ``cio-portfolio-thesis`` and ``advisory-maturity-evidence`` are n8n-native dispatcher lanes at stage shadow:
   write-free ``--dry-run``, LaneRunReceipt on a live run, allowlist ``live_arg`` null, a DRAFT health contract,
   and no forbidden capability in their import closure (the thesis materializer no longer imports api_v3_cio).

Every test uses tmp_path stores and injected inputs; nothing touches the live DB, n8n or the host.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.cio_plans import CIOPlanStore  # noqa: E402
from scripts.pipelines import pipeline_manifest as pm  # noqa: E402

LANES = ("cio-portfolio-thesis", "advisory-maturity-evidence")
SCRIPTS = {
    "cio-portfolio-thesis": "scripts/materialize_cio_portfolio_thesis.py",
    "advisory-maturity-evidence": "scripts/refresh_advisory_maturity_evidence.py",
}


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


# ── 1. plan expiry in the premarket pipeline ──────────────────────────────────────────────────────────────────


def test_premarket_hygiene_step_runs_expire_stale_and_manifest_is_valid():
    manifest = pm.load(ROOT / "config" / "pipelines" / "premarket.json")
    assert pm.validate(manifest) == []
    steps = [st for stage in manifest["stages"].values() for st in stage["steps"] if st["id"] == "cio_draft_plan_hygiene"]
    assert len(steps) == 1
    cmd = steps[0]["command"]
    assert "scripts/cio_draft_plan_hygiene.py --apply --expire-stale" in cmd
    assert "/tmp/cio_draft_hygiene.lock" in cmd  # same lock as the retired line
    assert "1417" in steps[0]["note"]


T0 = datetime.now(timezone.utc)
NOW = T0 + timedelta(days=60)


def _plan(store: CIOPlanStore, symbol: str, status: str = "draft") -> str:
    return store.create_plan(
        situation_type="S3_REENTRY_CANDIDATE", symbols=[symbol], title=f"re-entry {symbol}",
        options=[{"id": "wait", "label": "Wait"}], recommendation="wait",
        evidence_refs=[{"domain": "reentry"}], revisit_at=(T0 + timedelta(days=1)).isoformat(),
        owner_agent="steph", status=status,
    )["plan_id"]


def test_expire_stale_apply_is_append_only_and_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    import scripts.lib.cio_plan_expiry as cpe
    import scripts.lib.cio_plans as plans_mod

    store = CIOPlanStore(tmp_path / "plans.jsonl", tmp_path / "plans_projection.json")
    ids = {"draft": _plan(store, "AAA"), "proposed": _plan(store, "BBB", "proposed"),
           "accepted": _plan(store, "CCC", "accepted")}
    # Evaluate the rule 60 days on, so the 1-day revisit is past the 14-day grace.
    real_cands, real_reason = cpe.expiry_candidates, cpe.expiry_reason
    monkeypatch.setattr(cpe, "expiry_candidates", lambda plans, now, grace_days: real_cands(plans, now=NOW, grace_days=grace_days))
    monkeypatch.setattr(cpe, "expiry_reason", lambda plan, now, grace_days: real_reason(plan, now=NOW, grace_days=grace_days))
    monkeypatch.setattr(plans_mod, "CIOPlanStore", lambda *a, **k: store)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    hygiene = _load("scripts/cio_draft_plan_hygiene.py", "cio_draft_plan_hygiene_1417")

    log = tmp_path / "plans.jsonl"
    before = log.read_bytes()
    assert hygiene.main(["--apply", "--expire-stale", "--dry-run"]) == 0  # --dry-run wins
    assert "stale_expiry would_expire=2" in capsys.readouterr().out
    assert log.read_bytes() == before
    assert not (tmp_path / "data").exists() and not (tmp_path / "state").exists()

    assert hygiene.main(["--apply", "--expire-stale"]) == 0
    assert "stale_expiry would_expire=2 expired=2" in capsys.readouterr().out
    after = log.read_bytes()
    assert after.startswith(before) and len(after) > len(before)  # appended, nothing rewritten or deleted
    assert store.get_plan(ids["draft"])["status"] == "expired"
    assert store.get_plan(ids["proposed"])["status"] == "expired"
    assert store.get_plan(ids["accepted"])["status"] == "accepted"
    receipt = [json.loads(x) for x in (tmp_path / "data/cio/cio_plan_expiry_receipts.jsonl").read_text().splitlines()]
    assert len(receipt) == 1 and receipt[0]["expired"] == 2
    lane = json.loads((tmp_path / "state/data/runtime/cio-draft-plan-hygiene_last.json").read_text())
    assert lane["status"] == "ok" and lane["summary"]["stale_expired"] == 2


def test_plan_store_expiry_never_deletes():
    src = (ROOT / "scripts" / "expire_stale_cio_plans.py").read_text(encoding="utf-8")
    lib = (ROOT / "scripts" / "lib" / "cio_plans.py").read_text(encoding="utf-8")
    for token in ("unlink(", "os.remove", "rmtree", "truncate("):
        assert token not in src and token not in lib, token


# ── 2a. registry, allowlist, contract shape ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_n8n_native_shadow_dry_run(lane):
    from scripts.lib import lane_dispatch as LD
    from scripts.lib.lane_stage_clamp import clamp_mode

    rows = _json("config/lane_registry.json")["lanes"]
    row = next(r for r in rows if r["lane_id"] == lane)
    sched = row["scheduler"]
    assert (sched["kind"], sched["expression"], sched["stage"]) == ("n8n", "dispatcher", "shadow")
    assert row["dispatch"]["mode"] == "dry_run" and row["dispatch"]["cron"] == [sched["cadence"]]
    assert row["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
    assert LD.validate_dispatch_block(row) == []
    assert clamp_mode(lane, "live", rows)["effective_mode"] == "dry_run"

    entry = next(e for e in _json("config/n8n_run_allowlist.json")["lanes"] if e["lane_id"] == lane)
    assert entry["command"] == ["$PY", SCRIPTS[lane]]
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None
    assert entry["output_signal"] == row["output_signal"]["path"]
    assert not any(n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR")) for n in entry["env_names"])

    contract = next(c for c in _json("config/n8n_health_contracts.json")["contracts"] if c["id"] == lane)
    # DRAFT until the owner reviews it (AGENTS.md §23.19); the operator moves it to REVIEWED.
    assert contract["status"] == "DRAFT" and contract["stage"] == "shadow" and contract["owner"] == "cio"


def test_cadences_match_1417():
    rows = {r["lane_id"]: r for r in _json("config/lane_registry.json")["lanes"]}
    assert rows["cio-portfolio-thesis"]["scheduler"]["cadence"] == "47 17 * * 1-5"
    assert rows["advisory-maturity-evidence"]["scheduler"]["cadence"] == "17 6 * * *"


@pytest.mark.parametrize("lane", LANES)
def test_no_forbidden_capability_in_import_closure(lane):
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver(ROOT)
    order, _parent = res.closure(ROOT / SCRIPTS[lane])
    caps = set().union(*(res.info(m).caps for m in order))
    assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, caps
    assert "scripts/api_v3_cio.py" not in {res.info(m).path for m in order}


def test_thesis_inputs_use_the_api_env_overrides():
    api = (ROOT / "scripts" / "api_v3_cio.py").read_text(encoding="utf-8")
    lib = (ROOT / "scripts" / "lib" / "cio_portfolio_thesis_inputs.py").read_text(encoding="utf-8")
    for name in ("CIO_OPERATOR_PROFILE_JSONL", "TRADEAI_HOLDINGS_JSON", "CIO_CASH_EVIDENCE_JSON",
                 "CIO_PORTFOLIO_THESIS_JSONL", "CIO_THESES_PROJECTION_JSON", "CIO_CANON_CLAIMS_JSONL"):
        assert name in api and name in lib, name


# ── 2b. cio-portfolio-thesis: dry run writes nothing; live run publishes once ─────────────────────────────────


@pytest.fixture
def thesis(monkeypatch, tmp_path):
    from scripts.lib import cio_portfolio_thesis_inputs as inputs

    policy = {"status": "POLICY_REQUIRED", "version": "policy_v1", "content_hash": "p1", "fields": {}}
    portfolio = {"version": "portfolio_v1", "truth_quality": "UNVERIFIED_INVESTABLE", "observed_cash_usd": 1000.0,
                 "investable_cash_usd": None, "conflicted_position_count": 0, "positions": [],
                 "allocation": {"cash": {"pct": 50.0}, "equity": {"pct": 50.0}, "fixed_income": {"pct": 0.0}}}
    monkeypatch.setattr(inputs, "load_policy", lambda: policy)
    monkeypatch.setattr(inputs, "load_portfolio_state", lambda: portfolio)
    monkeypatch.setattr(inputs, "load_market_context", lambda: {"version": "m1", "truth_quality": "PARTIAL", "fields": {}})
    monkeypatch.setattr(inputs, "load_seasonality", lambda: {"version": "s1", "truth_quality": "UNAVAILABLE"})
    monkeypatch.setattr(inputs, "ratified_methodology_refs", lambda: [])
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    mod = _load(SCRIPTS["cio-portfolio-thesis"], "materialize_cio_portfolio_thesis_1417")
    store = tmp_path / "cio" / "theses.jsonl"
    args = ["--store", str(store), "--symbol-projection", str(tmp_path / "missing_projection.json")]
    return mod, store, args, tmp_path / "state" / "data" / "runtime" / "cio-portfolio-thesis_last.json"


def test_thesis_dry_run_writes_nothing(thesis, capsys):
    mod, store, args, receipt = thesis
    assert mod.main(args + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    line = json.loads(out.split("DRY-RUN ", 1)[1])
    assert line["summary"]["would_publish"] is True and line["would_write"]
    assert not store.parent.exists()  # no mkdir, no lock file, no append
    assert not receipt.exists()


def test_thesis_live_run_publishes_once_then_no_new_info(thesis):
    mod, store, args, receipt = thesis
    assert mod.main(args) == 0
    assert len(store.read_text().splitlines()) == 1
    first = json.loads(receipt.read_text())
    assert first["status"] == "ok" and first["produced_count"] == 1
    assert mod.main(args) == 0
    assert len(store.read_text().splitlines()) == 1  # idempotent
    second = json.loads(receipt.read_text())
    assert second["produced_count"] == 0 and second["empty_reason"] == "no_new_input"
    # dry run after publication: nothing new to publish, still writes nothing
    before = store.read_bytes()
    assert mod.main(args + ["--dry-run"]) == 0
    assert store.read_bytes() == before


def test_thesis_failure_writes_failed_receipt(thesis, monkeypatch):
    mod, _store, args, receipt = thesis
    from scripts.lib import cio_portfolio_thesis_inputs as inputs

    monkeypatch.setattr(inputs, "load_policy", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert mod.main(args) == 1
    assert json.loads(receipt.read_text())["status"] == "failed"


# ── 2c. advisory-maturity-evidence: dry run writes nothing; live run writes four snapshots ────────────────────


@pytest.fixture
def evidence(monkeypatch, tmp_path):
    from scripts import refresh_advisory_maturity_evidence as ev

    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "collect", lambda **_k: {name: {"schema": "x", "integrity_score": 1.0} for name in ev.SNAPSHOTS})
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return ev, tmp_path / "state" / "data" / "runtime" / "advisory-maturity-evidence_last.json"


def test_evidence_dry_run_writes_nothing(evidence, tmp_path, capsys):
    ev, receipt = evidence
    assert ev.main(["--dry-run"]) == 0
    assert "DRY-RUN " in capsys.readouterr().out
    assert not (tmp_path / "data").exists() and not receipt.exists()


def test_evidence_live_run_writes_snapshots_and_receipt(evidence, tmp_path, monkeypatch):
    ev, receipt = evidence

    def refresh(**_k):
        rows = ev.collect()
        for name, row in rows.items():
            ev._atomic_json(tmp_path / ev.OUT_DIR / name, row)
        return {"ok": True, "as_of": "t", "artifacts": rows}

    monkeypatch.setattr(ev, "refresh", refresh)
    assert ev.main([]) == 0
    assert sorted(p.name for p in (tmp_path / "data" / "cio").iterdir()) == sorted(ev.SNAPSHOTS)
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "ok" and doc["produced_count"] == 4


def test_evidence_env_read_is_bounded_to_db_names(tmp_path, monkeypatch):
    from scripts import refresh_advisory_maturity_evidence as ev

    (tmp_path / ".env").write_text("DB_HOST=h\nSCHWAB_APP_KEY=k\nTELEGRAM_BOT_TOKEN=t\nDB_PASSWORD='p'\n")
    for k in list(ev._ENV_KEYS) + ["SCHWAB_APP_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DB_NAME", "n")
    got = ev._env_values(tmp_path)
    assert got == {"DB_HOST": "h", "DB_PASSWORD": "p", "DB_NAME": "n"}
