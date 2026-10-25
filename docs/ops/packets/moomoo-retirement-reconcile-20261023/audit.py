#!/usr/bin/env python3
"""Regenerate static reference inventory; emits names/lines/roles, never account values."""

from __future__ import annotations

import ast
import csv
import io
import json
import subprocess
from pathlib import Path


BASE_SHA = "8ed8a246486317950df01f2a1846825627f369eb"


def inventory(root):
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE_SHA], cwd=root, text=True).splitlines()
    rows = set()
    parse_failures = []
    for filename in files:
        path = Path(root) / filename
        if path.suffix not in {".py", ".js", ".ts", ".tsx"}:
            continue
        text = path.read_text(errors="replace")
        if "account_summaries" not in text and "moomoo_taxable_live" not in text:
            continue
        scope = (
            "test"
            if filename.startswith("tests/") or ".test." in filename
            else "legacy_v2"
            if "command-center-v2/" in filename
            else "source"
        )
        if path.suffix != ".py":
            for line, content in enumerate(text.splitlines(), 1):
                if "account_summaries" in content:
                    rows.add((filename, line, scope, "summary_reference_needs_context", "account_summaries"))
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            parse_failures.append(filename)
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                key = node.args[0].value
                if (
                    key == "account_summaries"
                    or filename == "scripts/lib/data_broker/broker_access.py"
                    and key in {"retired", "retired_reason"}
                ):
                    role = "summary_container_read" if key == "account_summaries" else "retirement_metadata_read"
                    rows.add((filename, node.lineno, scope, role, key))
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "account_summaries"
            ):
                role = "summary_container_assignment" if isinstance(node.ctx, ast.Store) else "summary_container_read"
                rows.add((filename, node.lineno, scope, role, "account_summaries"))
            elif isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == "account_summaries":
                        rows.add((filename, key.lineno, scope, "summary_container_construction", key.value))
    return sorted(rows), parse_failures


def guard_sites(root):
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE_SHA], cwd=root, text=True).splitlines()
    rows = []
    for filename in files:
        if not filename.startswith("scripts/") or not filename.endswith(".py"):
            continue
        text = (Path(root) / filename).read_text(errors="replace")
        if "protected_holdings_write" not in text:
            continue
        tree = ast.parse(text)
        aliases = {"protected_holdings_write"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                aliases.update(
                    name.asname or name.name for name in node.names if name.name == "protected_holdings_write"
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in aliases:
                rows.append((filename, node.lineno, node.func.id, "guard_call_site_not_runtime_proof"))
    return sorted(rows)


def main():
    root = Path(__file__).resolve().parents[4]
    rows, failures = inventory(root)
    if failures:
        raise ValueError("unparsed sources: " + ", ".join(failures))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("path", "line", "scope", "role", "field"))
    writer.writerows(rows)
    Path(__file__).with_name("static-references.csv").write_text(out.getvalue())
    sites = guard_sites(root)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("path", "line", "entry", "role"))
    writer.writerows(sites)
    Path(__file__).with_name("guard-writer-sites.csv").write_text(out.getvalue())
    print(
        json.dumps(
            {
                "references": len(rows),
                "files": len({row[0] for row in rows}),
                "parse_failures": failures,
                "guard_sites": len(sites),
                "guard_files": len({row[0] for row in sites}),
            }
        )
    )


if __name__ == "__main__":
    main()
