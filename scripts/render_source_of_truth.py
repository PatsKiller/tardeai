#!/usr/bin/env python3
"""Render docs/SOURCE_OF_TRUTH.md and the AGENTS.md §7A table from config/data_source_authority.json.

The registry is the source; the documents are views. Run after any registry change:

    python scripts/render_source_of_truth.py            # writes both, prints a diff summary
    python scripts/render_source_of_truth.py --check    # exit 1 if either document is stale

What is rendered, and from where (nothing below is typed by hand):

    Domains of record          registry domains[]          (+ Approval column: the operator's grant)
    Writer ceilings            config/data_source_authority_baseline.json  (UNCONSOLIDATED stores)
    Providers                  registry providers[]        (+ Approval column)
    Approval records           distinct approval.reference values across both
    Monitors                   config/expected_services.json units whose _why names the campaign,
                               joined to config/lane_registry.json lanes and the timer files
    Enforcement                the gates, by name

A monitor row never claims the timer is INSTALLED: that is measured by
check_expected_services.py on the host, not by this renderer (AGENTS.md §0 rule 8).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "config" / "data_source_authority.json"
BASELINE = ROOT / "config" / "data_source_authority_baseline.json"
LANES = ROOT / "config" / "lane_registry.json"
EXPECTED = ROOT / "config" / "expected_services.json"
UNITS_DIR = ROOT / "config" / "systemd" / "user"
DOC = ROOT / "docs" / "SOURCE_OF_TRUTH.md"
AGENTS = ROOT / "AGENTS.md"
START, END = "<!-- SOURCE_OF_TRUTH_TABLE_START -->", "<!-- SOURCE_OF_TRUTH_TABLE_END -->"
CAMPAIGN_MARKER = "One Source of Truth"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _store(d: dict) -> str:
    s = d.get("store") or {}
    parts = []
    if s.get("table"):
        parts.append(f"`{s['table']}`")
    if s.get("file"):
        parts.append(f"`{s['file']}`")
    return " · ".join(parts) or "—"


def _writer(d: dict, baseline: dict) -> str:
    """How the store is written: one module, an operator, an unconsolidated set, or nobody."""
    w = d.get("writer")
    if w == "operator":
        return "operator (manual entry)"
    if w:
        return f"`{w}`"
    if d.get("writer_status") == "UNCONSOLIDATED":
        table = (d.get("store") or {}).get("table")
        n = (baseline.get("writers") or {}).get(table)
        count = f"{n} writers today" if isinstance(n, int) else "count not baselined"
        return f"UNCONSOLIDATED → `{d.get('writer_target')}` ({count}; ceiling may only fall)"
    return "**none — dead feed**"


def _approval(row: dict) -> str:
    a = row.get("approval") or {}
    if a.get("retired_by"):
        return f"retired by {a['retired_by']} {a.get('retired_on', '')}".strip()
    if a.get("approved_by"):
        return f"{a['approved_by']} {a.get('approved_on', '')}".strip()
    return "**UNAPPROVED**"


def table(auth: dict, baseline: dict | None = None) -> str:
    baseline = baseline if baseline is not None else _load(BASELINE)
    rows = ["| Domain | Class | Store of record | Single writer (how it is written) | Cadence | Stale after | Read path | Primary | Backup (same question) | Retired | No coverage | Approval |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in auth["domains"]:
        sa = d.get("stale_after_hours")
        rows.append("| " + " | ".join([
            f"**{d['domain']}**", d["class"], _store(d),
            _writer(d, baseline),
            d.get("cadence") or "—",
            f"{sa:g}h" if isinstance(sa, (int, float)) else "—",
            f"`{d['projection']}`" if d.get("projection") else "—",
            d.get("primary_provider") or "—",
            ", ".join(d.get("backup") or []) or "—",
            ", ".join(d.get("retired") or []) or "—",
            f"`{d.get('no_coverage')}`",
            _approval(d),
        ]) + " |")
    return "\n".join(rows)


def ceilings_table(auth: dict, baseline: dict) -> str:
    rows = ["| Domain | Store | Writers today (ceiling) | Consolidation target | Hub direct reads (ceiling) |", "|---|---|---|---|---|"]
    for d in auth["domains"]:
        if d.get("writer_status") != "UNCONSOLIDATED":
            continue
        table_name = (d.get("store") or {}).get("table")
        w = (baseline.get("writers") or {}).get(table_name, "—")
        r = (baseline.get("direct_reads") or {}).get(table_name, "—")
        rows.append(f"| **{d['domain']}** | `{table_name}` | {w} | `{d.get('writer_target')}` | {r} |")
    return "\n".join(rows)


def providers_table(auth: dict) -> str:
    rows = ["| Provider | Class | Status | Supplies | Markers the gate recognises | Approval |", "|---|---|---|---|---|---|"]
    for k, v in auth["providers"].items():
        rows.append(f"| **{k}** | {v['class']} | {v['status']}" + (f" ({v.get('retired_on')})" if v.get("retired_on") else "") +
                    f" | {', '.join(v.get('supplies') or [])} | " + ", ".join(f"`{m}`" for m in v.get("match", [])) +
                    f" | {_approval(v)} |")
    return "\n".join(rows)


def approval_records(auth: dict) -> str:
    refs: dict[str, list[str]] = {}
    for k, v in auth["providers"].items():
        refs.setdefault((v.get("approval") or {}).get("reference") or "**MISSING**", []).append(f"provider `{k}`")
    for d in auth["domains"]:
        refs.setdefault((d.get("approval") or {}).get("reference") or "**MISSING**", []).append(f"domain `{d['domain']}`")
    out = []
    for ref, rows in refs.items():
        out.append(f"- **{ref}** — {len(rows)} rows: " + ", ".join(rows))
    return "\n".join(out)


def _timer_schedule(unit: str) -> str:
    p = UNITS_DIR / unit
    if not p.exists():
        return "unit file missing"
    m = re.search(r"^OnCalendar=(.+)$", p.read_text(encoding="utf-8", errors="replace"), re.M)
    return f"`{m.group(1).strip()}`" if m else "no OnCalendar"


def monitors_table(lanes: dict, expected: dict) -> str:
    """The campaign's monitors: declared in expected_services, scheduled by a lane, receipted."""
    by_unit = {}
    for lane in lanes.get("lanes", []):
        expr = (lane.get("scheduler") or {}).get("expression")
        if expr:
            by_unit[expr] = lane
    rows = ["| Monitor lane | Timer unit | Schedule | Receipt (written every run) | Declared in expected_services | Installed? |",
            "|---|---|---|---|---|---|"]
    for u in expected.get("units", []):
        if CAMPAIGN_MARKER not in str(u.get("_why", "")):
            continue
        unit = u["unit"]
        lane = by_unit.get(unit)
        lane_id = f"`{lane['lane_id']}`" if lane else "**no lane row**"
        receipt = f"`{((lane or {}).get('output_signal') or {}).get('path', '—')}`" if lane else "—"
        rows.append(f"| {lane_id} | `{unit}` | {_timer_schedule(unit)} | {receipt} | yes | "
                    "measured by `check_expected_services.py` on the host — not asserted here |")
    return "\n".join(rows)


def render_doc(auth: dict, baseline: dict, lanes: dict, expected: dict) -> str:
    sf = auth["served_from"]
    return f"""# Source of Truth — one declaration per domain

**Rendered from `config/data_source_authority.json` by `scripts/render_source_of_truth.py`. Do not edit by hand.**
Registry as of {auth['as_of']} · schema `{auth.get('schema')}` · authority {auth['authority']} · {len(auth['domains'])} domains · {len(auth['providers'])} providers.

{auth['_why']}

## Rules

""" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(auth["_rules"])) + f"""

## Ownership and the grant

The registry names, for every authoritative store, **who owns it** (the single writer module, or the
operator for a manual store), **how it is written** (cadence, writer, projection it is read through)
and **what stands in for it** (the `backup` chain — same question, different provider — and the
declared `no_coverage` behaviour when the chain is exhausted). Each row also carries the
**operator's grant** in `approval`: who approved it, when, where that approval is recorded, and the
one-line scope of what the source may supply. A retired row records who retired it and when.

**Adding, replacing or retiring a data source — or a writer of an authoritative store — is an
operator-only decision** (`AGENTS.md` §17). An agent proposes the registry row in a PR; the operator
grants it; the grant is written into `approval`; only then may a call site exist. A row without a
complete approval fails `check_data_source_authority.py` with `UNAPPROVED_SOURCE`, and a host the
registry does not know fails with `UNDECLARED_PROVIDER` whose message says what to do: propose a
registry row with an approval record, do not add the host.

## Where every served store lives

Root: `{sf['root']}`. Directories that must resolve here from **both** the release and the dev tree:
""" + "\n".join(f"- `data/{d}`" for d in sf["linked_dirs"]) + f"""

{sf['_why']}

## Domains of record

{table(auth, baseline)}

## Writer ceilings — stores not yet consolidated to one writer

`config/data_source_authority_baseline.json` records how many files write each store today. The
number is a **ceiling, not a target**: `WRITER_COUNT_ROSE` fails the build when it rises, and it is
regenerated only after a deliberate reduction (`--write-baseline`). The consolidation target is the
module every other writer must call.

{ceilings_table(auth, baseline)}

## Providers

{providers_table(auth)}

## Approval records

Every provider and domain row carries `approval`. The distinct references, and the rows they cover:

{approval_records(auth)}

## Monitors

The campaign's monitors are declared three times so that a monitor that is OFF is itself a finding:
as a systemd unit in `config/systemd/user/`, as a lane in `config/lane_registry.json` with a receipt
`output_signal`, and as a required unit in `config/expected_services.json`. Installing a timer is
operator-only (`AGENTS.md` §9.3, §17); this table asserts the declarations, not the host state.

{monitors_table(lanes, expected)}

## How to add or retire a source

See `AGENTS.md` §7A. Short form: **operator grant first** (recorded in the row's `approval`), registry
row second, projection third, markers fourth, then re-render this document and the §7A table with
`scripts/render_source_of_truth.py` in the same PR. `scripts/check_data_source_authority.py` fails on
an ungranted row, an undeclared host, a retired call site, a writer count that rose, or a hub direct
read that rose.

## Enforcement

| Gate | Fails when | Where |
|---|---|---|
| `check_data_source_authority.py` | ungranted provider/domain (`UNAPPROVED_SOURCE`) · retired call site · undeclared provider · writer count rose · direct read rose · writer/projection missing | `ai_local_acceptance`, PR workflow |
| `render_source_of_truth.py --check` | this document or the `AGENTS.md` §7A table differs from the registry | `ai_local_acceptance`, PR workflow |
| `check_served_copy_split.py` | any linked dir resolves to two directories from dev vs served · anything references the reconcile archive | hourly timer, `[PLATFORM_AVAILABILITY]` interrupt |
| `check_data_source_health.py` | a source with a scheduled caller is not *effectively* healthy (decayed to unknown, or error) | hourly timer, `[PLATFORM_AVAILABILITY]` on change |
| `check_gap_resolution.py` | a gap open >2h with no attempt · a vector failing ≥3× today · a retired provider ran (`RETIRED_RAN`, must be 0) | 30-min timer, `[DATA_INTEGRITY]` interrupt |
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
    auth = _load(AUTH)
    baseline = _load(BASELINE)
    lanes = _load(LANES)
    expected = _load(EXPECTED)
    doc = render_doc(auth, baseline, lanes, expected)
    agents_text = AGENTS.read_text(encoding="utf-8")
    agents_new = splice(agents_text, table(auth, baseline)) if START in agents_text else agents_text
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
