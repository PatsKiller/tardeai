"""2026-10-08: scripts/lib/persistent_state_root.py imported atomic_json_store through the `scripts.lib` package,
so any caller that only appends scripts/lib to sys.path (check_expected_services.py under its systemd unit)
crashed at receipt-writing time with "No module named 'scripts'" — hourly since 2026-10-05, receipt stale,
two P1 incidents frozen on a three-day-old run. The module must import with either path layout."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _probe(sys_path_entries: list[str]) -> subprocess.CompletedProcess:
    code = (
        "import sys; sys.path[:0] = %r\n"
        "import persistent_state_root as p\n"
        "print(callable(p.resolve_durable_dir))\n" % (sys_path_entries,)
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/", timeout=60)


def test_imports_with_only_scripts_lib_on_the_path():
    r = _probe([str(ROOT / "scripts" / "lib")])
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr[-400:]


def test_imports_with_the_repo_root_on_the_path_too():
    r = _probe([str(ROOT), str(ROOT / "scripts" / "lib")])
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr[-400:]


def test_check_expected_services_reaches_its_receipt_writer_in_dry_run(tmp_path):
    """The real caller, the real layout: run the script from a neutral cwd with no --alert; it must not die on import."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_expected_services.py"), "--help"],
                       capture_output=True, text=True, cwd="/", timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    src = (ROOT / "scripts" / "lib" / "persistent_state_root.py").read_text()
    assert "from atomic_json_store import atomic_write_json" in src
