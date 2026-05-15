#!/usr/bin/env python3
"""phase2g_hybrid_canary_policy.py — Load and enforce Phase 2G canary policy.
Does NOT change production RAG routing or embedding defaults."""
import yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJ / "config" / "phase2g_hybrid_canary.yaml"

def load_policy(path=None):
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        return {"enabled": False, "error": f"Config not found: {p}"}
    return yaml.safe_load(p.read_text())

def is_workflow_allowed(workflow, policy=None):
    if policy is None:
        policy = load_policy()
    if not policy.get("enabled", False):
        return False
    return workflow in policy.get("allowed_workflows", [])

def is_workflow_blocked(workflow, policy=None):
    if policy is None:
        policy = load_policy()
    return workflow in policy.get("blocked_workflows", [])

def assert_canary_allowed(workflow, policy=None):
    if policy is None:
        policy = load_policy()
    if not policy.get("enabled"):
        raise RuntimeError("Phase 2G canary is disabled")
    if is_workflow_blocked(workflow, policy):
        raise RuntimeError(f"Workflow '{workflow}' is explicitly BLOCKED by canary policy")
    if not is_workflow_allowed(workflow, policy):
        raise RuntimeError(f"Workflow '{workflow}' is not in allowed_workflows — default is blocked")

def get_retrieval_config(policy=None):
    if policy is None:
        policy = load_policy()
    return policy.get("retrieval", {"final_k": 10, "top_k_nomic": 10, "top_k_qwen3": 10})

def get_limits(policy=None):
    if policy is None:
        policy = load_policy()
    return policy.get("canary_limits", {})

def describe_policy(policy=None):
    if policy is None:
        policy = load_policy()
    return {
        "enabled": policy.get("enabled"),
        "phase": policy.get("phase"),
        "global_rag_default": policy.get("global_rag_default"),
        "global_promotion_approved": policy.get("global_promotion_approved"),
        "production_embedding": policy.get("production_default_embedding"),
        "shadow_embedding": policy.get("shadow_embedding"),
        "allowed_workflows": policy.get("allowed_workflows", []),
        "blocked_workflows": policy.get("blocked_workflows", []),
        "limits": policy.get("canary_limits", {}),
    }

if __name__ == "__main__":
    import json
    print(json.dumps(describe_policy(), indent=2))
