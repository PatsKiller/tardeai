#!/usr/bin/env python3
"""audit_phase2g_canary_status.py — Show Phase 2G canary configuration and safety status."""
import json, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from phase2g_hybrid_canary_policy import load_policy, describe_policy

def main():
    policy = load_policy()
    desc = describe_policy(policy)
    print("=== Phase 2G Canary Audit ===")
    print(f"Config: config/phase2g_hybrid_canary.yaml")
    print(f"Enabled: {desc['enabled']}")
    print(f"Phase: {desc['phase']}")
    print(f"Global RAG default: {desc['global_rag_default']}")
    print(f"Global promotion approved: {desc['global_promotion_approved']}")
    print(f"Production embedding: {desc['production_embedding']}")
    print(f"Shadow embedding: {desc['shadow_embedding']}")
    print(f"Allowed workflows: {len(desc['allowed_workflows'])}")
    for w in desc['allowed_workflows']:
        print(f"  + {w}")
    print(f"Blocked workflows: {len(desc['blocked_workflows'])}")
    for w in desc['blocked_workflows']:
        print(f"  x {w}")
    print(f"\nRollback: ./scripts/rollback_phase2g_canary.sh --disable")
    print(f"Or: set 'enabled: false' in config/phase2g_hybrid_canary.yaml")

if __name__ == "__main__":
    main()
