"""Generated artifacts must be RECOMPUTED on merge, never line-merged.

THE ROOT CAUSE, MEASURED
------------------------
Six consecutive merges on 2026-09-06; 6 of 6 touched the same five files:

    docs/INDEX.md                     rebuilt from `git ls-files`
    FULL_TEST_MATRIX.txt              carries control_surface_digest
    RUFF_SHELLCHECK.txt                       "
    CONTROL7_WORKFLOW_PROOF.txt               "
    CONTROL7_LOCAL_EQUIVALENT.txt             "

Any two concurrent PRs therefore conflicted BY CONSTRUCTION, whatever they
changed. Four resolutions that day were all this; none was a disagreement about
code. Resolving them four times fixed the effect, not the cause.

Hand-merging a digest is wrong: it can match neither tree. Local Git's union
driver can preserve path/title index rows, which the checker validates, but it
does not guarantee GitHub mergeability. Recompute over the integrated tree.

These tests run a REAL git merge in a temp repo — two branches that both edit a
generated file — and assert the mechanism resolves it. Asserting that
.gitattributes contains a line would test the config, not the behaviour.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _git(*args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check, timeout=60)


@pytest.fixture
def repo(tmp_path):
    """A repo with the same generated-file shape as this one."""
    r = tmp_path / "r"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / ".gitattributes").write_text("gen.txt merge=regenerate\n", encoding="utf-8")
    (r / "gen.txt").write_text("digest=AAAA\n", encoding="utf-8")
    (r / "real.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-qm", "base", cwd=r)
    return r


def _register_driver(r: Path):
    _git("config", "merge.regenerate.name", "recompute", cwd=r)
    _git("config", "merge.regenerate.driver",
         f"{ROOT / 'scripts' / 'git_merge_regenerate.sh'} %O %A %B %L %P", cwd=r)


def _diverge(r: Path):
    """Two branches that both touch the generated file — the real situation."""
    _git("checkout", "-qb", "a", cwd=r)
    (r / "gen.txt").write_text("digest=BBBB\n", encoding="utf-8")
    (r / "feature_a.py").write_text("a = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r); _git("commit", "-qm", "a", cwd=r)
    _git("checkout", "-q", "main", cwd=r)
    _git("checkout", "-qb", "b", cwd=r)
    (r / "gen.txt").write_text("digest=CCCC\n", encoding="utf-8")
    (r / "feature_b.py").write_text("b = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r); _git("commit", "-qm", "b", cwd=r)


def test_without_the_driver_the_merge_conflicts():
    """The negative control. Without this, the test below proves nothing —
    it could pass because the merge was trivial, not because the driver worked."""
    pass


def test_the_conflict_is_real_without_the_driver(repo):
    _diverge(repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode != 0, "expected a conflict — the premise of this suite"
    status = _git("status", "--porcelain", cwd=repo).stdout
    assert "gen.txt" in status
    assert "UU" in status or "AA" in status, status


def test_the_driver_resolves_it(repo):
    """Same divergence, driver registered: the merge completes."""
    _register_driver(repo)
    _diverge(repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode == 0, f"driver did not resolve: {r.stdout}{r.stderr}"
    assert not _git("diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.strip()


def test_real_code_conflicts_are_still_conflicts(repo):
    """The driver must NOT swallow genuine disagreements. A mechanism that
    resolves everything is worse than the problem."""
    _register_driver(repo)
    _git("checkout", "-qb", "a", cwd=repo)
    (repo / "real.py").write_text("x = 2\n", encoding="utf-8")
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "a", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    _git("checkout", "-qb", "b", cwd=repo)
    (repo / "real.py").write_text("x = 3\n", encoding="utf-8")
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "b", cwd=repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode != 0, "a real code conflict must still stop the merge"


# ── the live repo's configuration ──────────────────────────────────────────

def test_every_file_that_conflicted_is_covered():
    """The five measured on 2026-09-06. If one is dropped, it starts conflicting
    again and the fix silently regresses."""
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for name in ("docs/INDEX.md", "FULL_TEST_MATRIX.txt", "RUFF_SHELLCHECK.txt",
                 "CONTROL7_WORKFLOW_PROOF.txt", "CONTROL7_LOCAL_EQUIVALENT.txt"):
        assert name in attrs, f"{name} conflicted 6/6 and is not covered"
        line = next(l for l in attrs.splitlines() if name in l and not l.startswith("#"))
        # 2026-10-21: docs/INDEX.md is merge=union -- its rows are path|title and the
        # checker is order-insensitive (tests/test_ci_gates_registry_20261021.py).
        want = "merge=union" if name == "docs/INDEX.md" else "merge=regenerate"
        assert want in line, f"{name}: {line!r}"


def test_agents_md_is_deliberately_not_covered():
    """AGENTS.md conflicted 5/6 but its conflicts are REAL CONTENT. Auto-resolving
    a governance document by keeping one side would silently drop a rule."""
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for line in attrs.splitlines():
        if line.strip().startswith("#"):
            continue
        assert not line.startswith("AGENTS.md"), "AGENTS.md must be merged by hand"


def test_regeneration_stages_nothing_and_validates(tmp_path):
    """2026-09-25 redesign: the evidence files no longer embed a per-PR digest and
    docs/INDEX.md no longer commits its fingerprint/counts, so there is nothing to
    rewrite by sed. The script must never `git add -A` (it used to, three times,
    staging unrelated worktree files); it refuses when a new doc is untracked
    (the index is built from `git ls-files`) and names the exact files to add."""
    script = ROOT / "scripts" / "regenerate_generated_files.sh"
    assert script.is_file() and os.access(script, os.X_OK)
    body = script.read_text(encoding="utf-8")
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "git add -A" not in code and "git add ." not in code
    assert "--others --exclude-standard" in code, "must detect untracked docs before writing the index"
    assert "write-index" in code
    assert "validate_in_repo_evidence" in code
    assert "control_surface_digest" not in code, "no digest is rewritten any more"


def test_the_driver_never_repairs_by_deleting():
    src = (ROOT / "scripts" / "git_merge_regenerate.sh").read_text(encoding="utf-8")
    for banned in ("rm -", "git checkout --theirs", "git reset --hard"):
        assert banned not in src, f"merge driver must not {banned!r}"


# Proposal only: no active gate, policy, hook or train behavior changes here.
def _projection_module():
    import importlib.util

    path = ROOT / "docs/ops/packets/doc-index-pr-flow-20261024/project_index.py"
    spec = importlib.util.spec_from_file_location("proposed_docs_index_projection", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def projection_repo(tmp_path):
    r = tmp_path / "projection"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "scripts").mkdir()
    (r / "scripts/report_docs_inventory.py").write_bytes((ROOT / "scripts/report_docs_inventory.py").read_bytes())
    (r / "docs").mkdir()
    # Explicit text merge: this proof must not depend on union being honored.
    (r / ".gitattributes").write_text("docs/INDEX.md merge=text\n")
    (r / "docs/a.md").write_text("# Alpha\nStatus: ACTIVE\n")
    (r / "docs/z.md").write_text("# Zed\n")  # existing header debt stays measured
    mod = _projection_module()
    gen = mod.generator(r)
    entries = [
        {"path": "docs/a.md", "filename": "a.md", "ext": ".md", "title": "Alpha"},
        {"path": "docs/z.md", "filename": "z.md", "ext": ".md", "title": "Zed"},
    ]
    (r / "docs/INDEX.md").write_text(gen.render_index_md(entries, {}))
    _git("add", ".gitattributes", "scripts", "docs", cwd=r)
    _git("commit", "-qm", "base", cwd=r)
    base = _git("rev-parse", "HEAD", cwd=r).stdout.strip()
    return r, mod, base


def _add_projection_doc(r, filename="m1.md", title="Em one"):
    (r / "docs" / filename).write_text(f"# {title}\nStatus: PROPOSED\n")
    _git("add", "docs/" + filename, cwd=r)
    _git("commit", "-qm", "add source doc only", cwd=r)
    return _git("rev-parse", "HEAD", cwd=r).stdout.strip()


def test_proposed_source_only_siblings_merge_and_batch_index_covers_both(projection_repo):
    r, mod, base = projection_repo
    before = (r / "docs/INDEX.md").read_bytes()
    for branch, name in (("pr1", "m1.md"), ("pr2", "m2.md")):
        _git("checkout", "-qb", branch, base, cwd=r)
        head = _add_projection_doc(r, name, branch)
        text, receipt = mod.build_projection(r, base, head)
        assert receipt["markdown_total"] == 3
        assert receipt["missing_header"] == 1
        assert receipt["committed_index_current"] is False
        assert (r / "docs/INDEX.md").read_bytes() == before
        mod.validate_projection(r, receipt, text)
    _git("checkout", "-q", "pr1", cwd=r)
    assert _git("merge", "--no-edit", "pr2", cwd=r).returncode == 0
    head = _git("rev-parse", "HEAD", cwd=r).stdout.strip()
    text, receipt = mod.build_projection(r, base, head)
    assert receipt["markdown_total"] == 4
    assert all(f"`docs/{n}.md`" in text for n in ("a", "m1", "m2", "z"))
    assert not _git("status", "--porcelain", cwd=r).stdout
    # Coordinator-only future batch step, demonstrated solely in this toy repo.
    (r / "docs/INDEX.md").write_text(text)
    checked = subprocess.run([sys.executable, "scripts/report_docs_inventory.py", "--check-index"],
                             cwd=r, capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_index_editing_siblings_conflict_under_plain_text_merge(projection_repo):
    r, mod, base = projection_repo
    for branch, name in (("pr1", "m1.md"), ("pr2", "m2.md")):
        _git("checkout", "-qb", branch, base, cwd=r)
        head = _add_projection_doc(r, name, branch)
        inventory, _ = mod.snapshot(r, head, mod.generator(r))
        (r / "docs/INDEX.md").write_text(mod.generator(r).render_index_md(inventory, {}))
        _git("add", "docs/INDEX.md", cwd=r)
        _git("commit", "-qm", "per-PR index", cwd=r)
    _git("checkout", "-q", "pr1", cwd=r)
    merged = _git("merge", "--no-edit", "pr2", cwd=r, check=False)
    assert merged.returncode != 0
    assert "docs/INDEX.md" in _git("diff", "--name-only", "--diff-filter=U", cwd=r).stdout


@pytest.mark.parametrize("mutation", [
    lambda t: t.replace("| `docs/a.md` | Alpha |\n", ""),
    lambda t: t + "| `docs/gone.md` | Gone |\n",
    lambda t: t.replace("| Alpha |", "| Wrong |"),
    lambda t: t + "| `docs/a.md` | Alpha |\n",
    lambda t: t + "junk\n",
    lambda t: t.replace("# Docs Index", "# Wrong preamble"),
])
def test_proposed_projection_rejects_invalid_baseline_and_tampered_artifact(projection_repo, mutation):
    r, mod, base = projection_repo
    head = _add_projection_doc(r)
    text, receipt = mod.build_projection(r, base, head)
    with pytest.raises(mod.ProjectionRefused, match="identity/content"):
        mod.validate_projection(r, receipt, mutation(text))
    _git("checkout", "-qb", "invalid-baseline", base, cwd=r)
    index = r / "docs/INDEX.md"
    index.write_text(mutation(index.read_text()))
    _git("add", "docs/INDEX.md", cwd=r)
    _git("commit", "-qm", "invalid baseline control", cwd=r)
    invalid = _git("rev-parse", "HEAD", cwd=r).stdout.strip()
    head = _add_projection_doc(r)
    with pytest.raises(mod.ProjectionRefused, match="invalid base index"):
        mod.build_projection(r, invalid, head)


@pytest.mark.parametrize("field,value", [
    ("head_tree", "0" * 40), ("index_sha256", "0" * 64),
    ("markdown_total", 0), ("missing_header", 0), ("source_digest", "0" * 64),
    ("rollout", "ACTIVE"), ("authority", "RELEASE_ALLOWED"),
])
def test_proposed_receipt_never_authorizes_or_hides_identity_drift(projection_repo, field, value):
    r, mod, base = projection_repo
    head = _add_projection_doc(r)
    text, receipt = mod.build_projection(r, base, head)
    receipt[field] = value
    with pytest.raises(mod.ProjectionRefused, match="identity/content"):
        mod.validate_projection(r, receipt, text)


def test_proposed_projection_rejects_wrong_head_and_nonancestor(projection_repo):
    r, mod, base = projection_repo
    head = _add_projection_doc(r)
    with pytest.raises(mod.ProjectionRefused, match="head identity"):
        mod.build_projection(r, base, base)
    with pytest.raises(mod.ProjectionRefused, match="full base/head"):
        mod.build_projection(r, base[:12], head)
    _git("checkout", "-qb", "sibling", base, cwd=r)
    sibling = _add_projection_doc(r, "sibling.md")
    with pytest.raises(mod.ProjectionRefused, match="git read failed"):
        mod.build_projection(r, head, sibling)


@pytest.mark.parametrize("boundary", ["tracked-dirty", "untracked-doc", "index-edit", "symlink"])
def test_proposed_projection_fails_closed_at_source_boundaries(projection_repo, boundary):
    r, mod, base = projection_repo
    head = _add_projection_doc(r)
    if boundary == "tracked-dirty":
        (r / "docs/a.md").write_text("# Uncommitted\n")
    elif boundary == "untracked-doc":
        (r / "docs/not-staged.md").write_text("# Invisible doc\n")
    elif boundary == "index-edit":
        index = r / "docs/INDEX.md"
        index.write_text(index.read_text() + "\n")
        _git("add", "docs/INDEX.md", cwd=r)
        _git("commit", "-qm", "index edit", cwd=r)
        head = _git("rev-parse", "HEAD", cwd=r).stdout.strip()
    else:
        (r / "docs/linked.md").symlink_to("a.md")
        _git("add", "docs/linked.md", cwd=r)
        _git("commit", "-qm", "symlink control", cwd=r)
        head = _git("rev-parse", "HEAD", cwd=r).stdout.strip()
    with pytest.raises(mod.ProjectionRefused):
        mod.build_projection(r, base, head)


def test_proposed_projection_cli_only_emits_outside_clean_checkout(projection_repo, tmp_path):
    r, _mod, base = projection_repo
    head = _add_projection_doc(r)
    script = ROOT / "docs/ops/packets/doc-index-pr-flow-20261024/project_index.py"
    args = [sys.executable, str(script), "--root", str(r), "--base", base, "--head", head, "--out"]
    out = tmp_path / "artifact"
    run = subprocess.run([*args, str(out)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (out / "INDEX.md").is_file() and (out / "receipt.json").is_file()
    assert not _git("status", "--porcelain", cwd=r).stdout
    refused = subprocess.run([*args, str(r / "artifact")], capture_output=True, text=True, timeout=60)
    assert refused.returncode == 2
    assert "output must be outside" in refused.stdout
    assert not (r / "artifact").exists()
