"""Architect review 2026-10-16: fail-closed duplicate protection and the nightly controller's transaction guarantees.

Defects pinned here (each test names the one it covers):

D1  the cron wrapper FAILED OPEN for a lane already handed over to n8n when the ledger was unreadable (a second run
    after the first finished was possible). Now: handed-over + ownership unknown -> nothing runs, P1 raised.
D2  the controller's "5 per night" was per evaluation; repeated invocations could exceed it. Now: a durable per-ET-night
    quota ledger written under the controller lock.
D3  apply evaluated one snapshot and reused it for every lane. Now: fresh grant / owner / versions / in-flight checks
    immediately before EACH lane's edit, inside the fenced handover.
D4  a crash between the crontab, registry and contract writes left a half-applied lane with no record. Now: a
    write-ahead transaction record and deterministic, idempotent recovery before any new work.

Hermetic: tmp ledgers, manifests, crontabs (a fake `crontab` on CRONTAB_CMD), tmp served roots; never the live host.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib import effect_ownership_watch as OW  # noqa: E402
from scripts.lib import nightly_cutover as NC  # noqa: E402
from scripts.lib import nightly_cutover_txn as TX  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402
from scripts import nightly_cutover_controller as CTL  # noqa: E402
from tests import test_nightly_cutover_controller_20261016 as T  # noqa: E402

WRAPPER = ROOT / "scripts" / "effect_claim_cron.sh"
SLOT = "20261016T0930"
NOW = T.NOW


# ══ D1: the wrapper fails CLOSED for handed-over lanes ═══════════════════════════════════════════════════════════════

@pytest.fixture
def wrap(tmp_path):
    ledger = tmp_path / "gov" / "ledger.sqlite"
    ledger.parent.mkdir()
    marker = tmp_path / "ran.txt"
    logs = tmp_path / "logs"
    incidents = tmp_path / "state" / OW.INCIDENTS_REL

    def cfg(cron_claim: bool, n8n_claim=None) -> Path:
        p = tmp_path / f"keys_{int(cron_claim)}_{n8n_claim}.json"
        spec = {"process": "x-lane", "input_version": "v1", "cron_claim": cron_claim}
        if n8n_claim is not None:
            spec["n8n_claim"] = n8n_claim
        p.write_text(json.dumps({"schema": E.EFFECT_CONFIG_SCHEMA, "lanes": {"x-lane": spec}}))
        return p

    def run(*, cron_claim=True, ledger_path=None, py=None, n8n_claim=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_EFFECT") and k != E.HANDOVER_ENV}
        env.update({"EFFECT_CLAIM_PY": py or sys.executable,
                    "TRADEAI_N8N_COORDINATION_LEDGER": str(ledger_path or ledger),
                    "TRADEAI_N8N_HANDOVER_MANIFEST": str(manifest),
                    "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
                    "EFFECT_CLAIM_LOG_DIR": str(logs), "TRADEAI_EFFECT_SLOT": SLOT,
                    "TRADEAI_EFFECT_CLAIM": "x-lane", "TRADEAI_EFFECT_CLAIM_CONFIG": str(cfg(cron_claim, n8n_claim))})
        cmd = ["bash", str(WRAPPER), "x-lane", "bash", "-c", f'echo run >> "{marker}"']
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)

    manifest = ledger.parent / E.HANDOVER_NAME

    class W:
        pass

    w = W()
    w.run, w.ledger, w.manifest, w.tmp, w.incidents = run, ledger, manifest, tmp_path, incidents
    w.runs = lambda: len(marker.read_text().splitlines()) if marker.exists() else 0
    w.events = lambda: [json.loads(x) for x in (logs / "effect_claim_events.jsonl").read_text().splitlines()] \
        if (logs / "effect_claim_events.jsonl").exists() else []
    w.store = lambda: E.EffectClaimStore(CoordinationLedger(ledger))
    w.own = lambda owner, expect=None: E.set_owner_with_manifest(w.store(), manifest, "x-lane", owner,
                                                                 expect_epoch=expect, by="t", now=1.0)
    w.p1 = lambda: [json.loads(x) for x in incidents.read_text().splitlines()] if incidents.exists() else []
    return w


def _break_ledger(w):
    """The sqlite ledger becomes unreadable (a directory where the file should be); the manifest is untouched."""
    w.ledger.unlink(missing_ok=True)
    w.ledger.mkdir()


@pytest.mark.parametrize("cron_claim", [True, False])
def test_D1_ledger_unreadable_handed_over_lane_runs_nothing_and_raises_p1(wrap, cron_claim):
    wrap.own("n8n")
    _break_ledger(wrap)
    r = wrap.run(cron_claim=cron_claim)
    assert r.returncode == 75 and wrap.runs() == 0, r.stderr
    ev = wrap.events()
    assert [e["event"] for e in ev] == ["skipped_ownership_unknown"]
    assert "ledger_unreachable_handed_over:manifest=n8n" in ev[0]["detail"]
    p1 = wrap.p1()
    assert len(p1) == 1 and p1[0]["severity"] == "P1" and p1[0]["lane"] == "x-lane"
    assert p1[0]["schema"] == "EffectOwnershipIncident@v1"
    # the existing incident path pages it: host-cron notifier rows (independent of the ledger and n8n) + fan-in keys
    found, note = OW.findings(wrap.tmp / "state", datetime.now(timezone.utc))
    assert [(f["source"], f["item"], f["severity"]) for f in found] == [("effect_ownership",
                                                                         "x-lane:OWNERSHIP_UNKNOWN", "P1")]
    from scripts import incident_notifier as IN
    rows, _ = IN.alert_path_rows(wrap.tmp / "state", datetime.now(timezone.utc), env={})
    own = [r for r in rows if r["source"] == "effect_ownership"]
    assert own and own[0]["severity"] == "P1" and own[0]["host_watch"] is True
    opened, _ = IN.open_incidents({"incidents": own}, set())
    assert list(opened.values())[0]["host_watch"] is True


def test_D1_ledger_unreadable_never_armed_lane_runs_but_the_missing_manifest_pages(wrap):
    _break_ledger(wrap)                                    # no manifest at all, and the key arms neither side
    r = wrap.run(cron_claim=False, n8n_claim=False)
    assert r.returncode == 0 and wrap.runs() == 1, r.stderr
    assert "skipped_ownership_unknown" not in [e["event"] for e in wrap.events()]
    # finding 2 (architect review of 26fd0518): a missing manifest file is itself a P1
    assert [p["reason"] for p in wrap.p1()] == ["ledger_unreachable_never_handed_over:manifest=file_absent,"
                                                "handover_manifest_missing"]


@pytest.mark.parametrize("cron_claim", [True, False])
def test_D1_ledger_unreadable_armed_lane_without_manifest_fails_closed(wrap, cron_claim):
    _break_ledger(wrap)                                    # manifest lost / never written; the key IS armed
    r = wrap.run(cron_claim=cron_claim)
    assert r.returncode == 75 and wrap.runs() == 0, r.stderr
    assert [e["event"] for e in wrap.events()] == ["skipped_ownership_unknown"]
    assert "ledger_unreachable_armed_unlisted:manifest=file_absent" in wrap.p1()[0]["reason"]


def test_D1_ledger_unreadable_lane_handed_back_to_cron_runs(wrap):
    wrap.own("n8n")
    wrap.own("cron", expect=1)                             # manifest records the hand-back AFTER the ledger
    _break_ledger(wrap)
    r = wrap.run(cron_claim=False)
    assert r.returncode == 0 and wrap.runs() == 1 and wrap.p1() == []


@pytest.mark.parametrize("ledger_owner, manifest_owner", [("cron", "n8n"), ("n8n", "cron"), ("n8n", None)])
def test_D1_manifest_and_ledger_disagree_fail_closed_and_report_both(wrap, ledger_owner, manifest_owner):
    wrap.store().set_owner("x-lane", ledger_owner, expect_epoch=None, by="t", now=1.0)    # ledger only
    procs = {} if manifest_owner is None else {"x-lane": {"owner": manifest_owner, "epoch": 1,
                                                          "switched_at": "x", "by": "t"}}
    wrap.manifest.write_text(json.dumps({"schema": E.HANDOVER_SCHEMA, "processes": procs}))
    before = (wrap.manifest.read_bytes(), wrap.store().owner("x-lane")["owner"])
    for cc in (True, False):
        r = wrap.run(cron_claim=cc)
        assert r.returncode == 75, r.stderr
    assert wrap.runs() == 0
    detail = wrap.events()[-1]["detail"]
    m = manifest_owner or "not_listed"
    assert f"manifest_ledger_disagree:manifest={m},ledger={ledger_owner}" in detail
    assert f"ledger={ledger_owner}" in detail and f"manifest={m}" in detail
    assert len(wrap.p1()) == 2 and "manifest_ledger_disagree" in wrap.p1()[0]["reason"]
    # never auto-reconciled: both stores exactly as they were
    assert (wrap.manifest.read_bytes(), wrap.store().owner("x-lane")["owner"]) == before


def test_D1_unreadable_manifest_fails_closed(wrap):
    wrap.own("cron")
    wrap.manifest.write_text("{torn")
    assert wrap.run(cron_claim=False).returncode == 75 and wrap.runs() == 0
    assert "handover_manifest_unreadable" in wrap.p1()[0]["reason"]


def test_D1_broken_interpreter_fails_closed_when_a_manifest_exists_or_the_key_is_armed(wrap, tmp_path):
    armed = tmp_path / "badpy_armed"     # lane-spec works (4 columns: n8n_claim 1), everything else exits 9
    armed.write_text("#!/usr/bin/env bash\n[ \"$2\" = lane-spec ] && { printf 'x-lane\\tv1\\t0\\t1\\n'; exit 0; }\n"
                     "exit 9\n")
    armed.chmod(armed.stat().st_mode | stat.S_IEXEC)
    r = wrap.run(cron_claim=False, py=str(armed))         # no manifest, but armed: fail closed (finding 2)
    assert r.returncode == 75 and wrap.runs() == 0
    assert "ownership_helper_failed" in wrap.p1()[-1]["reason"]
    bad = tmp_path / "badpy"
    bad.write_text("#!/usr/bin/env bash\n[ \"$2\" = lane-spec ] && { printf 'x-lane\\tv1\\t0\\t0\\n'; exit 0; }\n"
                   "exit 9\n")
    bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
    r = wrap.run(cron_claim=False, py=str(bad))           # no manifest, never armed: the old fail-open
    assert r.returncode == 0 and wrap.runs() == 1
    wrap.manifest.write_text(json.dumps({"schema": E.HANDOVER_SCHEMA, "processes": {}}))
    r = wrap.run(cron_claim=False, py=str(bad))
    assert r.returncode == 75 and wrap.runs() == 1
    assert "ownership_helper_failed" in wrap.p1()[-1]["reason"]


def test_D1_both_stores_n8n_is_a_quiet_skip(wrap):
    wrap.own("n8n")
    for cc in (True, False):
        assert wrap.run(cron_claim=cc).returncode == 0
    assert wrap.runs() == 0 and wrap.p1() == []
    assert [e["event"] for e in wrap.events()] == ["skipped_effect", "skipped_effect"]


def test_D1_set_owner_cli_writes_the_manifest_in_the_safe_order(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(E.HANDOVER_ENV, raising=False)
    led = tmp_path / "gov" / "l.sqlite"
    man = led.parent / E.HANDOVER_NAME
    assert E.main(["--ledger", str(led), "set-owner", "--process", "p-one", "--owner", "n8n", "--by", "t"]) == 0
    doc = E.read_handover_manifest(man)
    assert doc["processes"]["p-one"]["owner"] == "n8n" and doc["processes"]["p-one"]["epoch"] == 1
    assert not list(man.parent.glob(".*.tmp"))            # atomic: no temp file left
    # a refused compare-and-swap restores the manifest entry it wrote first (the switch did not happen)
    assert E.main(["--ledger", str(led), "set-owner", "--process", "p-two", "--owner", "n8n", "--by", "t",
                   "--expect-epoch", "7"]) == 2
    assert "p-two" not in E.read_handover_manifest(man)["processes"]
    # away from n8n: ledger first, then the manifest
    assert E.main(["--ledger", str(led), "set-owner", "--process", "p-one", "--owner", "cron", "--by", "t",
                   "--expect-epoch", "1"]) == 0
    assert E.read_handover_manifest(man)["processes"]["p-one"] == {
        "owner": "cron", "epoch": 2, "switched_at": E.read_handover_manifest(man)["processes"]["p-one"]["switched_at"],
        "by": "t"}
    capsys.readouterr()
    assert E.main(["--ledger", str(led), "ownership", "--process", "p-one"]) == 0
    assert capsys.readouterr().out.split("\t")[:3] == ["run", "cron", "cron"]


def test_D1_manifest_write_failure_after_ledger_leaves_the_safe_disagreement(tmp_path, monkeypatch):
    led = tmp_path / "l.sqlite"
    man = tmp_path / E.HANDOVER_NAME
    st = E.EffectClaimStore(CoordinationLedger(led))
    E.set_owner_with_manifest(st, man, "p-one", "n8n", expect_epoch=None, by="t", now=1.0)
    real = E._manifest_put

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(E, "_manifest_put", boom)
    with pytest.raises(OSError):
        E.set_owner_with_manifest(st, man, "p-one", "cron", expect_epoch=1, by="t", now=2.0)
    monkeypatch.setattr(E, "_manifest_put", real)
    d = E.ownership_decision("p-one", ledger=str(led), manifest=man)
    assert d["decision"] == E.DECIDE_SKIP_UNKNOWN and d["p1"] and d["ledger_owner"] == "cron" \
        and d["manifest_owner"] == "n8n"


def test_D1_seed_is_a_one_time_bootstrap_never_a_reconcile(tmp_path):
    led = tmp_path / "l.sqlite"
    man = tmp_path / E.HANDOVER_NAME
    E.EffectClaimStore(CoordinationLedger(led)).set_owner("p-one", "n8n", expect_epoch=None, by="t", now=1.0)
    out = E.handover_seed(str(led), man, apply=False, by="op", now=2.0)
    assert out["processes"]["p-one"]["owner"] == "n8n" and not man.exists()
    assert E.handover_seed(str(led), man, apply=True, by="op", now=2.0)["written"] is True
    assert E.read_handover_manifest(man)["processes"]["p-one"]["owner"] == "n8n"
    assert E.handover_seed(str(led), man, apply=True, by="op", now=3.0)["refused"].startswith("manifest_exists")


def test_D1_ownership_watch_window_and_absent_file(tmp_path):
    now = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)
    assert OW.findings(tmp_path, now) == ([], "effect_ownership:absent")
    p = tmp_path / OW.INCIDENTS_REL
    p.parent.mkdir(parents=True)
    old = {"ts": (now - timedelta(hours=8)).isoformat(), "lane": "a", "process": "a", "reason": "r"}
    new = {"ts": (now - timedelta(minutes=5)).isoformat(), "lane": "b", "process": "b", "reason": "r2"}
    p.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n" + json.dumps(new) + "\n")
    found, _ = OW.findings(tmp_path, now)
    assert [f["item"] for f in found] == ["b:OWNERSHIP_UNKNOWN"] and "x2" in found[0]["detail"]


# ══ controller fixtures ═══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_crontab(tmp_path, monkeypatch):
    store = tmp_path / "crontab.store"
    script = tmp_path / "fakecrontab"
    script.write_text(f"""#!/usr/bin/env bash
set -e
if [ "$1" = "-l" ]; then cat {store}; exit 0; fi
if [ "$1" = "-" ]; then cat > {store}; exit 0; fi
exit 2
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CRONTAB_CMD", str(script))
    monkeypatch.delenv(E.HANDOVER_ENV, raising=False)
    return store


def _cfg(tmp_path, **over):
    doc = json.loads((ROOT / "config/nightly_cutover_controller.json").read_text())
    doc.update(over)
    p = tmp_path / "controller.json"
    p.write_text(json.dumps(doc))
    return str(p)


LANES3 = ("alpha-lane", "beta-lane", "gamma-lane")


def _apply_env(tmp_path, fake_crontab, monkeypatch, lanes=("alpha-lane", "beta-lane"), **cfg):
    served, led, text = T._setup(tmp_path, lanes)
    fake_crontab.write_text(text)
    T._arm(tmp_path)
    monkeypatch.setattr(CTL.NC, "resolve_current", lambda p: (served, T.SHA))
    a = T.args(tmp_path, served, led, apply=True, config=_cfg(tmp_path, **cfg))
    return served, led, text, a


def _apply(a, **kw):
    kw.setdefault("notifier", lambda *x: True)
    return CTL.run(a, workflow_reader=T.reader, now=NOW, **kw)


def _reg_kind(tmp_path, lane):
    reg = json.loads((tmp_path / "regroot/config/lane_registry.json").read_text())
    return next(r for r in reg["lanes"] if r["lane_id"] == lane)["scheduler"]["kind"]


def _contract_stage(tmp_path, lane):
    con = json.loads((tmp_path / "regroot/config/n8n_health_contracts.json").read_text())
    return next(c for c in con["contracts"] if c["id"] == lane)["stage"]


# ══ D2: durable per-ET-night quota ═══════════════════════════════════════════════════════════════════════════════

def test_D2_night_key_is_noon_to_noon_et():
    et = T.ET
    assert TX.night_key(datetime(2026, 10, 16, 19, 30, tzinfo=et)) == "2026-10-16"
    assert TX.night_key(datetime(2026, 10, 17, 1, 0, tzinfo=et)) == "2026-10-16"
    assert TX.night_key(datetime(2026, 10, 17, 11, 59, tzinfo=et)) == "2026-10-16"
    assert TX.night_key(datetime(2026, 10, 17, 12, 0, tzinfo=et)) == "2026-10-17"


def test_D2_quota_is_counted_across_repeated_invocations(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, LANES3, max_lanes_per_night=2)
    code, rc = _apply(a)
    assert code == 0 and [s["lane_id"] for s in rc["applied"]] == ["alpha-lane", "beta-lane"], rc
    # second and third invocations the same night: the per-evaluation cap alone would allow 2 more each
    for _ in range(2):
        code, rc = _apply(a)
        assert code == 0 and rc["applied"] == [], rc
        g = next(v for v in rc["plan"]["lanes"] if v["lane_id"] == "gamma-lane")
        assert g["held"].startswith("nightly_cap_reached") and "already used tonight=2" in g["held"]
    assert fake_crontab.read_text().split("\n")[4] == text.split("\n")[4]          # gamma never retired
    q = TX.quota_read(Path(a.receipt_dir), TX.night_key(NOW))
    assert TX.quota_used(q) == 2 and [e["status"] for e in q["entries"]] == ["applied", "applied"]


def test_D2_reservation_under_the_lock_refuses_beyond_the_cap(tmp_path):
    rdir = tmp_path / "r"
    n = TX.night_key(NOW)
    assert TX.quota_reserve(rdir, n, lane="a", txn_id="t1", cap=1, now=NOW) == (True, 0)
    assert TX.quota_reserve(rdir, n, lane="b", txn_id="t2", cap=1, now=NOW) == (False, 1)
    TX.quota_mark(rdir, n, "t1", "released")                 # a rolled-back lane gives its slot back
    assert TX.quota_reserve(rdir, n, lane="b", txn_id="t2", cap=1, now=NOW) == (True, 0)


def test_D2_plan_and_dry_run_show_tonights_used_quota(tmp_path):
    served, led, text = T._setup(tmp_path, LANES3)
    ct = tmp_path / "ct.txt"
    ct.write_text(text)
    a = T.args(tmp_path, served, led, ct, dry_run=True, config=_cfg(tmp_path, max_lanes_per_night=2))
    TX.quota_reserve(Path(a.receipt_dir), TX.night_key(NOW), lane="x", txn_id="tx", cap=2, now=NOW)
    TX.txn_write(Path(a.receipt_dir), {"schema": TX.TXN_SCHEMA, "txn_id": "tx", "status": "committed",
                                       "lane_id": "x"})
    TX.quota_mark(Path(a.receipt_dir), TX.night_key(NOW), "tx", "applied")
    code, rc = CTL.run(a, workflow_reader=T.reader, now=NOW)
    assert code == 0 and rc["plan"]["quota_used_before"] == 1 and rc["plan"]["counts"] == {"ready": 1, "held": 2}


# ══ D3: fresh checks at mutation time, inside the fenced handover ════════════════════════════════════════════════

def _after_first_edit(hook):
    """An edit callable that runs the real edit capability, then `hook` once after the FIRST lane's edit."""
    state = {"n": 0}

    def edit(req, **kw):
        out = CTL.call_edit(req, **kw)
        if req["op"] == "retire":
            state["n"] += 1
            if state["n"] == 1:
                hook()
        return out
    return edit


def test_D3_grant_revoked_between_lanes_stops_the_cohort(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    edit = _after_first_edit(lambda: (tmp_path / "grants.json").write_text("{}"))
    code, rc = _apply(a, edit=edit)
    assert code == 2 and rc["cohort_stop"].startswith("authorization_revoked_mid_run"), rc["cohort_stop"]
    assert [s["lane_id"] for s in rc["applied"]] == ["alpha-lane"]               # the committed lane stays
    live = fake_crontab.read_text().split("\n")
    assert live[2].startswith("# RETIRED") and live[3] == text.split("\n")[3]   # beta untouched
    assert _reg_kind(tmp_path, "beta-lane") == "cron"


def test_D3_release_or_allowlist_changed_between_lanes_stops_the_cohort(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    al = served / "config/n8n_run_allowlist.json"
    edit = _after_first_edit(lambda: al.write_text(al.read_text() + " "))
    code, rc = _apply(a, edit=edit)
    assert code == 2 and rc["cohort_stop"] == "shared_state_changed_mid_run:allowlist_version", rc["cohort_stop"]
    assert fake_crontab.read_text().split("\n")[3] == text.split("\n")[3]


def test_D3_workflow_graph_changed_between_lanes_stops_the_cohort(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    graphs = {"wf": dict(T.DISPATCHER_WF, active=True)}
    edit = _after_first_edit(lambda: graphs.update(wf=dict(T.DISPATCHER_WF, active=True, settings={"x": 1})))
    code, rc = CTL.run(a, workflow_reader=lambda: [graphs["wf"]], now=NOW, edit=edit, notifier=lambda *x: True)
    assert code == 2 and rc["cohort_stop"] == "shared_state_changed_mid_run:workflow_live", rc["cohort_stop"]


def _keyed(served, led, tmp_path, lanes=("alpha-lane", "beta-lane")):
    (served / "config/n8n_effect_keys.json").write_text(json.dumps({"schema": "N8nEffectKeys@v1", "lanes": {
        l: {"process": l, "input_version": "v1", "n8n_claim": True, "cron_claim": False} for l in lanes}}))
    st = E.EffectClaimStore(CoordinationLedger(led))
    man = Path(led).parent / E.HANDOVER_NAME
    for l in lanes:
        E.set_owner_with_manifest(st, man, l, "n8n", expect_epoch=None, by="t", now=1.0)
    # allowlist/contract versions did not change; refresh the proof runs' versions only if needed
    return man


def test_D3_owner_flipped_mid_run_holds_that_lane(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    _keyed(served, led, tmp_path)

    def flip():
        c = sqlite3.connect(led)                           # a raw owner change (no manifest): the worst case
        c.execute("UPDATE effect_owners SET owner='cron', epoch=epoch+1 WHERE process='beta-lane'")
        c.commit()
        c.close()
    code, rc = _apply(a, edit=_after_first_edit(flip))
    assert code == 0 and [s["lane_id"] for s in rc["applied"]] == ["alpha-lane"], rc
    b = next(v for v in rc["plan"]["lanes"] if v["lane_id"] == "beta-lane")
    assert b["held"].startswith("changed_at_mutation:effect_owner_cron"), b["held"]
    assert fake_crontab.read_text().split("\n")[3] == text.split("\n")[3]


def test_D3_in_flight_run_appearing_mid_run_holds_that_lane(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)

    def start_run():
        c = sqlite3.connect(led)
        c.execute("INSERT INTO runs VALUES ('d:beta-lane:live:x','beta-lane','live','RUNNING','n8n:workflow:"
                  "tradeai-dispatcher',?,?,NULL,NULL,'{}')", (NOW.isoformat(), NOW.isoformat()))
        c.commit()
        c.close()
    code, rc = _apply(a, edit=_after_first_edit(start_run))
    b = next(v for v in rc["plan"]["lanes"] if v["lane_id"] == "beta-lane")
    assert code == 0 and b["held"].startswith("changed_at_mutation:in_flight_run"), b["held"]


def test_D3_the_handover_lock_is_held_across_each_lanes_check_and_edit(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    man = _keyed(served, led, tmp_path)
    seen = []

    def try_switch():
        with pytest.raises(E.HandoverLockTimeout):
            with E.handover_lock(man, timeout=0.2):
                pass
        seen.append("fenced")
    code, rc = _apply(a, edit=_after_first_edit(try_switch))
    assert seen == ["fenced"] and code == 0


def test_D3_concurrent_invocation_is_refused_and_changes_nothing(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch)
    rdir = Path(a.receipt_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    fd = os.open(rdir / TX.LOCK_NAME, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        code, rc = _apply(a)
    finally:
        os.close(fd)
    assert code == 1 and rc["refused"].startswith("controller_busy") and fake_crontab.read_text() == text
    assert not (rdir / "quota").exists()
    # and two real invocations racing: the second one, started while the first holds the lock, is refused
    results = []

    def nested():
        results.append(_apply(a))
    code, rc = _apply(a, edit=_after_first_edit(nested))
    assert code == 0 and results[0][0] == 1 and results[0][1]["refused"].startswith("controller_busy")


# ══ D4: write-ahead transaction, crash injection, deterministic idempotent recovery ══════════════════════════════

class SimulatedCrash(BaseException):
    """Process death: not an Exception, so no handler in the controller runs (only `finally` drops the locks)."""


def _crash_at(point):
    def cp(p):
        if p == point:
            raise SimulatedCrash(p)
    return cp


def _snapshot(tmp_path, fake_crontab):
    return (fake_crontab.read_text(), (tmp_path / "regroot/config/lane_registry.json").read_text(),
            (tmp_path / "regroot/config/n8n_health_contracts.json").read_text())


@pytest.mark.parametrize("point, outcome", [
    ("txn_written", "rolled_back"),            # record written, nothing mutated
    ("crontab_done", "rolled_back"),           # crontab done, registry not
    ("registry_done", "rolled_back"),          # registry done, contract not
    ("contracts_done", "committed_by_recovery"),  # every mutation landed, rollback receipt missing
    ("rollback_receipt_done", "committed_by_recovery"),  # everything landed, commit mark missing
])
def test_D4_crash_between_writes_is_recovered_deterministically(tmp_path, fake_crontab, monkeypatch, point, outcome):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, ("alpha-lane",))
    pristine = _snapshot(tmp_path, fake_crontab)
    with pytest.raises(SimulatedCrash):
        _apply(a, checkpoint=_crash_at(point))
    rdir = Path(a.receipt_dir)
    open_ = TX.open_txns(rdir)
    assert len(open_) == 1 and open_[0]["lane_id"] == "alpha-lane"
    rec = open_[0]
    assert rec["crontab"]["edits"] and rec["registry"]["before"] and rec["backups"]["crontab"]   # write-ahead intent
    assert Path(rec["backups"]["registry"]).read_text() == pristine[1]
    # a dry run reports the incomplete transaction and does no work
    d = T.args(tmp_path, served, led, dry_run=True, config=a.config)
    code, rc = CTL.run(d, workflow_reader=T.reader, now=NOW)
    assert code == 2 and rc["cohort_stop"].startswith("incomplete_txn_pending_recovery")
    # the next armed start recovers BEFORE any new work, then stops for the night
    code, rc = _apply(a)
    assert code == 2 and rc["cohort_stop"].startswith("recovered_incomplete_txn") and rc["applied"] == []
    assert [r["outcome"] for r in rc["recovered"]] == [outcome]
    final = TX.quota_read(rdir, TX.night_key(NOW))["entries"][0]["status"]
    if outcome == "rolled_back":
        assert _snapshot(tmp_path, fake_crontab) == pristine and final == "released"
    else:
        assert fake_crontab.read_text().split("\n")[2].startswith("# RETIRED 2026-10-16 n8n-cutover alpha-lane ")
        assert _reg_kind(tmp_path, "alpha-lane") == "n8n" and _contract_stage(tmp_path, "alpha-lane") == "cutover"
        assert final == "applied"
        rb = json.loads(Path(json.loads(TX.txn_path(rdir, rec["txn_id"]).read_text())
                             ["rollback_receipt_path"]).read_text())
        assert rb["schema"] == CTL.ROLLBACK_SCHEMA and rb["row_before"]["scheduler"]["kind"] == "cron"
    # recovery is idempotent: running it twice more changes nothing
    snap = _snapshot(tmp_path, fake_crontab)
    assert CTL.recover(rdir) == [] and CTL.recover(rdir) == []
    assert _snapshot(tmp_path, fake_crontab) == snap and TX.open_txns(rdir) == []


def test_D4_recovery_interrupted_midway_is_idempotent(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, ("alpha-lane",))
    pristine = _snapshot(tmp_path, fake_crontab)
    with pytest.raises(SimulatedCrash):
        _apply(a, checkpoint=_crash_at("registry_done"))
    rdir = Path(a.receipt_dir)
    real = NC.json_step
    calls = {"n": 0}

    def dying_step(step, undo=False):
        out = real(step, undo=undo)
        calls["n"] += 1
        raise SimulatedCrash("during recovery")            # the registry undo landed, the crontab undo did not
    monkeypatch.setattr(CTL.NC, "json_step", dying_step)
    with pytest.raises(SimulatedCrash):
        CTL.recover(rdir)
    monkeypatch.setattr(CTL.NC, "json_step", real)
    assert TX.open_txns(rdir)[0]["status"] == "rolling_back"
    out1 = CTL.recover(rdir)
    assert [r["outcome"] for r in out1] == ["rolled_back"] and _snapshot(tmp_path, fake_crontab) == pristine
    assert CTL.recover(rdir) == [] and _snapshot(tmp_path, fake_crontab) == pristine


def test_D4_a_target_changed_by_someone_else_is_reported_never_reconciled(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, ("alpha-lane",))
    with pytest.raises(SimulatedCrash):
        _apply(a, checkpoint=_crash_at("registry_done"))
    p = tmp_path / "regroot/config/lane_registry.json"
    doc = json.loads(p.read_text())
    doc["lanes"][0]["owner"] = "someone-else"              # neither the before nor the after image
    p.write_text(json.dumps(doc, indent=2) + "\n")
    snap = _snapshot(tmp_path, fake_crontab)
    code, rc = _apply(a)
    assert code == 2 and rc["cohort_stop"].startswith("recovery_conflict"), rc["cohort_stop"]
    assert rc["recovered"][0]["outcome"] == "conflict"
    assert rc["recovered"][0]["inspected"] == {"crontab": "applied", "registry": "conflict", "contracts": "not_applied"}
    assert _snapshot(tmp_path, fake_crontab) == snap        # nothing touched
    code, rc = _apply(a)                                    # still stopped on every later start
    assert code == 2 and rc["cohort_stop"].startswith("recovery_conflict")


def test_D4_orphan_reservation_without_a_record_is_released(tmp_path):
    rdir = tmp_path / "r"
    TX.quota_reserve(rdir, TX.night_key(NOW), lane="a", txn_id="never-written", cap=5, now=NOW)
    out = CTL.recover(rdir)
    assert out == [{"txn_id": "never-written", "lane_id": "a", "outcome": "orphan_reservation_released"}]
    assert TX.quota_used(TX.quota_read(rdir, TX.night_key(NOW))) == 0 and CTL.recover(rdir) == []


def test_D4_non_crash_failure_mid_lane_rolls_back_through_the_same_record(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, ("alpha-lane",))
    pristine = _snapshot(tmp_path, fake_crontab)
    real = NC.json_step

    def failing(step, undo=False):
        if not undo and step["path"].endswith("n8n_health_contracts.json"):
            raise NC.CohortStop("registry_write_failure:injected")
        return real(step, undo=undo)
    monkeypatch.setattr(CTL.NC, "json_step", failing)
    code, rc = _apply(a)
    assert code == 2 and "registry_write_failure:injected" in rc["cohort_stop"] and "rolled_back" in rc["cohort_stop"]
    assert _snapshot(tmp_path, fake_crontab) == pristine     # crontab and registry rolled back, byte-exact
    assert TX.open_txns(Path(a.receipt_dir)) == []
    assert TX.quota_used(TX.quota_read(Path(a.receipt_dir), TX.night_key(NOW))) == 0


def test_D4_contract_changed_mid_lane_is_a_conflict_nothing_is_undone(tmp_path, fake_crontab, monkeypatch):
    served, led, text, a = _apply_env(tmp_path, fake_crontab, monkeypatch, ("alpha-lane",))
    p = tmp_path / "regroot/config/n8n_health_contracts.json"

    def corrupt(point):
        if point == "registry_done":
            p.write_text(p.read_text().replace('"stage": "canary"', '"stage": "other"'))
    code, rc = _apply(a, checkpoint=corrupt)
    assert code == 2 and "changed by someone else" in rc["cohort_stop"] and "conflict" in rc["cohort_stop"]
    rec = TX.open_txns(Path(a.receipt_dir))[0]
    assert rec["status"] == "conflict" and rec["conflict"]["contracts"] == "conflict"
    assert fake_crontab.read_text().split("\n")[2].startswith("# RETIRED")   # left for the operator, reported
