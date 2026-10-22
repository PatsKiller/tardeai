"""Release Train v2 arming packet: scripts/ops/release_train_arm.sh (ANCHOR RELEASE_TRAIN_ARMING_20261021).

Hermetic. Every test runs the real script inside a sandbox under $TMPDIR (tests/fixtures/release_train_arm/
make_sandbox.sh): HOME, the state root, the config dir, the user unit dir, the relay live list and the receipts are
rebased into it, and psql / systemctl / docker / curl are stubs that record their argv. The script refuses a
sandbox in which any of those resolves outside it, so nothing here can reach the host's database, units, n8n or
Command Center. The code root is a symlink farm onto this checkout, so the real libraries (release_delegation,
release_capability, release_control_cli, release_window, the n8n checks) run against the sandbox.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARM = ROOT / "scripts" / "ops" / "release_train_arm.sh"
MAKE = ROOT / "tests" / "fixtures" / "release_train_arm" / "make_sandbox.sh"
PACKET = ROOT / "docs" / "ops" / "packets" / "release-train-arming-20261021" / "README.md"
LANES = ("release-train-request-1800", "release-train-request-0000", "release-train-request-0600",
         "release-train-request-0800", "pr-hygiene-audit")
ACK = "TRADEAI_RELEASE_TRAIN_ARM_ACK"
GRANTS = {"TRADEAI_CONFIG_WRITE_GRANT": "test-config-write", "TRADEAI_FABRIC_GRANT": "test-cron"}


class Sandbox:
    def __init__(self, base: Path) -> None:
        self.root = base / "sb"
        out = subprocess.run(["bash", str(MAKE), str(self.root), str(ROOT), sys.executable], check=True,
                             capture_output=True, text=True).stdout
        self.env = dict(os.environ)
        for line in out.splitlines():
            k, v = line.split("=", 1)
            self.env[k] = v
        self.env["TMPDIR"] = os.environ.get("TMPDIR") or "/tmp"
        self.env.pop(ACK, None)
        for k in GRANTS:
            self.env.pop(k, None)
        self.home = self.root / "home"
        self.state = self.home / "trade-ai-releases" / "persistent-state"
        self.state_dir = self.state / "data" / "runtime" / "release_window"
        self.conf = self.home / ".config" / "tradeai" / "release_train"
        self.units = self.home / ".config" / "systemd" / "user"
        self.live_env = self.home / ".config" / "tradeai" / "n8n-live-lanes.env"
        self.receipts = self.state / "data" / "runtime" / "release_train_arm" / "receipts.jsonl"

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        e = dict(self.env)
        e.update(env)
        return subprocess.run(["bash", str(ARM), *args], env=e, capture_output=True, text=True, timeout=300)

    def apply(self, step: str, **env: str) -> subprocess.CompletedProcess:
        return self.run(step, "--apply", **{ACK: step, **GRANTS, **env})

    def calls(self) -> list[str]:
        return (self.root / "calls.log").read_text().splitlines()

    def receipt_rows(self) -> list[dict]:
        if not self.receipts.exists():
            return []
        return [json.loads(x) for x in self.receipts.read_text().splitlines() if x.strip()]

    def tree(self) -> dict[str, tuple]:
        out = {}
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if rel == "calls.log" or rel.startswith("fake") or rel.startswith("code/") and p.is_symlink():
                continue
            st = p.lstat()
            out[rel] = (st.st_size, st.st_mtime_ns, st.st_mode)
        return out


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _out(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


# ── dry run ─────────────────────────────────────────────────────────────────────────────────────────

def test_plan_prints_what_every_step_would_do_and_writes_nothing(sb):
    before = sb.tree()
    r = sb.run("plan")
    out = _out(r)
    assert r.returncode == 0, out
    for step in "ABCDEFG":
        assert f"== {step}" in out
    assert "destructive statements: none (additive)" in out                       # A
    assert "WOULD: install -d -m 700" in out and "64 hex chars" in out            # B
    assert "status PAUSED, windows 1800/0000/0600/0800 all disabled" in out       # C
    assert "REFUSED DELEGATION_PAUSED" in out                                      # C.3 expectation
    assert "WOULD: systemctl --user enable --now tradeai-release-train-claim.path" in out   # D
    assert "WOULD: rewrite ONLY the TRADEAI_N8N_RELAY_LIVE_LANES= line" in out     # E
    assert "framework_gate" in out and "WOULD REFUSE --apply" in out              # F: the §23.24 gate today
    assert "verdict: MATCH" in out                                                 # G
    assert sb.tree() == before
    assert sb.receipt_rows() == []
    mutating = [c for c in sb.calls() if any(w in c for w in (" -f ", "--user enable ", "restart", "import:workflow",
                                                              "publish:workflow", "daemon-reload"))]
    assert mutating == []


@pytest.mark.parametrize("step", list("ABCDEFG"))
def test_each_step_dry_run_alone_exits_zero_and_writes_nothing(sb, step):
    before = sb.tree()
    r = sb.run(step)
    assert r.returncode == 0, _out(r)
    assert f"== {step} (dry)" in r.stdout
    assert sb.tree() == before


# ── --apply needs the per-step acknowledgement ──────────────────────────────────────────────────────

@pytest.mark.parametrize("step", list("ABCDEF"))
def test_apply_is_refused_without_the_acknowledgement(sb, step):
    r = sb.run(step, "--apply", **GRANTS)
    assert r.returncode == 2 and "REFUSED" in r.stdout and f"{ACK}={step}" in r.stdout
    assert not sb.conf.exists() and not sb.units.exists()
    assert "TRADEAI_N8N_RELAY_LIVE_LANES=disk-usage-monitor\n" in sb.live_env.read_text()
    assert [row["outcome"] for row in sb.receipt_rows()] == ["REFUSED_NO_ACK"]
    assert not [c for c in sb.calls() if " -f " in c or "--user enable " in c or "import:workflow" in c]


def test_an_acknowledgement_for_one_step_does_not_arm_another(sb):
    r = sb.run("C", "--apply", **{ACK: "B"})
    assert r.returncode == 2
    assert not (sb.conf / "delegation.json").exists()
    r = sb.run("B", "--apply", **{ACK: "1"})
    assert r.returncode == 2 and not (sb.conf / "capability.key").exists()


def test_grants_are_required_for_the_config_and_n8n_steps(sb):
    r = sb.run("E", "--apply", **{ACK: "E"})
    assert r.returncode == 2 and "TRADEAI_CONFIG_WRITE_GRANT" in r.stdout
    r = sb.run("F", "--apply", **{ACK: "F"})
    assert r.returncode == 2 and "TRADEAI_FABRIC_GRANT" in r.stdout


# ── idempotency ─────────────────────────────────────────────────────────────────────────────────────

def test_every_step_is_idempotent(sb):
    gate = {"RTARM_IMPORT_GATE": "stub-pass"}
    for step in "ABCDEF":
        r1 = sb.apply(step, **gate)
        assert r1.returncode == 0 and "APPLIED" in r1.stdout, (step, _out(r1))
        snap = sb.tree()
        r2 = sb.apply(step, **gate)
        assert r2.returncode == 0 and "NOOP" in r2.stdout, (step, _out(r2))
        changed = {k for k in set(snap) | set(sb.tree()) if snap.get(k) != sb.tree().get(k)}
        assert changed <= {sb.receipts.relative_to(sb.root).as_posix()}, (step, changed)
    r = sb.apply("G")
    assert r.returncode == 0 and "verdict: MATCH" in r.stdout
    calls = sb.calls()
    assert sum(" -f " in c and c.startswith("psql") for c in calls) == 1
    assert sum(c.startswith("systemctl --user enable") for c in calls) == 1
    assert sum(c.startswith("systemctl --user restart") for c in calls) == 1
    assert sum("import:workflow" in c for c in calls) == 1 and sum("publish:workflow" in c for c in calls) == 1
    outcomes = [(row["step"], row["outcome"]) for row in sb.receipt_rows()]
    assert outcomes == [(s, o) for s in "ABCDEF" for o in ("APPLIED", "NOOP")] + [("G", "MATCH")]
    for step in "ABCDEF":
        v = sb.run(step, "--verify", **gate)
        assert v.returncode == 0, (step, _out(v))


def test_verify_fails_before_apply(sb):
    for step in "ABCDEF":
        assert sb.run(step, "--verify").returncode == 1, step


def test_capability_key_is_600_hex_and_never_printed(sb):
    r = sb.apply("B")
    key = (sb.conf / "capability.key").read_text().strip()
    assert len(key) == 64 and int(key, 16) >= 0
    assert oct((sb.conf / "capability.key").stat().st_mode & 0o777) == "0o600"
    assert oct(sb.conf.stat().st_mode & 0o777) == "0o700"
    v = sb.run("B", "--verify")
    for res in (r, v):
        assert key not in _out(res)
    assert "KEY_OK" in v.stdout
    assert key not in sb.receipts.read_text()


def test_a_bad_key_is_refused_and_never_overwritten(sb):
    sb.conf.mkdir(parents=True)
    k = sb.conf / "capability.key"
    k.write_text("short\n")
    k.chmod(0o644)
    r = sb.apply("B")
    assert r.returncode == 2 and "archive" in r.stdout
    assert k.read_text() == "short\n"


def test_delegation_is_paused_with_every_window_disabled(sb):
    r = sb.apply("C")
    assert r.returncode == 0, _out(r)
    d = json.loads((sb.conf / "delegation.json").read_text())
    assert d["status"] == "PAUSED" and all(s["enabled"] is False for s in d["windows"]["slots"])
    assert oct((sb.conf / "delegation.json").stat().st_mode & 0o777) == "0o600"
    v = sb.run("C", "--verify")
    assert v.returncode == 0 and "PAUSED" in v.stdout and '"mode": "UNARMED"' in v.stdout


def test_a_paused_delegation_cannot_be_armed_at_the_cli(sb):
    """Packet step C.3: the host CLI's arm accepts only an ACTIVE record, so 'accept the PAUSED digest' is a refusal."""
    assert sb.apply("C").returncode == 0
    env = dict(sb.env, HOME=str(sb.home))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "release_control_cli.py"), "--state-dir",
                        str(sb.state_dir), "arm", "--delegation", str(sb.conf / "delegation.json"),
                        "--reason", "C.3 check", "--dry-run"], env=env, capture_output=True, text=True)
    assert r.returncode == 2 and '"DELEGATION_PAUSED"' in r.stdout
    assert not (sb.state_dir / "control.json").exists()


def test_an_invalid_delegation_is_refused_and_kept(sb):
    sb.conf.mkdir(parents=True)
    p = sb.conf / "delegation.json"
    p.write_text('{"schema": "nope"}')
    r = sb.apply("C")
    assert r.returncode == 2 and "INVALID" in r.stdout
    assert p.read_text() == '{"schema": "nope"}'


def test_migration_refuses_a_role_that_would_not_own_the_tables(sb):
    r = sb.apply("A", FAKE_DB_ROLE="postgres")
    assert r.returncode == 2 and "trade_ai" in r.stdout
    assert not any(" -f " in c for c in sb.calls())


def test_a_differing_installed_unit_is_refused_and_kept(sb):
    sb.units.mkdir(parents=True)
    u = sb.units / "tradeai-release-train-claim.service"
    u.write_text("[Service]\nExecStart=/bin/true\n")
    r = sb.apply("D")
    assert r.returncode == 2 and "differ" in r.stdout
    assert u.read_text() == "[Service]\nExecStart=/bin/true\n"
    assert not any("--user enable " in c for c in sb.calls())


def test_live_list_edit_keeps_other_lines_and_archives_a_backup(sb):
    r = sb.apply("E")
    assert r.returncode == 0, _out(r)
    text = sb.live_env.read_text()
    assert "OTHER_KEY=keep-me\n" in text
    line = next(x for x in text.splitlines() if x.startswith("TRADEAI_N8N_RELAY_LIVE_LANES="))
    names = line.split("=", 1)[1].split()
    assert names[0] == "disk-usage-monitor" and all(n in names for n in LANES) and len(names) == len(set(names))
    baks = list(sb.live_env.parent.glob("n8n-live-lanes.env.bak-*-release-train-arm"))
    assert len(baks) == 1 and baks[0].read_text() == "TRADEAI_N8N_RELAY_LIVE_LANES=disk-usage-monitor\nOTHER_KEY=keep-me\n"
    assert oct(sb.live_env.stat().st_mode & 0o777) == "0o600"
    assert any("restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service" in c for c in sb.calls())


def test_the_real_import_gate_refuses_the_workflow_and_nothing_is_imported(sb):
    """AGENTS §23.24: check_n8n_import_ready.py refuses tradeai-fabric-release-train today (framework_gate)."""
    for _ in range(2):
        r = sb.apply("F")
        assert r.returncode == 2 and "§23.24" in r.stdout
    assert not any("import:workflow" in c or "publish:workflow" in c or c.startswith("docker restart")
                   for c in sb.calls())


def test_n8n_restart_is_refused_near_a_train_tick(sb):
    r = sb.apply("F", RTARM_IMPORT_GATE="stub-pass", RTARM_NOW_HM="1625")
    assert r.returncode == 2 and "1630" in r.stdout
    assert not any("import:workflow" in c for c in sb.calls())


def test_state_dir_mismatch_is_reported_never_fixed(sb):
    before = sb.tree()
    r = sb.run("G", FAKE_CC_STATE_DIR="/srv/elsewhere/release_window")
    assert r.returncode == 0 and "MISMATCH" in r.stdout          # dry run reports, exit 0
    v = sb.run("G", "--verify", FAKE_CC_STATE_DIR="/srv/elsewhere/release_window")
    assert v.returncode == 1 and "never auto-remediate" in v.stdout
    assert sb.tree() == before


def test_status_is_read_only(sb):
    before = sb.tree()
    r = sb.run("status")
    assert r.returncode == 0 and "B capability key: ABSENT" in r.stdout and "C delegation: MISSING" in r.stdout
    assert sb.tree() == before


# ── identity and the sandbox contract ───────────────────────────────────────────────────────────────

def test_refuses_another_user(sb):
    r = sb.run("plan", RTARM_EXPECT_USER="someone-else")
    assert r.returncode == 2 and "portfolio-server user" in r.stdout


def test_refuses_another_host(sb):
    r = sb.run("plan", RTARM_EXPECT_HOST="not-" + socket.gethostname().split(".")[0])
    assert r.returncode == 2 and "run on host" in r.stdout


def test_refuses_when_portfolio_server_is_not_this_users_unit(sb):
    r = sb.run("plan", FAKE_NO_PS_UNIT="1")
    assert r.returncode == 2 and "not a user unit" in r.stdout


def test_sandbox_without_marker_is_refused(sb):
    (sb.root / ".rtarm-sandbox").unlink()
    r = sb.run("plan")
    assert r.returncode == 2 and "marker" in r.stdout


def test_sandbox_outside_tmpdir_is_refused(sb, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    r = sb.run("plan", TMPDIR=str(other))
    assert r.returncode == 2 and "must be under" in r.stdout


def test_sandbox_with_real_tools_on_path_is_refused(sb, tmp_path):
    fake_real = tmp_path / "realbin"
    fake_real.mkdir()
    (fake_real / "docker").write_text("#!/bin/sh\necho REAL >> /dev/null\n")
    (fake_real / "docker").chmod(0o755)
    r = sb.run("plan", PATH=f"{fake_real}:{sb.env['PATH']}")
    assert r.returncode == 2 and "docker resolves outside the sandbox" in r.stdout


def test_test_seams_are_read_only_inside_the_sandbox_branch():
    """Static: every RTARM_* override (identity, code root, interpreter, gate stub, probe, clock) is read only in the
    RTARM_SANDBOX branch, so outside a sandbox none of them can change identity, paths or the import gate. (Not run
    for real: outside a sandbox the script would talk to the live host, which these tests never do.)"""
    text = ARM.read_text(encoding="utf-8")
    head, rest = text.split('if [[ -n "${RTARM_SANDBOX:-}" ]]; then', 1)
    branch, after = rest.split("\nelse\n", 1)
    real_branch, tail = after.split("\nfi\n", 1)
    seams = ("RTARM_EXPECT_USER", "RTARM_EXPECT_HOST", "RTARM_CODE_ROOT", "RTARM_PY", "RTARM_RELAY_PROBE",
             "RTARM_IMPORT_GATE", "RTARM_NOW_HM")
    for seam in seams:
        assert "${" + seam in branch, seam
        assert "${" + seam not in head + real_branch + tail, seam
    assert 'EXPECT_USER="$EXPECT_USER_DEFAULT"' in real_branch and 'IMPORT_GATE="real"' in real_branch


def test_nothing_touches_real_paths(sb):
    real_home = Path(os.path.expanduser("~"))
    watch = [real_home / ".config" / "tradeai" / "release_train",
             real_home / ".config" / "tradeai" / "n8n-live-lanes.env",
             real_home / ".config" / "systemd" / "user",
             real_home / "trade-ai-releases" / "persistent-state" / "data" / "runtime" / "release_window",
             real_home / "trade-ai-releases" / "persistent-state" / "data" / "runtime" / "release_train_arm"]

    def snap():   # stat only: never reads a real file's contents
        out = {}
        for w in watch:
            try:
                st = w.stat()
                out[str(w)] = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                out[str(w)] = None
            if w.is_dir():
                out[str(w) + "/*"] = sorted(p.name for p in w.iterdir() if "release-train" in p.name
                                            or "release_train" in p.name)
        return out

    before = snap()
    for step in "ABCDEF":
        assert sb.apply(step, RTARM_IMPORT_GATE="stub-pass").returncode == 0, step
    sb.apply("G")
    sb.run("plan")
    assert snap() == before
    sbx = str(sb.root)
    for c in sb.calls():
        for tok in c.split():
            tok = tok.split("=", 1)[-1].replace("m8m-n8n:", "")
            if tok.startswith("/") and not tok.startswith("/tmp/tradeai-rtarm-wf-"):
                assert tok.startswith(sbx), c


# ── packet, gate registration, wiring ───────────────────────────────────────────────────────────────

def test_bash_suite_passes():
    env = dict(os.environ, RTARM_TEST_PY=sys.executable)
    r = subprocess.run(["bash", str(ROOT / "tests" / "release_train_arm_test.sh")], env=env, capture_output=True,
                       text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert ", 0 failed" in r.stdout


def test_packet_has_every_section_with_dry_run_verify_and_rollback():
    text = PACKET.read_text(encoding="utf-8")
    for sec in "ABCDEFGHIJKL":
        assert f"\n## {sec}." in text, sec
    for sec in "ABCDEFG":
        body = text.split(f"\n## {sec}.", 1)[1].split("\n## ", 1)[0]
        for word in ("Command", "Dry run", "Expected", "Verify", "Rollback"):
            assert f"**{word}" in body, (sec, word)


def test_ci_gate_is_registered():
    sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates

    names = {name: files for name, files in ci_gates.load_gates(ROOT)}
    assert names.get("release_train_arming_20261021") == ["tests/test_release_train_arming_20261021.py"]
    doc = json.loads((ROOT / "config" / "ci_gates" / "release_train_arming_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_ARMING_20261021"
    assert doc["comment"][0].startswith("ANCHOR: RELEASE_TRAIN_ARMING_20261021")
