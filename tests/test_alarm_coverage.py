"""C1 gate — the uncovered alarm set is a named number that can only shrink.

An alarm that has never been observed firing is indistinguishable from no alarm.
This gate does not pretend the 141 send_telegram sites are tested. It states how
many are, refuses to let that number grow, and names the rest as debt.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from alarm_firing_coverage import call_sites, declared_covers, summary  # noqa: E402

BASELINE = ROOT / "config" / "alarm_firing_baseline.txt"


def _baseline() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path, _, n = line.rpartition(" ")
        out[path] = int(n)
    return out


def test_no_file_gains_an_untested_alarm():
    covered = declared_covers(ROOT / "tests")
    uncovered = Counter(f for f, _ in call_sites(ROOT / "scripts") if f not in covered)
    base = _baseline()
    regressions = [f"  {f}: {n} untested send_telegram sites, baseline {base.get(f, 0)}"
                   for f, n in sorted(uncovered.items()) if n > base.get(f, 0)]
    assert not regressions, (
        "new alarm call sites with no firing test:\n" + "\n".join(regressions)
        + "\n\nAdd a firing test that injects the condition and asserts the message "
          "reaches the transport, then list the file in that test's COVERS."
    )


def test_baseline_has_no_stale_entries():
    """Debt paid must be recorded, or the slack absorbs the next regression."""
    covered = declared_covers(ROOT / "tests")
    uncovered = Counter(f for f, _ in call_sites(ROOT / "scripts") if f not in covered)
    stale = [f"  {f}: baseline {n}, actual {uncovered.get(f, 0)}"
             for f, n in sorted(_baseline().items()) if uncovered.get(f, 0) < n]
    assert not stale, "lower these baseline entries:\n" + "\n".join(stale)


def test_coverage_is_reported_not_implied():
    """The count must be legible. A gap nobody states is a gap nobody closes."""
    s = summary(ROOT / "scripts", ROOT / "tests")
    assert s["sites_total"] > 0
    assert s["sites_covered"] + s["sites_uncovered"] == s["sites_total"]
    print(f"\nC1 send_telegram coverage: {s['sites_covered']}/{s['sites_total']} sites "
          f"({s['files_total']} files); uncovered {s['sites_uncovered']} named in "
          f"config/alarm_firing_baseline.txt")


def test_positive_control_coverage_detector_sees_a_new_site(tmp_path):
    """A detector that cannot fail proves nothing."""
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "probe.py").write_text("def f():\n    send_telegram('x')\n")
    assert len(call_sites(d)) == 1


def test_positive_control_declared_covers_is_read(tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_probe.py").write_text('COVERS = ["scripts/probe.py"]\n')
    assert declared_covers(t) == {"scripts/probe.py"}
