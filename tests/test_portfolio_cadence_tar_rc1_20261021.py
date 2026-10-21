"""2026-10-21 backup-cadence failure: `tar: data/cio: file changed as we read it`.

tradeai-portfolio-backup-cadence.service failed 2026-10-21 02:52 ET:

    [backup:data] bundling 1 path(s): data
    tar: data/cio: file changed as we read it
    ---- step END: secrets_backup_data status=FAILED(rc=1) 49690ms ----
    tradeai-portfolio-backup-cadence.service: Main process exited, code=exited, status=1/FAILURE

Two defects, both pinned here:

1. scripts/backup_secrets_state.sh ran `tar` under `set -e`. GNU tar exits 1 ("some files
   differ") when a live writer touches a file or directory while it is being read; the archive is
   still complete. rc=1 aborted the script before gpg/upload, so no weekly data backup shipped.
   Fix: tar rc=1 is a warning (archive gzip-verified, fail closed if corrupt); rc>=2 stays fatal.
2. run_weekly_gated() in scripts/pipelines/run_portfolio_maintenance_pipeline.sh ended with
   `[ status = ok ] && touch stamp`. On a failed step that list returns 1, the function returns 1,
   and `set -e` killed the whole pipeline: db_offsite_backup and apps_backup never ran, no summary
   was written, and the unit exited 1 instead of recording overall=degraded. Fix: the helper
   always returns 0 (pm_step already records FAILED and sets overall=1 -> degraded).

Hermetic: scratch HOME/PROJ, fake gpg/gog on PATH, a tar wrapper that runs the real tar and then
exits 1 like a changed-file read. No Drive, no credentials, no production paths.
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKUP_SH = REPO / "scripts" / "backup_secrets_state.sh"
PIPELINE_SH = REPO / "scripts" / "pipelines" / "run_portfolio_maintenance_pipeline.sh"
REAL_TAR = shutil.which("tar") or "/usr/bin/tar"


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _scratch(tmp_path: Path, tar_rc: int) -> tuple[Path, dict]:
    home = tmp_path / "home"
    creds = home / ".openclaw" / "credentials"
    creds.mkdir(parents=True)
    (creds / "env_data_backup.pass").write_text("test-pass\n")
    (creds / "gog_keyring_password").write_text("test-keyring\n")
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    calls = tmp_path / "gog_calls.log"
    _exe(
        bindir / "gog",
        f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n'
        'if [ "$2" = "upload" ]; then printf "id\\tFAKEID\\nname\\t%s\\n" "$(basename "$3")"; fi\n',
    )

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    # gpg: copy the input (last arg) to the -o target.
    _exe(
        fakebin / "gpg",
        '#!/usr/bin/env bash\nout=""; prev=""\nfor a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        'cp "${@: -1}" "$out"\n',
    )
    # tar: run the real tar, then report a changed file the way GNU tar does.
    _exe(
        fakebin / "tar",
        f'#!/usr/bin/env bash\n"{REAL_TAR}" "$@" || exit $?\n'
        f'[ {tar_rc} -ne 0 ] && echo "tar: data/cio: file changed as we read it" >&2\nexit {tar_rc}\n',
    )

    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    shutil.copy2(BACKUP_SH, proj / "scripts" / "backup_secrets_state.sh")
    (proj / "data" / "cio").mkdir(parents=True)
    (proj / "data" / "cio" / "ledger.json").write_text("{}\n")
    (proj / "data" / "runtime").mkdir()
    (proj / "data" / "runtime" / "ephemeral.log").write_text("x\n")

    env = {
        "HOME": str(home),
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp_path),
    }
    return proj, {"env": env, "calls": calls, "fakebin": fakebin}


def _run_backup(proj: Path, ctx: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(proj / "scripts" / "backup_secrets_state.sh"), "data"],
        env=ctx["env"], cwd=proj, capture_output=True, text=True, timeout=60,
    )


def _uploaded(ctx: dict) -> bool:
    return ctx["calls"].exists() and "upload" in ctx["calls"].read_text()


def test_tar_changed_file_rc1_still_encrypts_and_uploads(tmp_path):
    proj, ctx = _scratch(tmp_path, tar_rc=1)
    r = _run_backup(proj, ctx)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "file changed as we read it" in out
    assert "encrypted -> data_backup_" in out
    assert _uploaded(ctx)
    assert "[backup:data] done" in out


def test_tar_fatal_rc2_still_fails_closed(tmp_path):
    proj, ctx = _scratch(tmp_path, tar_rc=2)
    r = _run_backup(proj, ctx)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not _uploaded(ctx)


def test_tar_rc1_with_corrupt_archive_fails_closed(tmp_path):
    proj, ctx = _scratch(tmp_path, tar_rc=1)
    # rc=1 but the archive is not valid gzip: must not upload a broken backup.
    _exe(
        ctx["fakebin"] / "tar",
        '#!/usr/bin/env bash\nout=""; prev=""\nfor a in "$@"; do case "$prev" in *f) out="$a";; esac; prev="$a"; done\n'
        'echo garbage > "$out"; echo "tar: data/cio: file changed as we read it" >&2; exit 1\n',
    )
    r = _run_backup(proj, ctx)
    assert r.returncode != 0, r.stdout + r.stderr
    assert not _uploaded(ctx)


def _extract_fn(src: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src, re.S | re.M)
    assert m, f"{name}() not found in pipeline"
    return m.group(0)


def test_failed_weekly_gated_step_does_not_abort_pipeline(tmp_path):
    src = PIPELINE_SH.read_text()
    harness = tmp_path / "harness.sh"
    stamp_dir = tmp_path / "stamps"
    stamp_dir.mkdir()
    harness.write_text(
        "set -euo pipefail\n"
        'DRY_RUN=0; overall=0; PROJ="' + str(tmp_path) + '"\n'
        "_ts() { date -u +%FT%TZ; }\n"
        "declare -a STEP_NAMES STEP_STATUS STEP_MS STEP_LABEL\n"
        + _extract_fn(src, "pm_step")
        + _extract_fn(src, "run_weekly_gated")
        # the step command: fail for 'data', succeed otherwise
        + 'bash() { [ "${2:-}" != "data" ]; }\n'
        + f'run_weekly_gated secrets_backup_data "{stamp_dir}/data.stamp" data\n'
        + f'run_weekly_gated db_offsite_backup "{stamp_dir}/db.stamp" db\n'
        + 'echo "REACHED_END overall=$overall statuses=${STEP_STATUS[*]}"\n'
    )
    r = subprocess.run(["/bin/bash", str(harness)], capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin"})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "REACHED_END overall=1 statuses=FAILED(rc=1) ok" in out, out
    assert not (stamp_dir / "data.stamp").exists()
    assert (stamp_dir / "db.stamp").exists()
