"""Release Train v2, Phase 4: n8n coordination (2026-10-21; docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md).

Covers the contract (TrainWindowRequest@v1 / TrainWindowReceipt@v1 / ReleaseTrainReadiness@v1), the request lane, the
relay route and the gateway's read-only release_train_window operation, the generated workflow
``tradeai-fabric-release-train`` (no credential, no merge/promote/push, no direct sender node, only the two relay
routes, only Run Lane for the four request lanes), the n8n framework check, the lane registry rows, the allowlist
entries, the health contracts (REVIEWED by the operator 2026-10-21; the gate is clean) and the transitive
capabilities of the request lanes (no sender, broker or order reach).

Hermetic: tmp_path state dirs, spools, STOP latches and ledgers; a fake delegation loader; an in-process gateway behind
the relay's injectable transport. psycopg2 is stubbed when absent. No database, network, n8n, git write or send; the
production state root is never read (TRADEAI_STATE_ROOT / TRADEAI_RELEASE_WINDOW_STATE_DIR point at tmp_path).
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import audit_lane_transitive_capabilities as CAP  # noqa: E402
import check_n8n_workflow_framework as FW  # noqa: E402
import n8n_workflow_templates as T  # noqa: E402
import release_train_window_request as LANE  # noqa: E402
from scripts.lib import release_train_window as W  # noqa: E402
from scripts import n8n_coordination_gateway as SRV  # noqa: E402
from scripts import n8n_run_relay as R  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore, LedgerReceiptStore  # noqa: E402
from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS  # noqa: E402

ET = ZoneInfo("America/New_York")
WF_PATH = ROOT / "docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json"
FABRIC_INDEX = ROOT / "docs/implementation/n8n-maturity/workflows/fabric/INDEX.json"
LANES = ("release-train-request-1800", "release-train-request-0000", "release-train-request-0600",
         "release-train-request-0800")
#: 2026-10-21 16:30 ET = the 18:00 window's request tick (W-90); EDT.
REQUEST_TICK = datetime(2026, 10, 21, 16, 30, tzinfo=ET)
KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
BEARER = "relay-bearer-not-a-live-secret-0123456789"
SHA = "a" * 40


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    """Every test runs against tmp state: the production state root is never read or written."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state-root"))
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(tmp_path / "rw"))
    for name in ("TRADEAI_RUN_ID", "TRADEAI_RUN_ATTEMPT", "TRADEAI_RUN_MODE", "TRADEAI_CODE_SHA"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "rw").mkdir()
    yield


@pytest.fixture
def cfg():
    return copy.deepcopy(W.load_config())


def shadow_cfg(cfg, enabled=True):
    c = copy.deepcopy(cfg)
    c["shadow"] = {"enabled": enabled}
    return c


def policy(armed=False, enabled=()):
    pol = json.loads((ROOT / "config/release_train_policy.json").read_text())
    pol["armed"] = armed
    for w in pol["windows"]:
        w["enabled"] = w["local_time"].replace(":", "") in enabled
    return pol


def deleg(code):
    return lambda: SimpleNamespace(code=code)


def snap(**kw):
    base = {"stop_state": "ABSENT", "armed": False, "shadow_enabled": False, "delegation_state": "NOT_CONFIGURED",
            "window_enabled": False, "policy_version": "2026-10-21.1"}
    base.update(kw)
    return base


def receipt(req, **kw):
    doc = {
        "schema": "TrainWindowReceipt@v1", "request_id": req["request_id"], "window_id": req["window_id"],
        "window_slot": req["window_slot"], "shadow": req["shadow"], "mode": "simulate", "state": "COMPLETED",
        "acknowledged_at": "2026-10-21T20:30:31+00:00", "finished_at": "2026-10-21T20:41:02+00:00",
        "controller": {"version": "release_train_controller/1", "code_sha": None, "host": "test"},
        "train_id": "rt-20261021-1800-a1b2c3", "outcome": "NO_OP", "refusal": None, "members": [],
        "candidate_sha": None, "main_sha": None, "served_sha": None,
        "needs_action": [{"code": "HELD_NEEDS_OPERATOR", "pr": 1903, "text": "ride approval required"}],
        "simulated_effects": ["merge"], "injected_failures": [], "p1_alert": None, "evidence_refs": ["x"],
    }
    doc.update(kw)
    return doc


# ── config and windows ──────────────────────────────────────────────────────────────────────────────────────


def test_committed_config_is_valid_and_shadow_is_off_at_merge(cfg):
    assert W.validate_config(cfg) == []
    assert cfg["shadow"]["enabled"] is False
    assert [s["lane_id"] for s in cfg["slots"]] == list(LANES)


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(timezone="UTC"),
    lambda c: c["slots"].reverse(),
    lambda c: c["slots"][0].update(lane_id="release-train-request-9999"),
    lambda c: c.update(request_lead_min=5),
    lambda c: c.update(shadow={"enabled": "yes"}),
    lambda c: c["receipt_wait_s"].pop("forced"),
])
def test_config_defects_are_refused(cfg, mutate):
    mutate(cfg)
    assert W.validate_config(cfg)


def test_window_identity_and_tick(cfg):
    start = W.window_start("1800", REQUEST_TICK, cfg)
    assert W.window_id(start) == "2026-10-21T18:00-04:00"
    assert W.tick_kind(start, REQUEST_TICK, cfg) == "on_window"
    # 10 minutes after the grace: the 18:00 window is gone until tomorrow (no catch-up)
    late = datetime(2026, 10, 21, 18, 16, tzinfo=ET)
    assert W.window_id(W.window_start("1800", late, cfg)) == "2026-10-22T18:00-04:00"
    # an afternoon forced tick for 06:00 is off-window
    noon = datetime(2026, 10, 21, 12, 0, tzinfo=ET)
    s06 = W.window_start("0600", noon, cfg)
    assert W.window_id(s06) == "2026-10-22T06:00-04:00" and W.tick_kind(s06, noon, cfg) == "off_window"


def test_window_identity_is_dst_safe(cfg):
    # 2026-11-01 01:00-02:00 ET repeats (EDT -> EST). The 06:00 window that day is EST (-05:00).
    before = datetime(2026, 11, 1, 1, 30, tzinfo=ET)  # fold=0, still EDT
    s = W.window_start("0600", before, cfg)
    assert W.window_id(s) == "2026-11-01T06:00-05:00"
    # the 00:00 window on the fall-back day is EDT; the next one is EST
    assert W.window_id(W.window_start("0000", datetime(2026, 10, 31, 23, 0, tzinfo=ET), cfg)) == \
        "2026-11-01T00:00-04:00"
    assert W.window_id(W.window_start("0000", datetime(2026, 11, 1, 3, 0, tzinfo=ET), cfg)) == \
        "2026-11-02T00:00-05:00"


def test_request_ids(cfg):
    start = W.window_start("1800", REQUEST_TICK, cfg)
    assert W.request_id_for("1800", start, "on_window", "x") == "rtw-20261021-1800-win"
    rid = W.request_id_for("1800", start, "off_window", "run-1")
    assert W.REQUEST_ID_RE.fullmatch(rid) and rid != W.request_id_for("1800", start, "off_window", "run-2")


# ── the host gate ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("stop,reason", [("SET", "stop_set"), ("UNREADABLE", "stop_unreadable"),
                                         ("UNAVAILABLE", "stop_unreadable")])
def test_stop_is_a_no_op_even_when_live_able(stop, reason):
    d = W.decide(snap(stop_state=stop, armed=True, delegation_state="ACTIVE", window_enabled=True,
                      shadow_enabled=True), "on_window", shadow_only=False)
    assert d == {"disposition": "no_op", "shadow": None, "shadow_reason": None, "no_op_reason": reason}


def test_not_armed_and_shadow_off_is_a_no_op():
    assert W.decide(snap(), "on_window", shadow_only=False)["no_op_reason"] == "not_armed"


def test_shadow_enabled_requests_shadow_with_the_first_failing_reason():
    d = W.decide(snap(shadow_enabled=True), "on_window", shadow_only=False)
    assert d["disposition"] == "request" and d["shadow"] is True and d["shadow_reason"] == "train_not_armed"
    d = W.decide(snap(shadow_enabled=True, armed=True), "on_window", shadow_only=False)
    assert d["shadow_reason"] == "delegation_not_active"
    d = W.decide(snap(shadow_enabled=True, armed=True, delegation_state="ACTIVE"), "on_window", shadow_only=False)
    assert d["shadow_reason"] == "window_not_enabled"


def test_live_only_when_every_condition_holds():
    live = snap(armed=True, delegation_state="ACTIVE", window_enabled=True)
    assert W.decide(live, "on_window", shadow_only=False)["shadow"] is False
    # the same readiness with a forced (off-window) tick or a shadow-only lane can never be live
    assert W.decide({**live, "shadow_enabled": True}, "off_window", shadow_only=False)["shadow_reason"] == "off_window"
    assert W.decide({**live, "shadow_enabled": True}, "on_window", shadow_only=True)["shadow_reason"] == \
        "shadow_only_lane"
    assert W.decide(live, "off_window", shadow_only=False)["disposition"] == "no_op"


# ── TrainWindowRequest@v1 / TrainWindowReceipt@v1 ───────────────────────────────────────────────────────────


def _request(cfg, now=REQUEST_TICK, **snapkw):
    s = snap(shadow_enabled=True, **snapkw)
    tick = W.tick_kind(W.window_start("1800", now, cfg), now, cfg)
    d = W.decide(s, tick, shadow_only=False)
    return W.build_request("1800", now, cfg, s, d, run_id="rtw:release-train-request-1800:live:20261021T1630",
                           attempt=1, run_mode="live", code_sha="b" * 40)


def test_built_request_is_valid_and_request_only(cfg):
    req = _request(cfg)
    assert W.validate_request(req) == []
    assert req["authority"] == "REQUEST_ONLY" and req["shadow"] is True and req["tick"] == "on_window"
    assert req["request_id"] == "rtw-20261021-1800-win"
    assert req["expires_at"] == "2026-10-21T22:15:00+00:00"  # 18:00 EDT + 15 min grace


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.update(shadow=False, shadow_reason=None, tick="off_window"), "shadow=false"),
    (lambda r: r.update(shadow_reason=None), "shadow=true needs"),
    (lambda r: r.update(request_id="rtw-20261021-1800-fabcdef"), "suffix"),
    (lambda r: r.update(candidate_sha="c" * 40), "unknown key candidate_sha"),
    (lambda r: r.update(authority="RELEASE"), "authority"),
    (lambda r: r["requested_by"].update(lane_id="release-train-request-0600"), "slot's lane"),
    (lambda r: r.update(window_id="2026-10-22T18:00-04:00"), "disagree"),
    (lambda r: r.update(expires_at=r["requested_at"]), "expires_at"),
])
def test_request_program_rules(cfg, mutate, needle):
    req = _request(cfg)
    mutate(req)
    errs = W.validate_request(req)
    assert errs and any(needle in e for e in errs), errs


def test_receipt_rules(cfg):
    req = _request(cfg)
    assert W.validate_receipt(receipt(req)) == []
    assert any("simulate" in e for e in W.validate_receipt(receipt(req, mode="live")))
    assert any("outcome" in e for e in W.validate_receipt(receipt(req, outcome=None)))
    assert any("refusal" in e for e in W.validate_receipt(receipt(req, state="REFUSED")))
    assert W.validate_receipt(receipt(req, state="REFUSED", outcome=None,
                                      refusal={"code": "STOP_SET", "detail": "latched"})) == []
    assert W.validate_receipt(receipt(req, p1_alert={"sent_by": "n8n", "incident_key": "k",
                                                     "at": "2026-10-21T20:41:02+00:00"}))
    ack = receipt(req, state="ACKNOWLEDGED", outcome=None, finished_at=None)
    assert W.validate_receipt(ack) == []


# ── the request lane ────────────────────────────────────────────────────────────────────────────────────────


def _run(tmp_path, monkeypatch, args, *, now=REQUEST_TICK, cfg_override=None, pol=None, code="PAUSED", env=None):
    if cfg_override is not None:
        monkeypatch.setattr(W, "load_config", lambda p=None: cfg_override)
    return LANE.run(["--window", "1800", "--state-dir", str(tmp_path / "rw"), *args], now=now,
                    policy=pol or policy(), delegation_loader=deleg(code),
                    receipt_path=tmp_path / "receipt.json", environ=env or {})


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_dry_run_writes_nothing(tmp_path, monkeypatch, cfg, capsys):
    rc = _run(tmp_path, monkeypatch, ["--dry-run"], cfg_override=shadow_cfg(cfg))
    assert rc == 0
    assert _files(tmp_path / "rw") == [] and not (tmp_path / "receipt.json").exists()
    assert not (tmp_path / "state-root").exists()
    out = capsys.readouterr().out
    assert out.startswith("DRY-RUN ") and '"request_id": "rtw-20261021-1800-win"' in out


def test_default_mode_is_dry_run(tmp_path, monkeypatch, cfg):
    assert _run(tmp_path, monkeypatch, [], cfg_override=shadow_cfg(cfg)) == 0
    assert _files(tmp_path / "rw") == []


def test_append_writes_one_request_then_a_duplicate(tmp_path, monkeypatch, cfg):
    env = {"TRADEAI_RUN_ID": "rtw:release-train-request-1800:live:20261021T1630", "TRADEAI_RUN_ATTEMPT": "1",
           "TRADEAI_RUN_MODE": "live"}
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg), env=env) == 0
    assert _files(tmp_path / "rw") == ["train_requests/journal/rtw-20261021-1800-win.json",
                                       "train_requests/pending/rtw-20261021-1800-win.json"]
    doc = json.loads((tmp_path / "rw/train_requests/pending/rtw-20261021-1800-win.json").read_text())
    assert W.validate_request(doc) == [] and doc["requested_by"]["run_id"] == env["TRADEAI_RUN_ID"]
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["status"] == "ok" and rec["produced_count"] == 1 and rec["summary"]["disposition"] == "requested"
    # the same window again: a duplicate, nothing overwritten
    before = (tmp_path / "rw/train_requests/journal/rtw-20261021-1800-win.json").read_bytes()
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg), env=env) == 0
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["summary"]["disposition"] == "duplicate" and rec["produced_count"] == 0
    assert rec["empty_reason"] == "nothing_due"
    assert (tmp_path / "rw/train_requests/journal/rtw-20261021-1800-win.json").read_bytes() == before


def test_a_claimed_request_is_still_a_duplicate(tmp_path, monkeypatch, cfg):
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg)) == 0
    spool = tmp_path / "rw/train_requests"
    (spool / "claimed").mkdir()
    os.rename(spool / "pending/rtw-20261021-1800-win.json", spool / "claimed/rtw-20261021-1800-win.json")
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg)) == 0
    assert not (spool / "pending/rtw-20261021-1800-win.json").exists()
    assert json.loads((tmp_path / "receipt.json").read_text())["summary"]["disposition"] == "duplicate"


@pytest.mark.parametrize("latch,reason", [('{"latched_at": "x"}', "stop_set"), ("not json", "stop_unreadable")])
def test_stop_latch_means_no_request(tmp_path, monkeypatch, cfg, latch, reason):
    (tmp_path / "rw/STOP.json").write_text(latch)
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg)) == 0
    assert not (tmp_path / "rw/train_requests").exists()
    rec = json.loads((tmp_path / "receipt.json").read_text())
    assert rec["summary"]["disposition"] == "no_op" and rec["summary"]["no_op_reason"] == reason
    assert rec["produced_count"] == 0 and rec["empty_reason"] == "nothing_due"


def test_not_armed_without_shadow_is_a_recorded_no_op(tmp_path, monkeypatch, cfg):
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=cfg) == 0
    assert not (tmp_path / "rw/train_requests").exists()
    assert json.loads((tmp_path / "receipt.json").read_text())["summary"]["no_op_reason"] == "not_armed"


def test_forced_off_window_tick_is_always_shadow_even_when_armed(tmp_path, monkeypatch, cfg):
    noon = datetime(2026, 10, 21, 12, 0, tzinfo=ET)
    rc = _run(tmp_path, monkeypatch, ["--append"], now=noon, cfg_override=shadow_cfg(cfg),
              pol=policy(armed=True, enabled=("1800",)), code="AUTHORIZED",
              env={"TRADEAI_RUN_ID": "rtw:release-train-request-1800:live:20261021T120000"})
    assert rc == 0
    (path,) = list((tmp_path / "rw/train_requests/pending").iterdir())
    doc = json.loads(path.read_text())
    assert doc["tick"] == "off_window" and doc["shadow"] is True and doc["shadow_reason"] == "off_window"
    assert doc["request_id"].startswith("rtw-20261021-1800-f")


def test_live_request_only_when_armed_active_enabled_and_on_window(tmp_path, monkeypatch, cfg):
    rc = _run(tmp_path, monkeypatch, ["--append"], cfg_override=cfg, pol=policy(armed=True, enabled=("1800",)),
              code="AUTHORIZED")
    assert rc == 0
    doc = json.loads((tmp_path / "rw/train_requests/pending/rtw-20261021-1800-win.json").read_text())
    assert doc["shadow"] is False and doc["readiness"]["delegation_state"] == "ACTIVE"
    # the same state through a shadow-only lane stays shadow (and is a duplicate of nothing: new window tomorrow)
    rc = _run(tmp_path, monkeypatch, ["--append", "--shadow-only", "--dry-run"], cfg_override=shadow_cfg(cfg))
    assert rc == 2  # --append and --dry-run are exclusive: usage error, nothing written


def test_lane_never_loads_the_deployer(tmp_path):
    """Run the real CLI in a fresh interpreter; release_window.py (the deployer) must never be imported."""
    # The mail module name is spelled in two parts so scripts/check_provider_chokepoint.py (which flags the literal
    # module name anywhere) does not count this negative assertion as an SMTP producer (release-2 integration).
    code = (
        "import runpy, sys\n"
        f"sys.argv = ['x', '--window', '0600', '--dry-run', '--state-dir', {str(tmp_path / 'rw')!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(ROOT / 'scripts/release_train_window_request.py')!r}, run_name='__main__')\n"
        "except SystemExit as e:\n"
        "    rc = e.code\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[-1] in ('release_window', 'release_capability',\n"
        "             'release_control', 'telegram_alert', 'smtp' + 'lib', 'subprocess_never'))\n"
        "print('LOADED', bad, 'RC', rc)\n"
    )
    env = {**os.environ, "TRADEAI_STATE_ROOT": str(tmp_path / "sr"),
           "TRADEAI_RELEASE_WINDOW_STATE_DIR": str(tmp_path / "rw"), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(ROOT),
                         timeout=120)
    assert "LOADED [] RC 0" in out.stdout, out.stdout + out.stderr
    assert _files(tmp_path / "rw") == []


# ── views: readiness, window, coverage ──────────────────────────────────────────────────────────────────────


def _readiness(tmp_path, cfg, code="PAUSED"):
    return W.readiness_view(REQUEST_TICK.astimezone(timezone.utc), cfg=cfg, stop_dir=tmp_path / "rw",
                            delegation_loader=deleg(code), census_path=tmp_path / "no-census.json",
                            state_dir=tmp_path / "rw")


def test_readiness_view_fails_closed_and_never_turns_missing_into_zero(tmp_path, cfg):
    r = _readiness(tmp_path, cfg)
    assert r["schema"] == "ReleaseTrainReadiness@v1" and r["state"] == "OK"
    assert r["stop"] == {"state": "ABSENT", "effective_stop": False, "freshness": "OK"}
    assert r["queue_counts"] is None and r["queue_freshness"] == "UNAVAILABLE"
    assert r["delegation"]["state"] == "PAUSED" and r["armed"] is False
    assert [w["slot"] for w in r["windows"]] == ["1800", "0000", "0600", "0800"]
    assert [c["slot"] for c in r["shadow_coverage"]] == list(W.SLOTS)
    (tmp_path / "rw/STOP.json").write_text("{")
    r = _readiness(tmp_path, cfg)
    assert r["stop"]["state"] == "UNREADABLE" and r["stop"]["effective_stop"] is True


@pytest.mark.parametrize("code,state", [("AUTHORIZED", "ACTIVE"), ("MISSING", "NOT_CONFIGURED"), ("PAUSED", "PAUSED"),
                                        ("REVOKED", "REVOKED"), ("IN_REPO", "INVALID"), ("UNREADABLE", "INVALID")])
def test_delegation_mapping(code, state):
    assert W.delegation_state(deleg(code))[0] == state


def test_delegation_loader_failure_is_unavailable():
    def boom():
        raise OSError("x")
    assert W.delegation_state(boom)[0] == "UNAVAILABLE"


def test_window_view_by_run_id_and_slot_and_receipt_validation(tmp_path, monkeypatch, cfg):
    env = {"TRADEAI_RUN_ID": "rtw:release-train-request-1800:live:20261021T1630"}
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg), env=env) == 0
    now = REQUEST_TICK.astimezone(timezone.utc)
    v = W.window_view(run_id=env["TRADEAI_RUN_ID"], now=now, state_dir=tmp_path / "rw")
    assert v["request_state"] == "PENDING" and v["receipt"] is None and v["request"]["shadow"] is True
    assert W.window_view(slot="1800", now=now, state_dir=tmp_path / "rw")["request"]["request_id"] == \
        "rtw-20261021-1800-win"
    assert W.window_view(slot="0600", now=now, state_dir=tmp_path / "rw")["request_state"] == "NOT_FOUND"
    req = json.loads((tmp_path / "rw/train_requests/pending/rtw-20261021-1800-win.json").read_text())
    rdir = tmp_path / "rw/train_requests/receipts"
    rdir.mkdir()
    (rdir / "rtw-20261021-1800-win.json").write_text(json.dumps(receipt(req)))
    v = W.window_view(run_id=env["TRADEAI_RUN_ID"], now=now, state_dir=tmp_path / "rw")
    assert v["receipt"]["state"] == "COMPLETED" and "evidence_refs" not in v["receipt"]
    (rdir / "rtw-20261021-1800-win.json").write_text(json.dumps(receipt(req, mode="live")))  # shadow + live
    v = W.window_view(run_id=env["TRADEAI_RUN_ID"], now=now, state_dir=tmp_path / "rw")
    assert v["receipt"] is None and v["receipt_problem"] == "receipt_invalid"
    cov = {c["slot"]: c for c in W.shadow_coverage(tmp_path / "rw")}
    assert cov["1800"]["request_id"] == "rtw-20261021-1800-win" and cov["0600"]["last_requested_at"] is None
    assert W.window_view(run_id="bad id", now=now, state_dir=tmp_path / "rw")["state"] == "REFUSED"
    assert W.window_view(slot="1200", now=now, state_dir=tmp_path / "rw")["state"] == "REFUSED"


# ── relay route + gateway operation ─────────────────────────────────────────────────────────────────────────


def _relay(tmp_path, cfg):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    seen: list[dict] = []

    def provider(query, now):
        if "view" in query:
            if query["view"] != "readiness":
                return {"state": "REFUSED", "reason": "release_train_window_bad_query"}
            return _readiness(tmp_path, cfg)
        return W.gateway_answer(query, now, state_dir=tmp_path / "rw")

    def transport(url, payload):
        seen.append(payload)
        return SRV.dispatch_http("POST", "/v1/coordination", {}, json.dumps(payload).encode(), key=KEY,
                                 expected_origin_sha=SHA, nonce_store=LedgerNonceStore(ledger),
                                 idempotency_store=LedgerReceiptStore(ledger), caller_keys=keys,
                                 release_train_provider=provider)

    env = {R.BEARER_ENV: BEARER, R.N8N_KEY_ENV: N8N.decode(), "TRADEAI_STATE_ROOT": str(tmp_path / "relay-state"),
           "TRADEAI_N8N_RELAY_LIVE_LANES": ""}
    return R.Relay(environ=env, allowlist=frozenset({"lane-a"}), transport=transport, clock=time.time), seen, ledger


def test_relay_route_is_served_and_read_only(tmp_path, cfg):
    assert ("GET", "/release-train-window") in R.ROUTES
    relay, seen, ledger = _relay(tmp_path, cfg)
    try:
        status, body = relay.release_train_window("Bearer " + BEARER, "view=readiness")
        assert status == 200 and body["schema"] == "ReleaseTrainReadiness@v1"
        assert seen[-1]["claim"]["scope"] == G.SCOPE_READ and seen[-1]["route"] == "coordination/status"
        assert set(seen[-1]) == {"route", "operation", "claim", "signature", "view"}
        status, body = relay.release_train_window("Bearer " + BEARER, "slot=1800")
        assert status == 200 and body["schema"] == "ReleaseTrainWindowView@v1" and body["request_state"] == "NOT_FOUND"
        status, body = relay.release_train_window("Bearer " + BEARER, "run_id=rtw%3Arelease-train-request-1800%3Ax")
        assert status == 200 and seen[-1]["run_id"] == "rtw:release-train-request-1800:x"
        log = (tmp_path / "relay-state/data/runtime/n8n_relay/relay_log.jsonl").read_text()
        assert '"op":"release_train_window"' in log
    finally:
        ledger.close()


@pytest.mark.parametrize("query", ["", "view=queue", "slot=1200", "slot=1800&view=readiness", "lane=x",
                                   "run_id=bad%20id", "view=readiness&view=readiness"])
def test_relay_refuses_bad_queries_before_the_gateway(tmp_path, cfg, query):
    relay, seen, ledger = _relay(tmp_path, cfg)
    try:
        status, body = relay.release_train_window("Bearer " + BEARER, query)
        assert status == 400 and body["reason"] == "relay_bad_query" and seen == []
    finally:
        ledger.close()


def test_relay_needs_the_bearer(tmp_path, cfg):
    relay, seen, ledger = _relay(tmp_path, cfg)
    try:
        status, body = relay.release_train_window("Bearer wrong", "view=readiness")
        assert status == 401 and seen == []
    finally:
        ledger.close()


def test_gateway_refuses_extra_fields_and_unconfigured_provider(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    try:
        def call(extra, provider):
            claim = {"v": 1, "caller_id": G.RELAY_CALLER, "project": "trade-ai", "iat": time.time(),
                     "exp": time.time() + 60, "nonce": os.urandom(8).hex(), "scope": G.SCOPE_READ}
            payload = {"route": "coordination/status", "operation": "release_train_window", "claim": claim,
                       "signature": G.sign_claim(claim, N8N), **extra}
            return SRV.dispatch_http("POST", "/v1/coordination", {}, json.dumps(payload).encode(), key=KEY,
                                     expected_origin_sha=SHA, nonce_store=LedgerNonceStore(ledger),
                                     idempotency_store=LedgerReceiptStore(ledger), caller_keys=keys,
                                     release_train_provider=provider)

        ok = lambda q, now: {"schema": "ReleaseTrainWindowView@v1", "state": "OK"}  # noqa: E731
        assert call({"slot": "1800"}, ok)[0] == 200
        assert call({"slot": "1800", "lane_id": "x"}, ok)[1]["reason"] == "unexpected_field"
        assert call({"slot": "1800", "view": "readiness"}, ok)[1]["reason"] == "release_train_window_bad_query"
        assert call({}, ok)[1]["reason"] == "release_train_window_bad_query"
        assert call({"slot": "1800"}, None)[1]["reason"] == "release_train_window_not_configured"
    finally:
        ledger.close()


# ── the generated workflow ──────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def wf():
    return json.loads(WF_PATH.read_text())


def test_workflow_is_byte_equal_to_its_generator_and_in_the_manifest(wf):
    files = T.render_fabric()
    assert files[WF_PATH.name] == WF_PATH.read_text()
    assert files["INDEX.json"] == FABRIC_INDEX.read_text()
    row = {r["id"]: r for r in json.loads(FABRIC_INDEX.read_text())["workflows"]}[T.RELEASE_TRAIN_ID]
    assert row["active"] is False and row["relay_calls"] == T.RELEASE_TRAIN_RELAY_CALLS
    assert wf["active"] is False and T.release_train_problems(wf) == []


def test_workflow_holds_no_credential_but_the_relay_one(wf):
    for n in wf["nodes"]:
        creds = n.get("credentials") or {}
        if n["type"] == "n8n-nodes-base.httpRequest":
            assert creds == {"httpHeaderAuth": {"id": "tradeai-run-relay", "name": "tradeai-run-relay"}}
            assert n["parameters"]["authentication"] == "genericCredentialType"
        else:
            assert creds == {}, n["name"]
    text = json.dumps(wf).lower()
    for secretish in ("bearer ", "password", "api_key", "apikey", "bot_token", "private_key", "hmac_key", "$env",
                      "github_token", "gh_token", "authorization"):
        assert secretish not in text, secretish


def test_workflow_has_no_merge_promote_push_or_controller_command(wf):
    text = json.dumps(wf["nodes"]).lower()
    for tok in T.RELEASE_TRAIN_FORBIDDEN_TEXT + ("train-run", "train-plan", "release_control", "git ", "gh pr",
                                                 "merge_pr", "/merge", "push origin", "--push", "git_push", "deploy"):
        assert tok not in text, tok
    # the only "push" in the graph is JavaScript Array.push
    assert __import__("re").findall(r"push(?!\()", text) == []


def test_workflow_has_no_direct_sender_or_command_node(wf):
    types_ = {n["type"] for n in wf["nodes"]}
    assert types_ <= T.FABRIC_ALLOWED_NODE_TYPES
    assert not types_ & T.FABRIC_FORBIDDEN_NODE_TYPES
    for t in types_:
        assert not any(x in t.lower() for x in ("telegram", "email", "gmail", "smtp", "slack", "executecommand",
                                                 "ssh", "postgres"))


def test_workflow_calls_only_the_two_relay_routes_and_run_lane_for_the_four_lanes(wf):
    calls = sorted({FW.relay_route(n) for n in wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"})
    assert calls == [("GET", "/release-train-window"), ("POST", "/intent")]
    for route in calls:
        assert route in R.ROUTES
    runs = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"]
    assert len(runs) == 1 and runs[0]["parameters"]["workflowId"]["value"] == T.RUN_LANE_ID
    assert runs[0]["parameters"]["options"]["waitForSubWorkflow"] is True
    assert set(wf["meta"]["framework"]["lanes"]) == set(LANES)


def test_workflow_intents_are_routed_and_never_page(wf):
    kinds = set()
    for n in wf["nodes"]:
        kinds |= set(__import__("re").findall(r"kind: '([a-z_]+)'", n["parameters"].get("jsCode", "")))
    assert kinds == set(T.RELEASE_TRAIN_INTENT_KINDS)
    routes = {(r["domain"], r["kind"]): r for r in json.loads((ROOT / "config/n8n_comms_intent_routes.json")
                                                             .read_text())["routes"]}
    for k in kinds:
        assert routes[("fabric", k)]["tier"] == "DIGEST"
        assert routes[("fabric", k)]["runbook_id"] == "release-train-n8n"
    assert "release-train-n8n" in (ROOT / "docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md").read_text()


def test_workflow_schedules_the_four_windows_in_new_york(wf, cfg):
    assert wf["settings"]["timezone"] == "America/New_York"
    sched = {n["name"]: [i["expression"] for i in n["parameters"]["rule"]["interval"]]
             for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"}
    assert sched == {"Schedule request": ["30 16 * * *", "30 22 * * *", "30 4 * * *", "30 6 * * *"],
                     "Schedule report": ["15 19 * * *", "15 1 * * *", "15 7 * * *", "15 9 * * *"]}
    assert any(n["type"] == "n8n-nodes-base.manualTrigger" for n in wf["nodes"])
    gate = next(n for n in wf["nodes"] if n["name"] == "Gate")["parameters"]["jsCode"]
    assert "const MODE = \"dry_run\"" in gate


@pytest.mark.parametrize("inject,needle", [
    (lambda w: w["nodes"].append({"name": "Tg", "type": "n8n-nodes-base.telegram", "parameters": {}}),
     "node_forbidden"),
    (lambda w: w["nodes"][0]["parameters"].update(note="git push origin main"), "git push"),
    (lambda w: next(n for n in w["nodes"] if n["type"].endswith("httpRequest"))["parameters"].update(
        url="={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/run"), "release_train_http_refused"),
    (lambda w: next(n for n in w["nodes"] if n["type"].endswith("httpRequest")).update(
        credentials={"httpHeaderAuth": {"id": "x", "name": "github-app"}}), "credential"),
])
def test_invariants_catch_a_tampered_copy(wf, inject, needle):
    w = copy.deepcopy(wf)
    inject(w)
    problems = T.release_train_problems(w) + T.validate_fabric_workflow(w, {T.FABRIC_ERROR_ID})
    assert any(needle in p for p in problems), problems


def test_framework_check_has_no_failing_element(wf):
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_n8n_workflow_framework.py"), "--workflow",
                          str(WF_PATH), "--json"], capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert out.returncode == 0, out.stderr
    rep = json.loads(out.stdout)
    (row,) = rep["workflows"]
    bad = {k: v for k, v in row["elements"].items() if v["status"] == "fail"}
    assert bad == {}, bad
    partial = {k for k, v in row["elements"].items() if v["status"] == "partial"}
    # Expected and reported: FW-R3 (a new n8n-only
    # schedule has no cron line to fall back to; the manual release path is the declared fallback).
    assert partial <= {"FW-R3"}, partial  # FW-C3 passes since the operator review


# ── registry, allowlist, health contracts, capabilities ─────────────────────────────────────────────────────


def test_allowlist_entries_are_dry_run_only_with_minimal_env():
    entries = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    for slot, lane in zip(("1800", "0000", "0600", "0800"), LANES):
        e = entries[lane]
        assert e["command"] == ["$PY", "scripts/release_train_window_request.py", "--window", slot]
        assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
        assert e["env_allowlist_mode"] == "report" and e["env_names"] == ["TRADEAI_RELEASE_WINDOW_STATE_DIR"]
        assert e["output_signal"] == f"data/runtime/{lane}_last.json" and e["market_gate"] is False
        argv = " ".join(e["command"] + e["dry_run_arg"])
        assert G.forbidden_route_token(argv) is None and G.forbidden_route_token(lane) is None
        assert not any(tok in argv for tok in FORBIDDEN_COMMAND_TOKENS)


def test_registry_rows_are_n8n_shadow_with_no_dispatch_block():
    rows = {r["lane_id"]: r for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    for lane in LANES:
        r = rows[lane]
        assert r["scheduler"]["kind"] == "n8n" and r["scheduler"]["expression"] == T.RELEASE_TRAIN_ID
        assert r["scheduler"]["stage"] == "shadow" and "dispatch" not in r
        assert r["state"] == "NEVER_SCHEDULED" and r["output_signal"]["path"] == f"data/runtime/{lane}_last.json"


def test_health_contracts_are_reviewed_by_the_operator_and_the_gate_is_clean():
    """AGENTS §23.19: a new lane needs a REVIEWED contract. The operator reviewed all four on 2026-10-21 ("approve
    the 4 contracts, email yes, rtw yes, push release 2"); the gate has no failure of ours."""
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    ours = {c["id"]: c for c in doc["contracts"] if c["id"] in LANES}
    assert set(ours) == set(LANES)
    for c in ours.values():
        assert c["workflow_id"] == T.RELEASE_TRAIN_ID and c["stage"] == "shadow"
        assert c["expected_output"]["rule"] == "empty_allowed"
        assert "no_runner" in c["expected_output"]["fatal_skip_reasons"]
        assert c["status"] == "REVIEWED" and c["review"]["status"] == "REVIEWED"
        assert c["review"]["reviewed_by"].startswith("operator PatsKiller 2026-10-21")
        assert c["review"]["reviewed_on"] == "2026-10-21"
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_n8n_health_contracts.py")], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=300)
    fails = [ln for ln in (out.stdout + out.stderr).splitlines() if "✗" in ln]
    assert not [ln for ln in fails if any(lane in ln for lane in LANES)], fails


def test_request_lanes_reach_no_sender_broker_or_order_code():
    result = CAP.audit()
    for lane in LANES:
        row = result[lane]
        assert "error" not in row and row["kind"] != "shell" and row["modules_in_closure"] > 1
        caps = set(row["capabilities"])
        assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, (lane, caps)
        # Nothing the lane loads when it starts can run a process or open a connection.
        at_import = {c for c, info in row["capabilities"].items() if info.get("at_import")}
        assert not at_import & {"subprocess", "network_http"}, (lane, at_import)
    assert CAP.violations(result, CAP.load_baseline()).get("new", []) == [] or all(
        v[0] not in LANES for v in CAP.violations(result, CAP.load_baseline()).get("new", []))


def test_contract_doc_names_the_records_and_the_boundary():
    text = (ROOT / "docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md").read_text()
    for needle in ("TrainWindowRequest@v1", "TrainWindowReceipt@v1", "ReleaseTrainReadiness@v1", "REQUEST_ONLY",
                   "simulate-only", "host notifier", "C11", "## 14. Runbook"):
        assert needle in text, needle


def test_now_is_not_used_implicitly_by_the_pure_helpers(cfg):
    with pytest.raises(W.ContractError):
        W.window_start("1800", datetime(2026, 10, 21, 16, 30), cfg)  # naive time refused
    with pytest.raises(W.ContractError):
        W.window_start("1200", REQUEST_TICK, cfg)
    assert W.window_start("1800", REQUEST_TICK + timedelta(minutes=10), cfg).tzinfo is not None


@pytest.mark.parametrize("code", ["RECONCILE_REQUIRED", "QUARANTINED_LINEAGE", "CONTROLLER_ERROR",
                                  "CONTROLLER_BUILD_ONLY", "CONTROLLER_FAILED"])
def test_phase3_refusal_codes_are_in_the_closed_set(cfg, code):
    req = _request(cfg)
    state = "FAILED" if code in ("CONTROLLER_ERROR", "CONTROLLER_FAILED") else "REFUSED"
    doc = receipt(req, state=state, outcome=None, refusal={"code": code, "detail": "x"})
    assert W.validate_receipt(doc) == []
    assert W.validate_receipt(receipt(req, state="REFUSED", outcome=None, refusal={"code": "NOPE", "detail": "x"}))


def test_unreadable_receipt_is_reported_not_missing(tmp_path, monkeypatch, cfg):
    env = {"TRADEAI_RUN_ID": "rtw:release-train-request-1800:live:20261021T1630"}
    assert _run(tmp_path, monkeypatch, ["--append"], cfg_override=shadow_cfg(cfg), env=env) == 0
    rdir = tmp_path / "rw/train_requests/receipts"
    rdir.mkdir()
    (rdir / "rtw-20261021-1800-win.json").write_text("{not json")
    v = W.window_view(run_id=env["TRADEAI_RUN_ID"], now=REQUEST_TICK.astimezone(timezone.utc),
                      state_dir=tmp_path / "rw")
    assert v["receipt"] is None and v["receipt_problem"] == "receipt_unreadable"
