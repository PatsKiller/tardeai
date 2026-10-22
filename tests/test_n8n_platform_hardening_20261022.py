"""n8n platform hardening packet (ANCHOR N8N_PLATFORM_HARDENING_20261022): FW-P1..P6 of the AGENTS §23.24 import gate.

Pinned here:

* the platform probe measures each element from host evidence (fake runner: docker container/image inspect, an env template
  that names only allowlisted keys, pg_roles, systemctl --user, ss, docker network inspect, an operator ufw
  capture) and an element PASSes only from a fresh host probe — a cited or stale file caps at PARTIAL;
* the ufw verdict needs active + default deny + ALLOW (lab subnet, lab bridge) before DENY, and refuses a
  shadowing allow;
* the drift watch and the host dead-man page P1 through the host SYSTEM ops sender (never n8n), once per onset,
  remind after 6 h, recover once, and never mark a held send delivered; dry runs write and send nothing;
* the n8n_app role script: RFC 7677 SCRAM verifier, plan prints the SQL with the verifier redacted, apply makes a
  mode-600 password file and sends Postgres only the verifier, refuses to overwrite, rollback never drops;
* the import guard prints FW-P1..P6 with their source; the packet's compose patches compose and carry no secret.

Hermetic: tmp state roots, stub runner / sender / prober. No docker, n8n, DB, systemd, ufw or network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_n8n_import_ready as IR  # noqa: E402
import check_n8n_workflow_framework as F  # noqa: E402
from scripts import n8n_drift_watch as DW  # noqa: E402
from scripts import n8n_host_deadman as DM  # noqa: E402
from scripts import probe_n8n_platform_facts as P  # noqa: E402
from scripts.lib import host_p1_pager as PG  # noqa: E402
from scripts.ops import n8n_db_app_role as R  # noqa: E402
from tests.test_n8n_workflow_drift_20261009 import _gen_dir, _git_doc, _live  # noqa: E402

PACKET = ROOT / "docs" / "ops" / "packets" / "n8n-platform-hardening-20261022"
NOW = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
DIGEST = "sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c"
IMAGE_ID = "sha256:" + "a" * 64

UFW_GOOD = """Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    192.168.1.0/24
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 172.19.0.1 18092/tcp on br-fdc1921eeccb ALLOW IN    172.19.0.0/16              # n8n lab -> relay (FW-P4)
[ 2] 172.19.0.1 18092/tcp       DENY IN     Anywhere                   # relay: nobody else (FW-P4)
[ 3] 22/tcp                     ALLOW IN    192.168.1.0/24
"""


# ── a fake host ──────────────────────────────────────────────────────────────────────────────────────────────────


class FakeHost:
    def __init__(self, **over):
        self.env = {
            "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "all",
            "EXECUTIONS_DATA_SAVE_ON_ERROR": "all",
            "EXECUTIONS_DATA_PRUNE": "true",
            "EXECUTIONS_DATA_MAX_AGE": "168",
            "EXECUTIONS_DATA_PRUNE_MAX_COUNT": "20000",
            "N8N_BLOCK_ENV_ACCESS_IN_NODE": "true",
            "N8N_COMMUNITY_PACKAGES_ENABLED": "false",
            "DB_POSTGRESDB_USER": "n8n_app",
            "DB_POSTGRESDB_DATABASE": "n8n",
        }
        self.env.update(over.pop("env", {}))
        self.image = over.pop("image", f"n8nio/n8n:2.43.0@{DIGEST}")
        self.repo_digests = over.pop("repo_digests", [f"n8nio/n8n@{DIGEST}"])
        self.ufw_probe = over.pop("ufw_probe", True)
        self.rolsuper = over.pop("rolsuper", False)
        self.timers = over.pop("timers", {P.DRIFT_TIMER: ("enabled", "active"), P.DEADMAN_TIMER: ("enabled", "active")})
        self.binds = over.pop("binds", ["127.0.0.1:5678", "172.19.0.1:18092"])
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kw):
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "inspect"] and "Config.Env" in argv[-1]:
            if argv[2] == P.N8N_CONTAINER:
                return 0, "".join(f"{k}={v}\n" for k, v in self.env.items()) + "N8N_ENCRYPTION_KEY=SHOULD-BE-DROPPED\n", ""
            return 0, "POSTGRES_USER=n8n\nPOSTGRES_DB=n8n\n", ""
        if argv[:2] == ["docker", "inspect"]:
            assert "RepoDigests" not in argv[-1], "RepoDigests must be read from ImageInspect"
            assert argv[2:4] == ["--type=container", P.N8N_CONTAINER]
            return 0, f"{self.image}\n{IMAGE_ID}\n", ""
        if argv[:3] == ["docker", "image", "inspect"]:
            assert argv[3] == IMAGE_ID
            assert "RepoDigests" in argv[-1]
            return 0, json.dumps(self.repo_digests) + "\n", ""
        if argv[:3] == [P.SUDO_BIN, "-n", P.UFW_BIN]:
            if self.ufw_probe and argv[3:5] == ["status", "verbose"]:
                return 0, UFW_GOOD.split("[ 1]")[0], ""
            if self.ufw_probe and argv[3:5] == ["status", "numbered"]:
                return 0, UFW_GOOD, ""
            return 1, "", "not authorized"
        if argv[:2] == ["docker", "exec"]:
            return 0, json.dumps({"role": "n8n_app", "rolsuper": self.rolsuper, "rolcreaterole": False,
                                  "rolcreatedb": False, "rolreplication": False, "rolbypassrls": False}) + "\n", ""
        if argv[:3] == ["docker", "network", "inspect"]:
            return 0, "fdc1921eeccb00c873de34a39e25a2c4879f322be49b2ae5272d54c3f29135c8 172.19.0.0/16 172.19.0.1\n", ""
        if argv[0] == "systemctl":
            en, ac = self.timers.get(argv[3], ("not-found", "inactive"))
            return (0 if argv[2] == "is-enabled" and en == "enabled" else 1), (en if argv[2] == "is-enabled" else ac) + "\n", ""
        if argv[0] == "ss":
            return 0, "".join(f"LISTEN 0 64 {b} 0.0.0.0:*\n" for b in self.binds), ""
        return 127, "", "unexpected " + " ".join(argv)


def _host_root(tmp_path: Path, *, now=NOW, ufw=UFW_GOOD) -> Path:
    root = tmp_path / "state"
    rt = root / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "n8n_drift_watch_last.json").write_text(json.dumps(
        {"schema": "N8nDriftWatch@v1", "as_of": (now - timedelta(minutes=10)).isoformat(), "mode": "live",
         "verdict": "CLEAN", "p1_path": PG.P1_PATH}))
    (rt / "n8n_workflow_drift_last.json").write_text(json.dumps(
        {"schema": "N8nWorkflowDriftReceipt@v1", "as_of": (now - timedelta(minutes=10)).isoformat(), "verdict": "CLEAN"}))
    (rt / "n8n_host_deadman_last.json").write_text(json.dumps(
        {"schema": "N8nHostDeadman@v1", "checked_at": (now - timedelta(minutes=3)).isoformat(), "mode": "live",
         "status": "OK", "runs_inside_n8n": False, "alert_path": PG.P1_PATH}))
    if ufw is not None:
        cap = rt / "ufw_status_n8n_relay.txt"
        cap.write_text(ufw)
        os.utime(cap, (now.timestamp() - 3600, now.timestamp() - 3600))
    return root


def _probe(tmp_path, host=None, **kw):
    root = kw.pop("root", None) or _host_root(tmp_path)
    return P.probe(root=root, now=NOW, run=host or FakeHost(), **kw)


# ── FW-P1..P6 from host evidence ─────────────────────────────────────────────────────────────────────────────────


def test_a_hardened_host_passes_all_six_from_a_fresh_probe(tmp_path):
    facts = _probe(tmp_path)
    assert facts["schema"] == F.PLATFORM_FACTS_SCHEMA and facts["source_kind"] == "host_probe"
    plat = F.score_platform(facts, now=NOW)
    assert {k: v["status"] for k, v in plat.items()} == {f"FW-P{i}": F.PASS for i in range(1, 7)}, plat


def test_fw_p5_reads_container_reference_and_repo_digests_from_distinct_objects(tmp_path):
    host = FakeHost()
    plat = F.score_platform(_probe(tmp_path, host), now=NOW)
    container_calls = [c for c in host.calls if c[:2] == ["docker", "inspect"] and "Config.Image" in c[-1]]
    image_calls = [c for c in host.calls if c[:3] == ["docker", "image", "inspect"]]
    assert len(container_calls) == len(image_calls) == 1
    assert container_calls[0][-1] == "{{.Config.Image}}\n{{.Image}}"
    assert image_calls[0][3:5] == [IMAGE_ID, "--format"]
    assert plat["FW-P5"]["status"] == F.PASS


def test_the_probe_never_reads_a_secret_env_value(tmp_path):
    host = FakeHost()
    facts = _probe(tmp_path, host)
    tpl = P.env_template()
    for secret in ("PASSWORD", "ENCRYPTION_KEY", "TOKEN", "SECRET"):
        assert secret not in tpl and secret not in json.dumps(facts)
    assert all(k in tpl for k in P.ENV_ALLOWLIST)
    env_calls = [c for c in host.calls if c[:2] == ["docker", "inspect"] and "Config.Env" in c[-1]]
    assert env_calls and all(c[-1] == tpl for c in env_calls)


@pytest.mark.parametrize(
    "over, element, needle",
    [
        ({"env": {"EXECUTIONS_DATA_SAVE_ON_SUCCESS": "none"}}, "FW-P1", "SAVE_ON_SUCCESS=none"),
        ({"env": {"EXECUTIONS_DATA_PRUNE": "false"}}, "FW-P1", "PRUNE=false"),
        ({"rolsuper": True}, "FW-P2", "rolsuper=t"),
        ({"timers": {P.DEADMAN_TIMER: ("enabled", "active")}}, "FW-P3", "timer not enabled+active"),
        ({"binds": ["0.0.0.0:18092"]}, "FW-P4", "relay"),
        ({"image": "n8nio/n8n:2.43.0"}, "FW-P5", "tag pin"),
        ({"env": {"N8N_BLOCK_ENV_ACCESS_IN_NODE": "false"}}, "FW-P5", "N8N_BLOCK_ENV_ACCESS_IN_NODE=false"),
        ({"timers": {P.DRIFT_TIMER: ("enabled", "active")}}, "FW-P6", "timer not enabled+active"),
    ],
)
def test_each_element_fails_on_its_own_host_evidence(tmp_path, over, element, needle):
    plat = F.score_platform(_probe(tmp_path, FakeHost(**over)), now=NOW)
    assert plat[element]["status"] != F.PASS and needle in plat[element]["evidence"], plat[element]
    assert all(v["status"] == F.PASS for k, v in plat.items() if k != element)


def test_a_digest_pin_that_is_not_the_running_image_is_not_a_pin(tmp_path):
    host = FakeHost(repo_digests=["n8nio/n8n@sha256:" + "0" * 64])
    plat = F.score_platform(_probe(tmp_path, host), now=NOW)
    assert plat["FW-P5"]["status"] == F.PARTIAL and "NOT present in the running image RepoDigests" in plat["FW-P5"]["evidence"]


def test_saved_ufw_capture_cannot_authorize_firewall_pass(tmp_path):
    facts = _probe(tmp_path, FakeHost(ufw_probe=False))
    platform = F.score_platform(facts, now=NOW)
    assert platform["FW-P4"]["status"] == F.FAIL
    assert "saved capture cannot authorize PASS" in platform["FW-P4"]["evidence"]
    assert facts["facts"]["relay_bind_firewall_verified"]["detail"]["ufw_evidence_source"] == "untrusted_capture_or_unavailable"


def test_stale_or_cannot_run_receipts_fail_p3_and_p6(tmp_path):
    root = _host_root(tmp_path, now=NOW - timedelta(hours=2))
    plat = F.score_platform(_probe(tmp_path, root=root), now=NOW)
    assert plat["FW-P3"]["status"] == F.FAIL and plat["FW-P6"]["status"] == F.FAIL
    root2 = _host_root(tmp_path / "b")
    w = root2 / P.DRIFT_WATCH_REL
    w.write_text(json.dumps({**json.loads(w.read_text()), "verdict": "CANNOT_RUN"}))
    assert F.score_platform(_probe(tmp_path, root=root2), now=NOW)["FW-P3"]["status"] == F.FAIL


def test_a_cited_or_stale_facts_file_can_never_pass(tmp_path):
    facts = _probe(tmp_path)
    cited = {k: v for k, v in facts.items() if k not in ("source_kind", "probed_at")}
    assert all(v["status"] == F.PARTIAL and "PASS withheld" in v["evidence"] for v in F.score_platform(cited, now=NOW).values())
    stale = F.score_platform(facts, now=NOW + timedelta(hours=25))
    assert all(v["status"] == F.PARTIAL for v in stale.values())
    committed = json.loads((ROOT / F.DEFAULT_PLATFORM).read_text())
    assert F.score_platform(committed)["FW-P2"]["status"] == F.FAIL  # the 2026-10-15 measurement is unchanged


def test_a_fresh_forged_host_probe_file_cannot_authorize_pass(tmp_path):
    facts = _probe(tmp_path)
    facts["probed_at"] = datetime.now(timezone.utc).isoformat()
    f = tmp_path / "forged-host-probe.json"
    f.write_text(json.dumps(facts))

    loaded, source = IR.load_platform_facts(str(f))
    report = IR.platform_report(loaded)

    assert source["kind"] == "cited_file"
    assert loaded["source_kind"] == "cited_file"
    assert all(v["status"] == F.PARTIAL for v in report.values()), report


def test_only_direct_host_probe_can_authorize_fresh_pass(tmp_path):
    facts = _probe(tmp_path)
    loaded, source = IR.load_platform_facts(probe_host=True, prober=lambda: facts)
    report = IR.platform_report(loaded)

    assert source["kind"] == "host_probe"
    assert {k: v["status"] for k, v in report.items()} == {f"FW-P{i}": F.PASS for i in range(1, 7)}


# ── ufw (FW-P4) ──────────────────────────────────────────────────────────────────────────────────────────────────

KW = dict(relay_ip="172.19.0.1", port=18092, subnet="172.19.0.0/16", bridge="br-fdc1921eeccb")


def test_ufw_good_rules_pass():
    ok, problems, picked = P.ufw_verdict(UFW_GOOD, **KW)
    assert ok and not problems and picked["allow"]["n"] == 1 and picked["deny"]["n"] == 2


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda t: t.replace("Status: active", "Status: inactive"), "ufw status inactive"),
        (lambda t: t.replace("Default: deny (incoming)", "Default: allow (incoming)"), "default incoming"),
        (lambda t: t.replace("[ 2] 172.19.0.1 18092/tcp       DENY IN     Anywhere", "[ 2] 22/tcp DENY IN Anywhere"), "no DENY"),
        (lambda t: t.replace("on br-fdc1921eeccb ", "on br-000000000000 "), "no ALLOW"),
        (lambda t: t.replace("[ 1] 172.19.0.1 18092/tcp on br-fdc1921eeccb ALLOW IN    172.19.0.0/16",
                             "[ 9] 172.19.0.1 18092/tcp on br-fdc1921eeccb ALLOW IN    172.19.0.0/16"), "after the DENY"),
        (lambda t: t.replace("[ 3] 22/tcp", "[ 0] Anywhere                   ALLOW IN    172.16.0.0/12\n[ 3] 22/tcp"), "shadows"),
        (lambda t: t + "[ 0] 18000:19000/tcp            ALLOW IN    Anywhere\n", "shadows"),
    ],
)
def test_ufw_rejects_each_gap(mutate, needle):
    ok, problems, _ = P.ufw_verdict(mutate(UFW_GOOD), **KW)
    assert not ok and any(needle in p for p in problems), problems


def test_live_ufw_probe_does_not_depend_on_saved_capture(tmp_path):
    root = _host_root(tmp_path, ufw=None)
    ev = F.score_platform(_probe(tmp_path, root=root), now=NOW)["FW-P4"]
    assert ev["status"] == F.PASS
    root2 = _host_root(tmp_path / "old")
    cap = root2 / P.UFW_CAPTURE_REL
    os.utime(cap, (NOW.timestamp() - 9 * 86400,) * 2)
    assert F.score_platform(_probe(tmp_path, root=root2), now=NOW)["FW-P4"]["status"] == F.PASS


# ── the pager (onset / remind / recover) ─────────────────────────────────────────────────────────────────────────


def test_pager_pages_once_per_onset_reminds_and_recovers():
    st, a = PG.decide(None, bad=True, key="down", now=NOW, prefix="x", threshold=2)
    assert a["kind"] == PG.NONE  # one bad run is a blip
    st, a = PG.decide(st, bad=True, key="down", now=NOW + timedelta(minutes=5), prefix="x", threshold=2)
    assert a["kind"] == PG.PAGE and a["identity"].endswith(":p1")
    st = PG.mark_delivered(st, a, now=NOW + timedelta(minutes=5))
    st, a = PG.decide(st, bad=True, key="down", now=NOW + timedelta(hours=1), prefix="x", threshold=2)
    assert a["kind"] == PG.NONE
    st, a = PG.decide(st, bad=True, key="down", now=NOW + timedelta(hours=7), prefix="x", threshold=2)
    assert a["kind"] == PG.REMIND and a["identity"].endswith(":p2")
    st, a2 = PG.decide(st, bad=True, key="other", now=NOW + timedelta(hours=7), prefix="x", threshold=1)
    assert a2["kind"] == PG.PAGE and a2["identity"] != a["identity"]  # a new condition is a new onset
    st = PG.mark_delivered(st, a2, now=NOW + timedelta(hours=7))
    st, a = PG.decide(st, bad=False, key="other", now=NOW + timedelta(hours=8), prefix="x")
    assert a["kind"] == PG.RECOVER and a["identity"].endswith(":recovered")
    assert PG.mark_delivered(st, a, now=NOW)["pages_delivered"] == 0


@pytest.mark.parametrize(
    "rec, ok",
    [
        ({"ok": True, "message_id": 5}, True),
        ({"ok": True, "suppressed": "held", "reason": "suppressed:held"}, False),
        ({"ok": False, "reason": "not_configured"}, False),
        ({"ok": True, "deduped": True, "message_id": None}, False),
        ({"ok": True, "deduped": True, "message_id": 9}, True),
    ],
)
def test_only_a_delivered_send_marks_the_page(rec, ok):
    assert PG.delivered(rec) is ok


# ── FW-P3 drift watch ────────────────────────────────────────────────────────────────────────────────────────────


class Sender:
    def __init__(self, ok=True):
        self.sent: list[tuple[str, str, str]] = []
        self.ok = ok

    def __call__(self, text, *, identity, kind):
        self.sent.append((text, identity, kind))
        return {"ok": self.ok, "message_id": 1 if self.ok else None, **({} if self.ok else {"reason": "held"})}


def _dw(tmp_path, workflows, *, live, sender=None, now=NOW, previewer=None):
    gen = _gen_dir(tmp_path)
    return DW.run_once(
        live=live, root=tmp_path / "state", workflows=workflows, now=now, sender=sender,
        previewer=previewer or (lambda *a, **k: {"would_send": True, "reason": "would_send"}),
        generated_dir=gen, generic_dir=tmp_path / "no-generic", index_path=gen / "INDEX.json",
    )


def test_drift_watch_clean_writes_both_receipts_and_pages_nothing(tmp_path):
    s = Sender()
    rec = _dw(tmp_path, [_live(_git_doc())], live=True, sender=s)
    assert rec["verdict"] == "CLEAN" and rec["page"]["action"] == PG.NONE and not s.sent
    rt = tmp_path / "state" / "data" / "runtime"
    assert json.loads((rt / "n8n_drift_watch_last.json").read_text())["schema"] == "N8nDriftWatch@v1"
    assert json.loads((rt / "n8n_workflow_drift_last.json").read_text())["schema"] == "N8nWorkflowDriftReceipt@v1"


def test_drift_pages_p1_once_through_the_host_sender_then_recovers(tmp_path):
    drifted = _live(_git_doc())
    drifted["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"] = "* * * * *"
    s = Sender()
    rec = _dw(tmp_path, [drifted], live=True, sender=s)
    assert rec["verdict"] == "DRIFT" and rec["severity"] == "P1" and rec["page"]["delivered"] is True
    assert len(s.sent) == 1 and "P1 n8n workflow DRIFT" in s.sent[0][0] and s.sent[0][2] == "n8n_workflow_drift"
    assert rec["page"]["p1_path"].startswith("host:") and "n8n not involved" in rec["page"]["p1_path"]
    _dw(tmp_path, [drifted], live=True, sender=s, now=NOW + timedelta(minutes=15))
    assert len(s.sent) == 1  # same drift: no second page inside the reminder window
    rec = _dw(tmp_path, [_live(_git_doc())], live=True, sender=s, now=NOW + timedelta(minutes=30))
    assert rec["page"]["action"] == PG.RECOVER and len(s.sent) == 2 and "CLEARED" in s.sent[1][0]


def test_a_held_drift_page_is_retried_not_marked(tmp_path):
    drifted = _live(_git_doc())
    drifted["settings"]["timezone"] = "UTC"
    s = Sender(ok=False)
    _dw(tmp_path, [drifted], live=True, sender=s)
    _dw(tmp_path, [drifted], live=True, sender=s, now=NOW + timedelta(minutes=15))
    assert len(s.sent) == 2 and s.sent[0][1] == s.sent[1][1]


def test_drift_watch_dry_run_writes_and_sends_nothing(tmp_path):
    drifted = _live(_git_doc())
    drifted["settings"]["timezone"] = "UTC"
    s = Sender()
    rec = _dw(tmp_path, [drifted], live=False, sender=s)
    assert rec["mode"] == "dry_run" and rec["page"]["action"] == PG.PAGE and rec["page"]["preview"]["would_send"]
    assert not s.sent and not (tmp_path / "state").exists()


def test_drift_watch_cannot_run_is_not_drift_and_pages_nothing(tmp_path):
    def boom():
        raise RuntimeError("db down")

    s = Sender()
    rec = DW.run_once(live=True, root=tmp_path, reader=boom, now=NOW, sender=s)
    assert rec["verdict"] == "CANNOT_RUN" and not s.sent
    assert not (tmp_path / "data" / "runtime" / "n8n_workflow_drift_last.json").exists()


# ── FW-P6 host dead-man ──────────────────────────────────────────────────────────────────────────────────────────


def _hb(root: Path, age_min: float):
    p = root / DM.HEARTBEAT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "LaneRunReceipt@v1", "lane_id": "heartbeat-watch",
                             "ok_at": (NOW - timedelta(minutes=age_min)).isoformat()}))


def _dm(root, *, ok=True, live=True, sender=None, now=NOW):
    return DM.run_once(
        live=live, root=root, now=now, sender=sender,
        prober=lambda u: {"ok": ok, "http_status": 200 if ok else None, "error": None if ok else "connection_refused"},
        previewer=lambda *a, **k: {"would_send": True, "reason": "would_send"},
    )


def test_deadman_ok_writes_a_receipt_that_says_it_runs_outside_n8n(tmp_path):
    _hb(tmp_path, 3)
    rec = _dm(tmp_path)
    assert rec["status"] == "OK" and rec["runs_inside_n8n"] is False and rec["alert_path"].startswith("host:")
    assert json.loads((tmp_path / DM.RECEIPT_REL).read_text())["schema"] == "N8nHostDeadman@v1"


def test_deadman_pages_p1_after_two_bad_runs_and_recovers(tmp_path):
    _hb(tmp_path, 3)
    s = Sender()
    assert _dm(tmp_path, ok=False, sender=s)["page"]["action"] == PG.NONE
    rec = _dm(tmp_path, ok=False, sender=s, now=NOW + timedelta(minutes=5))
    assert rec["page"]["action"] == PG.PAGE and len(s.sent) == 1 and "P1 n8n DEAD-MAN" in s.sent[0][0]
    assert rec["condition"] == "down"
    rec = _dm(tmp_path, ok=True, sender=s, now=NOW + timedelta(minutes=10))
    assert rec["page"]["action"] == PG.RECOVER and len(s.sent) == 2


def test_a_healthy_process_that_stopped_scheduling_is_not_ok(tmp_path):
    _hb(tmp_path, 45)
    rec = _dm(tmp_path, ok=True, live=False)
    assert rec["status"] == "BAD" and rec["condition"] == "not_scheduling"
    assert not (tmp_path / DM.RECEIPT_REL).exists()  # dry run writes nothing


def test_deadman_and_drift_watch_never_import_n8n_paths():
    for mod in ("scripts/n8n_host_deadman.py", "scripts/n8n_drift_watch.py", "scripts/lib/host_p1_pager.py"):
        src = (ROOT / mod).read_text(encoding="utf-8")
        for banned in ("n8n_incident_fanin", "telegram_alert import send_telegram", "n8n_run_relay", "/webhook"):
            assert banned not in src, (mod, banned)


# ── FW-P2 role script ────────────────────────────────────────────────────────────────────────────────────────────


def test_scram_verifier_matches_rfc7677():
    v = R.scram_verifier("pencil", salt=base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ=="))
    server_key = base64.b64decode(v.split("$")[2].split(":")[1])
    auth = ("n=user,r=rOprNGfwEbeRWgbNEkqO,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,"
            "s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096,c=biws,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0")
    sig = base64.b64encode(hmac.new(server_key, auth.encode(), hashlib.sha256).digest()).decode()
    assert v.startswith("SCRAM-SHA-256$4096:") and sig == "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4="


class DB:
    def __init__(self, exists=False, rolsuper=False, connects="n8n", role_memberships=None):
        self.exists, self.rolsuper, self.connects = exists, rolsuper, connects
        self.role_memberships = role_memberships or []
        self.inputs: list[str] = []

    def __call__(self, argv, *, input_text=None, **_):
        if input_text is not None:
            self.inputs.append(input_text)
        if argv[:2] == ["docker", "inspect"]:
            return 0, f"DB_POSTGRESDB_USER={self.connects}\n", ""
        if input_text and input_text.startswith("BEGIN"):
            self.exists = True
            return 0, "", ""
        inv = {"role_exists": self.exists, "role": {"rolsuper": self.rolsuper, "rolcanlogin": True} if self.exists else None,
               "admin_rolsuper": True, "owners": {"n8n:r": 157}, "functions": {"n8n:own": 2}, "not_owned_by_role": 0,
               "role_memberships": self.role_memberships,
               "functions_not_owned_by_role": 0, "db_connect": True if self.exists else None,
               "schema_create": True if self.exists else None, "extensions": ["plpgsql", "uuid-ossp"],
               "password_encryption": "scram-sha-256", "server_version": "16.15"}
        return 0, json.dumps(inv) + "\n", ""


def test_role_plan_is_read_only_and_redacts_the_verifier(tmp_path, capsys):
    db = DB()
    assert R.main(["--password-file", str(tmp_path / "pw")], run=db) == 0
    out = capsys.readouterr().out
    assert "CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in out
    assert R.REDACTED in out and "GRANT USAGE, CREATE ON SCHEMA public TO n8n_app" in out
    assert not (tmp_path / "pw").exists() and all(not i.startswith("BEGIN") for i in db.inputs)
    assert all("default_transaction_read_only=on" in " ".join(R.psql_argv(read_only=True)) for _ in [0])


def test_role_apply_makes_a_600_file_and_sends_only_the_verifier(tmp_path, capsys):
    db = DB()
    pw = tmp_path / "cfg" / "n8n_app_pg_password"
    assert R.main(["--apply", "--password-file", str(pw)], run=db) == 0
    secret = pw.read_text()
    assert stat.S_IMODE(pw.stat().st_mode) == 0o600 and stat.S_IMODE(pw.parent.stat().st_mode) == 0o700
    sql = next(i for i in db.inputs if i.startswith("BEGIN"))
    assert "SCRAM-SHA-256$4096:" in sql and secret not in sql and "DROP" not in sql.upper().replace("DROPPED", "")
    out = capsys.readouterr()
    assert secret not in out.out and secret not in out.err
    assert R.main(["--apply", "--password-file", str(pw)], run=db) == 2  # never overwritten
    assert pw.read_text() == secret


def test_role_verify_and_rollback_never_drop(tmp_path, capsys):
    assert R.main(["--verify"], run=DB(exists=True, connects="n8n")) == 1  # compose switch pending
    assert R.main(["--verify"], run=DB(exists=True, connects="n8n_app")) == 0
    assert R.main(["--verify"], run=DB(exists=True, rolsuper=True, connects="n8n_app")) == 1
    assert R.main(["--verify"], run=DB(exists=True, connects="n8n_app", role_memberships=["pg_write_all_data"])) == 1
    assert "DROP ROLE" not in R.ROLLBACK_SQL and "NOLOGIN" in R.ROLLBACK_SQL
    db = DB(exists=True)
    assert R.main(["--rollback"], run=db) == 0 and not any(i.startswith("BEGIN") for i in db.inputs)


# ── the import guard reports each element ────────────────────────────────────────────────────────────────────────

WF = "docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json"


def test_import_guard_does_not_trust_fresh_host_probe_file_claim(tmp_path, capsys):
    facts = _probe(tmp_path)
    facts["probed_at"] = datetime.now(timezone.utc).isoformat()
    f = tmp_path / "facts.json"
    f.write_text(json.dumps(facts))
    rc = IR.main([WF, "--relay-url", "http://172.19.0.1:18092", "--known-id", "tradeai-fabric-error",
                  "--platform-facts", str(f), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1  # runtime evidence is still owed: the gate is not weakened
    assert doc["platform_source"]["kind"] == "cited_file"
    assert {k: v["status"] for k, v in doc["platform"].items()} == {f"FW-P{i}": "partial" for i in range(1, 7)}
    blocking = doc["files"][0]["framework_gate"]["blocking"]
    assert any(b.startswith("platform FW-P") for b in blocking), blocking


def test_import_guard_default_still_reads_the_committed_measurement(capsys, monkeypatch):
    monkeypatch.delenv(IR.PLATFORM_ENV, raising=False)
    IR.main([WF, "--relay-url", "http://172.19.0.1:18092", "--known-id", "tradeai-fabric-error"])
    out = capsys.readouterr().out
    assert "platform facts: cited" in out and "FW-P2 FAIL" in out


def test_probe_host_mode_uses_the_probe_and_fails_closed(tmp_path):
    facts, src = IR.load_platform_facts(probe_host=True, prober=lambda: _probe(tmp_path))
    assert src["kind"] == "host_probe" and facts["source_kind"] == "host_probe"

    def boom():
        raise RuntimeError("docker unavailable")

    with pytest.raises(IR.CannotRun):
        IR.load_platform_facts(probe_host=True, prober=boom)
    with pytest.raises(IR.CannotRun):
        IR.load_platform_facts(str(tmp_path / "absent.json"))


# ── the packet ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_compose_patches_compose_to_the_proposed_file_and_hold_no_secret():
    c = PACKET / "compose"
    proposed = (c / "docker-compose.n8n.yml.proposed").read_text()
    n8n_service = proposed[proposed.index("\n  n8n:\n"):]
    assert f"image: n8nio/n8n:2.43.0@{DIGEST}" in n8n_service
    assert "EXECUTIONS_DATA_SAVE_ON_SUCCESS: all" in n8n_service and 'EXECUTIONS_DATA_PRUNE: "true"' in n8n_service
    assert "DB_POSTGRESDB_USER: n8n_app" in n8n_service and "DB_POSTGRESDB_PASSWORD:" not in n8n_service
    assert "DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password" in n8n_service
    assert 'N8N_BLOCK_ENV_ACCESS_IN_NODE: "true"' in n8n_service and 'N8N_COMMUNITY_PACKAGES_ENABLED: "false"' in n8n_service
    for f in c.iterdir():  # every secret-bearing key is an interpolation or a file path, never a value
        for line in f.read_text().splitlines():
            body = line.lstrip("+- ").strip()
            if re.match(r"^[A-Z0-9_]*(PASSWORD|ENCRYPTION_KEY|TOKEN|SECRET)[A-Z0-9_]*:\s", body):
                value = body.split(":", 1)[1].strip()
                assert value.startswith("${") or value.startswith("/run/secrets/"), (f.name, line)
    for name in ("fw-p5-image-digest", "fw-p1-save-success", "fw-p2-n8n-app-role", "fw-p1-p2-p5-combined"):
        assert (c / f"{name}.compose.diff.proposed").read_text().startswith("--- a/docker-compose.n8n.yml\n")


def _hunks(diff: str) -> list[tuple[int, int, list[str]]]:
    out: list[tuple[int, int, list[str]]] = []
    for ln in diff.splitlines(True):
        if ln.startswith("@@ "):
            old, new = ln.split()[1:3]
            out.append((int(old.lstrip("-").split(",")[0]), int(new.lstrip("+").split(",")[0]), []))
        elif out and ln[:1] in (" ", "-", "+"):
            out[-1][2].append(ln)
    return out


def _apply_unified(text: str, diff: str, *, reverse: bool = False) -> str:
    lines = text.splitlines(True)
    drop, add = ("+", "-") if reverse else ("-", "+")
    out, i = [], 0
    for old_start, new_start, body in _hunks(diff):
        start = (new_start if reverse else old_start) - 1
        out.extend(lines[i:start])
        i = start
        for ln in body:
            if ln.startswith(" "):
                assert lines[i] == ln[1:], (lines[i], ln)
                out.append(lines[i])
                i += 1
            elif ln.startswith(drop):
                assert lines[i] == ln[1:], (lines[i], ln)
                i += 1
            elif ln.startswith(add):
                out.append(ln[1:])
    out.extend(lines[i:])
    return "".join(out)


def test_the_three_step_patches_equal_the_combined_patch():
    c = PACKET / "compose"
    proposed = (c / "docker-compose.n8n.yml.proposed").read_text()
    base = _apply_unified(proposed, (c / "fw-p1-p2-p5-combined.compose.diff.proposed").read_text(), reverse=True)
    assert "EXECUTIONS_DATA_SAVE_ON_SUCCESS: none" in base and "image: n8nio/n8n:2.43.0\n" in base
    text = base
    for name in ("fw-p5-image-digest", "fw-p1-save-success", "fw-p2-n8n-app-role"):
        text = _apply_unified(text, (c / f"{name}.compose.diff.proposed").read_text())
    assert text == proposed


def test_units_are_proposed_outside_n8n_and_point_at_committed_scripts():
    u = PACKET / "units"
    for name, script in (("tradeai-n8n-drift-watch", "scripts/n8n_drift_watch.py"),
                         ("tradeai-n8n-host-deadman", "scripts/n8n_host_deadman.py")):
        svc = (u / f"{name}.service.proposed").read_text()
        tmr = (u / f"{name}.timer.proposed").read_text()
        assert svc.startswith("# PROPOSED, NOT INSTALLED") and tmr.startswith("# PROPOSED, NOT INSTALLED")
        assert f"CURRENT/{script} --live" in svc and (ROOT / script).exists()
        assert "SuccessExitStatus=1" in svc and f"Unit={name}.service" in tmr and "OnCalendar=" in tmr
        assert "n8n" not in svc.split("ExecStart=", 1)[1].split("\n", 1)[0].replace(script, "").replace("tradeai-n8n", "")


def test_readme_has_an_ordered_step_for_every_element():
    text = (PACKET / "README.md").read_text(encoding="utf-8")
    for k in range(1, 7):
        assert f'<a id="fw-p{k}"></a>' in text, k
    for word in ("Dry run", "Apply", "Verify", "Rollback"):
        assert text.count(f"**{word}") >= 6, word
    assert "Status:" in text[:600] and "as_of:" in text[:600]
