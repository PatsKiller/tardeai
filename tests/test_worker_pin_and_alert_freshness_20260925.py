"""Worker pin check + watch-alert quote freshness + case recorder dry run."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_worker_pins as W  # noqa: E402

SERVED = "1c60ecb4264ba4dcc6a38106e76fae0d96a26787"
_REAL_SERVED_SHA = W.served_sha  # the real reader; _rows() points it at a fixture CURRENT
DEV = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")


def _rows(dev_sha, monkeypatch, tmp_path):
    W._DEV_SHA_CACHE[str(DEV)] = dev_sha
    # Pin the served release to a fixture instead of the host's live CURRENT symlink: a
    # "cd …/portfolio-server/CURRENT" cron row resolves through served_sha(), and the real
    # CURRENT moves on every promote (it broke this test when 35146acba went live).
    fixture_release = tmp_path / f"{SERVED[:9]}-main-exact-fixture"
    fixture_release.mkdir(exist_ok=True)
    (fixture_release / "SOURCE_COMMIT").write_text(SERVED + "\n", encoding="utf-8")
    fixture_current = tmp_path / "CURRENT"
    if not fixture_current.is_symlink():
        fixture_current.symlink_to(fixture_release)
    monkeypatch.setattr(W, "served_sha", lambda current=None: _REAL_SERVED_SHA(fixture_current))
    cron = (
        "0 10-15 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && bash linux_launchers/reconcile_alpaca_paper_options.sh\n"
        "*/5 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && .venv/bin/python scripts/cio_wake_dispatch_entrypoint.py\n"
        "# 20 18 * * * cd CURRENT && python scripts/sweep_commitment_outcomes.py\n"
    )
    units = [{"kind": "unit", "name": "portfolio-server.service", "active": "active",
              "path": f"/home/johnclaw/trade-ai-releases/portfolio-server/{SERVED[:9]}-main-exact-phase2-20260925-091436",
              **W.tree_of(f"/home/johnclaw/trade-ai-releases/portfolio-server/{SERVED[:9]}-main-exact-phase2-20260925-091436")},
             {"kind": "unit", "name": "tradeai-cio-telegram.service", "active": "active",
              "path": "/home/johnclaw/trade-ai-releases/portfolio-server/8a9222cc6-main-exact-phase2-20260925-081649",
              **W.tree_of("/home/johnclaw/trade-ai-releases/portfolio-server/8a9222cc6-main-exact-phase2-20260925-081649")}]
    return units + W.cron_rows(cron)


def test_worker_sha_mismatch_detected_for_stale_unit_and_diverged_dev_tree(monkeypatch, tmp_path):
    rep = W.evaluate(served=SERVED, rows=_rows("8a95e30c1000000000000000000000000000000", monkeypatch, tmp_path))
    assert rep["ok"] is False
    names = {m["name"]: m["verdict"] for m in rep["mismatches"]}
    assert names["tradeai-cio-telegram.service"] == "MISMATCH"           # bot still on the previous release
    assert names["reconcile_alpaca_paper_options"] == "DEV_TREE_DIVERGED"  # launcher hard-codes the dev tree
    assert "cio_wake_dispatch_entrypoint" not in names                    # CURRENT cron is fine


def test_dev_tree_worker_same_sha_passes_with_a_hazard_note(monkeypatch, tmp_path):
    rep = W.evaluate(served=SERVED, rows=_rows(SERVED, monkeypatch, tmp_path))
    assert rep["ok"] is False                                              # the bot mismatch still fails
    rows = {r["name"]: r["verdict"] for r in rep["rows"]}
    assert rows["reconcile_alpaca_paper_options"] == "DEV_TREE_SAME_SHA"
    assert "reconcile_alpaca_paper_options" in rep["dev_tree_workers"]
    rep2 = W.evaluate(served=SERVED, rows=[r for r in _rows(SERVED, monkeypatch, tmp_path) if r["name"] != "tradeai-cio-telegram.service"])
    assert rep2["ok"] is True and "diverge" in rep2["note"]


def test_watch_alert_eval_skips_stale_quote(monkeypatch):
    import watch_alerts_eval as E
    calls = []

    def ex(sql, params=None, fetch=None):
        calls.append(sql.split()[0] + ":" + sql[:40])
        if "FROM alert_events" in sql:
            return None
        if "FROM market_quotes" in sql:
            return {"price": 33.90, "fetched_at": "2026-09-18T15:59:00-04:00"}   # a week-old print
        return None
    alerts = [{"id": 5, "symbol": "SCHD", "condition_type": "price_cross_above", "threshold": 33.85,
               "recurring": False, "last_fired_at": None}]
    lines, fired = E._evaluate_single_condition_alerts(ex, alerts, "2026-09-25")
    assert fired == [] and lines == []
    assert not any(c.startswith("INSERT") for c in calls)
    assert E._quote_is_current("2026-09-18T15:59:00-04:00") is False


def test_case_recorder_dry_run_writes_nothing_and_apply_writes_one_linked_row(tmp_path):
    spec = {"symbol": "SCHD", "served_sha": SERVED, "answering_tree": "CURRENT",
            "lineage": {"inbound_channel": "openclaw:maria", "inbound_message_ref": "maria-session:ddac33e0…#4",
                        "inbound_at": "2026-09-25T14:48:39Z", "outbound_at": "2026-09-25T14:49:02Z",
                        "producer_chain": ["maria_parity_hook.try_shared_perspective_entry", "operator_internal_first.answer_internal_first",
                                           "cio_operator_desk_loop.handle_operator_desk_question", "cio_telegram_converse.format_reentry_symbol_reply"],
                        "prose_author": "deepseek-v4-pro via OpenClaw maria"},
            "plan": {"plan_id": 19648, "created_at": "2026-09-15T18:51:22-04:00", "stop": 33.55},
            "quotes": {"desk": {"price": 33.12, "as_of": "2026-09-25T10:30:06-04:00"}, "operator": {"price": 33.68}},
            "integrity": {"state": "INVALIDATED_BY_PRICE_OR_STOP"}, "defects": ["plan shown as actionable below stop"],
            "corrected_answer": "Monitor / no action — see incident report."}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    store = tmp_path / "cases.jsonl"
    cmd = [sys.executable, str(ROOT / "scripts" / "record_decision_integrity_case.py"), "--spec", str(tmp_path / "spec.json"), "--path", str(store)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0 and "DRY RUN" in r.stderr and not store.exists()
    payload = json.loads(r.stdout)["payload"]
    assert payload["case_type"] == "watch_contradiction" and payload["lineage"]["prose_author"].startswith("deepseek")
    assert "trade_outcome" in payload["not_evidence_of"]
    r2 = subprocess.run(cmd + ["--apply"], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    rows = [json.loads(l) for l in store.read_text().splitlines() if l.strip()]
    assert len(rows) == 1 and rows[0]["payload"]["symbol"] == "SCHD"
