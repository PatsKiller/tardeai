"""REPRODUCTION for codex-cloud P1 on #2692 at 014d8b97f — the merge exemption can suppress NEWLY INTRODUCED PII.

Written by cc-deepseek-3 for cc-deepseek-8 to adopt (handed over by one line; the file is NOT in the repo).

The defect, in the cloud's words: "during a merge-up the exemption can SUPPRESS NEWLY INTRODUCED PII when the identifying
label sits on the preceding line. ACCOUNT_RE and CHAT_ID_RE accept newlines between the label and the value, but a finding
records only the VALUE's line. So if main already publishes an unlabelled numeric line and a merge resolution changes the
blank line above it to `account =`, the value line is byte-identical to main and gets exempted — while the label that makes
it identifying is new."

The construction below is exactly that, and the assertion is the honest one: the scan must REFUSE (exit 1). Today it exits 0,
because the exemption compares the value line only.

It is hermetic: two temporary git repositories, no network, no live store.

Run it against a checkout of the branch under repair (placeholders shown; the real host paths are not committed
to this PUBLIC repository):

    <coordinator>/test_slot.sh \
      <repo>/.venv/bin/python -m pytest \
      <scratch>/test_check_no_pii_context_suppression.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# The value is assembled at runtime: a literal here would be a finding in the very gate this test is about.
BARE_VALUE = "123" + "4567"
LABEL = "acc" + "ount ="


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _repos(tmp_path: Path) -> tuple[Path, Path]:
    """(upstream, work): main publishes the BARE number with a blank line above it; the branch is made before that."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _git(upstream, "config", "user.email", "synthetic@example.com")
    _git(upstream, "config", "user.name", "synthetic")
    (upstream / "README.md").write_text("synthetic\n", encoding="utf-8")
    _commit(upstream, "seed")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(upstream), str(work))
    _git(work, "config", "user.email", "synthetic@example.com")
    _git(work, "config", "user.name", "synthetic")

    # Main adds the bare number — not a finding on its own, because nothing labels it.
    (upstream / "config").mkdir()
    (upstream / "config" / "ledger.md").write_text(f"# ledger\n\n{BARE_VALUE}\n", encoding="utf-8")
    _commit(upstream, "main publishes an unlabelled numeric line")

    _git(work, "fetch", "-q", "origin")
    _git(work, "checkout", "-q", "-b", "feature")
    (work / "feature.md").write_text("branch work\n", encoding="utf-8")
    _commit(work, "branch work")
    return upstream, work


def _merge_up(work: Path) -> subprocess.CompletedProcess:
    """Stage the merge WITHOUT committing: the pre-commit hook runs in exactly this state (MERGE_HEAD present)."""
    return _git(work, "merge", "--no-commit", "--no-ff", "--no-edit", "origin/main", check=False)


def _scan_staged(repo_root: Path, work: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "check_no_pii.py"), "--repo", str(work), "--staged"],
        capture_output=True, text=True, timeout=120,
    )


def test_a_new_label_above_mains_unchanged_value_is_not_exempt(tmp_path):
    """THE DEFECT: the merge resolution introduces the label; the value line is byte-identical to main's."""
    repo_root = Path(__file__).resolve().parents[3] if (Path(__file__).resolve().parents[3] / "scripts" / "check_no_pii.py").exists() else None
    if repo_root is None:
        # When run from the scratch dir, import the module from whichever repo is under test via C.NO_PII_ROOT, else skip.
        import importlib.util
        spec = importlib.util.find_spec("check_no_pii")
        assert spec is not None, "run this from a checkout that contains scripts/check_no_pii.py"
        repo_root = Path(spec.origin).resolve().parents[1]

    upstream, work = _repos(tmp_path)

    # The merge resolution itself: change ONLY the blank line above main's value into the label.
    assert _merge_up(work).returncode == 0, "the synthetic merge-up itself failed"
    ledger = work / "config" / "ledger.md"
    original = ledger.read_text(encoding="utf-8")            # "# ledger\n\n1234567\n"
    assert original == f"# ledger\n\n{BARE_VALUE}\n", repr(original)
    ledger.write_text(f"# ledger\n{LABEL}\n{BARE_VALUE}\n", encoding="utf-8")
    _git(work, "add", "-A")

    proc = _scan_staged(repo_root, work)
    detail = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        "the merge exemption suppressed NEWLY INTRODUCED PII: the label on the preceding line is new, the value line is "
        f"byte-identical to main's, and the scan passed. exit={proc.returncode}\n{detail}"
    )
    assert "account" in detail.lower() or "private" in detail.lower(), detail
