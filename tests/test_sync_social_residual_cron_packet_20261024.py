"""WP-33 item2: offline exact residual retirement and fake-crontab operator rehearsal."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/sync-social-residual-cron-20261024"
spec = importlib.util.spec_from_file_location("wp33_residual_packet", PACKET / "retire_packet.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
EXACT = (
    "30 11,15 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && "
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python "
    "scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1"
).encode()
OLD_FLOCKED = (
    "30 11,15 * * 1-5 cd $PROJ && flock -n /tmp/sync_social_to_intelligence.lock "
    "$PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1"
).encode()
PREFIX = b"# RETIRED WP33-20261024 sync-social-to-intelligence residual (operator packet; n8n owns) "
FIXED = "2026-10-24T03:48:19Z"


def big_snapshot(line: bytes = EXACT) -> bytes:
    # Target is genuinely line 1077, with a >200 KB unrelated snapshot and the historical line at875.
    lines = [f"# unrelated {i} ".encode() + b"x" * 240 for i in range(1076)]
    lines[0] = b"SHELL=/bin/bash"
    lines[874] = b"# N8N-OWNED 2026-10-22 " + OLD_FLOCKED
    return b"\n".join(lines + [line, b"*/5 * * * * untouched-job --fixture"]) + b"\n"


def test_exact_historical_target_is_pinned_and_distinct_from_old_packet():
    assert mod.target()[:2] == (EXACT, PREFIX)
    historical = (ROOT / "docs/ops/N8N_CUTOVER_EFFECT_CLAIM_WRAPPER_20261023.md").read_bytes()
    old_packet = (ROOT / "docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh").read_bytes()
    assert EXACT in historical and OLD_FLOCKED in old_packet and EXACT not in old_packet


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b""])
def test_exact_comment_only_change_preserves_all_other_bytes_and_endings(ending):
    before = b"# unrelated\n" + OLD_FLOCKED + b"\n" + EXACT + ending
    after, receipt = mod.prepare(before)
    assert after == b"# unrelated\n" + OLD_FLOCKED + b"\n" + PREFIX + EXACT + ending
    assert receipt["changed_lines"] == 1 and receipt["change"] == "PREFIX_ONE_EXACT_LINE_ONLY"
    assert mod.verify(before, after, receipt, after)["verification"] == "INSTALLED_READBACK_MATCHES"
    assert receipt["n8n_acceptance"] == "NOT_MEASURED"


def test_large_snapshot_retains_legacy_flocked_comment_and_every_unrelated_byte():
    before = big_snapshot()
    after, receipt = mod.prepare(before)
    assert len(before) > 200_000 and receipt["line_number_in_snapshot"] == 1077
    expected = before.split(b"\n")
    expected[1076] = PREFIX + EXACT
    assert after == b"\n".join(expected)
    assert b"# N8N-OWNED 2026-10-22 " + OLD_FLOCKED in after


@pytest.mark.parametrize("variant", [
    OLD_FLOCKED, b" " + EXACT, EXACT + b" ", b"# custom retirement " + EXACT,
    EXACT.replace(b"11,15", b"11,16"), EXACT.replace(b"CURRENT", b"OLD"),
    EXACT.replace(b" && ", b" && flock -n /tmp/other.lock "),
])
def test_absent_or_drifted_residual_is_refused_instead_of_matching_a_similar_line(variant):
    with pytest.raises(mod.Refused, match="exact residual line absent"):
        mod.prepare(big_snapshot(variant))


@pytest.mark.parametrize("lines", [[EXACT, EXACT], [EXACT, PREFIX + EXACT], [PREFIX + EXACT, PREFIX + EXACT]])
def test_duplicate_and_mixed_active_retired_targets_are_refused(lines):
    with pytest.raises(mod.Refused, match="ambiguous target"):
        mod.prepare(b"\n".join(lines))


def test_an_exact_already_retired_snapshot_is_idempotent_without_install():
    before = big_snapshot(PREFIX + EXACT)
    after, receipt = mod.prepare(before)
    assert after == before and receipt["changed_lines"] == 0
    assert receipt["status"] == "ALREADY_RETIRED_IN_SNAPSHOT"


@pytest.mark.parametrize("tamper", ["unrelated", "delete_target", "receipt", "readback"])
def test_verifier_rejects_any_candidate_receipt_or_readback_drift(tamper):
    before = big_snapshot()
    after, receipt = mod.prepare(before)
    installed = after
    if tamper == "unrelated":
        after += b"# unrelated changed\n"
    elif tamper == "delete_target":
        after = after.replace(PREFIX + EXACT, b"")
    elif tamper == "receipt":
        receipt["changed_lines"] = 999
    else:
        installed += b"# concurrent change\n"
    with pytest.raises(mod.Refused):
        mod.verify(before, after, receipt, installed)


def test_offline_cli_keeps_private_non_overwritten_backup_and_zero_context_diff(tmp_path, capsys):
    snapshot = tmp_path / "supplied.cron"
    snapshot.write_bytes(big_snapshot())
    out = tmp_path / "plan"
    args = ["plan", "--snapshot", str(snapshot), "--out-dir", str(out), "--observed-at", FIXED]
    assert mod.main(args) == 0
    receipt = json.loads((out / "plan.json").read_text())
    assert receipt["observed_at"] == FIXED
    assert (out / "crontab.before").read_bytes() == snapshot.read_bytes()
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    diff = (out / "target-only.diff").read_bytes()
    assert b"@@ -1077 +1077 @@" in diff and b"unrelated" not in diff and b"SHELL=" not in diff
    old = (out / "crontab.candidate").read_bytes()
    assert mod.main(args) == 3 and (out / "crontab.candidate").read_bytes() == old
    assert "REFUSED" in capsys.readouterr().out


def fake_env(tmp: Path, before: bytes, **flags: str) -> dict:
    shim = tmp / "bin"
    shim.mkdir()
    store = tmp / "fake.cron"
    store.write_bytes(before)
    log = tmp / "fake.calls"
    fake = """import os,sys
from pathlib import Path
store=Path(os.environ['WP33_FAKE_STORE']); log=Path(os.environ['WP33_FAKE_LOG'])
if sys.argv[1:] == ['-l']:
    previous=log.read_text() if log.exists() else ''
    with log.open('a') as f: f.write('READ\\n')
    if os.getenv('WP33_FAKE_FAIL_READ'): sys.exit(1)
    sys.stdout.buffer.write(store.read_bytes())
    if os.getenv('WP33_FAKE_DRIFT') and not previous: store.write_bytes(store.read_bytes()+b'# concurrent writer\\n')
elif len(sys.argv)==2:
    with log.open('a') as f: f.write('WRITE\\n')
    store.write_bytes(Path(sys.argv[1]).read_bytes())
    if os.getenv('WP33_FAKE_BAD_READBACK'): store.write_bytes(store.read_bytes()+b'# concurrent after install\\n')
else: sys.exit(10)
"""
    for name, body in {"crontab": fake, "hostname": "print('ms01-openclaw')\n", "id": "print('johnclaw')\n"}.items():
        script = shim / name
        script.write_text(f"#!{sys.executable}\n{body}")
        script.chmod(0o700)
    return dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", WP33_FAKE_STORE=str(store),
                WP33_FAKE_LOG=str(log), WP33_EVIDENCE_ROOT=str(tmp / "evidence"), **flags)


def run_operator(tmp: Path, mode="--preview", answer="", before=None, **flags):
    before = big_snapshot() if before is None else before
    env = fake_env(tmp, before, **flags)
    result = subprocess.run(["bash", str(PACKET / "operator.sh"), mode], env=env, input=answer,
                            capture_output=True, text=True, timeout=30)
    calls = (tmp / "fake.calls").read_text().splitlines()
    return result, calls, (tmp / "fake.cron").read_bytes()


def test_operator_preview_uses_fake_crontab_once_and_never_installs(tmp_path):
    before = big_snapshot()
    result, calls, stored = run_operator(tmp_path, before=before)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREVIEW ONLY" in result.stdout and calls == ["READ"] and stored == before


def test_operator_apply_writes_one_exact_candidate_and_reads_it_back(tmp_path):
    before = big_snapshot()
    result, calls, stored = run_operator(tmp_path, "--apply", "ACK-RETIRE-SYNC-SOCIAL-RESIDUAL\n", before)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["READ", "READ", "WRITE", "READ"]
    assert stored == mod.prepare(before)[0] and "COMMENT INSTALLED AND READ BACK" in result.stdout
    saved = next((tmp_path / "evidence").glob("*/installed-verification.json"))
    proof = json.loads(saved.read_text())
    assert proof["verification"] == "INSTALLED_READBACK_MATCHES" and proof["n8n_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("flag", ["WP33_FAKE_FAIL_READ", "WP33_FAKE_DRIFT", "WP33_FAKE_BAD_READBACK"])
def test_operator_refuses_read_failure_drift_or_bad_readback_without_whole_backup_restore(tmp_path, flag):
    before = big_snapshot()
    result, calls, stored = run_operator(tmp_path, "--apply", "ACK-RETIRE-SYNC-SOCIAL-RESIDUAL\n", before, **{flag: "1"})
    assert result.returncode != 0 and "REFUSED" in result.stdout + result.stderr
    assert "COMMENT INSTALLED AND READ BACK" not in result.stdout
    if flag == "WP33_FAKE_BAD_READBACK":
        assert calls.count("WRITE") == 1 and stored == mod.prepare(before)[0] + b"# concurrent after install\n"
    else:
        assert "WRITE" not in calls
        assert stored == before + (b"# concurrent writer\n" if flag == "WP33_FAKE_DRIFT" else b"")


def test_operator_wrong_ack_and_already_retired_do_not_write(tmp_path):
    bad = tmp_path / "wrong"
    bad.mkdir()
    result, calls, stored = run_operator(bad, "--apply", "APPLY\n")
    assert result.returncode == 4 and "WRITE" not in calls and stored == big_snapshot()
    done = tmp_path / "already"
    done.mkdir()
    result, calls, stored = run_operator(done, "--apply", before=big_snapshot(PREFIX + EXACT))
    assert result.returncode == 0 and calls == ["READ"] and stored == big_snapshot(PREFIX + EXACT)
    assert "ALREADY RETIRED IN SNAPSHOT" in result.stdout
