"""2026-09-15: a bare % inside parameterized SQL crashes psycopg2 (IndexError: tuple index out of range).

#1031 added a SQL comment saying 'moved 21%' inside price_excursions; the detector then failed every
30-minute run from 12:30 ET and no material-change notice went out. The unit tests mocked the cursor,
so the SQL itself was never formatted. This formats every execute() string the way psycopg2 does.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "material_change_detector.py").read_text()


def _parameterized_sql():
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "execute"
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            yield node.lineno, node.args[0].value


def test_every_parameterized_query_has_only_placeholders_or_escaped_percents():
    offenders = []
    for lineno, sql in _parameterized_sql():
        for m in re.finditer(r"%(?![s%])", sql):
            offenders.append(f"line {lineno}: ...{sql[max(0, m.start() - 25):m.start() + 5]!r}")
    assert not offenders, "bare % in parameterized SQL:\n" + "\n".join(offenders)


def test_placeholder_count_matches_what_psycopg2_will_format():
    for lineno, sql in _parameterized_sql():
        # Python %-formatting is what psycopg2 applies; a bare % would raise here too.
        n = len(re.findall(r"%s", sql))
        sql % tuple(["x"] * n)
