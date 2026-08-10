"""C3/C4 Integration Checkpoint Audit Script.

Runs the evidence chain: Registry → DomainEvidence → Snapshot → Evidence Gate.
"""
import sys
import os as _os

_project_root = _os.path.dirname(_os.path.abspath(__file__))
sys.path.insert(0, _project_root)
sys.path.insert(0, _os.path.join(_project_root, 'scripts'))  # for 'lib' imports

import tempfile
import os

print("=== C3/C4 INTEGRATION CHECKPOINT ===\n")

# ── Load registry ────────────────────────────────────────────────────────────
from scripts.lib.cio_domain_registry import CIODomainRegistry

try:
    reg = CIODomainRegistry.load()
    print(f"Registry loaded: {reg.registry_version}, schema {reg.schema_version}")
except Exception as e:
    print(f"Registry load FAILED: {e}")
    sys.exit(1)

print(f"Registry domains: {len(reg.domain_ids)}")
print(f"Supported: {sorted(reg.supported_domains())}")
print(f"Broken: {reg.broken_domains()}")
print(f"Unsupported: {sorted(reg.unsupported_domains())}")

# ── Test: For each supported domain, call the collector if found ─────────────
from scripts.lib.data_broker.cio_portfolio import _COLLECTORS as _BROKER_COLLECTORS
from scripts.lib.cio_domain_evidence import DomainEvidence, ReasonCode

_REGISTRY_TO_COLLECTOR_KEY = {
    "broker_reconciliation": "reconciliation",
}

data_broker_collectors = dict(_BROKER_COLLECTORS)
for reg_key, coll_key in _REGISTRY_TO_COLLECTOR_KEY.items():
    if coll_key in _BROKER_COLLECTORS:
        data_broker_collectors[reg_key] = _BROKER_COLLECTORS[coll_key]

print(f"\n=== EVIDENCE COLLECTION FOR SUPPORTED DOMAINS ===")
collector_map = {}
for domain_id in reg.supported_domains():
    collector = data_broker_collectors.get(domain_id)
    if collector is None:
        print(f"  {domain_id:30s} NO COLLECTOR FOUND in data_broker")
        collector_map[domain_id] = None
        continue
    try:
        result = collector()
    except Exception as exc:
        print(f"  {domain_id:30s} COLLECTOR EXCEPTION: {exc}")
        collector_map[domain_id] = ("ERROR", str(exc))
        continue

    if isinstance(result, DomainEvidence):
        qs = result.quality_state
        rc = result.reason_code or "-"
        sr = (result.source_ref or "-")[:50]
        ao = result.as_of or "-"
        dk = list(result.data.keys()) if result.data else []
        pf = result.partial_fields or []
        gk = result.gap_reason or "-"
        print(f"  {domain_id:30s} state={qs:20s} code={rc:25s} src={sr:50s} as_of={ao}")
        if result.data is not None and qs == "AVAILABLE" and not result.data:
            print(f"    ** WARNING: AVAILABLE with empty data dict! **")
        if pf:
            print(f"    partial_fields={pf} gap_reason={gk}")
        collector_map[domain_id] = (qs, rc, sr, ao, dk)
    elif isinstance(result, dict):
        state = result.get("quality_state") or result.get("state", "?")
        sr = result.get("source_ref", "-")[:50]
        ao = result.get("as_of", "-")
        print(f"  {domain_id:30s} state={state:20s} src={sr:50s} as_of={ao}")
        collector_map[domain_id] = (state, "dict-return", sr, ao, list(result.keys()))

# ── Verify semantic corrections in snapshot builder ──────────────────────────
from scripts.lib.cio_financial_snapshot import build_canonical_snapshot, SEMANTIC_CORRECTION_MAP

print(f"\n=== SEMANTIC CORRECTION MAP ===")
print(f"  Map: {SEMANTIC_CORRECTION_MAP}")
print(f"  'risk' -> 'health_data_quality': {'risk' in SEMANTIC_CORRECTION_MAP}")
print(f"  'watch' -> 'open_cio_actions': {'watch' in SEMANTIC_CORRECTION_MAP}")
print(f"  Map used in build_canonical_snapshot? Checking...")

# Check if SEMANTIC_CORRECTION_MAP is referenced in the function body
import inspect
src = inspect.getsource(build_canonical_snapshot)
map_used = "SEMANTIC_CORRECTION_MAP" in src
print(f"  SEMANTIC_CORRECTION_MAP referenced in build_canonical_snapshot: {map_used}")

# ── Build a snapshot and verify domain populations ───────────────────────────
class MockProfile:
    def get_all_confirmed(self):
        return {"operator": "test", "domains": ["portfolio", "risk"]}
    _version = "v1"
    _ips_version = "v1"

class MockHealth:
    def current_advisory_state(self):
        return "HEALTHY"
    def latest_decision_id(self):
        return "dec-123"

class MockLedger:
    def list_actions(self):
        return []

snapshot = build_canonical_snapshot(
    operator_profile=MockProfile(),
    health_boundary=MockHealth(),
    action_ledger=MockLedger(),
)

print(f"\n=== SNAPSHOT DOMAIN STATES ===")
for domain, entry in sorted(snapshot._domains.items()):
    state = entry.get("state", "?")
    source = entry.get("source_ref", "none")
    as_of = entry.get("as_of", "none")
    gap = entry.get("gap_reason", "")
    print(f"  {domain:30s} state={state:20s} source={source:50s} as_of={as_of}")

# ── Verify no semantic collisions ────────────────────────────────────────────
print(f"\n=== SEMANTIC COLLISION CHECKS ===")
risk_entry = snapshot._domains.get("risk", {})
hdq_entry = snapshot._domains.get("health_data_quality", {})
watch_entry = snapshot._domains.get("watch_intelligence", {})
oci_entry = snapshot._domains.get("open_cio_actions", {})

print(f"  risk.source_ref={risk_entry.get('source_ref','?')}")
print(f"  health_data_quality.source_ref={hdq_entry.get('source_ref','?')}")
print(f"  watch_intelligence.source_ref={watch_entry.get('source_ref','?')}")
print(f"  open_cio_actions.source_ref={oci_entry.get('source_ref','?')}")

risk_is_health = risk_entry.get("state") == "AVAILABLE" and risk_entry.get("source_ref") == "health_boundary"
watch_is_ledger = watch_entry.get("state") == "AVAILABLE" and watch_entry.get("source_ref") == "action_ledger"

print(f"\n  CRITICAL: risk==health_boundary: {risk_is_health} (must be False)")
print(f"  CRITICAL: watch==action_ledger: {watch_is_ledger} (must be False)")

# ── Verify AVAILABLE domains have source_ref and data ───────────────────────
print(f"\n=== AVAILABLE DOMAIN CONTRACT CHECKS ===")
failures = []
for domain, entry in snapshot._domains.items():
    state = entry.get("state")
    if state == "AVAILABLE":
        if not entry.get("source_ref"):
            failures.append(f"{domain}: missing source_ref")
        if entry.get("data") is None:
            failures.append(f"{domain}: missing data (None)")
        elif not entry.get("data"):
            failures.append(f"{domain}: empty data dict")
        if not entry.get("as_of"):
            failures.append(f"{domain}: missing as_of timestamp")
        if "quality_state" not in entry and "state" not in entry:
            failures.append(f"{domain}: missing quality_state/state")

if failures:
    for f in failures:
        print(f"  FAIL: {f}")
else:
    print("  All AVAILABLE domains have source_ref, data, as_of: PASS")

# ── Collect and count domain states ──────────────────────────────────────────
available = snapshot.available_domains()
stale_list = snapshot.stale_domains()
unavailable = snapshot.unavailable_domains()
not_applicable = snapshot.not_applicable_domains()

print(f"\n=== DOMAIN STATE BREAKDOWN ===")
print(f"  AVAILABLE ({len(available)}): {sorted(available)}")
print(f"  STALE ({len(stale_list)}): {sorted(stale_list)}")
print(f"  DATA_UNAVAILABLE ({len(unavailable)}): {sorted(unavailable)}")
print(f"  NOT_APPLICABLE ({len(not_applicable)}): {sorted(not_applicable)}")

# ── Check stale/conflicted/error states ─────────────────────────────────────
partial_domains = {d for d, e in snapshot._domains.items() if e["state"] == "PARTIAL"}
conflicted = {d for d, e in snapshot._domains.items() if e["state"] == "CONFLICTED"}
error = {d for d, e in snapshot._domains.items() if e["state"] == "ERROR"}

print(f"\n  PARTIAL ({len(partial_domains)}): {sorted(partial_domains)}")
print(f"  CONFLICTED ({len(conflicted)}): {sorted(conflicted)}")
print(f"  ERROR ({len(error)}): {sorted(error)}")

# ── Freshness checks ────────────────────────────────────────────────────────
print(f"\n=== FRESHNESS CHECK ===")
freshness_check_found = False
for domain, entry in snapshot._domains.items():
    if entry.get("stale_since"):
        freshness_check_found = True
        print(f"  {domain}: stale_since={entry['stale_since']}")
    if "collected_at" in entry:
        pass  # expected, collection timestamp is separate from source timestamp

# Verify freshness check exists in code
freshness_code = "age_s > threshold" in src
print(f"  Source-timestamp freshness check in build_canonical_snapshot: {freshness_code}")
collection_as_freshness = '"as_of"' not in src or "collected_at" not in src
print(f"  Collection timestamp used as source freshness: check code manually")
print(f"  (code uses evidence.as_of for freshness — source timestamp)")

# Check for collection timestamp used as freshness
uses_as_of = "age_s = (now - as_of_dt)" in src
print(f"  Uses as_of (source timestamp) for age calculation: {uses_as_of}")

# ── Evidence chain test ─────────────────────────────────────────────────────
print(f"\n=== EVIDENCE CHAIN TEST ===")
print("  Registry -> DomainEvidence -> Snapshot -> Evidence Gate")

try:
    from scripts.lib.cio_run_worker import CIORunWorker
    print("  CIORunWorker import: OK")
except Exception as e:
    print(f"  CIORunWorker import: FAILED ({e})")

try:
    from scripts.lib.cio_action_validator import validate_action_evidence
    print("  cio_action_validator import: OK")
except Exception as e:
    print(f"  cio_action_validator import: FAILED ({e})")

# ── Verify every AVAILABLE has provenance ───────────────────────────────────
print(f"\n=== PROVENANCE CHECKS ===")
prov_failures = []
for domain, entry in snapshot._domains.items():
    state = entry.get("state")
    if state == "AVAILABLE":
        if not entry.get("source_ref"):
            prov_failures.append(f"{domain}: no source_ref")
        # Check if snapshot includes provenance_contract-like info
        # (source_lineage may not be in the snapshot dict directly)

if prov_failures:
    for f in prov_failures:
        print(f"  FAIL: {f}")
else:
    print("  All AVAILABLE domains have source_ref (provenance): PASS")

# ── Verify no broken adapter marks AVAILABLE ────────────────────────────────
print(f"\n=== BROKEN ADAPTER CHECK ===")
broken = reg.broken_domains()
broken_available = [d for d in broken if d in available]
print(f"  Registry BROKEN domains: {broken}")
print(f"  BROKEN domains that are AVAILABLE in snapshot: {broken_available}")
if broken_available:
    print(f"  ** WARNING: Broken adapters returning AVAILABLE! **")
else:
    print(f"  No broken adapters return AVAILABLE: PASS")

# ── Verify watch_intelligence adapter status ────────────────────────────────
print(f"\n=== WATCH_INTELLIGENCE ADAPTER CHECK ===")
watch_capability = reg.get("watch_intelligence")
print(f"  watch_intelligence adapter_state: {watch_capability.adapter_state}")
print(f"  watch_intelligence canonical_source: {watch_capability.canonical_source}")

# Check if get_watch_intelligence function exists
import importlib
try:
    mod = importlib.import_module("scripts.lib.data_broker.watch_intelligence")
    fn = getattr(mod, "get_watch_intelligence", None)
    print(f"  get_watch_intelligence function exists: {fn is not None}")
    if fn is None:
        print(f"  Functions available: {[x for x in dir(mod) if not x.startswith('_')]}")
except Exception as e:
    print(f"  Import failed: {e}")

# ── Invariant checks: any AVAILABLE with empty/fallback data? ───────────────
print(f"\n=== INVARIANT: AVAILABLE WITH EMPTY/FALLBACK DATA ===")
for domain, entry in snapshot._domains.items():
    state = entry.get("state")
    if state == "AVAILABLE":
        data = entry.get("data")
        if data is None:
            print(f"  WARNING: {domain} AVAILABLE but data=None")
        elif isinstance(data, dict) and len(data) == 0:
            print(f"  WARNING: {domain} AVAILABLE but data is empty dict")
        elif isinstance(data, dict):
            # Check for obviously empty/fallback content
            all_none = all(v is None for v in data.values())
            all_zero = all(v in (0, 0.0) for v in data.values() if isinstance(v, (int, float)))
            if all_none and len(data) > 0:
                print(f"  WARNING: {domain} AVAILABLE but all values are None")

print(f"\n=== CHECKPOINT COMPLETE ===")
