"""Cron effect-claim wrap (2026-10-16): wrapper semantics and the packet's line mapping.

On 2026-10-16 no crontab line ran through scripts/effect_claim_cron.sh, so effect owner = n8n did not stop the cron
copy; only the shared flock kept the two schedulers apart, and n8n lost that race. This suite pins:

1. the wrapper: owner cron runs the command; owner n8n exits 0 with event ``skipped_effect`` and writes no claim;
   an unreachable ledger fails OPEN (the command runs unclaimed, event ``run_unclaimed_ledger_unreachable``); a
   child's own exit 2 after a granted claim is not mistaken for a ledger failure (no second run);
2. ``effect_claim.py owner`` (read-only) and ``run --decision-out``;
3. the packet plan (docs/ops/packets/cron-effect-claim-wrap-20261016/plan.py) on a fixture crontab: which lines it
   wraps, every skip reason, byte preservation, unwrap = rollback, and a wrapped line run end to end by bash;
4. apply.sh / rollback.sh: dry run by default, diff count = planned count, backup first, install with
   ``crontab -`` and a byte-exact read-back, all against a fake ``crontab`` on PATH.

Hermetic: tmp_path ledgers, configs, crontab text and a fake crontab/guard; never the live crontab or ledger.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

WRAPPER = ROOT / "scripts" / "effect_claim_cron.sh"
PKT = ROOT / "docs" / "ops" / "packets" / "cron-effect-claim-wrap-20261016"
SLOT = "20261016T0930"


def _plan_mod():
    spec = importlib.util.spec_from_file_location("cron_effect_claim_wrap_plan", PKT / "plan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _plan_mod()


# ── 1. wrapper semantics ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def wrap(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    marker = tmp_path / "ran.txt"
    logs = tmp_path / "logs"

    def cfg(cron_claim: bool) -> Path:
        p = tmp_path / f"keys_{int(cron_claim)}.json"
        p.write_text(json.dumps({"schema": E.EFFECT_CONFIG_SCHEMA, "lanes": {
            "x-lane": {"process": "x-lane", "input_version": "v1", "cron_claim": cron_claim}}}))
        return p

    def run(*, cron_claim=True, code=0, ledger_path=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_EFFECT")}
        env.update({
            "EFFECT_CLAIM_PY": sys.executable,
            "TRADEAI_N8N_COORDINATION_LEDGER": str(ledger_path or ledger),
            "EFFECT_CLAIM_LOG_DIR": str(logs),
            "TRADEAI_EFFECT_SLOT": SLOT,
            "TRADEAI_EFFECT_CLAIM": "x-lane",
            "TRADEAI_EFFECT_CLAIM_CONFIG": str(cfg(cron_claim)),
        })
        cmd = ["bash", str(WRAPPER), "x-lane", "bash", "-c", f'echo run >> "{marker}"; exit {code}']
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)

    def runs() -> int:
        return len(marker.read_text().splitlines()) if marker.exists() else 0

    def events() -> list[str]:
        f = logs / "effect_claim_events.jsonl"
        return [json.loads(x)["event"] for x in f.read_text().splitlines()] if f.exists() else []

    def store():
        return E.EffectClaimStore(CoordinationLedger(ledger))

    class W:
        pass

    w = W()
    w.run, w.runs, w.events, w.store, w.ledger, w.tmp = run, runs, events, store, ledger, tmp_path
    return w


@pytest.mark.parametrize("cron_claim", [True, False])
def test_owner_cron_runs_the_command(wrap, cron_claim):
    wrap.store().set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    r = wrap.run(cron_claim=cron_claim, code=3)
    assert r.returncode == 3 and wrap.runs() == 1
    if cron_claim:
        assert wrap.events() == ["completed_claimed"]
        assert wrap.store().get(f"fx:x-lane:{SLOT}:v1")["scheduler"] == "cron"
    else:
        assert wrap.events() == ["run_unclaimed_cron_claim_false", "completed_unclaimed"]


@pytest.mark.parametrize("cron_claim", [True, False])
def test_owner_n8n_exits_0_logs_skipped_effect_and_writes_nothing(wrap, cron_claim):
    wrap.store().set_owner("x-lane", "n8n", expect_epoch=None, by="t", now=1.0)
    r = wrap.run(cron_claim=cron_claim)
    assert r.returncode == 0 and wrap.runs() == 0
    assert wrap.events() == ["skipped_effect"]
    assert wrap.store().get(f"fx:x-lane:{SLOT}:v1") is None  # no claim row


@pytest.mark.parametrize("cron_claim", [True, False])
def test_unreachable_ledger_fails_open_and_logs_it(wrap, cron_claim):
    blocker = wrap.tmp / "not-a-dir"
    blocker.write_text("x")  # the ledger's parent is a FILE: the ledger can be neither opened nor created
    r = wrap.run(cron_claim=cron_claim, code=0, ledger_path=blocker / "ledger.sqlite")
    assert r.returncode == 0 and wrap.runs() == 1
    ev = wrap.events()
    if cron_claim:
        assert ev == ["run_unclaimed_ledger_unreachable", "completed_unclaimed"]
    else:
        assert ev == ["run_unclaimed_cron_claim_false", "completed_unclaimed"]
        log = (wrap.tmp / "logs" / "effect_claim_events.jsonl").read_text()
        assert "owner=ledger_unreachable" in log


def test_unreadable_sqlite_ledger_fails_open(wrap):
    wrap.ledger.mkdir()  # a directory where the sqlite file should be: sqlite3 cannot open it
    r = wrap.run(cron_claim=True)
    assert r.returncode == 0 and wrap.runs() == 1
    assert wrap.events()[0] == "run_unclaimed_ledger_unreachable"


def test_child_exit_2_after_a_granted_claim_is_not_run_twice(wrap):
    wrap.store().set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    r = wrap.run(cron_claim=True, code=2)
    assert r.returncode == 2 and wrap.runs() == 1
    assert wrap.events() == ["completed_claimed"]


def test_already_claimed_slot_still_refuses_75(wrap):
    wrap.store().set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    assert wrap.run().returncode == 0
    r = wrap.run()
    assert r.returncode == E.REFUSED_EXIT and wrap.runs() == 1
    assert wrap.events()[-1] == "refused_claim"


def test_armed_lane_without_owner_row_still_refuses(wrap):
    wrap.store()  # creates the tables, no owner row
    r = wrap.run(cron_claim=True)
    assert r.returncode == E.REFUSED_EXIT and wrap.runs() == 0


# ── 2. effect_claim.py owner + run --decision-out ─────────────────────────────────────────────────────────────────


def test_owner_cli_is_read_only(tmp_path, capsys):
    led = tmp_path / "l.sqlite"
    assert E.main(["--ledger", str(led), "owner", "--process", "x-lane"]) == 2  # missing: unreachable
    assert not led.exists()  # a read never creates the ledger
    st = E.EffectClaimStore(CoordinationLedger(led))
    capsys.readouterr()
    assert E.main(["--ledger", str(led), "owner", "--process", "x-lane"]) == 0
    assert capsys.readouterr().out.strip() == "none"
    st.set_owner("x-lane", "n8n", expect_epoch=None, by="t", now=1.0)
    assert E.main(["--ledger", str(led), "owner", "--process", "x-lane"]) == 0
    assert capsys.readouterr().out.strip() == "n8n"


def test_owner_read_only_on_a_ledger_without_effect_tables(tmp_path):
    import sqlite3

    led = tmp_path / "bare.sqlite"
    sqlite3.connect(led).execute("CREATE TABLE runs (x)").connection.commit()
    assert E.owner_read_only("x-lane", str(led)) == "none"


def test_decision_out_written_before_the_command(tmp_path):
    led = tmp_path / "l.sqlite"
    E.EffectClaimStore(CoordinationLedger(led)).set_owner("x-lane", "n8n", expect_epoch=None, by="t", now=1.0)
    out = tmp_path / "d.json"
    rc = E.main(["--ledger", str(led), "run", "--process", "x-lane", "--slot", SLOT, "--input-version", "v1",
                 "--scheduler", "cron", "--decision-out", str(out), "--", "true"])
    d = json.loads(out.read_text())
    assert rc == E.REFUSED_EXIT and d["ok"] is False and d["reason"] == "effect_fenced_owner" and d["owner"] == "n8n"


def test_decision_out_write_failure_runs_nothing_and_keeps_the_key_reclaimable(tmp_path):
    led = tmp_path / "l.sqlite"
    st = E.EffectClaimStore(CoordinationLedger(led))
    st.set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    marker = tmp_path / "ran"
    rc = E.main(["--ledger", str(led), "run", "--process", "x-lane", "--slot", SLOT, "--input-version", "v1",
                 "--scheduler", "cron", "--decision-out", str(tmp_path / "no" / "dir" / "d.json"), "--",
                 "touch", str(marker)])
    assert rc == 2 and not marker.exists()
    row = E.EffectClaimStore(CoordinationLedger(led)).get(f"fx:x-lane:{SLOT}:v1")
    assert row["state"] == "FAILED" and row["pre_effect"] == 1
    assert st.claim(f"fx:x-lane:{SLOT}:v1", scheduler="cron", now=3.0).ok  # reclaimable


# ── 3. the plan ──────────────────────────────────────────────────────────────────────────────────────────────────

HOME = "/home/op"
PROJ = f"{HOME}/trade-ai-releases/portfolio-server/CURRENT"


def _reg(*rows):
    return {"lanes": [{"lane_id": lid, "state": "ACTIVE", "scheduler": {"kind": kind, "match": match}}
                      for lid, kind, match in rows]}


REGISTRY = _reg(
    ("alpha", "cron", "scripts/alpha.py"),
    ("beta", "cron", "scripts/beta.py"),
    ("gamma", "cron", "scripts/gamma.py"),
    ("daemon", "cron", "scripts/daemon.py"),
    ("sysd", "systemd", "scripts/sysd.py"),
    ("unkeyed", "cron", "scripts/unkeyed.py"),
    ("dup-a", "cron", "scripts/dup.py"),
    ("dup-b", "cron", "scripts/dup.py --x"),
    ("broker", "cron", "scripts/broker.py"),
    ("armed", "cron", "scripts/armed.py"),
    ("n8nown", "cron", "scripts/n8nown.py"),
    ("ghost", "cron", "scripts/ghost.py"),
    ("deferred", "cron", "scripts/deferred.py"),
    ("nofam", "cron", "scripts/nofam.py"),
)
KEYED = ["alpha", "beta", "gamma", "daemon", "sysd", "dup-a", "dup-b", "broker", "armed", "n8nown", "ghost",
         "deferred", "nofam"]
KEYS = {"lanes": {k: {"process": k, "input_version": "v1", "cron_claim": k in ("armed", "n8nown", "ghost")}
                  for k in KEYED}}


def _fam(lane, fid, source="crontab", wave="M2"):
    return {"lane_id": lane, "family_id": fid, "source": source, "wave": wave}


FAMILIES = {
    lane: [_fam(lane, fid)]
    for lane, fid in [("alpha", "F43"), ("beta", "F12"), ("gamma", "F47"), ("daemon", "F07"), ("dup-a", "F12"),
                      ("dup-b", "F12"), ("broker", "F09"), ("armed", "F12"), ("n8nown", "F12"), ("ghost", "F12")]
}
FAMILIES["sysd"] = [_fam("sysd", "F20", source="registry_systemd")]
FAMILIES["deferred"] = [_fam("deferred", "F30", wave="DEFERRED-I2")]
FAMILIES["nofam"] = [_fam("nofam", "")]

CRONTAB = f"""SHELL=/bin/bash
PROJ={PROJ}
PY={HOME}/venv/bin/python
# a comment line mentioning scripts/alpha.py is never touched
0 10 * * 1-5 cd $PROJ && flock -n /tmp/alpha.lock $PY scripts/alpha.py --run >> logs/alpha.log 2>&1
5 17 * * 1-5 cd {PROJ} && flock -n /tmp/beta.lock bash -c "set -a; $PY scripts/beta.py" >> logs/b.log 2>&1  # note
20 * * * * cd $PROJ && FOO=1 $PY scripts/gamma.py --apply >> logs/gamma.log 2>&1
7,37 * * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/g.lock $PY scripts/gamma.py --x >> logs/g.log 2>&1
1 1 * * * cd $PROJ && flock -n -w 5 /tmp/a2.lock timeout 10m $PY scripts/alpha.py >> logs/a2.log 2>&1
@reboot cd $PROJ && $PY scripts/daemon.py >> logs/daemon.log 2>&1
0 2 * * * cd $PROJ && $PY scripts/sysd.py
0 3 * * * cd $PROJ && $PY scripts/unkeyed.py
0 4 * * * cd $PROJ && $PY scripts/dup.py --x
0 5 * * * cd $PROJ && $PY scripts/broker.py  # TRADEAI_LANE broker
0 6 * * * cd $PROJ && $PY scripts/armed.py
0 7 * * * cd $PROJ && $PY scripts/n8nown.py
0 8 * * * cd $PROJ && $PY scripts/ghost.py
0 9 * * * cd $PROJ && $PY scripts/deferred.py
0 10 * * * cd $PROJ && $PY scripts/nofam.py
40 6 * * 1 CUR=$(readlink -f $PROJ) && cd "$CUR" && $PY scripts/alpha.py
41 6 * * 1 cd $PROJ && $PY scripts/alpha.py | tee -a logs/x.log
42 6 * * 1 $PY {PROJ}/scripts/alpha.py
43 6 * * 1 cd /tmp && $PY scripts/alpha.py
44 6 * * 1 cd $PROJ && flock -n /tmp/x.lock env TRADEAI_EFFECT_CLAIM=alpha bash scripts/effect_claim_cron.sh alpha $PY scripts/alpha.py
45 6 * * 1 cd $PROJ && $PY scripts/beta.py  # TRADEAI_LANE alpha
46 6 * * 1 cd $PROJ && $PY scripts/alpha.py; echo done
"""

OWNERS = {"armed": "cron", "n8nown": "n8n", "ghost": "n8n"}
RELAY = {"n8nown"}


def _plan(text=CRONTAB, **kw):
    args = dict(registry=REGISTRY, effect_keys=KEYS, families=FAMILIES, relay_live=RELAY, owners=OWNERS, home=HOME)
    args.update(kw)
    return P.build_plan(text, **args)


def _line(n):
    return CRONTAB.splitlines()[n - 1]


def test_plan_wraps_exactly_the_certain_candidates():
    plan = _plan()
    got = {w["line_no"]: w["lane"] for w in plan["wrapped"]}
    assert got == {5: "alpha", 6: "beta", 7: "gamma", 8: "gamma", 9: "alpha", 15: "armed", 16: "n8nown"}
    by = {w["line_no"]: w for w in plan["wrapped"]}
    assert by[5]["new"] == (
        "0 10 * * 1-5 cd $PROJ && flock -n /tmp/alpha.lock env TRADEAI_EFFECT_CLAIM=alpha bash "
        "scripts/effect_claim_cron.sh alpha $PY scripts/alpha.py --run >> logs/alpha.log 2>&1"
    )
    assert by[6]["new"].endswith(
        'flock -n /tmp/beta.lock env TRADEAI_EFFECT_CLAIM=beta bash scripts/effect_claim_cron.sh beta bash -c '
        '"set -a; $PY scripts/beta.py" >> logs/b.log 2>&1  # note'
    )
    assert "&& FOO=1 env TRADEAI_EFFECT_CLAIM=gamma bash scripts/effect_claim_cron.sh gamma $PY" in by[7]["new"]
    assert "safe_flock.sh /tmp/g.lock env TRADEAI_EFFECT_CLAIM=gamma bash" in by[8]["new"]
    assert "-w 5 /tmp/a2.lock env TRADEAI_EFFECT_CLAIM=alpha bash scripts/effect_claim_cron.sh alpha timeout" \
        in by[9]["new"]
    assert by[16]["owner"] == "n8n" and by[16]["relay_live"] is True and by[15]["cron_claim"] is True


def test_plan_reports_every_skip_with_its_reason():
    plan = _plan()
    got = {s["line_no"]: s["reason"] for s in plan["skipped"]}
    assert got == {
        10: "family_F07",
        11: "registry_systemd",
        13: "ambiguous_registry_match",
        14: "family_F09_broker_held_for_CD6",
        17: "owner_n8n_not_relay_live",
        18: "wave_DEFERRED-I2",
        19: "family_unknown",
        20: "shape:shell_metachar:(",
        21: "shape:shell_metachar:|",
        22: "shape:no_cd_prefix",
        23: "shape:cwd_is_not_PROJ",
        24: "already_wrapped",
        25: "tag_registry_conflict",
        26: "shape:shell_metachar:;",
    }
    assert plan["out_of_scope"] == {"no_effect_key": 1}  # line 12, unkeyed
    assert plan["active_job_lines"] == 22
    assert plan["wrapped_count"] + plan["skipped_count"] + sum(plan["out_of_scope"].values()) == 22


def test_armed_lane_without_owner_row_is_skipped():
    plan = _plan(owners={"n8nown": "n8n", "ghost": "n8n"})
    assert {s["line_no"]: s["reason"] for s in plan["skipped"]}[15] == "armed_without_owner_row"


def test_owners_unknown_does_not_block_and_is_reported():
    plan = _plan(owners=None)
    assert plan["owners_read"] is False
    assert {w["line_no"] for w in plan["wrapped"]} >= {15, 16, 17}
    assert all(w["owner"] == "unknown" for w in plan["wrapped"])


def test_include_f09_wraps_the_broker_line():
    plan = _plan(include_f09=True)
    assert 14 in {w["line_no"] for w in plan["wrapped"]}


def test_candidate_changes_only_the_wrapped_lines_and_unwrap_restores_bytes():
    plan = _plan()
    old, new = CRONTAB.splitlines(keepends=True), plan["candidate"].splitlines(keepends=True)
    assert len(old) == len(new)
    changed = [i + 1 for i, (a, b) in enumerate(zip(old, new)) if a != b]
    assert changed == sorted(w["line_no"] for w in plan["wrapped"])
    assert P.unwrap(plan["candidate"]) == (P.unwrap(CRONTAB)[0], len(changed) + 1)  # +1: line 24, wrapped before
    assert P.unwrap(CRONTAB)[1] == 1


def test_unwrap_counts_preexisting_wrapped_lines_too():
    # line 24 already carries the same prefix shape; rollback removes it too (apply.sh compares unwrap deltas).
    plan = _plan()
    restored, n = P.unwrap(plan["candidate"])
    assert n == plan["wrapped_count"] + 1
    assert restored.splitlines()[23] == "44 6 * * 1 cd $PROJ && flock -n /tmp/x.lock $PY scripts/alpha.py"


def test_no_trailing_newline_and_crlf_free_bytes_preserved():
    text = CRONTAB.rstrip("\n")
    plan = _plan(text)
    assert not plan["candidate"].endswith("\n")
    assert P.unwrap(plan["candidate"])[0].splitlines()[:23] == text.splitlines()[:23]


def test_wrapped_line_runs_end_to_end_under_bash(tmp_path):
    """The rewritten line's command, run by bash in the repo tree like cron (cwd = $PROJ): n8n owns -> skipped."""
    text = (f"PROJ={ROOT}\n0 1 * * * cd $PROJ && flock -n {tmp_path}/a.lock "
            f"$PY -c \"open('{tmp_path}/ran','w').write('x')\" >> {tmp_path}/a.log 2>&1  # TRADEAI_LANE alpha\n")
    plan = P.build_plan(text, registry=REGISTRY, effect_keys=KEYS, families=FAMILIES, relay_live={"alpha"},
                        owners={"alpha": "n8n"}, home=HOME)
    assert plan["wrapped_count"] == 1
    new = plan["wrapped"][0]["new"]
    cmd = new[P.command_offset(new):]
    led = tmp_path / "l.sqlite"
    st = E.EffectClaimStore(CoordinationLedger(led))
    st.set_owner("alpha", "n8n", expect_epoch=None, by="t", now=1.0)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_EFFECT")}
    cfg = tmp_path / "keys.json"
    cfg.write_text(json.dumps({"schema": E.EFFECT_CONFIG_SCHEMA, "lanes": {
        "alpha": {"process": "alpha", "input_version": "v1", "cron_claim": True}}}))
    env.update({"PROJ": str(ROOT), "PY": sys.executable, "EFFECT_CLAIM_PY": sys.executable,
                "TRADEAI_EFFECT_CLAIM_CONFIG": str(cfg), "TRADEAI_EFFECT_SLOT": SLOT,
                "TRADEAI_N8N_COORDINATION_LEDGER": str(led), "EFFECT_CLAIM_LOG_DIR": str(tmp_path / "logs")})
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and not (tmp_path / "ran").exists()
    assert "skipped_effect" in (tmp_path / "logs" / "effect_claim_events.jsonl").read_text()
    st.set_owner("alpha", "cron", expect_epoch=1, by="t", now=2.0)
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "ran").read_text() == "x"


def test_relay_live_reader_reads_only_the_lane_list(tmp_path):
    f = tmp_path / "live.env"
    f.write_text("# x\nOTHER=secret-ish\nTRADEAI_N8N_RELAY_LIVE_LANES=a b  c\n")
    assert P.load_relay_live(f) == {"a", "b", "c"}
    assert P.load_relay_live(tmp_path / "missing") == set()


def test_plan_cli_json_and_candidate(tmp_path, capsys):
    ct = tmp_path / "ct"
    ct.write_text(CRONTAB)
    reg, keys, fam = tmp_path / "reg.json", tmp_path / "keys.json", tmp_path / "fam.csv"
    reg.write_text(json.dumps(REGISTRY))
    keys.write_text(json.dumps(KEYS))
    rows = [r for v in FAMILIES.values() for r in v]
    fam.write_text("lane_id,family_id,source,wave\n" + "".join(
        f"{r['lane_id']},{r['family_id']},{r['source']},{r['wave']}\n" for r in rows))
    live = tmp_path / "live.env"
    live.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=n8nown\n")
    cand = tmp_path / "cand"
    rc = P.main(["--crontab", str(ct), "--registry", str(reg), "--effect-keys", str(keys), "--disposition", str(fam),
                 "--relay-live", str(live), "--no-ledger", "--home", HOME, "--json", "--emit-candidate", str(cand)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["wrapped_count"] == 8 and "candidate" not in out  # owners unread: 17 wraps too
    assert cand.read_text() != CRONTAB


# ── 4. apply.sh / rollback.sh against a fake crontab ──────────────────────────────────────────────────────────────


@pytest.fixture
def fake_host(tmp_path):
    """A fake `crontab` (and `guard`) on PATH; HOME, ledger and backups in tmp_path. Uses the REAL repo configs, so
    the fixture line is a real keyed lane (finviz-screener-runner, family F43)."""
    home = tmp_path / "home"
    (home / ".config" / "tradeai").mkdir(parents=True)
    (home / ".config" / "tradeai" / "n8n-live-lanes.env").write_text(
        "TRADEAI_N8N_RELAY_LIVE_LANES=finviz-screener-runner\n")
    proj = f"{home}/trade-ai-releases/portfolio-server/CURRENT"
    store = tmp_path / "crontab.store"
    store.write_text(
        f"PROJ={proj}\nPY=/x/python\n"
        "0 10 * * 1-5 cd $PROJ && flock -n /tmp/finviz_screener.lock $PY scripts/finviz_screener_runner.py --run "
        ">> logs/finviz_screener.log 2>&1\n"
        "0 3 * * * cd $PROJ && $PY scripts/some_unkeyed_thing.py\n"
    )
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    installs = tmp_path / "installs.log"
    (bin_ / "crontab").write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "-l" ]; then cat "{store}"; exit 0; fi\n'
        f'if [ "$1" = "-" ]; then cat > "{store}"; echo install >> "{installs}"; exit 0; fi\n'
        "exit 9\n"
    )
    (bin_ / "guard").write_text("#!/usr/bin/env bash\necho 'cron  grant cron-effect-claim-wrap-20261016'\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    led = tmp_path / "ledger.sqlite"
    E.EffectClaimStore(CoordinationLedger(led)).set_owner(
        "finviz-screener-runner", "n8n", expect_epoch=None, by="t", now=1.0)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_")}
    env.update({"HOME": str(home), "PATH": f"{bin_}:{os.environ['PATH']}", "PY3": sys.executable,
                "TRADEAI_N8N_COORDINATION_LEDGER": str(led), "BACKUP_ROOT": str(tmp_path / "backups"),
                "SERVED": str(ROOT)})

    def run(script, *args, **extra):
        e = dict(env)
        e.update(extra)
        return subprocess.run(["bash", str(PKT / script), *args], env=e, capture_output=True, text=True, timeout=120)

    return {"run": run, "store": store, "installs": installs, "tmp": tmp_path}


def test_apply_dry_run_by_default_backs_up_and_installs_nothing(fake_host):
    before = fake_host["store"].read_text()
    r = fake_host["run"]("apply.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "planned wraps: 1" in r.stdout and "checks OK: diff count = planned = 1" in r.stdout
    assert "DRY RUN" in r.stdout and not fake_host["installs"].exists()
    assert fake_host["store"].read_text() == before
    backups = list((fake_host["tmp"] / "backups").glob("cron-effect-claim-wrap-*/crontab.backup"))
    assert len(backups) == 1 and backups[0].read_text() == before


def test_apply_refuses_when_the_served_tree_lacks_the_new_wrapper(fake_host, tmp_path):
    old = tmp_path / "old_served" / "scripts" / "lib"
    old.mkdir(parents=True)
    (old.parent / "effect_claim_cron.sh").write_text("# old wrapper\n")
    (old / "effect_claim.py").write_text("# old\n")
    r = fake_host["run"]("apply.sh", "--apply", SERVED=str(tmp_path / "old_served"))
    assert r.returncode == 3 and "P1 FAIL" in r.stdout and not fake_host["installs"].exists()


def test_apply_installs_byte_exact_and_rollback_restores(fake_host):
    before = fake_host["store"].read_text()
    r = fake_host["run"]("apply.sh", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "installed exactly (1 lines wrapped)" in r.stdout
    after = fake_host["store"].read_text()
    assert "env TRADEAI_EFFECT_CLAIM=finviz-screener-runner bash scripts/effect_claim_cron.sh finviz-screener-runner" \
        in after
    assert len(after.splitlines()) == len(before.splitlines())
    # a second apply plans nothing (the line is already wrapped)
    r2 = fake_host["run"]("apply.sh")
    assert "planned wraps: 0" in r2.stdout
    rb = fake_host["run"]("rollback.sh")
    assert rb.returncode == 0 and "lines to unwrap: 1" in rb.stdout and "DRY RUN" in rb.stdout
    rb = fake_host["run"]("rollback.sh", "--apply")
    assert rb.returncode == 0 and "rolled back exactly (1 lines)" in rb.stdout
    assert fake_host["store"].read_text() == before


def test_packet_scripts_parse_and_follow_the_house_pattern():
    for f in ("apply.sh", "rollback.sh"):
        text = (PKT / f).read_text()
        assert subprocess.run(["bash", "-n", str(PKT / f)]).returncode == 0
        assert "set -f" in text and "crontab -l > " in text and "crontab - < " in text
        assert "| cmp - " in text and ".local/state/tradeai/backups" in text
        assert 'MODE="${1:-dry-run}"' in text
    assert subprocess.run(["bash", "-n", str(WRAPPER)]).returncode == 0
