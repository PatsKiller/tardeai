"""CI de-conflict (operator-approved process plan 2026-10-21): gates are one file per gate, and
docs/INDEX.md is checked by presence and title.

* config/ci_gates/<name>.json is the gate registry; run_cio_hardening_ci.GATES loads it sorted by
  name and holds no inline list; every file is a valid CiGate@v1 record.
* scripts/ci_gates_migrate.py: dry run writes nothing; --apply moves inline entries (comments
  and ANCHOR ids kept) and rewrites the runner; a re-run is a no-op; a differing existing file is
  a conflict unless --overwrite.
* report_docs_inventory index check: missing / stale / mistitled / duplicated rows and junk
  lines fail; row order does not.
* the self-heal diff guard admits ADDING one valid gate file and refuses changing one.
* two branches that each add a gate and a doc merge with no conflict (git, tmp repo).

Hermetic: tmp roots and a tmp git repo; reads the committed registry read-only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import ci_gates  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load("ci_gates_migrate_t", "scripts/ci_gates_migrate.py")
INV = _load("report_docs_inventory_t", "scripts/report_docs_inventory.py")


def _git(*args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check, timeout=60)


# ── the committed registry ─────────────────────────────────────────────────────────────


def test_runner_gates_come_from_the_registry_sorted_by_name():
    runner = _load("run_cio_hardening_ci_t", "scripts/run_cio_hardening_ci.py")
    loaded = ci_gates.load_gates(ROOT)
    assert runner.GATES == loaded
    names = [n for n, _ in loaded]
    assert names == sorted(names) and len(names) == len(set(names))
    assert len(names) >= 533  # the 2026-10-21 migration moved 533


def test_runner_holds_no_inline_gate_list():
    tree = ast.parse((ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8"))
    node = MIG._gates_assign(tree)
    assert node is not None and not isinstance(node.value, ast.List), "add a config/ci_gates/*.json file instead"


def test_every_gate_file_is_canonical():
    for p in sorted(ci_gates.gates_dir(ROOT).glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        ci_gates.validate(doc, stem=p.stem)
        assert p.read_text(encoding="utf-8") == ci_gates.render(doc), f"{p.name}: not canonical JSON"


def test_this_gate_is_registered():
    assert "tests/test_ci_gates_registry_20261021.py" in ci_gates.registry_text(ROOT)


@pytest.mark.parametrize(
    "doc, why",
    [
        ({"schema": "CiGate@v1", "name": "other", "files": ["tests/test_a.py"]}, "stem"),
        ({"schema": "CiGate@v1", "name": "g", "files": []}, "non-empty"),
        ({"schema": "CiGate@v1", "name": "g", "files": ["tests/test_a.py"], "extra": 1}, "unknown keys"),
        ({"schema": "CiGate@v0", "name": "g", "files": ["tests/test_a.py"]}, "schema"),
        ({"schema": "CiGate@v1", "name": "g", "files": ["t.py", "t.py"]}, "duplicate"),
    ],
)
def test_a_malformed_gate_file_fails_closed(tmp_path, doc, why):
    d = tmp_path / "config" / "ci_gates"
    d.mkdir(parents=True)
    (d / "g.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ci_gates.GateRegistryError, match=why):
        ci_gates.load_gates(tmp_path)


def test_unparseable_or_empty_registry_fails_closed(tmp_path):
    with pytest.raises(ci_gates.GateRegistryError):
        ci_gates.load_gates(tmp_path)  # no directory
    d = tmp_path / "config" / "ci_gates"
    d.mkdir(parents=True)
    with pytest.raises(ci_gates.GateRegistryError):
        ci_gates.load_gates(tmp_path)  # empty
    (d / "g.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ci_gates.GateRegistryError, match="unreadable"):
        ci_gates.load_gates(tmp_path)


# ── the migration script ───────────────────────────────────────────────────────────────

INLINE = '''import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Ordered, explicit suite list (Phase 10.2)
GATES = [
    # ANCHOR: B_GATE_20261021 — first line
    # second line
    ("b_gate", ["tests/test_b.py"]),
    ("a_gate", ["tests/test_a1.py", "tests/test_a0.py"]),  # trailing note
    (
        # inside the tuple
        "c_gate",
        ["tests/test_c.py"],
    ),
]


def main():
    return 0
'''


def _fixture(tmp_path: Path, text: str = INLINE) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_cio_hardening_ci.py").write_text(text, encoding="utf-8")
    return tmp_path


def test_comments_attach_to_their_own_entry():
    _node, entries = MIG.parse_inline(INLINE)
    got = {e["name"]: e["comment"] for e in entries}
    assert got == {
        "b_gate": ["ANCHOR: B_GATE_20261021 — first line", "second line"],
        "a_gate": ["trailing note"],
        "c_gate": ["inside the tuple"],
    }


def test_dry_run_writes_nothing_then_apply_migrates_and_rerun_is_a_noop(tmp_path, capsys):
    root = _fixture(tmp_path)
    assert MIG.migrate(root, apply=False) == 0
    assert not (root / "config").exists()
    assert "DRY RUN" in capsys.readouterr().out

    assert MIG.migrate(root, apply=True) == 0
    assert ci_gates.load_gates(root) == [
        ("a_gate", ["tests/test_a1.py", "tests/test_a0.py"]),  # file order inside a gate kept
        ("b_gate", ["tests/test_b.py"]),
        ("c_gate", ["tests/test_c.py"]),
    ]
    rec = json.loads(ci_gates.gate_path(root, "b_gate").read_text(encoding="utf-8"))
    assert rec["anchor"] == "B_GATE_20261021"
    runner = (root / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "GATES = _ci_gates.load_gates(REPO)" in runner
    assert '("b_gate"' not in runner and "Ordered, explicit suite list" not in runner
    assert "def main():" in runner
    ast.parse(runner)

    before = {p.name: p.read_bytes() for p in ci_gates.gates_dir(root).glob("*.json")}
    assert MIG.migrate(root, apply=True) == 0
    assert "nothing to migrate" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in ci_gates.gates_dir(root).glob("*.json")} == before


def test_rerun_on_a_newer_inline_list_picks_up_new_gates(tmp_path):
    """The pre-merge re-run: main's runner (inline list, now with one more gate) over the
    branch's gate files."""
    root = _fixture(tmp_path)
    assert MIG.migrate(root, apply=True) == 0
    newer = INLINE.replace("]\n\n\ndef main", '    ("d_gate", ["tests/test_d.py"]),\n]\n\n\ndef main')
    (root / "scripts" / "run_cio_hardening_ci.py").write_text(newer, encoding="utf-8")
    assert MIG.migrate(root, apply=True) == 0
    assert [n for n, _ in ci_gates.load_gates(root)] == ["a_gate", "b_gate", "c_gate", "d_gate"]


def test_a_differing_existing_gate_file_is_a_conflict_unless_overwrite(tmp_path):
    root = _fixture(tmp_path)
    assert MIG.migrate(root, apply=True) == 0
    changed = INLINE.replace('["tests/test_b.py"]', '["tests/test_b.py", "tests/test_b2.py"]')
    (root / "scripts" / "run_cio_hardening_ci.py").write_text(changed, encoding="utf-8")
    assert MIG.migrate(root, apply=True) == 1
    assert dict(ci_gates.load_gates(root))["b_gate"] == ["tests/test_b.py"]  # nothing written
    assert MIG.migrate(root, apply=True, overwrite=True) == 0
    assert dict(ci_gates.load_gates(root))["b_gate"] == ["tests/test_b.py", "tests/test_b2.py"]


def test_a_non_literal_entry_is_refused(tmp_path):
    root = _fixture(tmp_path, INLINE.replace('        "c_gate",', '        NAME + "c",'))
    with pytest.raises(SystemExit):
        MIG.migrate(root, apply=False)


# ── docs/INDEX.md: presence and title ──────────────────────────────────────────────────


def _inv(*docs):
    return [{"path": p, "filename": p.rsplit("/", 1)[-1], "ext": ".md", "title": t} for p, t in docs]


DOCS = _inv(("docs/a.md", "Alpha"), ("docs/b.md", "Beta"), ("docs/c.md", "Gamma"))


def test_index_check_passes_on_render_and_ignores_row_order():
    text = INV.render_index_md(DOCS, {})
    assert INV.index_problems(text, DOCS) == ([], True)
    lines = text.splitlines()
    i = lines.index("| `docs/a.md` | Alpha |")
    lines[i], lines[i + 2] = lines[i + 2], lines[i]
    assert INV.index_problems("\n".join(lines) + "\n", DOCS) == ([], False)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda t: t.replace("| `docs/b.md` | Beta |\n", ""), "missing row: docs/b.md"),
        (lambda t: t + "| `docs/gone.md` | Gone |\n", "stale row: docs/gone.md"),
        (lambda t: t.replace("| Beta |", "| Bet |"), "title differs: docs/b.md"),
        (lambda t: t + "| `docs/b.md` | Beta |\n", "duplicate row for docs/b.md"),
        (lambda t: t + "\n<!-- drift probe -->\n", "not an index row"),
        (lambda t: t.replace("# Docs Index", "# Docs Idx"), "preamble differs"),
    ],
)
def test_index_check_fails_on_a_real_gap(mutate, needle):
    problems, _ordered = INV.index_problems(mutate(INV.render_index_md(DOCS, {})), DOCS)
    assert any(needle in p for p in problems), problems


def test_index_rows_carry_no_content_hash():
    text = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    assert "| Path | Title |" in text and "sha12" not in text


# ── self-heal fixer guard: add-only registration ───────────────────────────────────────


def _guard(name_status, numstat, unified):
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib import self_heal_fixer as F

    cfg = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text(encoding="utf-8"))
    return {r["code"] for r in F.guard_diff(
        name_status=name_status, numstat=numstat, unified=unified, base_ci_text="GATES = _x\n", cfg=cfg)}


def _added_file_diff(path: str, body: str) -> str:
    lines = body.splitlines()
    return (f"diff --git a/{path} b/{path}\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
            + "".join(f"+{s}\n" for s in lines))


def test_self_heal_may_add_one_valid_gate_file_and_never_change_one():
    gate = "config/ci_gates/self_heal_lane_x.json"
    body = ci_gates.render(ci_gates.make_record("self_heal_lane_x", ["tests/test_self_heal_lane_x.py"], ["why"]))
    test_body = "def test_x():\n    assert True\n"
    u = _added_file_diff(gate, body) + _added_file_diff("tests/test_self_heal_lane_x.py", test_body)
    ns = f"A\t{gate}\nA\ttests/test_self_heal_lane_x.py\n"
    st = f"{len(body.splitlines())}\t0\t{gate}\n2\t0\ttests/test_self_heal_lane_x.py\n"
    codes = _guard(ns, st, u)
    assert not {c for c in codes if c.startswith(("append_only", "protected_path"))}, codes

    bad = body.replace('"self_heal_lane_x"', '"other_name"', 1)
    codes = _guard(ns, st, _added_file_diff(gate, bad))
    assert "append_only:invalid_gate_file" in codes

    m_ns = "M\tconfig/ci_gates/alarm_fires.json\n"
    codes = _guard(m_ns, "1\t1\tconfig/ci_gates/alarm_fires.json\n", "")
    assert {"append_only:gate_file_changed", "protected_path"} <= codes


# ── the point of it all: parallel PRs merge cleanly ────────────────────────────────────


def test_two_branches_each_adding_a_gate_and_a_doc_merge_without_conflict(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / ".gitattributes").write_text("docs/INDEX.md merge=union\n", encoding="utf-8")
    base = _inv(("docs/a.md", "Alpha"), ("docs/z.md", "Zed"))
    (r / "docs").mkdir()
    (r / "docs" / "INDEX.md").write_text(INV.render_index_md(base, {}), encoding="utf-8")
    d = r / "config" / "ci_gates"
    d.mkdir(parents=True)
    (d / "base_gate.json").write_text(ci_gates.render(ci_gates.make_record("base_gate", ["tests/test_0.py"])))
    _git("add", "-A", cwd=r)
    _git("commit", "-qm", "base", cwd=r)

    def branch(name, doc, title, gate):
        _git("checkout", "-qb", name, "main", cwd=r)
        inv = base + _inv((doc, title))
        (r / "docs" / "INDEX.md").write_text(INV.render_index_md(inv, {}), encoding="utf-8")
        (d / f"{gate}.json").write_text(ci_gates.render(ci_gates.make_record(gate, [f"tests/test_{gate}.py"])))
        _git("add", "-A", cwd=r)
        _git("commit", "-qm", name, cwd=r)

    # adjacent rows in the same gap of the sorted table: the worst case for a line merge
    branch("pr1", "docs/m1.md", "Em one", "gate_one")
    branch("pr2", "docs/m2.md", "Em two", "gate_two")
    _git("checkout", "-q", "pr1", cwd=r)
    m = _git("merge", "--no-edit", "pr2", cwd=r, check=False)
    assert m.returncode == 0, m.stdout + m.stderr
    assert _git("diff", "--name-only", "--diff-filter=U", cwd=r).stdout == ""
    assert [n for n, _ in ci_gates.load_gates(r)] == ["base_gate", "gate_one", "gate_two"]
    merged = base + _inv(("docs/m1.md", "Em one"), ("docs/m2.md", "Em two"))
    problems, _ordered = INV.index_problems((r / "docs" / "INDEX.md").read_text(encoding="utf-8"), merged)
    assert problems == []
