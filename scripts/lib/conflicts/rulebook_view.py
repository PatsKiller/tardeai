"""Read-only plain-language view of the active conflict rulebook (GET /api/v3/conflicts/rulebook).

Everything a threshold says comes from config/conflict_rulebook.json or config/investment_policy_statement.json
(No Hardcoded Values rule); config/conflict_rules_explained.json supplies words only. Coverage is re-checked on
every read against the files in this tree, so a removed test or rule shows as MISSING instead of a stale claim.
Pure read: no ledger write, no network, no broker (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from .ledger import ACTIVE, ConflictLedger

SCHEMA = "ConflictRulebookView@v1"
REPO = Path(__file__).resolve().parents[3]
TERMINAL = ("CLEARED", "SUPERSEDED")
MATRIX_DIR = "data/coordination/handoffs/conflict-resolution-20261024"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _test_names(path: Path, cache: dict) -> set:
    if path not in cache:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            cache[path] = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        except (OSError, SyntaxError, ValueError):
            cache[path] = set()
    return cache[path]


def coverage(rule: dict, repo: Path = REPO) -> dict:
    """IMPLEMENTED only when every code marker is present and at least one named test exists in this tree."""
    texts: dict = {}
    names: dict = {}
    code = []
    for ref in rule.get("code", []):
        path = repo / ref["path"]
        if path not in texts:
            try:
                texts[path] = path.read_text(encoding="utf-8")
            except OSError:
                texts[path] = None
        code.append({**ref, "found": bool(texts[path] is not None and ref["match"] in texts[path])})
    tests = [{**ref, "found": ref["name"] in _test_names(repo / ref["path"], names)} for ref in rule.get("tests", [])]
    implemented = bool(code) and all(c["found"] for c in code) and any(t["found"] for t in tests)
    return {
        "status": "IMPLEMENTED" if implemented else "MISSING",
        "code": code,
        "tests": tests,
        "gap_note": rule.get("gap_note"),
    }


def _matrix_check(expected: str | None) -> dict:
    try:
        from scripts.lib.persistent_state_root import resolve_durable_dir

        path = Path(resolve_durable_dir(MATRIX_DIR)) / "EXCEPTIONS_MATRIX.md"
        if not path.is_file():
            return {"verified": None, "reason": "the binding matrix file is not readable on this host"}
        actual = _sha(path)
        return {
            "verified": actual == expected,
            "actual_sha256": actual,
            "reason": None
            if actual == expected
            else "the matrix file on this host differs from the pinned fingerprint",
        }
    except (OSError, ImportError, ValueError) as exc:
        return {"verified": None, "reason": f"matrix check unavailable ({type(exc).__name__})"}


def _scale(rulebook: dict, names: dict) -> dict:
    from .profiles.vocabulary import ordinal

    sec = rulebook["security_stance"]
    labels = [label for family in sec["families"].values() for label in family]
    out = {}
    for name, held in (("held", True), ("not_held", False)):
        steps: dict = {}
        for label in labels:
            step = ordinal(label, held)
            if step is not None:
                steps.setdefault(step, []).append(label)
        primary = {v: k for k, v in sec["ordinal"].items()} if held else {}
        words = names.get(name, {})
        out[name] = [
            {"step": step, "primary": words.get(str(step)) or primary.get(step, members[0]), "labels": members}
            for step, members in sorted(steps.items())
        ]
    return out


def _concentration(ips_path: Path, labels: dict) -> dict:
    try:
        policy = _json(ips_path)["constraints"]["concentration_policy"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"rows": [], "gap": {"reason": "concentration policy missing from the Investment Policy Statement"}}
    limits = policy.get("limits_pct") or {}
    near = policy.get("near_limit_fraction")
    fc = policy.get("fund_classification") or {}

    def rule_text(key):
        if key == "broad_diversified_fund" and {"broad_min_holdings", "broad_largest_holding_lt_pct"} <= fc.keys():
            return (
                f"≥ {fc['broad_min_holdings']:g} holdings and largest holding < {fc['broad_largest_holding_lt_pct']:g}%"
            )
        if key == "narrow_thematic_fund" and {"narrow_holdings_lt", "narrow_top10_gt_pct"} <= fc.keys():
            return f"< {fc['narrow_holdings_lt']:g} holdings or top-10 weight > {fc['narrow_top10_gt_pct']:g}%"
        if key == "leveraged_inverse_fund":
            return "From fund metadata"
        if key.startswith("lookthrough_"):
            return "Portfolio › Look-through"
        return None

    rows = []
    for key, limit in limits.items():
        near_at = round(limit * near, 4) if isinstance(limit, (int, float)) and isinstance(near, (int, float)) else None
        rows.append(
            {
                "key": key,
                "label": labels.get(key) or key.replace("_", " "),
                "limit_pct": limit,
                "near_limit_pct": near_at,
                "detection": rule_text(key),
            }
        )
    midrange = fc.get("midrange_class")
    note = None
    if midrange and {"narrow_holdings_lt", "broad_min_holdings"} <= fc.keys():
        note = (
            f"Funds with {fc['narrow_holdings_lt']:g}–{fc['broad_min_holdings'] - 1:g} holdings are treated as "
            f"{labels.get(midrange, midrange)} unless you class them."
        )
    return {
        "rows": rows,
        "near_limit_fraction": near,
        "midrange_note": note,
        "scope": policy.get("scope"),
        "approval_ref": policy.get("approval_ref"),
        "as_of": policy.get("as_of"),
        "unknown_classification": policy.get("unknown_classification"),
        "source": "config/investment_policy_statement.json constraints.concentration_policy",
        "gap": None,
    }


def _live(root) -> dict:
    try:
        if root is None:
            from .api import _root

            root = _root()
        if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
            return {
                "by_kind": {},
                "by_state": {},
                "open_total": None,
                "gap": {"reason": "conflict ledger not yet produced"},
            }
        records = list(ConflictLedger(root).records().values())
        by_kind: dict = {}
        by_state: dict = {}
        for record in records:
            by_state[record["state"]] = by_state.get(record["state"], 0) + 1
            if record["state"] in ACTIVE:
                by_kind[record.get("kind") or "UNKNOWN"] = by_kind.get(record.get("kind") or "UNKNOWN", 0) + 1
        return {
            "by_kind": by_kind,
            "by_state": by_state,
            "open_total": sum(by_kind.values()),
            "gap": None,
            "as_of": max((r["updated_at"] for r in records), default=None),
            "source": "conflict_events.jsonl",
        }
    except (OSError, ValueError, KeyError, ImportError):
        return {
            "by_kind": {},
            "by_state": {},
            "open_total": None,
            "gap": {"reason": "conflict ledger unavailable or invalid"},
        }


def _resolver_receipt(root) -> dict | None:
    try:
        if root is None:
            from .api import _root

            root = _root()
        path = Path(root) / "data/runtime/conflict-resolver_last.json"
        if not path.is_file():
            return None
        doc = _json(path)
        return {
            k: doc.get(k) for k in ("phase", "status", "started_at", "finished_at", "findings_count", "rulebook_sha256")
        }
    except (OSError, ValueError, ImportError):
        return None


def build(repo: Path = REPO, *, root=None) -> dict:
    rulebook_path = repo / "config/conflict_rulebook.json"
    rulebook = _json(rulebook_path)
    explained = _json(repo / "config/conflict_rules_explained.json")
    pinned = rulebook.get("matrix_sha256")
    text_gap = (
        None
        if explained.get("matrix_sha256") == pinned
        else {"reason": "the plain-language text was written for a different matrix version than the active rulebook"}
    )
    from .engine import ENGINE_VERSION

    precedence = sorted((rulebook.get("precedence") or {}).items(), key=lambda item: item[1])
    t4_labels = explained.get("t4_order_labels", {})
    never = [
        {"id": key, "label": explained.get("never_auto_labels", {}).get(key)} for key in rulebook.get("never_auto", [])
    ]
    rules = [
        {k: v for k, v in rule.items() if k not in {"code", "tests", "gap_note"}} | {"coverage": coverage(rule, repo)}
        for rule in explained.get("rules", [])
    ]
    return {
        "schema": SCHEMA,
        "rulebook": {
            "status": rulebook.get("status"),
            "version": rulebook.get("version"),
            "approval": rulebook.get("approval"),
            "live_enabled": bool(rulebook.get("live_enabled")),
            "matrix_sha256": pinned,
            "matrix_check": _matrix_check(pinned),
            "rulebook_sha256": _sha(rulebook_path),
            "source": rulebook.get("source"),
            "engine_version": ENGINE_VERSION,
            "matrix_source": explained.get("matrix_source"),
        },
        "text_gap": text_gap,
        "tiers": explained.get("tiers", []),
        "t4_order": [
            {"key": key, "rank": rank, "label": t4_labels[key]} for key, rank in precedence if key in t4_labels
        ],
        "rules": rules,
        "coverage_summary": {
            "implemented": sum(r["coverage"]["status"] == "IMPLEMENTED" for r in rules),
            "missing": sum(r["coverage"]["status"] == "MISSING" for r in rules),
            "total": len(rules),
        },
        "never_auto": never,
        "never_auto_matrix_text": explained.get("never_auto_matrix_text"),
        "action_scale": {
            **_scale(rulebook, explained.get("action_scale_names", {})),
            "text": explained.get("action_scale_text", {}),
        },
        "thresholds": {
            "supersede_days": rulebook["security_stance"].get("supersede_days"),
            "default_supersede_days": rulebook["security_stance"].get("default_supersede_days"),
            "canonical_max_age_trading_days": rulebook["security_stance"].get("canonical_max_age_trading_days"),
            "refresh_after_trading_days": rulebook["security_stance"].get("refresh_after_trading_days"),
            "trade_go_clear": rulebook["security_stance"].get("trade_go_clear"),
            "unmapped_labels": rulebook["security_stance"].get("unmapped_labels"),
            "hysteresis": rulebook.get("hysteresis"),
            "flap_limit": (rulebook.get("universal") or {}).get("flap_limit"),
            "flap_window_days": (rulebook.get("universal") or {}).get("flap_window_days"),
        },
        "concentration": _concentration(
            repo / "config/investment_policy_statement.json", explained.get("concentration_labels", {})
        ),
        "lifecycle": {
            "states": explained.get("lifecycle", []),
            "active_states": sorted(ACTIVE),
            "terminal_states": list(TERMINAL),
            "cadence_design": explained.get("cadence_design"),
            "last_run": _resolver_receipt(root),
        },
        "live": _live(root),
    }
