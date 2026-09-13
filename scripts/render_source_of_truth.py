#!/usr/bin/env python3
"""Render docs/SOURCE_OF_TRUTH.md and the AGENTS.md §7B table from config/data_source_authority.json.

The registry is the source; the documents are views. Run after any registry change:

    python scripts/render_source_of_truth.py            # writes both, prints a diff summary
    python scripts/render_source_of_truth.py --check    # exit 1 if either document is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "config" / "data_source_authority.json"
DOC = ROOT / "docs" / "SOURCE_OF_TRUTH.md"
AGENTS = ROOT / "AGENTS.md"
START, END = "<!-- SOURCE_OF_TRUTH_TABLE_START -->", "<!-- SOURCE_OF_TRUTH_TABLE_END -->"


def _store(d: dict) -> str:
    s = d.get("store") or {}
    parts = []
    if s.get("table"):
        parts.append(f"`{s['table']}`")
    if s.get("file"):
        parts.append(f"`{s['file']}`")
    return " · ".join(parts) or "—"


def table(auth: dict) -> str:
    rows = ["| Domain | Class | Store of record | Single writer | Cadence | Stale after | Read path | Primary | Backup (same question) | Retired | No coverage |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in auth["domains"]:
        sa = d.get("stale_after_hours")
        rows.append("| " + " | ".join([
            f"**{d['domain']}**", d["class"], _store(d),
            f"`{d['writer']}`" if d.get("writer") and d["writer"] != "operator" else (d.get("writer") or "**none — dead feed**"),
            d.get("cadence") or "—",
            f"{sa:g}h" if isinstance(sa, (int, float)) else "—",
            f"`{d['projection']}`" if d.get("projection") else "—",
            d.get("primary_provider") or "—",
            ", ".join(d.get("backup") or []) or "—",
            ", ".join(d.get("retired") or []) or "—",
            f"`{d.get('no_coverage')}`",
        ]) + " |")
    return "\n".join(rows)


def providers_table(auth: dict) -> str:
    rows = ["| Provider | Class | Status | Supplies | Markers the gate recognises |", "|---|---|---|---|---|"]
    for k, v in auth["providers"].items():
        rows.append(f"| **{k}** | {v['class']} | {v['status']}" + (f" ({v.get('retired_on')})" if v.get("retired_on") else "") +
                    f" | {', '.join(v.get('supplies') or [])} | " + ", ".join(f"`{m}`" for m in v.get("match", [])) + " |")
    return "\n".join(rows)


def render_doc(auth: dict) -> str:
    sf = auth["served_from"]
    return f"""# Source of Truth — one declaration per domain

**Rendered from `config/data_source_authority.json` by `scripts/render_source_of_truth.py`. Do not edit by hand.**
Registry as of {auth['as_of']} · authority {auth['authority']} · {len(auth['domains'])} domains · {len(auth['providers'])} providers.

{auth['_why']}

## Rules

""" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(auth["_rules"])) + f"""

## Where every served store lives

Root: `{sf['root']}`. Directories that must resolve here from **both** the release and the dev tree:
""" + "\n".join(f"- `data/{d}`" for d in sf["linked_dirs"]) + f"""

{sf['_why']}

## Domains of record

{table(auth)}

## Providers

{providers_table(auth)}

## How to add or retire a source

See `AGENTS.md` §7B. Short form: registry first, projection second, markers third, table row in the
same PR. `scripts/check_data_source_authority.py` fails on an undeclared host, a retired call site,
a writer count that rose, or a hub direct read that rose.

## Enforcement

| Gate | Fails when | Where |
|---|---|---|
| `check_data_source_authority.py` | retired call site · undeclared provider · writer count rose · direct read rose · writer/projection missing | `ai_local_acceptance`, PR workflow |
| `check_served_copy_split.py` | any linked dir resolves to two directories from dev vs served · anything references the reconcile archive | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
| `data_plausibility_monitor.py` | a declared column leaves its declared scale | 06:20 timer, `[DATA_INTEGRITY]` interrupt |
| `check_expected_services.py` | a declared unit or flag is off | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
"""


def splice(text: str, block: str) -> str:
    a, b = text.index(START), text.index(END)
    return text[: a + len(START)] + "\n" + block + "\n" + text[b:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    doc = render_doc(auth)
    agents_text = AGENTS.read_text(encoding="utf-8")
    agents_new = splice(agents_text, table(auth)) if START in agents_text else agents_text
    stale = []
    if not DOC.exists() or DOC.read_text(encoding="utf-8") != doc:
        stale.append(str(DOC.relative_to(ROOT)))
    if agents_new != agents_text:
        stale.append("AGENTS.md §7A table")
    if args.check:
        print("stale: " + (", ".join(stale) if stale else "none"))
        return 1 if stale else 0
    DOC.write_text(doc, encoding="utf-8")
    if agents_new != agents_text:
        AGENTS.write_text(agents_new, encoding="utf-8")
    print("rendered: " + (", ".join(stale) if stale else "no change"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
