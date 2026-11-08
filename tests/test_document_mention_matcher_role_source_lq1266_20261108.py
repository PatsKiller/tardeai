"""ANCHOR: DOCUMENT_MENTION_ROLE_SOURCE_LQ1266_20261108 — LQ-20261107-1266: every role_source the code
can emit is one the DDL's CHECK accepts.

The allowed set is PARSED from sql/document_mentions.sql on every run, never restated here. The
constraint is the only authority on which values may be written; a copy of it in this file would
agree with the DDL today and drift from it silently later, which is the class of defect this gate
exists for -- the writer invented 'document_mention_matcher', the constraint was right, and every
insert since the fold raised CheckViolation.

Two halves, because there are two ways a value reaches a row:
  * the static scan reads every role_source write in scripts/ (dict key, subscript assignment,
    keyword argument) and resolves it through module constants. A write it cannot read fails the
    test instead of passing unexamined; a function-parameter pass-through is named explicitly in
    PASS_THROUGH, and every call site that feeds it is checked too.
  * the runtime half drives the public producers on synthetic text and asserts what they emit.

Synthetic issuers only (ZZQ*). No database, no network, no credential read.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import document_mention_matcher as MM  # noqa: E402

DDL = ROOT / "sql" / "document_mentions.sql"
SCRIPTS = ROOT / "scripts"
PRODUCERS = {"scripts/lib/document_mention_matcher.py", "scripts/lib/document_mentions.py"}

#: The only place a role_source value is written through a function parameter instead of a literal or
#: a module constant. Every caller of that function is checked by
#: test_every_row_builder_call_passes_an_allowed_value; a new pass-through must be added here and
#: decided, never waved through.
PASS_THROUGH = {
    ("scripts/lib/document_mentions.py", "_row", "role_source"),
}

ROLE_SOURCE_CHECK = re.compile(
    r"role_source\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*role_source\s+IN\s*\((?P<values>[^)]*)\)", re.S)


# ── the allowed set: parsed from the DDL, never copied ───────────────────────────────────────────────────────────


def allowed_role_sources(sql_text: str) -> frozenset[str]:
    """The values `document_mentions.role_source` accepts, read out of its CHECK constraint."""
    match = ROLE_SOURCE_CHECK.search(sql_text)
    assert match, "sql/document_mentions.sql no longer states a role_source IN (...) CHECK"
    values = frozenset(re.findall(r"'([^']*)'", match.group("values")))
    assert values, "the role_source CHECK parsed to an empty set: refusing to call that an allow-list"
    return values


def test_the_parser_reads_the_constraint_instead_of_assuming_one():
    """Canary: a CHECK with other values parses to those values (so the parser is not a constant)."""
    ddl = ("CREATE TABLE t (role_source TEXT NOT NULL CHECK "
           "(role_source IN ('alpha','beta')))")
    assert allowed_role_sources(ddl) == {"alpha", "beta"}


def test_the_ddl_states_the_constraint():
    allowed = allowed_role_sources(DDL.read_text(encoding="utf-8"))
    assert allowed, "empty allowed set"


# ── static scan: every role_source write under scripts/ ──────────────────────────────────────────────────────────


def _module_constants(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                if isinstance(target, ast.Name):
                    out[target.id] = value.value
    return out


def _role_source_sites(tree: ast.Module):
    """(owner, params, kind, node) for every place a row's role_source value is written."""
    sites: list[tuple[str, frozenset[str], str, ast.AST]] = []

    def walk(node: ast.AST, owner: str, params: frozenset[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            every = (*getattr(node.args, "posonlyargs", ()), *node.args.args, *node.args.kwonlyargs)
            owner, params = node.name, frozenset(a.arg for a in every)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "role_source":
                    sites.append((owner, params, "dict", value))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "role_source"):
                    sites.append((owner, params, "subscript", node.value))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "role_source":
                    sites.append((owner, params, "keyword", keyword.value))
        for child in ast.iter_child_nodes(node):
            walk(child, owner, params)

    walk(tree, "", frozenset())
    return sites


def _resolved(node: ast.AST, consts: dict[str, str]) -> tuple[set[str], bool]:
    """(string values, unreadable) for one write site. None contributes no value and is readable."""
    if isinstance(node, ast.Constant) and node.value is None:
        return set(), False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}, False
    if isinstance(node, ast.Name) and node.id in consts:
        return {consts[node.id]}, False
    if isinstance(node, ast.IfExp):
        left, left_bad = _resolved(node.body, consts)
        right, right_bad = _resolved(node.orelse, consts)
        return left | right, left_bad or right_bad
    return set(), True


def scan_writes(root: Path):
    """(emitted per file, unreadable sites, files inspected) over every .py under root."""
    emitted: dict[str, set[str]] = {}
    unreadable: list[tuple[str, str, str | None]] = []
    inspected: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "role_source" not in text:
            continue
        rel = path.relative_to(root.parent).as_posix()
        inspected.add(rel)
        tree = ast.parse(text, filename=rel)
        consts = _module_constants(tree)
        for owner, params, kind, node in _role_source_sites(tree):
            values, bad = _resolved(node, consts)
            if bad:
                name = node.id if isinstance(node, ast.Name) else None
                unreadable.append((rel, owner, name if name in params else None))
                continue
            emitted.setdefault(rel, set()).update(values)
    return emitted, unreadable, inspected


def test_every_role_source_write_in_scripts_is_statically_readable():
    _emitted, unreadable, _inspected = scan_writes(SCRIPTS)
    unknown = [site for site in unreadable if site[2] is None]
    assert not unknown, (
        "a role_source write is not a literal, a module constant or a known pass-through parameter; "
        f"resolve it or decide it here: {unknown}"
    )
    assert {site[:3] for site in unreadable} == PASS_THROUGH


def test_every_role_source_value_the_scripts_can_emit_is_allowed():
    emitted, _unreadable, inspected = scan_writes(SCRIPTS)
    assert PRODUCERS <= inspected, f"the scan missed a producer file: {sorted(PRODUCERS - inspected)}"
    assert emitted, "the scan found no role_source writes at all: the gate would pass vacuously"
    allowed = allowed_role_sources(DDL.read_text(encoding="utf-8"))
    bad = {path: sorted(values - allowed) for path, values in emitted.items() if values - allowed}
    assert not bad, f"role_source values outside the DDL CHECK {sorted(allowed)}: {bad}"
    assert MM.ROLE_SOURCE in allowed


def test_the_scan_fails_closed_on_a_write_it_cannot_read(tmp_path):
    """A value computed at runtime is not waved through: it fails until someone decides it here."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "producer.py").write_text(
        'def rows(x):\n'
        '    return [{"role_source": pick(x)}]\n', encoding="utf-8")

    emitted, unreadable, inspected = scan_writes(pkg)

    assert inspected == {"pkg/producer.py"}
    assert emitted == {}
    assert unreadable == [("pkg/producer.py", "rows", None)]


def _row_builder_calls(root: Path):
    """Calls to the pass-through helper, in the modules that hold it.

    `_row` is a module-private name and other modules (desks_a, alert_quotes, ...) have their own,
    unrelated `_row`; only the files named in PASS_THROUGH are this helper's call sites.
    """
    calls = []
    holders = {root.parent / rel for rel, _owner, _param in PASS_THROUGH}
    for path in sorted(holders):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root.parent).as_posix()
        tree = ast.parse(text, filename=rel)
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "_row" or len(node.args) < 3:
                continue
            values, bad = _resolved(node.args[2], consts)
            calls.append((rel, node.lineno, values, bad))
    return calls


def test_every_row_builder_call_passes_an_allowed_value():
    """The pass-through is only as safe as its call sites: each one must pass a known allowed value."""
    allowed = allowed_role_sources(DDL.read_text(encoding="utf-8"))
    calls = _row_builder_calls(SCRIPTS)
    assert calls, "no _row(...) call sites found: the pass-through check would pass vacuously"
    unreadable = [(rel, line) for rel, line, _values, bad in calls if bad]
    assert not unreadable, f"_row() call sites pass a value this test cannot read: {unreadable}"
    bad = [(rel, line, sorted(values - allowed))
           for rel, line, values, _bad in calls if values - allowed]
    assert not bad, f"_row() is called with a role_source outside the DDL CHECK: {bad}"


# ── runtime: what the producers actually emit ────────────────────────────────────────────────────────────────────

NAMES = {"ZZQA": ["Quasar Rocket Works"], "ZZQB": ["Orbital Metal Works"], "ZZQN": ["Northwind"]}


def _assert_allowed(rows, allowed):
    for row in rows:
        if row.get("role"):
            assert row["role_source"] is not None, row
            assert row["role_source"] in allowed, row
        else:
            # An undecided row must carry no source: persist() skips it, and a source on a None role
            # would let a row with no decision reach the table.
            assert row["role_source"] is None, row


def test_the_matcher_emits_only_allowed_role_sources_where_it_decides():
    allowed = allowed_role_sources(DDL.read_text(encoding="utf-8"))

    single = MM.match_mentions("Quasar Rocket Works wins a synthetic contract",
                               names=NAMES, own_symbol="ZZQA")
    assert [row["role"] for row in single] == ["subject"]
    _assert_allowed(single, allowed)

    multi = MM.match_mentions("Orbital Metal Works comments on Quasar Rocket Works guidance",
                              names=NAMES, own_symbol="ZZQB")
    assert sorted(row["role"] for row in multi) == ["mentioned", "subject"]
    _assert_allowed(multi, allowed)

    undecided = MM.match_mentions("Orbital Metal Works comments on Quasar Rocket Works guidance",
                                  names=NAMES, own_symbol=None)
    assert undecided and all(row["role"] is None for row in undecided)
    _assert_allowed(undecided, allowed)

    anchored = MM.match_mentions("Northwind (ZZQN) wins a synthetic award", names=NAMES, own_symbol="ZZQN")
    assert [row["role"] for row in anchored] == ["subject"]
    _assert_allowed(anchored, allowed)


def test_deterministic_rows_carry_no_confidence():
    """The DDL's contract, ruled on in LQ-20261107-1275: role_confidence is NULL when deterministic.

    The matcher's agreement is exact token equality, not a probability -- it either holds or the row is
    not emitted -- and the legacy extractor already writes NULL, so a 1.0 here marks nothing and
    contradicts the column's own comment.
    """
    single = MM.match_mentions("Quasar Rocket Works wins a synthetic contract",
                               names=NAMES, own_symbol="ZZQA")
    multi = MM.match_mentions("Orbital Metal Works comments on Quasar Rocket Works guidance",
                              names=NAMES, own_symbol="ZZQB")
    anchored = MM.match_mentions("Northwind (ZZQN) wins a synthetic award", names=NAMES, own_symbol="ZZQN")
    rows = [*single, *multi, *anchored]

    assert rows and all(row["role"] for row in rows)
    assert all(row["role_source"] == MM.ROLE_SOURCE for row in rows)
    assert all(row["role_confidence"] is None for row in rows)


def test_the_legacy_extractor_emits_only_allowed_role_sources(monkeypatch):
    from lib import document_mentions as DM
    from lib import inbound_identity_tagger as T

    resolved = [
        {"symbol": "ZZQA", "subject_guid": None, "issuer_guid": None, "identity_status": "CONFIRMED",
         "matched_via": "company_name", "matched_text": "Quasar Rocket Works"},
        {"symbol": "ZZQB", "subject_guid": None, "issuer_guid": None, "identity_status": "CONFIRMED",
         "matched_via": "company_name", "matched_text": "Orbital Metal Works"},
    ]
    monkeypatch.setattr(T, "tag_inbound", lambda text, registry=None: {"resolved": list(resolved)})
    allowed = allowed_role_sources(DDL.read_text(encoding="utf-8"))

    single = DM.extract("Quasar Rocket Works wins a synthetic contract", own_symbol="ZZQA", registry={})
    assert [row["role"] for row in single] == ["subject"]
    _assert_allowed(single, allowed)

    multi = DM.extract("Quasar Rocket Works and Orbital Metal Works both issued guidance",
                       own_symbol="ZZQB", registry={})
    assert sorted(row["role"] for row in multi) == ["mentioned", "subject"]
    _assert_allowed(multi, allowed)

    undecided = DM.extract("Quasar Rocket Works and Orbital Metal Works both issued guidance",
                           own_symbol=None, registry={})
    assert undecided and all(row["role"] is None for row in undecided)
    _assert_allowed(undecided, allowed)


def test_subject_from_symbol_emits_only_allowed_role_sources(monkeypatch):
    from lib import research_identity as RI

    monkeypatch.setattr(RI, "resolve", lambda doc, symbol: {
        "symbol": "ZZQA", "subject_guid": None, "issuer_guid": None, "identity_status": "CONFIRMED"})
    from lib import document_mentions as DM

    rows = DM.subject_from_symbol("ZZQA", registry={})
    assert [row["role"] for row in rows] == ["subject"]
    _assert_allowed(rows, allowed_role_sources(DDL.read_text(encoding="utf-8")))


def test_the_lane_receipt_records_which_matcher_produced_the_rows(monkeypatch):
    """role_source names the decision authority; the run receipt names the ruleset (provenance)."""
    import backfill_document_mentions as B

    seen: dict = {}

    class Receipt:
        @staticmethod
        def now_iso() -> str:
            return "2026-11-08T00:00:00+00:00"

        @staticmethod
        def write_lane_receipt(lane, **kwargs) -> None:
            seen.clear()
            seen.update(kwargs)

    monkeypatch.setattr(B, "_receipt_lib", lambda: Receipt)
    monkeypatch.setattr(B, "_run", lambda a, targets, stats: 0)

    assert B.main(["--table", "news_articles"]) == 0
    assert seen["summary"]["matcher"] == "rebuild"
    assert B.main(["--table", "news_articles", "--legacy-matcher"]) == 0
    assert seen["summary"]["matcher"] == "legacy"
