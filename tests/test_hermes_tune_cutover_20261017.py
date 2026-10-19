"""hermes-learning TUNE cutover (2026-10-17): autonomous_self_tune goes live on the n8n fabric at 17:00 ET.

Operator 2026-10-17 00:25 ET: "do a dry run now, it works no errors, make active now". Directive 2026-10-15: all
families to n8n, with F41 retention approved for n8n. Packet: docs/ops/packets/hermes-tune-cutover-20261017/cutover.sh.

1. Committed config (mirrors the learn PR-1/PR-2 pins):
   * the lane runs the cron step's own argv, BOTH halves (no --learn), with live_arg [--apply];
   * registry stage is canary, cron_claim is true, output_receipt is v2;
   * the tune cron runner row is at 20 17, while the effect slot stays the manifest minute (T1700);
   * the fabric workflow is byte-identical (no re-import).
2. Cron runner: the REAL manifest's tune stage under PIPELINE_EFFECT_CLAIM=1 and the COMMITTED effect keys.
   * owner n8n: the step is skipped_effect and nothing runs;
   * owner cron: the step claims, runs and ends DONE;
   * switch off: unchanged.
   The step command is swapped for a marker, so it never touches a DB.
3. Output verdict: main() in a fake n8n attempt with the DB faked writes LaneRunReceipt@v2 produced_count.
   * graft-gated with nothing to purge is empty_allowed (nothing_due);
   * applied grafts or purged rows are produced;
   * a dry run writes no receipt;
   * a raised run writes a failed one.
4. The packet: dry by default, refusals (window, order, grant), backup + byte-exact read-back, and proof.
   Fake crontab, tmp ledger, no service, no network.

Hermetic: tmp state roots and ledgers, no DB, no network, no broker, no secret.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_autonomous_self_tune as ST  # noqa: E402
from scripts import n8n_workflow_templates as T  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import lane_stage_clamp as C  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402
from tests.pipeline_runner_fixtures import runner_env, sandbox_runner  # noqa: E402
from tests.support import hermes_learning_cutover as HL  # noqa: E402
from tests.support import lane_produced_count as LPC  # noqa: E402

LANE = "hermes-learning-autonomous-self-tune"
SID = "autonomous_self_tune"
WID = "tradeai-fabric-hermes-learning"
PACKET = ROOT / "docs" / "ops" / "packets" / "hermes-tune-cutover-20261017" / "cutover.sh"
SPEC = json.loads((ROOT / "config" / "n8n_fabric_processes.json").read_text())["processes"]["hermes-learning"]
MANIFEST = json.loads((ROOT / SPEC["manifest"]).read_text())
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
REG = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
EFFECTS = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text())
CONTRACT = next(
    c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"] if c["id"] == LANE
)
OLD_LINE = (
    "0 17 * * * cd $PROJ && bash scripts/pipelines/run_hermes_pipeline.sh --stage tune --apply >> "
    "logs/pipelines/hermes_cron.log 2>&1  # TRADEAI_LANE hermes-learning-pipeline-tune (parallel dry-run)"
)
NEW_LINE = OLD_LINE.replace("0 17 * * * cd $PROJ && bash", "20 17 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash", 1)
LEARN_LINE = (
    "20 11 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash scripts/pipelines/run_hermes_pipeline.sh --stage learn "
    "--apply >> logs/pipelines/hermes_cron.log 2>&1  # TRADEAI_LANE hermes-learning-pipeline-learn (parallel dry-run)"
)


# ── 1. committed config ────────────────────────────────────────────────────────────────────────────────────────


def test_tune_lane_is_in_the_shared_cutover_list():
    assert HL.TUNE_LIVE == (LANE,) and LANE in HL.LIVE and LANE not in HL.HELD
    assert len(HL.LEARN_LIVE) == 4 and set(HL.LEARN_LIVE) <= set(HL.LIVE)
    assert len(HL.LIVE) == 5
    assert HL.HELD == ("hermes-learning-outcome-feedback-agent",) and HL.FEEDBACK_LIVE == ()


def test_lane_runs_the_cron_step_argv_both_halves_at_canary():
    e = ALLOW[LANE]
    step = SPEC["steps"][SID]
    assert e["command"] == ["$PY", "scripts/hermes_autonomous_self_tune.py"]
    assert e["live_arg"] == step["cutover_live_arg"] == ["--apply"]
    assert e["dry_run_arg"] == ["--dry-run"] and step["lane_extra_args"] == []
    cron_step = next(s for s in MANIFEST["stages"]["tune"]["steps"] if s["id"] == SID)
    # the cron step: `flock -n <lock> $PY scripts/hermes_autonomous_self_tune.py --apply` -- the same argv
    assert cron_step["command"].split("$PY ", 1)[1].split() == e["command"][1:] + e["live_arg"]
    assert PM.lock_paths(cron_step["command"]) == [e["lock"]] and e["lock_kind"] == "flock"
    assert e["output_receipt"] == "v2" and e["market_gate"] is False and e["timeout_s"] == 1800
    row = REG[LANE]["scheduler"]
    assert row["stage"] == "canary" and row["process_step"] == SID and row["expression"] == WID
    assert C.clamp_mode(LANE, "live", list(REG.values()))["effective_mode"] == "live"
    assert EFFECTS["lanes"][LANE]["cron_claim"] is True and EFFECTS["lanes"][LANE]["stage"] == "tune"


def test_cron_runner_row_moves_to_1720_and_the_effect_slot_stays_1700():
    assert REG["hermes-learning-pipeline-tune"]["scheduler"]["expression"] == "20 17 * * *"
    assert MANIFEST["stages"]["tune"]["proposed_schedule"] == "0 17 * * *"  # n8n's trigger + both sides' slot
    assert PM.effect_slot(MANIFEST, "tune", "20261017") == "20261017T1700"
    assert PM.effect_spec(MANIFEST, "tune", EFFECTS) == [(SID, LANE, "v1")]
    assert len(PM.effect_spec(MANIFEST, "learn", EFFECTS)) == 5  # the learn stage is untouched
    gen = next(x for x in T.LANES if x["lane_id"] == "hermes-learning-pipeline-tune")
    assert gen["cron"] == ["20 17 * * *"]


def test_fabric_workflow_is_unchanged_so_no_republish_is_needed():
    d = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "fabric"
    row = next(w for w in json.loads((d / "INDEX.json").read_text())["workflows"] if w["id"] == WID)
    # the graph published 2026-10-16 17:19Z (PR-2 + manual-slots PR); the packet's `publish` step pins the same hash
    assert row["graph_sha256"] == "f1d0984c64b06191020008af6d09f8b26a9c5a0ba5789f8e97ddb0e45215ebe4"
    assert row["graph_sha256"] in PACKET.read_text()
    js = json.loads((d / row["file"]).read_text())
    ctx = next(n for n in js["nodes"] if n["name"] == T.PN_CTX)["parameters"]["jsCode"]
    assert 'const MODE = "live";' in ctx and '"tune": "1700"' in ctx


def test_health_contract_declares_the_both_halves_output_rule():
    eo = CONTRACT["expected_output"]
    assert OV.validate_expected_output(eo) == []
    assert eo["rule"] == "empty_allowed" and set(eo["empty_allowed_reasons"]) == {"nothing_due", "no_new_input"}
    assert "retention rows" in eo["unit"]
    checks = {c["check"] for part in ("healthy", "failed") for c in CONTRACT[part]}
    assert "purge_archive_first" in checks and "purge_not_archived" in checks
    assert not checks & {"learn_only_no_purge", "learn_ran_purge"}


# ── 2. the cron runner honours PIPELINE_EFFECT_CLAIM for the tune stage ────────────────────────────────────────

RUNNER = ROOT / "scripts" / "pipelines" / "run_hermes_pipeline.sh"
KEY = f"fx:{LANE}:20261017T1700:v1"


def _sandbox(tmp_path: Path) -> Path:
    import shutil

    runner = sandbox_runner(tmp_path, RUNNER)
    lib = tmp_path / "scripts" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in ("effect_claim.py", "n8n_coordination_ledger.py", "n8n_coordination_gateway.py"):
        shutil.copyfile(ROOT / "scripts" / "lib" / name, lib / name)
    return runner


def _tune_manifest(tmp_path: Path, marker: Path) -> Path:
    """The REAL manifest's tune stage, with the step command swapped for a marker (never the script, never a DB)."""
    m = copy.deepcopy(MANIFEST)
    m["stages"] = {"tune": m["stages"]["tune"]}
    (st,) = m["stages"]["tune"]["steps"]
    assert st["id"] == SID
    st["command"] = f"echo x >> {marker}"
    st["cron_line_verbatim"] = f"0 17 * * * cd $PROJ && {st['command']}"  # the manifest's verbatim-slice rule
    st.pop("log", None)
    p = tmp_path / "hermes_learning.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def _run_stage(tmp_path: Path, marker: Path, ledger: Path, *, claim: bool, apply: bool = True):
    env = runner_env(tmp_path)
    env.update(
        {
            "PIPELINE_EFFECT_CONFIG": str(ROOT / "config" / "n8n_effect_keys.json"),  # the COMMITTED keys
            "PIPELINE_EFFECT_LEDGER": str(ledger),
            "PIPELINE_EFFECT_DATE": "20261017",
        }
    )
    if claim:
        env["PIPELINE_EFFECT_CLAIM"] = "1"
    cmd = [
        "bash",
        str(_sandbox(tmp_path)),
        "--manifest",
        str(_tune_manifest(tmp_path, marker)),
        "--project-root",
        str(tmp_path),
        "--stage",
        "tune",
        "--apply" if apply else "--dry-run",
    ]
    return subprocess.run(cmd, cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120)


def _step(tmp_path: Path) -> dict:
    doc = json.loads((tmp_path / "data" / "runtime" / "pipeline_hermes_learning_tune_last.json").read_text())
    (s,) = doc["steps"]
    return s


def _claim_row(ledger: Path):
    conn = sqlite3.connect(str(ledger))
    try:
        return conn.execute("SELECT state, scheduler FROM effect_claims WHERE effect_key = ?", (KEY,)).fetchone()
    finally:
        conn.close()


def _owner(ledger: Path, owner: str, expect: int | None) -> None:
    args = ["--ledger", str(ledger), "set-owner", "--process", LANE, "--owner", owner, "--by", "test"]
    if expect is not None:
        args += ["--expect-epoch", str(expect)]
    assert E.main(args) == 0


def test_n8n_owner_skips_the_cron_tune_step(tmp_path, monkeypatch):
    monkeypatch.setenv(E.HANDOVER_ENV, str(tmp_path / "handover.json"))
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _owner(ledger, "cron", None)
    _owner(ledger, "n8n", 1)  # packet c3
    r = _run_stage(tmp_path, marker, ledger, claim=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "claiming steps: autonomous_self_tune" in r.stdout
    assert not marker.exists() and _claim_row(ledger) is None
    s = _step(tmp_path)
    assert s["status"] == "skipped_effect" and s["rc"] == E.REFUSED_EXIT and s["effect_key"] == KEY


def test_cron_owner_claims_runs_and_holds_the_slot(tmp_path, monkeypatch):
    monkeypatch.setenv(E.HANDOVER_ENV, str(tmp_path / "handover.json"))
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _owner(ledger, "cron", None)  # packet c1 (the interim owner row)
    r = _run_stage(tmp_path, marker, ledger, claim=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == "x\n" and _step(tmp_path)["status"] == "ok"
    assert _claim_row(ledger) == ("DONE", "cron")
    r = _run_stage(tmp_path, marker, ledger, claim=True)  # same business slot again: refused, nothing runs
    assert marker.read_text() == "x\n" and _step(tmp_path)["status"] == "skipped_effect"


def test_switch_off_and_dry_run_claim_nothing(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    r = _run_stage(tmp_path, marker, ledger, claim=False)
    assert r.returncode == 0 and marker.read_text() == "x\n" and not ledger.exists() and "[effect]" not in r.stdout
    r = _run_stage(tmp_path, marker, ledger, claim=True, apply=False)
    assert r.returncode == 0 and not ledger.exists() and marker.read_text() == "x\n"


# ── 3. output verdict: LaneRunReceipt@v2 from the real main() (DB faked) ───────────────────────────────────────

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.connection = conn
        self._last = ""
        self.rowcount = 0

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.conn.log.append(text)
        if self.conn.readonly and text.split(" ", 1)[0].upper() in WRITE_VERBS:
            raise RuntimeError("write in a read-only session")
        if self.conn.raise_on and self.conn.raise_on in text:
            raise RuntimeError("db went away")
        self._last = text
        self.rowcount = self.conn.update_rows if text.upper().startswith("UPDATE") else 0

    def fetchone(self):
        for needle, v in self.conn.answers:
            if needle in self._last:
                return v
        return (0,)

    def fetchall(self):
        for needle, v in self.conn.answers:
            if needle in self._last:
                return v
        return []


class _Conn:
    def __init__(self, answers, *, update_rows=0, raise_on=None):
        self.answers, self.update_rows, self.raise_on = answers, update_rows, raise_on
        self.log: list[str] = []
        self.readonly = False
        self.commits = 0

    def cursor(self):
        return _Cur(self)

    def set_session(self, readonly=False, **_kw):
        self.readonly = bool(readonly)

    def rollback(self):
        pass

    def commit(self):
        self.commits += 1

    def close(self):
        pass


GATED = [  # today's state (dry run 2026-10-17): weekly drift 0.107 > cap 0.10
    ("count(DISTINCT created_at::date)", (12,)),
    ("jsonb_array_elements(detail->'changes')", (0, 0.107)),
    ("SELECT to_regclass(%s)", ("t",)),
]
GRAFTING = [
    ("count(DISTINCT created_at::date)", (12,)),
    ("jsonb_array_elements(detail->'changes')", (0, 0.01)),
    ("DISTINCT ON (factor)", [("momentum", 0.40, 0.3), ("value", 0.10, 0.1)]),
    ("SELECT to_regclass(%s)", ("t",)),
]
NO_SUGGESTIONS = [
    ("count(DISTINCT created_at::date)", (12,)),
    ("jsonb_array_elements(detail->'changes')", (0, 0.0)),
    ("DISTINCT ON (factor)", []),
    ("SELECT to_regclass(%s)", ("t",)),
]


@pytest.fixture
def tune(monkeypatch, tmp_path):
    state = types.SimpleNamespace(conns=[], deleted=0, purges=[])

    def use(answers, **kw):
        def _conn():
            c = _Conn(answers, **kw)
            state.conns.append(c)
            return c

        monkeypatch.setattr(ST, "_conn", _conn)

    ra = types.ModuleType("lib.retention_archive")

    def managed_purge(conn, *, table, where_sql, params, label, writer, apply):
        state.purges.append((table, apply))
        return {"deleted": state.deleted if apply else 0, "eligible": state.deleted}

    ra.managed_purge = managed_purge
    monkeypatch.setitem(sys.modules, "lib.retention_archive", ra)
    weights = tmp_path / "hermes_score_weights.yaml"
    weights.write_text("version: 3\nweights:\n  momentum: 0.5\n  value: 0.5\n", encoding="utf-8")
    monkeypatch.setattr(ST, "WEIGHTS_FILE", weights)
    monkeypatch.setattr(ST, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    monkeypatch.setattr(ST, "_LEARN_ONLY", False)
    state.use = use
    state.run_id = LPC.attempt_env(monkeypatch, tmp_path, LANE)
    state.root = tmp_path
    return state


def test_lane_is_opted_in_with_code_that_writes_produced_count():
    LPC.assert_opted_in(LANE)


def test_graft_gated_and_nothing_to_purge_is_a_verified_empty(tune, capsys):
    tune.use(GATED)
    assert ST.main(["--apply"]) == 0
    doc = LPC.attempt_receipt(tune.root, LANE, tune.run_id)
    assert doc["empty_reason"] == "nothing_due" and doc["skipped_reasons"] == {"graft_gated_weekly_drift_cap": 1}
    out = LPC.check(tune.root, LANE, tune.run_id, produced=0, expect="empty_allowed")
    assert out["output_verdict"]["empty_reason"] == "nothing_due"
    assert [t for t, _ in tune.purges] == [
        "hermes_embedding_queue",
        "hermes_score_history",
        "hermes_research_intelligence",
        "hermes_external_research",
        "watchlist_research_results",
        "watchlist_research_queue",
        "proposal_research_packets",
    ]  # both halves ran


def test_applied_grafts_are_produced(tune):
    tune.use(GRAFTING)
    assert ST.main(["--apply"]) == 0
    LPC.check(tune.root, LANE, tune.run_id, produced=2, expect="produced")
    assert "version: 4" in (tune.root / "hermes_score_weights.yaml").read_text()


def test_purged_rows_alone_are_produced(tune):
    tune.use(GATED, update_rows=3)  # 3 stale advisory events expired + 3 failed embeddings re-queued
    tune.deleted = 2  # each of the 7 archived purges removed 2 rows
    assert ST.main(["--apply"]) == 0
    doc = LPC.attempt_receipt(tune.root, LANE, tune.run_id)
    assert doc["output_evidence"][0]["purged_rows"] == 3 + 3 + 2 * 7
    LPC.check(tune.root, LANE, tune.run_id, produced=20, expect="produced")


def test_no_outcome_suggestions_is_no_new_input(tune):
    tune.use(NO_SUGGESTIONS)
    assert ST.main(["--apply"]) == 0
    out = LPC.check(tune.root, LANE, tune.run_id, produced=0, expect="empty_allowed")
    assert out["output_verdict"]["empty_reason"] == "no_new_input"


def test_dry_run_writes_no_receipt_and_nothing_else(tune, capsys):
    tune.use(GATED)
    assert ST.main(["--dry-run", "--apply"]) == 0  # --dry-run wins
    assert not LR.attempt_receipt_path(LANE, tune.run_id, tune.root).exists()
    assert not LR.receipt_path(LANE, tune.root).exists()
    assert all(c.readonly and c.commits == 0 for c in tune.conns)
    assert all(not apply for _, apply in tune.purges)


def test_a_raised_run_leaves_a_failed_receipt_and_still_fails(tune):
    tune.use(GATED, raise_on="UPDATE hermes_advisory_events")
    with pytest.raises(RuntimeError, match="db went away"):
        ST.main(["--apply"])
    doc = LPC.attempt_receipt(tune.root, LANE, tune.run_id)
    assert doc["status"] != "ok" and doc["produced_count"] == 0
    assert doc["skipped_reasons"] == {"dependency_unavailable": 1}
    assert LPC.verdict(tune.root, LANE, tune.run_id)["state"] == "RUN_FAILED"


def test_cron_run_without_attempt_identity_writes_only_the_last_receipt(tune, monkeypatch):
    monkeypatch.delenv(LR.RUN_ID_ENV)
    tune.use(GATED)
    assert ST.main(["--apply"]) == 0
    assert LR.receipt_path(LANE, tune.root).is_file()
    assert not (LR.receipt_path(LANE, tune.root).parent / "lane_attempts" / LANE).exists()


@pytest.mark.parametrize(
    "result,want",
    [
        (
            {"auto_graft": {"status": "applied", "changes": [1, 2, 3]}, "self_purge": {"dead_table_rows_purged": 4}},
            (7, None),
        ),
        ({"auto_graft": {"status": "gated_persistence"}, "self_purge": {"embeddings_dropped": -1}}, (0, "nothing_due")),
        ({"auto_graft": {"status": "dry", "changes": [1]}}, (0, "nothing_due")),
        (
            {
                "auto_graft": {"status": "no_outcome_suggestions"},
                "self_purge": {"dead_table_errors": ["x: absent"], "dead_tables_truncated": ["a", "b"]},
            },
            (0, "no_new_input"),
        ),
    ],
)
def test_lane_output_counts(result, want):
    out = ST.lane_output(result)
    assert (out["produced_count"], out["empty_reason"]) == want
    assert out["attempted_count"] == out["produced_count"]
    if "dead_table_errors" in result.get("self_purge", {}):
        assert out["skipped_reasons"]["dead_table_error"] == 1


# ── 4. the operator packet ─────────────────────────────────────────────────────────────────────────────────────


def _fake_crontab(tmp_path: Path, text: str) -> Path:
    tab = tmp_path / "crontab.txt"
    tab.write_text(text, encoding="utf-8")
    exe = tmp_path / "bin" / "crontab"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text(
        f'#!/bin/bash\nif [ "$1" = "-l" ]; then cat {tab}; elif [ "$1" = "-" ]; then cat > {tab}; else exit 9; fi\n',
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


def _packet(tmp_path: Path, *args: str, hm: str = "1200", grant: bool = True, **extra: str):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "PY": sys.executable,
        "SERVED": str(extra.pop("served", ROOT)),
        "REPO": str(ROOT),
        "CRONTAB_BIN": str(tmp_path / "bin" / "crontab"),
        "FX_LEDGER": str(tmp_path / "ledger.sqlite"),
        "LEDGER": str(tmp_path / "ledger.sqlite"),
        "STATE": str(tmp_path / "state"),
        "BACKUPS": str(tmp_path / "backups"),
        "LIVE_LANES_ENV": str(tmp_path / "live.env"),
        "NOW_HM": hm,
        E.HANDOVER_ENV: str(tmp_path / "handover.json"),
        "PYTHONPATH": str(ROOT),
    }
    if grant:
        env["TRADEAI_FABRIC_GRANT"] = "g-test"
    env.update(extra)
    return subprocess.run(["bash", str(PACKET), *args], env=env, capture_output=True, text=True, timeout=120)


def test_packet_is_valid_bash_and_dry_by_default():
    assert subprocess.run(["bash", "-n", str(PACKET)]).returncode == 0
    text = PACKET.read_text()
    assert "set -euo pipefail" in text and "set -f" in text and "APPLY=0" in text
    assert "LANE=hermes-learning-autonomous-self-tune" in text
    assert "relay_live_not_enabled" in text  # c3 refuses before relay
    for step in ("pre)", "c1)", "c2)", "relay)", "publish)", "c3)", "proof)", "rollback)"):
        assert f"\n  {step}" in text, step


def test_packet_refuses_unknown_steps_and_args(tmp_path):
    assert "usage" in _packet(tmp_path, "bogus").stdout
    assert "unknown arg" in _packet(tmp_path, "c1", "--force").stdout
    assert "--date YYYYMMDD" in _packet(tmp_path, "proof").stdout


def test_c2_dry_then_apply_rewrites_exactly_the_tune_line(tmp_path):
    _fake_crontab(tmp_path, f"# head\n{LEARN_LINE}\n{OLD_LINE}\n# tail\n")
    before = (tmp_path / "crontab.txt").read_text()
    r = _packet(tmp_path, "c2")
    assert r.returncode == 0 and "DRY RUN — crontab unchanged" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "crontab.txt").read_text() == before
    r = _packet(tmp_path, "c2", "--apply")
    assert r.returncode == 0 and "installed byte-exact" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "crontab.txt").read_text() == before.replace(OLD_LINE, NEW_LINE)
    (backup,) = (tmp_path / "backups").iterdir()
    assert backup.read_text() == before
    r = _packet(tmp_path, "c2", "--apply")
    assert r.returncode == 0 and "already applied" in r.stdout


@pytest.mark.parametrize("tab", [f"{LEARN_LINE}\n", f"{OLD_LINE}\n{OLD_LINE}\n"])
def test_c2_refuses_without_exactly_one_tune_line(tmp_path, tab):
    _fake_crontab(tmp_path, tab)
    r = _packet(tmp_path, "c2", "--apply")
    assert r.returncode == 1 and "REFUSED: expected exactly one tune line" in r.stdout
    assert (tmp_path / "crontab.txt").read_text() == tab


def test_c1_c3_rollback_owner_acts_with_refusals(tmp_path):
    _fake_crontab(tmp_path, f"{OLD_LINE}\n")
    r = _packet(tmp_path, "c1")
    assert "DRY RUN — would run: effect_claim.py set-owner" in r.stdout, r.stdout + r.stderr
    assert "REFUSED: TRADEAI_FABRIC_GRANT not set" in _packet(tmp_path, "c1", "--apply", grant=False).stdout
    r = _packet(tmp_path, "c1", "--apply")
    assert r.returncode == 0 and "-> cron 1" in r.stdout, r.stdout + r.stderr
    assert "already cron" in _packet(tmp_path, "c1", "--apply").stdout
    # c3 order refusals: window, c2, relay
    for hm in ("1650", "1700", "1719", "1725"):
        assert "inside the tune window" in _packet(tmp_path, "c3", "--apply", hm=hm).stdout, hm
    assert "c2 not applied" in _packet(tmp_path, "c3", "--apply").stdout
    _packet(tmp_path, "c2", "--apply")
    (tmp_path / "live.env").write_text("TRADEAI_N8N_RELAY_LIVE_LANES=hermes-learning-tag-engine\n")
    assert "relay not applied" in _packet(tmp_path, "c3", "--apply").stdout
    (tmp_path / "live.env").write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES=hermes-learning-tag-engine {LANE}\n")
    r = _packet(tmp_path, "c3")
    assert r.returncode == 0 and "DRY RUN — would run: effect_claim.py set-owner --process" in r.stdout
    assert "--owner n8n --expect-epoch 1" in r.stdout
    r = _packet(tmp_path, "c3", "--apply", hm="1640")
    assert r.returncode == 0 and "-> n8n 2" in r.stdout, r.stdout + r.stderr
    manifest = json.loads((tmp_path / "handover.json").read_text())
    assert manifest["processes"][LANE]["owner"] == "n8n"  # set-owner wrote the fail-closed manifest
    assert "already n8n" in _packet(tmp_path, "c3", "--apply").stdout
    r = _packet(tmp_path, "rollback", "--apply")
    assert r.returncode == 0 and "-> cron 3" in r.stdout, r.stdout + r.stderr


def test_relay_dry_run_lists_the_addition_and_changes_nothing(tmp_path):
    env_file = tmp_path / "live.env"
    env_file.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=a-lane hermes-learning-tag-engine\n")
    r = _packet(tmp_path, "relay")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"adds: {LANE}" in r.stdout and "keeps: 2 existing lanes" in r.stdout and "DRY RUN" in r.stdout
    assert env_file.read_text() == "TRADEAI_N8N_RELAY_LIVE_LANES=a-lane hermes-learning-tag-engine\n"


def test_publish_confirms_no_reimport_against_the_committed_tree(tmp_path):
    r = _packet(tmp_path, "publish")
    assert r.returncode == 0 and "NO RE-IMPORT NEEDED" in r.stdout, r.stdout + r.stderr


def _proof_fixture(tmp_path: Path, *, verdict: str, cron_status: str | None) -> Path:
    led = tmp_path / "ledger.sqlite"
    c = sqlite3.connect(str(led))
    c.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, receipt_json TEXT)")
    c.execute("CREATE TABLE effect_claims (effect_key TEXT, state TEXT, scheduler TEXT, run_id TEXT)")
    rid = f"p:{LANE}:live:20261017T1700"
    rec = {"output_verdict": {"verdict": verdict, "produced_count": 0, "empty_reason": "nothing_due"}}
    c.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (rid, LANE, "live", "RUN_DONE", json.dumps(rec)))
    c.execute("INSERT INTO effect_claims VALUES (?,?,?,?)", (KEY, "DONE", "n8n", rid))
    c.commit()
    c.close()
    served = tmp_path / "served"
    j = served / "logs" / "pipelines" / "hermes_learning" / "tune_steps.jsonl"
    j.parent.mkdir(parents=True)
    lines = [json.dumps({"ts": "2026-10-16T21:00:03Z", "id": SID, "status": "ok", "rc": 0, "dry_run": False})]
    if cron_status:
        lines.append(
            json.dumps(
                {
                    "ts": "2026-10-17T21:20:02Z",
                    "id": SID,
                    "status": cron_status,
                    "rc": 75,
                    "dry_run": False,
                    "effect_key": KEY,
                }
            )
        )
    j.write_text("\n".join(lines) + "\n")
    return served


def test_proof_passes_on_n8n_done_with_a_useful_verdict_and_cron_skipped(tmp_path):
    served = _proof_fixture(tmp_path, verdict="empty_allowed", cron_status="skipped_effect")
    r = _packet(tmp_path, "proof", "--date", "20261017", served=served)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "n8n half: PASS" in r.stdout and "cron half: PASS" in r.stdout


@pytest.mark.parametrize(
    "verdict,cron", [("unverifiable", "skipped_effect"), ("empty_allowed", "ok"), ("empty_allowed", None)]
)
def test_proof_fails_on_a_bad_verdict_or_a_cron_run(tmp_path, verdict, cron):
    served = _proof_fixture(tmp_path, verdict=verdict, cron_status=cron)
    r = _packet(tmp_path, "proof", "--date", "20261017", served=served)
    assert r.returncode == 1, r.stdout + r.stderr


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_hermes_tune_cutover_20261017.py" in text
