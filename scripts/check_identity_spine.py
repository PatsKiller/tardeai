#!/usr/bin/env python3
"""Report where one question still has several identities. Read-only.

REPORTS, NEVER FAILS. Exit code is 0 whatever it finds, because every finding
below describes id-minting that is LIVE and correct-by-its-own-lights; changing
any of those ids would break the receipts already keyed on them. P1 of the
goal-loop plan deliberately changes no id and adds no sixth scheme -- it
registers the existing ids on the existing subject spine
(`scripts/lib/cio_identity_spine.py`). This lint says what remains true anyway,
so the next phase argues from measurements rather than from memory.

WHAT IT MEASURES
----------------

1. `GAP_PREFIX_COLLISION` -- two modules mint a uuid5 over a `tradeai:gap:`
   prefix with DIFFERENT tuples:

       scripts/lib/research_gap.py   tradeai:gap:{security_guid}|{reason}|{question}
       scripts/lib/gap_resolver.py   tradeai:gap:{domain}|{subject}|{question}

   Same namespace, same prefix, same intent -- so the two look interchangeable
   and are not. One logical gap minted on both paths gets two UUIDs, and
   neither store can tell that they are the same gap. This is demonstrated
   below by minting both for one gap and printing the two guids, not asserted.

2. `QUESTION_GUID_INCOMPATIBLE` -- two functions named `question_guid` take
   argument tuples that cannot be substituted for one another, and mint in
   different namespaces:

       scripts/lib/research_circle.py       (chat_id, message_id, text)  QUESTION_NAMESPACE
       scripts/due_diligence_questions.py   (subject_guid, change_guid, text)  NAMESPACE_URL

   An operator's question and the diligence question raised by a change about
   the same company therefore share nothing -- not a value, not a namespace,
   not even a callable signature.

3. `SPINE_COVERAGE` -- rows per `source_table` in `narrative_subjects`, and
   which of the six schemes P1 registers have not landed yet. Skipped, not
   guessed, when there is no database.

USAGE
-----
    python3 scripts/check_identity_spine.py
    python3 scripts/check_identity_spine.py --json
"""
from __future__ import annotations

SCHEMA = "IdentitySpineLint@v1"
NO_CONSUMER_REASON = (
    "advisory lint, run by hand or by the operator. Installing a timer for it is a new "
    "scheduled entry and therefore operator-only under AGENTS.md §17; this phase proposes "
    "and stops rather than scheduling itself."
)

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

AUTHORITY = "READ_ONLY_ADVISORY"

GAP_PREFIX = "tradeai:gap:"

#: The two minting sites, found by reading the source rather than by pinning a
#: line number that rots the next time either file is edited.
_GAP_MINTERS = (
    ("scripts/lib/research_gap.py", "security_guid|reason|question"),
    ("scripts/lib/gap_resolver.py", "domain|subject|question"),
)


def _find_line(rel: str, needle: str) -> int | None:
    """1-based line of the first occurrence of `needle`, or None."""
    path = PROJECT_ROOT / rel
    try:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if needle in line:
                return n
    except OSError:
        return None
    return None


def gap_prefix_collision() -> dict[str, Any]:
    """Mint both ids for ONE gap and show that they differ.

    The evidence is the two guids, not the claim: if a later change ever makes
    the two schemes agree, this finding disappears on its own.
    """
    sites = []
    for rel, tuple_desc in _GAP_MINTERS:
        line = _find_line(rel, GAP_PREFIX)
        sites.append({"module": rel, "line": line, "tuple": tuple_desc,
                      "prefix": GAP_PREFIX})

    # One gap, described the way each store describes it.
    question = "no promoted research for HPE"
    guids: dict[str, str] = {}
    try:
        from scripts.lib.research_gap import gap_id as research_gap_id

        guids["research_gaps"] = research_gap_id(
            security_guid="subject-HPE", reason="hermes_research", question=question)
    except Exception as exc:  # noqa: BLE001
        guids["research_gaps"] = f"UNAVAILABLE: {type(exc).__name__}"
    try:
        from scripts.lib.gap_resolver import DataGap

        guids["gap_resolver_gaps"] = DataGap(
            domain="hermes_research", subject="HPE", question=question).gap_id
    except Exception as exc:  # noqa: BLE001
        guids["gap_resolver_gaps"] = f"UNAVAILABLE: {type(exc).__name__}"

    distinct = len({g for g in guids.values() if not g.startswith("UNAVAILABLE")}) > 1
    return {
        "finding": "GAP_PREFIX_COLLISION",
        "severity": "REPORT_ONLY",
        "collides": distinct,
        "prefix": GAP_PREFIX,
        "sites": sites,
        "same_gap_two_guids": guids,
        "detail": (
            "Both mint uuid5(NAMESPACE_URL, 'tradeai:gap:...') over different tuples, so "
            "the same gap has two ids and neither store can recognise the other's. "
            "P1 does not renumber either: both are registered on narrative_subjects "
            "under their own source_table, which makes them joinable by SUBJECT."
        ),
    }


def question_guid_incompatible() -> dict[str, Any]:
    """The two `question_guid` functions, by signature and by namespace."""
    import inspect

    sites: list[dict[str, Any]] = []
    for rel, module_path, ns_name in (
        ("scripts/lib/research_circle.py", "scripts.lib.research_circle", "QUESTION_NAMESPACE"),
        ("scripts/due_diligence_questions.py", "due_diligence_questions", "uuid.NAMESPACE_URL"),
    ):
        entry: dict[str, Any] = {"module": rel, "line": _find_line(rel, "def question_guid")}
        try:
            mod = __import__(module_path, fromlist=["question_guid"])
            entry["parameters"] = list(inspect.signature(mod.question_guid).parameters)
            ns = getattr(mod, "QUESTION_NAMESPACE", None)
            entry["namespace"] = str(ns) if ns is not None else str(uuid.NAMESPACE_URL)
            entry["namespace_name"] = ns_name
        except Exception as exc:  # noqa: BLE001
            entry["parameters"] = f"UNAVAILABLE: {type(exc).__name__}: {exc}"
            entry["namespace"] = None
        sites.append(entry)

    params = [s.get("parameters") for s in sites]
    namespaces = {s.get("namespace") for s in sites if s.get("namespace")}
    return {
        "finding": "QUESTION_GUID_INCOMPATIBLE",
        "severity": "REPORT_ONLY",
        "incompatible_arguments": params[0] != params[1],
        "different_namespaces": len(namespaces) > 1,
        "sites": sites,
        "detail": (
            "Two functions of the same name take argument tuples that cannot be "
            "substituted and mint in different uuid namespaces. Neither is wrong for its "
            "own store; what was missing is any way to tell that the operator's question "
            "and the diligence question concern one subject. P1 registers them as "
            "'operator_questions' and 'due_diligence_questions' on the same spine."
        ),
    }


def spine_coverage() -> dict[str, Any]:
    """Rows per source_table, and which P1 schemes have not landed yet."""
    try:
        from scripts.lib.cio_identity_spine import SOURCE_TABLES, coverage
    except Exception as exc:  # noqa: BLE001
        return {"finding": "SPINE_COVERAGE", "severity": "REPORT_ONLY",
                "status": f"UNAVAILABLE: {type(exc).__name__}: {exc}"}
    counts = coverage()
    if counts is None:
        # No database is not "no rows". The distinction is the whole reason
        # cio_subject_guid separates LOOKUP_FAILED from UNRESOLVED.
        return {"finding": "SPINE_COVERAGE", "severity": "REPORT_ONLY",
                "status": "NO_DATABASE", "counts": None,
                "detail": "narrative_subjects was not readable from here; nothing is claimed."}
    return {
        "finding": "SPINE_COVERAGE",
        "severity": "REPORT_ONLY",
        "status": "READ",
        "counts": counts,
        "registered_source_tables": [t for t in SOURCE_TABLES if counts.get(t)],
        "not_yet_registered": [t for t in SOURCE_TABLES if not counts.get(t)],
        "total_rows": sum(counts.values()),
    }


def report() -> dict[str, Any]:
    findings = [gap_prefix_collision(), question_guid_incompatible(), spine_coverage()]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "reports_only": True,
        "findings": findings,
        "finding_count": len(findings),
    }


def _print_human(rep: dict[str, Any]) -> None:
    print("Identity spine — report only, exit 0 regardless\n")
    for f in rep["findings"]:
        print(f"[{f['finding']}]")
        if f["finding"] == "GAP_PREFIX_COLLISION":
            print(f"  prefix {f['prefix']!r} minted by two modules with different tuples:")
            for s in f["sites"]:
                print(f"    {s['module']}:{s['line']}  uuid5(NAMESPACE_URL, 'tradeai:gap:{s['tuple']}')")
            print("  one gap ('no promoted research for HPE'), two ids:")
            for store, guid in f["same_gap_two_guids"].items():
                print(f"    {store:<20} {guid}")
            print(f"  collides: {f['collides']}")
        elif f["finding"] == "QUESTION_GUID_INCOMPATIBLE":
            for s in f["sites"]:
                print(f"    {s['module']}:{s['line']}  question_guid{tuple(s['parameters']) if isinstance(s['parameters'], list) else s['parameters']}")
                print(f"      namespace {s.get('namespace_name')} = {s.get('namespace')}")
            print(f"  incompatible arguments: {f['incompatible_arguments']} · "
                  f"different namespaces: {f['different_namespaces']}")
        else:
            print(f"  status: {f.get('status')}")
            if f.get("counts") is not None:
                for table, n in sorted(f["counts"].items(), key=lambda kv: -kv[1]):
                    print(f"    {table:<34} {n}")
                print(f"  P1 source_tables still empty: {f.get('not_yet_registered')}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = report()
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        _print_human(rep)
    # Always 0: everything here is a report about live, deliberate id minting.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
