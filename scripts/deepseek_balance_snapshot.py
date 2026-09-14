#!/usr/bin/env python3
"""deepseek_balance_snapshot.py — record the DeepSeek account balance so logged cost can be checked. Dry run by default.

WHY
---
Operator, 2026-09-14: "make sure you research exactly what the complete costs are with DeepSeek's website".

**What was checked.** Last week's logged cost ($5.45) was recomputed from token counts at the prices on
api-docs.deepseek.com, peak-aware: $5.42.

**What could not be checked.** Nothing recorded the account balance over time, so the logged cost could
never be compared with what DeepSeek actually deducted.

WHAT
----
Reads `GET https://api.deepseek.com/user/balance` (free; no tokens) and, with `--apply`, appends one row to
`data/runtime/deepseek_balance_history.jsonl`. `llm_spend.reconcile_balance` turns consecutive rows into
"deducted" (drops) and "topped up" (rises) for any window. The spend report compares that with the logged
DeepSeek cost.

The API key is read through the model registry and never printed or written.

AUTHORITY: READ_ONLY_ADVISORY. Reads an account balance; never spends, orders or changes caps.
MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

AUTHORITY = "READ_ONLY_ADVISORY"
HISTORY = PROJECT_ROOT / "data" / "runtime" / "deepseek_balance_history.jsonl"
BALANCE_URL = "https://api.deepseek.com/user/balance"
NO_CONSUMER_REASON = "scheduled ledger lane; llm_spend.reconcile_balance and the spend report read the history"


def parse_balance(body: dict[str, Any]) -> dict[str, Any]:
    """Pure. The USD balance row (else the first), as floats."""
    infos = body.get("balance_infos") or []
    pick = next((b for b in infos if str(b.get("currency") or "").upper() == "USD"), infos[0] if infos else {})

    def num(v: Any) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "currency": pick.get("currency"),
        "total_balance": num(pick.get("total_balance")),
        "granted_balance": num(pick.get("granted_balance")),
        "topped_up_balance": num(pick.get("topped_up_balance")),
        "is_available": bool(body.get("is_available")),
    }


def fetch_balance(key: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(BALANCE_URL, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 -- fixed vendor URL
        return json.loads(resp.read().decode("utf-8"))


def _api_key() -> str:
    try:
        from lib.llm_model_registry import get_deepseek_api_key  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from scripts.lib.llm_model_registry import get_deepseek_api_key  # type: ignore  # noqa: PLC0415
    key, _env_name, _legacy = get_deepseek_api_key()
    return key or ""


def load_history(path: Path = HISTORY) -> list[dict[str, Any]]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return rows


def run_once(
    *,
    apply: bool,
    now: Optional[datetime] = None,
    path: Path = HISTORY,
    fetcher: Optional[Callable[[], dict[str, Any]]] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if fetcher is None:
        key = _api_key()
        if not key:
            return {"schema": "DeepSeekBalanceSnapshot@v1", "ok": False, "error": "no_api_key", "authority": AUTHORITY}
        fetcher = lambda: fetch_balance(key)  # noqa: E731
    row = {
        "schema": "DeepSeekBalanceSnapshot@v1",
        "ts": now.replace(microsecond=0).isoformat(),
        **parse_balance(fetcher()),
        "authority": AUTHORITY,
    }
    history = load_history(path) + [row]
    try:
        from lib.llm_spend import reconcile_balance  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from scripts.lib.llm_spend import reconcile_balance  # type: ignore  # noqa: PLC0415
    last_day = reconcile_balance(history, now - timedelta(hours=24), now)
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    return {"ok": True, "mode": "apply" if apply else "dry_run", "snapshot": row, "last_24h": last_day}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="append the snapshot to the history (default: dry run)")
    args = ap.parse_args(argv)
    out = run_once(apply=args.apply)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
