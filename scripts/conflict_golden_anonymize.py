#!/usr/bin/env python3
"""Deterministic anonymizer: real golden capture (private) -> synthetic golden fixture (safe for the public repo).

The real capture (scripts/conflict_golden_capture.py) holds the operator's portfolio facts: which symbols are held,
per-account membership, concentration weights, protection states and CIO convictions. It lives only under
persistent-state/data/conflicts/golden/ (chmod 600). This writes a synthetic twin that keeps every structural case
the engine judges (agreement, superseded, each gate kind, needs-operator, data errors, the real conflict):

  symbols      -> SYM001... in an order keyed by a private salt (no alphabetical leakage)
  GUIDs        -> uuid5 of salt + GUID (joins preserved, values unlinkable)
  account ids  -> generic labels by kind (taxable_a, ira_a, roth_a, ...)
  weights      -> bucketed while preserving their relation to the limit / near-limit (status unchanged)
  convictions  -> rounded to the nearest 5
  times        -> shifted by exactly 52 weeks (weekdays and relative ages kept)
  source shas  -> dropped (they fingerprint the real files)

The salt never leaves the private directory. Output is refused unless every real symbol, GUID and account id is gone.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import uuid

SCHEMA = "ConflictGoldenFixture@v1"
NO_CONSUMER_REASON = "operator/agent CLI; its output is read by tests/test_conflict_golden_replay_20261025.py"
SHIFT = timedelta(weeks=52)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.]+([+-]\d{2}:\d{2}|Z)?)?$")
SYMBOL_KEYS = {"symbol", "label"}
ACCOUNT_KEYS = {"account", "account_id"}


def account_label(real: str, seen: dict) -> str:
    low = real.lower()
    kind = "roth" if "roth" in low else "ira" if "ira" in low or "rollover" in low else "taxable" if "taxable" in low else "account"
    if real not in seen:
        n = sum(1 for v in seen.values() if v.startswith(kind + "_"))
        seen[real] = f"{kind}_{chr(ord('a') + n)}"
    return seen[real]


def shift_time(value: str) -> str:
    if len(value) == 10:
        return (datetime.fromisoformat(value) - SHIFT).date().isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    out = (parsed - SHIFT).isoformat()
    return out.replace("+00:00", "Z") if value.endswith("Z") else out if "T" in value else out.replace("T", " ")


def bucket_weight(policy: dict) -> float | None:
    weight, limit, near = policy.get("weight_pct"), policy.get("limit_pct"), policy.get("near_limit_pct")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        return weight
    if isinstance(limit, (int, float)) and weight > limit:
        return float(limit) + 1.0
    if isinstance(near, (int, float)) and weight >= near:
        return round((near + (limit if isinstance(limit, (int, float)) else near)) / 2, 1)
    bucketed = max(1.0, round(weight / 2) * 2.0) if weight >= 1 else 0.5
    return min(bucketed, float(near) - 0.5) if isinstance(near, (int, float)) else bucketed


def anonymize(doc: dict, salt: str) -> dict:
    symbols = sorted({s["symbol"] for s in doc["subjects"]},
                     key=lambda sym: hashlib.sha256((salt + sym).encode()).hexdigest())
    sym_map = {sym: f"SYM{n:03d}" for n, sym in enumerate(symbols, start=1)}
    accounts: dict = {}
    guid_ns = uuid.uuid5(uuid.NAMESPACE_URL, "tradeai-golden-" + salt)

    def walk(value, key=None):
        if isinstance(value, dict):
            out = {k: walk(v, k) for k, v in value.items()}
            if "weight_pct" in out:
                out["weight_pct"] = bucket_weight(value)
            return out
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str):
            if key in SYMBOL_KEYS and value in sym_map:
                return sym_map[value]
            if key == "classification_source":
                return "position_source"                      # names the broker read; not needed by the engine
            if key in ACCOUNT_KEYS or key == "accounts":
                return account_label(value, accounts)
            if UUID_RE.match(value):
                return str(uuid.uuid5(guid_ns, value))
            if DATE_RE.match(value):
                try:
                    return shift_time(value)
                except ValueError:
                    return value
            return value
        if key == "conviction" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(round(value / 5) * 5)
        return value

    subjects = sorted((walk(s) for s in doc["subjects"]), key=lambda s: s["symbol"])
    out = {"schema": SCHEMA, "synthetic": True,
           "derived_from": "private real capture (sha256 in tests/fixtures/conflicts/golden_20261025/REAL_CAPTURE.json)",
           "transform": "scripts/conflict_golden_anonymize.py", "captured_at": shift_time(doc["captured_at"]),
           "now": shift_time(doc["now"]), "counts": {"subjects": len(subjects)}, "subjects": subjects}
    text = json.dumps(out)
    leaked = [s for s in sym_map if re.search(r'"' + re.escape(s) + r'"', text)]
    leaked += [a for a in accounts if a in text]
    leaked += [g for g in set(re.findall(r'"([0-9a-f-]{36})"', json.dumps(doc))) if g in text]
    if leaked:
        raise ValueError(f"anonymizer leaked {len(leaked)} real identifiers")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--real", required=True)
    parser.add_argument("--salt-file", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    doc = json.loads(Path(args.real).read_text(encoding="utf-8"))
    salt = Path(args.salt_file).read_text(encoding="utf-8").strip()
    synthetic = anonymize(doc, salt)
    Path(args.out).write_text(json.dumps(synthetic, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "subjects": synthetic["counts"]["subjects"], "out": args.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
