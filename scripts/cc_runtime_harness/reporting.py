"""Machine-readable JSON/JUnit + concise Markdown reports."""

from __future__ import annotations

import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .safety import redact_secrets


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=False, default=str)
    text = redact_secrets(text)
    path.write_text(text + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_secrets(text), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return hashlib.sha256(b"").hexdigest()
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: redact_secrets(str(v) if v is not None else "") for k, v in r.items()})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_junit(path: Path, suite_name: str, cases: list[dict[str, Any]]) -> str:
    """cases: {name, classname, time, status=pass|fail|error, message?}"""
    suite = ET.Element("testsuite", name=suite_name, tests=str(len(cases)))
    failures = 0
    errors = 0
    for c in cases:
        tc = ET.SubElement(
            suite,
            "testcase",
            classname=c.get("classname", "cc_runtime_harness"),
            name=c["name"],
            time=str(c.get("time", 0)),
        )
        st = c.get("status", "pass")
        if st == "fail":
            failures += 1
            fail = ET.SubElement(tc, "failure", message=redact_secrets(c.get("message", "fail")))
            fail.text = redact_secrets(c.get("detail", ""))
        elif st == "error":
            errors += 1
            err = ET.SubElement(tc, "error", message=redact_secrets(c.get("message", "error")))
            err.text = redact_secrets(c.get("detail", ""))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    tree = ET.ElementTree(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
