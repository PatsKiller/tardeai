#!/usr/bin/env python3
"""Enforce config/data_source_authority.json: one source of truth per domain. Read-only.

WHY
---
For five months Performance (10 Years) was stored as a 1-5 analyst rating; for
eighteen days the site served a copy of the state tree that nothing wrote to; a
six-slot news chain ran with four dead slots. Each was possible because the
answer to "which store, which writer, which provider is the source for X" lived
in a docstring, a memory, or nowhere. The authority file is where it lives now,
and this gate is what makes the file mean something.

CHECKS
------
    RETIRED_CALL_SITE     a retired provider is referenced outside the allowlist
    UNDECLARED_PROVIDER   a provider host / SDK marker appears in scripts/ but not
                          in the registry (baseline can only shrink). The finding
                          tells the agent what to do: propose a registry row WITH
                          an operator approval record; do not add the host.
    UNAPPROVED_SOURCE     a provider or domain row has no complete `approval`
                          record. Adding, replacing or retiring a source is an
                          operator-only decision (AGENTS.md §17); the grant is the
                          row's approval {approved_by, approved_on, reference,
                          scope} — retired rows carry {retired_by, retired_on,
                          reference}. An ungranted source fails the build.
    WRITER_MISSING        a domain's declared writer file does not exist
    WRITER_UNDECLARED     a domain has no writer and does not declare UNCONSOLIDATED + a target
    PROJECTION_MISSING    a domain's declared projection is not in the broker catalog
    WRITER_COUNT_ROSE     more files write a declared store than the recorded baseline
    DIRECT_READ_ROSE      more hub handlers read a declared store directly than baseline
    LANE_DIRECT_READ_ROSE more scheduled-lane files read a projection-owned store directly
                          (FROM <table>, or the raw enrichment cache file) than baseline.
                          Lane scripts are the ones config/lane_registry.json schedules
                          (scheduler.match / command_text / expression, exec_start), plus
                          the scripts/lib modules they import directly. Every bypass is
                          listed in the report (lane_bypasses) whether or not it fails.

Baselines live in config/data_source_authority_baseline.json and may only fall.
Regenerate with --write-baseline after a deliberate reduction; a rise fails.
The lane ceilings (lane_direct_reads, lane_raw_cache_reads) never rise even under
--write-baseline: a regeneration keeps min(prior, now) per key.

LANE SCAN — what it structurally cannot see (2026-10-10, GAP 5)
---------------------------------------------------------------
* A lane's transitive imports beyond one hop into scripts/lib, and any import that is
  not a ``lib.``/``scripts.lib.`` module.
* Reads spelled any way other than ``FROM <table>`` (``JOIN <table>``, an f-string
  table name, an ORM) and cache reads that never spell the file name (a resolver
  call such as enrichment_cache_store.load_enrichment_cache in n8nmat/finviz-cache-n8n).
* Lanes whose command line names no scripts/ file (wrappers under linux_launchers/,
  other repositories); they are counted in ``lane_scan.unresolved``.
* The broker execution file set (config/agents_guard_hook_rules.json
  broker.execution_code_edit / broker.order_invoke) is never opened by the lane scan
  (AGENTS.md §0 rule 2).

USAGE
-----
    python scripts/check_data_source_authority.py
    python scripts/check_data_source_authority.py --json
    python scripts/check_data_source_authority.py --write-baseline

EXIT 0 clean · 1 findings · 2 could not run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTHORITY = PROJECT_ROOT / "config" / "data_source_authority.json"
BASELINE = PROJECT_ROOT / "config" / "data_source_authority_baseline.json"

SCHEMA = "DataSourceAuthorityReport@v1"
AUTHORITY_SCHEMA = "DataSourceAuthority@v2"
NO_CONSUMER_REASON = "this IS a CI gate; ai_local_acceptance and the PR workflow invoke it and read the exit code."

#: What an agent must do when the gate names a host it does not know. The grant
#: is the operator's (AGENTS.md §17); the agent's part is the proposal.
UNDECLARED_ACTION = ("propose a registry row in config/data_source_authority.json WITH an operator "
                     "approval record {approved_by, approved_on, reference, scope}; do not add the host "
                     "until the operator has granted it (AGENTS.md §7A, §17)")

#: A complete grant. Active rows are approved; retired rows record who retired them.
APPROVAL_KEYS_ACTIVE = ("approved_by", "approved_on", "reference", "scope")
APPROVAL_KEYS_RETIRED = ("retired_by", "retired_on", "reference")

#: Files that legitimately mention retired providers: secret-hygiene scanners
#: (they must keep recognising a leaked key), the registry itself, this gate,
#: and the retired-providers module that reads the registry.
RETIRED_ALLOWLIST = (
    "scripts/check_secret_exposure.sh",
    "scripts/secret_validators.py",
    "scripts/secrets_admin.py",
    "scripts/telegram_command_handler.py",
    "scripts/trade_ai_validator.py",
    "scripts/lib/retired_providers.py",
    "scripts/check_data_source_authority.py",
    "scripts/requirements.txt",
)

SCAN_DIRS = ("scripts",)
SCAN_SUFFIXES = (".py", ".sh")
HUB_FILES = ("scripts/api_v2.py",)

# ── Lane scan (GAP 5, operator-approved 2026-10-10) ─────────────────────────────────────────────
LANE_REGISTRY = PROJECT_ROOT / "config" / "lane_registry.json"
#: Never opened by the lane scan: the broker execution file set (AGENTS.md §0 rule 2; kept a superset
#: of config/agents_guard_hook_rules.json by tests), the broker itself and the single writers (they
#: ARE the read path / the owner), the hub (counted by DIRECT_READ_ROSE) and this gate.
LANE_SCAN_EXCLUDE_PREFIXES = ("scripts/brokers/", "scripts/active_trader/", "scripts/moomoo/",
                              "scripts/lib/data_broker/", "scripts/lib/writers/")
LANE_SCAN_EXCLUDE_FILES = ("scripts/lib/trading_session_grant.py", "scripts/schwab_transport.py",
                           "scripts/schwab_oco_bracket.py", "scripts/schwab_token_manager.py",
                           "scripts/check_data_source_authority.py",
                           # the store's one path resolver (n8nmat/finviz-cache-n8n); it spells the file by design
                           "scripts/lib/enrichment_cache_store.py") + HUB_FILES
#: Raw state files a broker projection owns. A lane that spells the file name reads it raw.
RAW_CACHE_FILES = {
    "ticker_enrichment_cache.json": {"projection": "finviz_enrichment_snapshot",
                                     "writer": "scripts/finviz_enrichment.py"},
}
_LANE_TOKEN_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|sh))\b")
_LIB_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(?:scripts\.)?lib\.([\w.]+)", re.M)
_LIB_FROM_RE = re.compile(r"^\s*from\s+(?:scripts\.)?lib\s+import\s+\(?([\w ,]+)", re.M)


def _files() -> list[Path]:
    out: list[Path] = []
    for d in SCAN_DIRS:
        for p in (PROJECT_ROOT / d).rglob("*"):
            if p.suffix in SCAN_SUFFIXES and p.is_file() and "/tests/" not in p.as_posix() and "__pycache__" not in p.parts:
                out.append(p)
    return out


def _rel(p: Path) -> str:
    return p.relative_to(PROJECT_ROOT).as_posix()


def scan_retired(auth: dict, files: list[Path]) -> list[dict]:
    """Every file outside the allowlist that matches a retired provider's markers."""
    retired = {k: v for k, v in auth["providers"].items() if v.get("status") == "retired"}
    findings = []
    for p in files:
        rel = _rel(p)
        if rel in RETIRED_ALLOWLIST or rel.startswith("archive/"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, spec in retired.items():
            hit = next((m for m in spec.get("match", []) if m.lower() in text.lower()), None)
            if hit:
                findings.append({"check": "RETIRED_CALL_SITE", "provider": name, "file": rel, "marker": hit})
    return findings


def scan_undeclared(auth: dict, files: list[Path]) -> list[dict]:
    """Known-provider host patterns not declared in the registry."""
    declared_markers = {m.lower() for v in auth["providers"].values() for m in v.get("match", [])}
    host_re = re.compile(r"https?://([a-z0-9.-]+\.(?:com|io|org|net|gov|co|ai|markets))", re.I)
    internal = ("localhost", "127.0.0.1", "github.com", "api.telegram.org", "googleapis.com", "anthropic.com", "openai.com",
                "x.ai", "raw.githubusercontent.com", "pypi.org", "docs.", "example.com", "schemas.", "w3.org", "claude.ai",
                "grok.com", "chatgpt.com", "google.com", "youtube.com", "youtu.be", "wikipedia.org", "bitwarden.com",
                "tailscale.com", "slack.com", "discord.com", "hooks.", "ollama.ai", "huggingface.co", "npmjs.org")
    seen: dict[str, str] = {}
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in host_re.finditer(text):
            host = m.group(1).lower()
            if any(i in host for i in internal):
                continue
            if any(mk in host or host in mk for mk in declared_markers):
                continue
            seen.setdefault(host, _rel(p))
    return [{"check": "UNDECLARED_PROVIDER", "host": h, "first_seen": f, "action": UNDECLARED_ACTION}
            for h, f in sorted(seen.items())]


def _approval_missing(row: dict, required: tuple[str, ...]) -> list[str]:
    """Names of the required approval fields that are absent or blank."""
    appr = row.get("approval")
    if not isinstance(appr, dict):
        return list(required)
    return [k for k in required if not str(appr.get(k) or "").strip()]


def check_approvals(auth: dict) -> list[dict]:
    """Every provider and every domain carries the operator's grant.

    A source is not a source because a call site exists; it is a source because
    the operator granted it and the grant is written where a program can read it.
    A row with no complete approval is UNAPPROVED_SOURCE and fails the build.
    """
    findings = []
    for name, p in auth.get("providers", {}).items():
        required = APPROVAL_KEYS_RETIRED if p.get("status") == "retired" else APPROVAL_KEYS_ACTIVE
        missing = _approval_missing(p, required)
        if missing:
            findings.append({"check": "UNAPPROVED_SOURCE", "kind": "provider", "name": name, "missing": missing,
                             "action": "operator-only (AGENTS.md §17): propose the approval record in a PR; do not use the source until granted"})
    for d in auth.get("domains", []):
        missing = _approval_missing(d, APPROVAL_KEYS_ACTIVE)
        if missing:
            findings.append({"check": "UNAPPROVED_SOURCE", "kind": "domain", "name": d.get("domain"), "missing": missing,
                             "action": "operator-only (AGENTS.md §17): propose the approval record in a PR; do not use the source until granted"})
    return findings


def check_domains(auth: dict) -> list[dict]:
    findings = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from lib.data_broker.catalog import PROJECTIONS  # type: ignore
        projection_ids = {p["id"] for p in PROJECTIONS}
    except Exception:  # noqa: BLE001
        projection_ids = None
    for d in auth["domains"]:
        w = d.get("writer")
        if w and w != "operator" and not (PROJECT_ROOT / w).exists():
            findings.append({"check": "WRITER_MISSING", "domain": d["domain"], "writer": w})
        if w is None and d.get("class") not in ("dead_feed", "manual"):
            # An unconsolidated store must SAY so and name the target module; the
            # writer-count ceiling in the baseline is what forces it to shrink.
            if d.get("writer_status") != "UNCONSOLIDATED" or not d.get("writer_target"):
                findings.append({"check": "WRITER_UNDECLARED", "domain": d["domain"]})
        pj = d.get("projection")
        if pj and projection_ids is not None and pj not in projection_ids:
            findings.append({"check": "PROJECTION_MISSING", "domain": d["domain"], "projection": pj})
    return findings


def count_writers(auth: dict, files: list[Path]) -> dict[str, int]:
    """Files that INSERT/UPDATE/COPY into each declared table (regex over source)."""
    out: dict[str, int] = {}
    for d in auth["domains"]:
        table = (d.get("store") or {}).get("table")
        if not table:
            continue
        pat = re.compile(rf"\b(INSERT\s+INTO|UPDATE|COPY)\s+{re.escape(table)}\b", re.I)
        n = 0
        for p in files:
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                    n += 1
            except OSError:
                pass
        out[table] = n
    return out


def count_direct_reads(auth: dict) -> dict[str, int]:
    """Hub handlers reading a projection-owned table with FROM <table> directly."""
    out: dict[str, int] = {}
    texts = []
    for hf in HUB_FILES:
        p = PROJECT_ROOT / hf
        if p.exists():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(texts)
    for d in auth["domains"]:
        table = (d.get("store") or {}).get("table")
        if not table or not d.get("projection"):
            continue
        out[table] = len(re.findall(rf"\bFROM\s+{re.escape(table)}\b", blob, re.I))
    return out


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _lane_excluded(rel: str) -> bool:
    return rel in LANE_SCAN_EXCLUDE_FILES or rel.startswith(LANE_SCAN_EXCLUDE_PREFIXES)


def lane_scripts(registry: dict, root: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """Scheduled lane entrypoints -> the lane ids that run them, plus command tokens naming no scripts/ file.

    A lane is scheduled unless its state is RETIRED. Tokens come from every scheduler string
    (match, command_text, expression, install_line, schedules) and exec_start; ``.../x.py``
    (elided paths) and bare names resolve by a unique basename under scripts/.
    """
    root = root or PROJECT_ROOT
    by_name: dict[str, list[str]] = {}
    for p in (root / "scripts").rglob("*"):
        if p.suffix in SCAN_SUFFIXES and p.is_file() and "__pycache__" not in p.parts and "/tests/" not in p.as_posix():
            by_name.setdefault(p.name, []).append(p.relative_to(root).as_posix())
    found: dict[str, set[str]] = {}
    unresolved: set[str] = set()
    for lane in registry.get("lanes", []):
        if str(lane.get("state") or "").upper() == "RETIRED":
            continue
        for text in _strings(lane.get("scheduler") or {}) + _strings(lane.get("exec_start") or []):
            for m in _LANE_TOKEN_RE.finditer(text):
                tok = m.group(1)
                hit = None
                if "/scripts/" in "/" + tok:
                    cand = "scripts/" + ("/" + tok).split("/scripts/", 1)[1]
                    hit = cand if (root / cand).is_file() else None
                if hit is None and (root / "scripts" / tok).is_file():
                    hit = f"scripts/{tok}"
                if hit is None and len(by_name.get(Path(tok).name, [])) == 1:
                    hit = by_name[Path(tok).name][0]
                if hit is None:
                    unresolved.add(tok)
                elif not _lane_excluded(hit):
                    found.setdefault(hit, set()).add(lane.get("lane_id") or "?")
    return {k: sorted(v) for k, v in sorted(found.items())}, sorted(unresolved)


def _lib_modules(text: str, root: Path) -> set[str]:
    """scripts/lib modules a file imports directly (``lib.x`` / ``scripts.lib.x`` / ``from lib import x``)."""
    names = {m.group(1) for m in _LIB_IMPORT_RE.finditer(text)}
    for m in _LIB_FROM_RE.finditer(text):
        names.update(n.strip().split(" as ")[0].strip() for n in m.group(1).split(",") if n.strip())
    out = set()
    for n in names:
        parts = n.split(".")
        for k in range(len(parts), 0, -1):  # lib.a.b.func -> the longest prefix that is a module
            base = root / "scripts" / "lib" / Path(*parts[:k])
            if base.with_suffix(".py").is_file():
                out.add(base.with_suffix(".py").relative_to(root).as_posix())
                break
            if (base / "__init__.py").is_file():
                out.add((base / "__init__.py").relative_to(root).as_posix())
                break
    return out


def lane_scan(auth: dict, registry: dict, root: Path | None = None) -> dict:
    """Direct reads of projection-owned stores by scheduled lanes and the lib modules they import.

    Returns ``{"direct_reads": {table: files}, "raw_cache_reads": {file_name: files},
    "bypasses": [...], "scanned": {"entrypoints", "lib_modules", "unresolved"}}``. A table's own
    declared writer reading it is not a bypass.
    """
    root = root or PROJECT_ROOT
    entry, unresolved = lane_scripts(registry, root)
    via: dict[str, dict[str, list[str]]] = {f: {"lanes": lanes, "via": []} for f, lanes in entry.items()}
    texts: dict[str, str] = {}
    for f in list(entry):
        try:
            texts[f] = (root / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            texts[f] = ""
        for mod in sorted(_lib_modules(texts[f], root)):
            if _lane_excluded(mod) or mod in entry:
                continue
            via.setdefault(mod, {"lanes": [], "via": []})
            via[mod]["via"].append(f)
            for lane_id in entry[f]:
                if lane_id not in via[mod]["lanes"]:
                    via[mod]["lanes"].append(lane_id)
    owned = {(d.get("store") or {}).get("table"): d for d in auth["domains"]
             if (d.get("store") or {}).get("table") and d.get("projection")}
    reads = {t: 0 for t in owned}
    raw = {name: 0 for name in RAW_CACHE_FILES}
    bypasses: list[dict] = []
    for f in sorted(via):
        if f not in texts:
            try:
                texts[f] = (root / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[f] = ""
        text = texts[f]
        meta = {"file": f, "lanes": sorted(via[f]["lanes"]), **({"via": sorted(via[f]["via"])} if via[f]["via"] else {})}
        for table, d in owned.items():
            if f == d.get("writer"):
                continue
            n = len(re.findall(rf"\bFROM\s+{re.escape(table)}\b", text, re.I))
            if n:
                reads[table] += 1
                bypasses.append({**meta, "kind": "table", "store": table, "occurrences": n,
                                 "read_path": d.get("projection")})
        for name, spec in RAW_CACHE_FILES.items():
            if f == spec["writer"]:
                continue
            n = text.count(name)
            if n:
                raw[name] += 1
                bypasses.append({**meta, "kind": "cache_file", "store": name, "occurrences": n,
                                 "read_path": spec["projection"]})
    return {"direct_reads": reads, "raw_cache_reads": raw, "bypasses": bypasses,
            "scanned": {"entrypoints": len(entry), "lib_modules": len(via) - len(entry),
                        "unresolved": unresolved}}


def compare_lane_baseline(kind: str, current: dict[str, int], baseline: dict[str, int] | None,
                          bypasses: list[dict]) -> list[dict]:
    """Like compare_baseline, but a key absent from a present baseline is a ceiling of 0 and the
    finding names the files. No lane baseline at all (an older baseline file) checks nothing."""
    if baseline is None:
        return []
    findings = []
    for k, v in current.items():
        b = int(baseline.get(k, 0))
        if v > b:
            findings.append({"check": kind, "store": k, "baseline": b, "now": v,
                             "files": sorted({x["file"] for x in bypasses if x["store"] == k}),
                             "action": "read it through the broker projection (AGENTS.md §7A rule 3); "
                                       "the ceiling may only fall"})
    return findings


def compare_baseline(kind: str, current: dict[str, int], baseline: dict[str, int]) -> list[dict]:
    findings = []
    for k, v in current.items():
        b = baseline.get(k)
        if b is not None and v > b:
            findings.append({"check": kind, "table": k, "baseline": b, "now": v})
    return findings


def check_routing_policy(auth: dict) -> list[dict]:
    """ROUTING_POLICY_INVALID (2026-10-10): a domain that names a ``routing_policy`` must point at a policy
    file that validates (scripts/lib/search_routing_policy.py) against this very registry."""
    findings: list[dict] = []
    for d in auth.get("domains") or []:
        rel = (d or {}).get("routing_policy")
        if not rel:
            continue
        path = PROJECT_ROOT / rel
        if not path.exists():
            findings.append({"check": "ROUTING_POLICY_INVALID", "domain": d.get("domain"), "policy": rel,
                             "errors": ["policy file missing"]})
            continue
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from scripts.lib.search_routing_policy import validate_policy
            errors = validate_policy(json.loads(path.read_text(encoding="utf-8")), registry=auth)
        except Exception as exc:  # noqa: BLE001
            errors = [f"{type(exc).__name__}: {exc}"]
        if errors:
            findings.append({"check": "ROUTING_POLICY_INVALID", "domain": d.get("domain"), "policy": rel,
                             "errors": errors[:20]})
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-baseline", action="store_true", help="record current writer/direct-read counts as the ceiling")
    ap.add_argument("--list-bypasses", action="store_true", help="print every lane bypass (informational)")
    args = ap.parse_args()
    if not AUTHORITY.exists():
        print(f"ERROR: {AUTHORITY} missing", file=sys.stderr)
        return 2
    auth = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    if auth.get("schema") != AUTHORITY_SCHEMA:
        print(f"ERROR: unexpected authority schema {auth.get('schema')!r}; expected {AUTHORITY_SCHEMA}", file=sys.stderr)
        return 2
    files = _files()

    writers = count_writers(auth, files)
    reads = count_direct_reads(auth)
    undeclared = scan_undeclared(auth, files)
    registry = json.loads(LANE_REGISTRY.read_text(encoding="utf-8")) if LANE_REGISTRY.exists() else {"lanes": []}
    lanes = lane_scan(auth, registry)
    if args.write_baseline:
        # Undeclared hosts seen today are inherited debt: URLs in research seeds, library
        # references and regulator pages, not data providers. They are recorded so the
        # gate is green on day one and any NEW host fails — the lane-registry precedent.
        prior = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}

        def _never_rise(key: str, now: dict[str, int]) -> dict[str, int]:
            old = prior.get(key)
            if not isinstance(old, dict):
                return now
            return {k: min(v, int(old[k])) if k in old else v for k, v in now.items()}
        BASELINE.write_text(json.dumps({
            "schema": "DataSourceAuthorityBaseline@v1",
            # measured history survives a regeneration; the ceiling is what is enforced
            **({"history": prior["history"]} if isinstance(prior.get("history"), dict) else {}),
            "_why": "Ceilings, not targets. Each number may only fall and each list may only shrink. Regenerate deliberately with --write-baseline after a reduction.",
            "writers": writers, "direct_reads": reads,
            "undeclared_hosts": sorted(u["host"] for u in undeclared),
            **({"lane_scan": prior["lane_scan"]} if isinstance(prior.get("lane_scan"), dict) else {}),
            "lane_direct_reads": _never_rise("lane_direct_reads", lanes["direct_reads"]),
            "lane_raw_cache_reads": _never_rise("lane_raw_cache_reads", lanes["raw_cache_reads"]),
        }, indent=2) + "\n")
        print(f"baseline written: {BASELINE}")
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {"writers": {}, "direct_reads": {}}

    findings = []
    findings += scan_retired(auth, files)
    undeclared_baseline = set(baseline.get("undeclared_hosts", []))
    findings += [u for u in undeclared if u["host"] not in undeclared_baseline]
    findings += check_approvals(auth)
    findings += check_domains(auth)
    findings += check_routing_policy(auth)
    findings += compare_baseline("WRITER_COUNT_ROSE", writers, baseline.get("writers", {}))
    findings += compare_baseline("DIRECT_READ_ROSE", reads, baseline.get("direct_reads", {}))
    findings += compare_lane_baseline("LANE_DIRECT_READ_ROSE", lanes["direct_reads"],
                                      baseline.get("lane_direct_reads"), lanes["bypasses"])
    findings += compare_lane_baseline("LANE_DIRECT_READ_ROSE", lanes["raw_cache_reads"],
                                      baseline.get("lane_raw_cache_reads"), lanes["bypasses"])

    unapproved = [f for f in findings if f["check"] == "UNAPPROVED_SOURCE"]
    approved = {"providers": len(auth["providers"]) - sum(1 for f in unapproved if f["kind"] == "provider"),
                "domains": len(auth["domains"]) - sum(1 for f in unapproved if f["kind"] == "domain")}
    report = {"schema": SCHEMA, "authority_schema": auth.get("schema"),
              "domains": len(auth["domains"]), "providers": len(auth["providers"]),
              "retired": sorted(k for k, v in auth["providers"].items() if v.get("status") == "retired"),
              "approved": approved,
              "writers": writers, "direct_reads": reads, "undeclared_hosts_seen": [u["host"] for u in undeclared],
              "lane_direct_reads": lanes["direct_reads"], "lane_raw_cache_reads": lanes["raw_cache_reads"],
              "lane_scan": lanes["scanned"], "lane_bypasses": lanes["bypasses"],
              "findings": findings}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Data source authority — one source of truth per domain")
        print("=" * 74)
        print(f"  domains={report['domains']}  providers={report['providers']}  retired={','.join(report['retired'])}")
        print(f"  operator grants     : providers={approved['providers']}/{report['providers']}  "
              f"domains={approved['domains']}/{report['domains']}  (schema {report['authority_schema']})")
        print(f"  writers per store   : {json.dumps(writers)}")
        print(f"  hub direct reads    : {json.dumps(reads)}")
        sc = lanes["scanned"]
        print(f"  lane scan           : entrypoints={sc['entrypoints']} lib_modules={sc['lib_modules']} "
              f"unresolved={len(sc['unresolved'])}")
        print(f"  lane direct reads   : {json.dumps({k: v for k, v in lanes['direct_reads'].items() if v})}")
        print(f"  lane raw cache reads: {json.dumps(lanes['raw_cache_reads'])}")
        print(f"  lane bypasses       : {len(lanes['bypasses'])} (listed with --json or --list-bypasses)")
        if args.list_bypasses:
            for b in lanes["bypasses"]:
                print(f"    [LANE_BYPASS] {b['file']} -> {b['store']} (x{b['occurrences']}; use {b['read_path']}) "
                      f"lanes={','.join(b['lanes'][:4])}{'…' if len(b['lanes']) > 4 else ''}")
        for f in findings:
            print(f"  [{f['check']}] {json.dumps({k: v for k, v in f.items() if k != 'check'})}")
        print("-" * 74)
        print(f"  findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
