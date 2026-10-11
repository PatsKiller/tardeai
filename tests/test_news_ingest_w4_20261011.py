"""News ingest joins W4 (operator ruling 2026-10-11): lane contract of scripts/news_ingestion.py + its shadow rows.

COVERS = ["scripts/news_ingestion.py", "scripts/hermes_source_policy.py", "scripts/reconcile_lane_registry.py",
          "config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

Before this PR scripts/news_ingestion.py had no --dry-run and an unknown flag fell through to the live --priority
branch (:592-594 on e24ccd6c5), so a dispatcher "--dry-run" would have ingested for real; it wrote no LaneRunReceipt;
and the per-article source-policy lookup (hermes_source_policy._db_rows) copied EVERY name in the checkout .env into
os.environ, broker pairs included. The failures this guards against:

* a cron line whose live behaviour changed: every cron argv (L193, L649, L650 on 2026-10-11) and every in-repo caller
  argv must reach ingest() with the same arguments, the same pipeline_runs calls and the same stdout as the pre-W4
  dispatch (a verbatim copy below);
* a dry run that reaches run_start, the DB, a provider, the .env or any file write;
* an unknown or abbreviated flag that runs anything (argparse error, exit 2);
* a real lane run without a receipt, a failed run that advances ok_at, a manual run that refreshes a lane receipt;
* the lane process carrying a broker credential name from the .env (§23.18 ruling 3);
* a registry row that the R1 gate refuses, a live argv at shadow, a match that hits more than its own line, a
  contract that is not REVIEWED, a KEEP_ON_CRON the next reconcile would put back.

Hermetic: TRADE_AI_CI=1, tmp state roots, fakes for ingest / pipeline_registry / the network; repo config read only.
MBI_BEHAVIOR = 0: no broker, order or send path.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import types
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_source_policy as hsp  # noqa: E402
import news_ingestion as ni  # noqa: E402

from scripts import reconcile_lane_registry as R  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
SNAPSHOT = json.loads((ROOT / "docs" / "implementation" / "n8n-maturity" / "data" /
                       "scheduler_snapshot_20261009.json").read_text())

#: crontab -l on 2026-10-11 (read-only): line number -> command after the schedule.
CRON = {
    193: ("30 12 * * 1-5", "cd $PROJ && $PY scripts/news_ingestion.py --priority >> logs/news_ingestion.log 2>&1"),
    649: ("30 0 * * *", "cd $PROJ && flock -n /tmp/news_priority_overnight.lock timeout 45m $PY "
                        "scripts/news_ingestion.py --priority >> logs/news_ingestion.log 2>&1"),
    650: ("0 10,14,18 * * 0,6", "cd $PROJ && flock -n /tmp/news_tail_rotate.lock timeout 90m $PY "
                                "scripts/news_ingestion.py --tail-rotate >> logs/news_ingestion.log 2>&1"),
}
#: lane_id -> (cron line, receipt the row reads, lock, lock already on the cron line?)
LANES = {
    "news-ingestion": (193, "data/runtime/news-ingestion_last.json", "/tmp/news_priority_overnight.lock", False),
    "news-ingestion-overnight": (649, "data/runtime/news-ingestion_last.json", "/tmp/news_priority_overnight.lock",
                                 True),
    "news-ingestion-tail": (650, "data/runtime/news-ingestion-tail_last.json", "/tmp/news_tail_rotate.lock", True),
}


def cron_argv(text: str) -> list[str]:
    """The script's own argv in a cron command: the words after scripts/news_ingestion.py, up to the redirect."""
    words = text.split()
    i = words.index("scripts/news_ingestion.py")
    out = []
    for w in words[i + 1:]:
        if w.startswith(">") or w in ("2>&1", "|", "&&", ";"):
            break
        out.append(w)
    return out


#: Every argv the script is started with: the three cron lines plus the in-repo callers (api_v2 :9837,
#: remediate_watchlist_news_guard :76/:80, agent_event_router :244, watch_decision_refresh :184, the health
#: remediation command, pipeline_controller.bootstrap.yaml) and the documented legacy forms.
CALLER_ARGVS = [
    ["--symbol", "AAPL", "--json"], ["--symbol", "aapl"], ["--symbol", " msft "], ["--priority"], ["--full"],
    ["--full", "--json"], ["--tail-rotate", "--json"], ["--priority", "--json"], [],
    ["--symbol", "NVDA", "--tail-rotate"],
    # precedence pins: --symbol, then --tail-rotate, then --full, else priority
    ["--tail-rotate", "--full"], ["--full", "--tail-rotate"], ["--full", "--priority"], ["--json", "--symbol", "x", "--full"],
]
ALL_ARGVS = [cron_argv(t) for _s, t in CRON.values()] + CALLER_ARGVS


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────────

class Calls(list):
    def rec(self, *a, **k):
        self.append((a, k))


def fake_registry(calls: Calls, *, run_id="run-1"):
    mod = types.ModuleType("pipeline_registry")
    mod.run_start = lambda name: (calls.rec("run_start", name), run_id)[1]
    mod.run_complete = lambda rid, rows_processed=None: calls.rec("run_complete", rid, rows_processed=rows_processed)
    mod.run_fail = lambda rid, err: calls.rec("run_fail", rid, err)
    return mod


def fake_ingest(calls: Calls, *, raises: Exception | None = None):
    def ingest(*a, **k):
        calls.rec("ingest", *a, **k)
        if raises:
            raise raises
        mode = k.get("mode", "priority")
        return {"scanned": 3, "new_articles": 2, "skipped_symbol_mismatch": 0, "by_source": {"yahoo_rss": 2},
                "mode": mode, **({"offset": 5, "next_offset": 8, "tail_size": 20} if mode == "tail_rotate" else {})}
    return ingest


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(hsp, "ENV_LOAD_KEYS", hsp.ENV_LOAD_KEYS)  # restored after each test
    monkeypatch.setattr(ni, "ROTATION_FILE", tmp_path / "rotation" / "news_ingest_rotation.json")


def legacy_main(argv: list[str], ingest, registry) -> None:
    """The pre-W4 ``__main__`` of scripts/news_ingestion.py (e24ccd6c5 :570-610), verbatim but for injection."""
    sys_argv = ["scripts/news_ingestion.py", *argv]
    _run_id = None
    try:
        _run_id = registry.run_start("news_ingestion")
    except Exception:
        pass
    try:
        single = None
        for i, arg in enumerate(sys_argv):
            if arg == "--symbol" and i + 1 < len(sys_argv):
                single = sys_argv[i + 1].strip().upper()
                break
        if single:
            result = ingest(mode="priority", single_symbol=single)
        elif "--tail-rotate" in sys_argv:
            result = ingest(mode="tail_rotate")
        elif "--full" in sys_argv:
            result = ingest(mode="full")
        else:
            result = ingest(mode="priority")
        if "--json" in sys_argv:
            print(json.dumps(result, indent=2, default=str))
        if _run_id:
            registry.run_complete(_run_id, rows_processed=result.get("new_articles", 0))
    except Exception as _e:
        if _run_id:
            registry.run_fail(_run_id, str(_e))
        raise


def run_new(monkeypatch, argv, *, raises=None):
    calls = Calls()
    monkeypatch.setitem(sys.modules, "pipeline_registry", fake_registry(calls))
    monkeypatch.setattr(ni, "ingest", fake_ingest(calls, raises=raises))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ni.main(list(argv))
    return rc, calls, buf.getvalue()


# ── the script: live behaviour of every existing invocation is unchanged ───────────────────────────────

def test_the_cron_argvs_are_the_three_live_lines():
    assert [cron_argv(t) for _s, t in CRON.values()] == [["--priority"], ["--priority"], ["--tail-rotate"]]
    for lane, (line, *_rest) in LANES.items():
        sched, text = CRON[line]
        assert ROWS[lane]["scheduler"]["command_text"] == text and ROWS[lane]["scheduler"]["expression"] == sched
        snap = [c["line"] for c in SNAPSHOT["cron_lines"] if c["line"] == f"{sched} {text}"]
        assert len(snap) == 1, lane  # the committed scheduler snapshot carries the same live line


@pytest.mark.parametrize("argv", ALL_ARGVS, ids=lambda a: " ".join(a) or "<none>")
def test_every_invocation_reaches_ingest_exactly_as_before(monkeypatch, argv):
    old_calls = Calls()
    buf = io.StringIO()
    with redirect_stdout(buf):
        legacy_main(argv, fake_ingest(old_calls), fake_registry(old_calls))
    rc, new_calls, out = run_new(monkeypatch, argv)
    assert rc == 0
    assert new_calls == old_calls  # same ingest(...) arguments, same run_start / run_complete, same order
    assert out == buf.getvalue()  # byte-identical stdout (the --json result)


def test_a_failing_run_raises_and_fails_the_pipeline_run_like_before(monkeypatch):
    old_calls = Calls()
    with pytest.raises(RuntimeError):
        legacy_main(["--priority"], fake_ingest(old_calls, raises=RuntimeError("db down")), fake_registry(old_calls))
    with pytest.raises(RuntimeError):
        run_new(monkeypatch, ["--priority"], raises=RuntimeError("db down"))
    assert old_calls[-1] == (("run_fail", "run-1", "db down"), {})


@pytest.mark.parametrize("argv", [["--dry"], ["--dryrun"], ["--apply"], ["--priority", "--bogus"], ["--tail"],
                                  ["--prio"], ["--symbol"], ["priority"], ["--dry-run=1"]])
def test_an_unknown_or_abbreviated_flag_is_refused_before_anything_runs(monkeypatch, capsys, argv):
    calls = Calls()
    monkeypatch.setitem(sys.modules, "pipeline_registry", fake_registry(calls))
    monkeypatch.setattr(ni, "ingest", fake_ingest(calls))
    with pytest.raises(SystemExit) as ei:
        ni.main(argv)
    assert ei.value.code == 2
    assert calls == []  # no run_start, no ingest: the old fall-through to the live --priority run is gone
    assert "usage:" in capsys.readouterr().err


# ── the dry run: plan only ─────────────────────────────────────────────────────────────────────────────

def _forbid_side_effects(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("a dry run reached a side effect")

    monkeypatch.setitem(sys.modules, "pipeline_registry", types.SimpleNamespace(
        run_start=boom, run_complete=boom, run_fail=boom))
    monkeypatch.setattr(ni, "ingest", boom)
    monkeypatch.setattr(ni, "_get_conn", boom)
    monkeypatch.setattr(ni, "_save_rotation", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(hsp, "limit_env_loading", boom)  # the real-run branch only
    real_read_text, real_open = Path.read_text, builtins.open

    def read_text(self, *a, **k):
        if self.name == ".env":
            raise AssertionError("a dry run read the .env")
        return real_read_text(self, *a, **k)

    def guarded_open(file, mode="r", *a, **k):
        if any(m in mode for m in "wax+"):
            raise AssertionError(f"a dry run opened {file} for writing")
        if str(file).endswith(".env"):
            raise AssertionError("a dry run read the .env")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(builtins, "open", guarded_open)


@pytest.mark.parametrize("argv,lane", [
    (cron_argv(CRON[193][1]), "news-ingestion"),
    (cron_argv(CRON[649][1]), "news-ingestion"),
    (cron_argv(CRON[650][1]), "news-ingestion-tail"),
    (["--symbol", "aapl"], "news-ingestion-manual-single_symbol"),
    (["--full"], "news-ingestion-manual-full"),
])
def test_dry_run_reaches_no_side_effect_and_writes_nothing(monkeypatch, tmp_path, argv, lane):
    ni.ROTATION_FILE.parent.mkdir(parents=True)
    ni.ROTATION_FILE.write_text(json.dumps({"offset": 481, "tail_size": 2272}))
    before = sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    monkeypatch.setenv("NEWS_INGEST_MAX", "60")
    monkeypatch.delenv("BENZINGA_API_KEY", raising=False)
    _forbid_side_effects(monkeypatch)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ni.main([*argv, "--dry-run"])
    assert rc == 0
    out = buf.getvalue()
    line = next(ln for ln in out.splitlines() if ln.startswith("DRY-RUN "))
    rep = json.loads(line[len("DRY-RUN "):])
    assert rep["dry_run"] is True and rep["lane_id"] == lane
    assert rep["summary"]["lane_run"] is (not lane.startswith("news-ingestion-manual"))
    assert any("news_articles" in w for w in rep["would_write"])
    if lane == "news-ingestion-tail":
        assert '"offset": 481' in out and '"batch_size": 500' in out
    assert sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before  # nothing written or touched
    assert not (tmp_path / "state").exists()


def test_dry_run_is_checked_before_run_start_and_the_connection():
    src = (ROOT / "scripts" / "news_ingestion.py").read_text(encoding="utf-8")
    main = src[src.index("def main("):]
    assert main.index("if args.dry_run:") < main.index("_limit_env_loading()") < main.index('run_start("news_ingestion")')
    assert main.index("return 0") < main.index("run_start(")
    plan_src = src[src.index("def plan("):src.index("def _would_write(")]
    assert "_get_conn" not in plan_src and ".env\").read" not in plan_src and "urlopen" not in plan_src


# ── the receipt ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv,lane", [(["--priority"], "news-ingestion"), ([], "news-ingestion"),
                                       (["--tail-rotate"], "news-ingestion-tail")])
def test_a_real_lane_run_writes_its_receipt(monkeypatch, tmp_path, argv, lane):
    rc, _calls, _out = run_new(monkeypatch, argv)
    assert rc == 0
    doc = json.loads((tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json").read_text())
    assert doc["schema"] == "LaneRunReceipt@v1" and doc["lane_id"] == lane and doc["script"] == "news_ingestion.py"
    assert doc["status"] == "ok" and doc["exit"] == 0 and doc["ok_at"] == doc["finished_at"]
    assert doc["summary"]["new_articles"] == 2 and doc["summary"]["scanned"] == 3
    if lane == "news-ingestion-tail":
        assert doc["summary"]["next_offset"] == 8


@pytest.mark.parametrize("argv", [["--symbol", "AAPL", "--json"], ["--full"]])
def test_a_manual_run_writes_no_lane_receipt(monkeypatch, tmp_path, argv):
    run_new(monkeypatch, argv)
    assert not (tmp_path / "state" / "data" / "runtime").exists()


def test_a_failed_run_keeps_the_previous_ok_at_and_scrubs_the_error(monkeypatch, tmp_path):
    run_new(monkeypatch, ["--priority"])
    path = tmp_path / "state" / "data" / "runtime" / "news-ingestion_last.json"
    ok_at = json.loads(path.read_text())["ok_at"]
    with pytest.raises(RuntimeError):
        run_new(monkeypatch, ["--priority"], raises=RuntimeError("password authentication failed for user x"))
    doc = json.loads(path.read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1 and doc["ok_at"] == ok_at
    assert doc["error"] == "RuntimeError"  # never the message


def test_lane_ids_match_the_registry_rows():
    assert ni.LANE_IDS == {"priority": "news-ingestion", "tail_rotate": "news-ingestion-tail"}
    for lane, (_line, receipt, _lock, _has) in LANES.items():
        assert ROWS[lane]["output_signal"] == {"kind": "json_key", "path": receipt, "key": "ok_at"}
    # both --priority lines run the same argv, so both rows read the one --priority receipt
    assert (ROWS["news-ingestion"]["output_signal"]["path"] == ROWS["news-ingestion-overnight"]["output_signal"]["path"]
            == f"data/runtime/{ni.LANE_IDS['priority']}_last.json")


# ── secrets: the lane loads only the names it needs ───────────────────────────────────────────────────

def _fake_env_root(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".env").write_text("DB_HOST=127.0.0.9\nDB_PASSWORD=fake-db\nALPACA_API_KEY=fake-broker\n"
                               "SCHWAB_APP_SECRET=fake-broker-2\nOTHER_TOKEN=fake\n")
    monkeypatch.setattr(hsp, "ROOT", root)
    import psycopg2

    def refuse(*_a, **_k):
        raise RuntimeError("no db in tests")

    monkeypatch.setattr(psycopg2, "connect", refuse)
    for k in ("DB_HOST", "DB_PASSWORD", "ALPACA_API_KEY", "SCHWAB_APP_SECRET", "OTHER_TOKEN"):
        monkeypatch.delenv(k, raising=False)


def test_the_news_process_loads_only_db_names_from_the_env_file(monkeypatch, tmp_path):
    _fake_env_root(tmp_path, monkeypatch)
    run_new(monkeypatch, ["--priority"])  # main narrows before any lookup
    assert hsp.ENV_LOAD_KEYS == hsp.DB_ENV_KEYS
    assert hsp._db_rows() == []
    assert os.environ.get("DB_HOST") == "127.0.0.9" and os.environ.get("DB_PASSWORD") == "fake-db"
    for k in ("ALPACA_API_KEY", "SCHWAB_APP_SECRET", "OTHER_TOKEN"):
        assert k not in os.environ, k


def test_other_importers_keep_the_legacy_env_loading(monkeypatch, tmp_path):
    """Opt-in per process: api_v2 and the other importers are not changed by this PR."""
    _fake_env_root(tmp_path, monkeypatch)
    monkeypatch.setattr(hsp, "ENV_LOAD_KEYS", None)
    hsp._db_rows()
    assert os.environ.get("OTHER_TOKEN") == "fake"


def test_the_allowlist_env_names_carry_no_broker_credential():
    for lane in LANES:
        names = ALLOW[lane]["env_names"]
        assert "BENZINGA_API_KEY" in names and "DB_PASSWORD" in names
        for name in names:
            assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)


# ── registry, allowlist, contract ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lane", sorted(LANES))
def test_row_is_a_w4_shadow_cron_row_admitted_by_the_r1_gate(lane):
    line, _receipt, _lock, _has = LANES[lane]
    sched, text = CRON[line]
    row = ROWS[lane]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == "W4" and s["expression"] == sched
    assert "schedules" not in s and s["command_text"] == text
    assert row["state"] == "ACTIVE" and row["owner"] == "research"
    assert "generated_by" not in row and row["adopted_from_generator"] == "reconcile_lane_registry@v1"
    assert row["dispatch"] == {"mode": "dry_run", "cron": [sched], "tz": "America/New_York", "wave": "W4",
                               "class": "ingest", "priority": 5, "retry_policy": "none"}
    assert LD.dispatch_mode(row) == "dry_run" and LD.validate_dispatch_block(row) == []
    assert LD.dispatch_eligible(row) == (True, "eligible")
    assert LD.r1_class_admission(row) == (True, "r1_admitted:ingest")
    ok, why = LD.r1_class_admission(row, ALLOW[lane], shadow_shape_status="PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), why


@pytest.mark.parametrize("lane", sorted(LANES))
def test_keep_on_cron_is_dropped_by_operator_ruling_and_reconcile_keeps_it_dropped(lane):
    row = ROWS[lane]
    assert row["recommendation"] == "PIPELINE:P03" and row["rationalization"]["recommendation"] == "PIPELINE:P03"
    assert row["rationalization"]["f_recommendation"] == "KEEP (inside its pipeline)"  # the F text stays visible
    ruling = row["operator_ruling"]
    assert ruling["recommendation"] == "PIPELINE:P03" and ruling["ruled_on"] == "2026-10-11"
    assert "stay_on_cron" not in row
    # what annotate_existing does on every reconcile: re-derive KEEP_ON_CRON from F, then apply the ruling
    probe = json.loads(json.dumps(row))
    probe["recommendation"] = probe["rationalization"]["recommendation"] = "KEEP_ON_CRON"
    R.apply_operator_ruling(probe, None)
    assert probe["recommendation"] == probe["rationalization"]["recommendation"] == "PIPELINE:P03"


def test_an_operator_ruling_never_lifts_a_forced_stay_on_cron():
    row = {"recommendation": "KEEP_ON_CRON", "rationalization": {"recommendation": "KEEP_ON_CRON"},
           "operator_ruling": {"recommendation": "PIPELINE:P03"}}
    R.apply_operator_ruling(row, {"class": "broker", "token": "alpaca"})
    assert row["recommendation"] == "KEEP_ON_CRON" and row["rationalization"]["recommendation"] == "KEEP_ON_CRON"
    row2 = {"recommendation": "PIPELINE:P03", "operator_ruling": {"recommendation": "KEEP_ON_CRON"}}
    R.apply_operator_ruling(row2, None)
    assert row2["recommendation"] == "PIPELINE:P03"  # a ruling to KEEP is a no-op, not an override


@pytest.mark.parametrize("lane", sorted(LANES))
def test_allowlist_entry_is_shadow_only(lane):
    line, receipt, lock, has_lock = LANES[lane]
    e = ALLOW[lane]
    assert e["command"] == ["$PY", "scripts/news_ingestion.py", *cron_argv(CRON[line][1])]
    assert e["live_arg"] is None and e["dry_run_arg"] == ["--dry-run"]
    assert e["output_signal"] == receipt == LD.receipt_signal_path(ROWS[lane])
    assert e["env_allowlist_mode"] == "report" and e["env_report_reason"]
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []
    assert e["market_gate"] is False and e["lock_kind"] == "flock" and e["lock"] == lock
    # the dispatcher argv parses: the allowlist dry run is the real --dry-run, not a fall-through
    args = ni.build_parser().parse_args(e["command"][2:] + e["dry_run_arg"])
    assert args.dry_run is True


@pytest.mark.parametrize("lane", sorted(LANES))
def test_lock_is_the_cron_lock_or_proposed(lane):
    _line, _receipt, lock, has_lock = LANES[lane]
    e = ALLOW[lane]
    text = ROWS[lane]["scheduler"]["command_text"]
    canary = json.loads(json.dumps(ROWS[lane]))
    canary["scheduler"]["stage"] = "canary"
    canary["dispatch"]["mode"] = "live"
    ok, why = LD.r1_canary_lock_matches(canary, dict(e, live_arg=[]))
    if has_lock:
        assert LD.cron_flock_locks(text) == [lock] and ok, why
    else:
        assert LD.cron_flock_locks(text) == [] and not ok, why
        assert "PROPOSED" in e["source"] and lock in e["source"]


def test_each_match_hits_exactly_its_own_cron_line():
    snap_lines = [c["line"] for c in SNAPSHOT["cron_lines"]]
    for lane, (line, *_rest) in LANES.items():
        marker = ROWS[lane]["scheduler"]["match"]
        assert [ln for ln in snap_lines if marker in ln] == [" ".join(CRON[line])], lane
    mapping = R.line_mapping(REGISTRY, [" ".join(v) for v in CRON.values()])
    assert {ln: ids for ln, ids in mapping.items()} == {" ".join(CRON[ln]): [lane] for lane, (ln, *_r) in LANES.items()}


@pytest.mark.parametrize("lane", sorted(LANES))
def test_health_contract_is_reviewed_and_complete(lane):
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and c["owner"] == ROWS[lane]["owner"]
    assert H.validate_contract(c) == [] and H.unknown_fields(c) == []
    assert not [e for e in c["connects_to"] if e["kind"] == "inventory_text"]
    assert {e["direction"] for e in c["connects_to"]} >= {"read", "write", "calls"}
    assert c["evidence"]["receipt"] == ALLOW[lane]["output_signal"]
    assert lane in " ".join(c["evidence"]["verify"])
    b = c["baseline"]
    if lane == "news-ingestion-tail":
        assert (b["freshness_degraded_after_h"], b["freshness_failed_after_h"]) == (138.0, 142.0)
    else:  # two --priority fires per market day, one per weekend day
        assert (b["freshness_degraded_after_h"], b["freshness_failed_after_h"]) == (14.0, 26.0)
        assert (b["freshness_closed_degraded_after_h"], b["freshness_closed_failed_after_h"]) == (26.0, 50.0)
    assert b["duration_degraded_above_s"] == round(ALLOW[lane]["timeout_s"] * 0.8, 1)


def test_contract_gate_is_clean():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    idx = json.loads((ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "INDEX.json").read_text())
    res = H.check(doc, REGISTRY, idx)
    assert res["errors"] == []
    assert not set(LANES) & set(doc["grandfathered_draft"])


START = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)  # Monday 00:00 America/New_York


def test_compute_due_week_sweep_emits_dry_run_on_the_live_slots_only():
    rows = [ROWS[x] for x in LANES]
    slots: dict[str, set] = {}
    errors = set()
    t = START
    while t < START + timedelta(days=7):
        resp = D.compute_due(rows, ALLOW, POLICIES, None, t)
        for it in resp["items"]:
            assert it["mode"] == "dry_run", it
            slots.setdefault(it["lane_id"], set()).add(it["slot_local"])
        errors |= {(e["lane_id"], e["code"]) for e in resp["errors"]}
        t += timedelta(minutes=30)
    assert errors == set(), sorted(errors)
    assert {k: sorted({s[-4:] for s in v}) for k, v in slots.items()} == {
        "news-ingestion": ["1230"], "news-ingestion-overnight": ["0030"],
        "news-ingestion-tail": ["1000", "1400", "1800"]}
    assert (len(slots["news-ingestion"]), len(slots["news-ingestion-overnight"]), len(slots["news-ingestion-tail"])) \
        == (5, 7, 6)
