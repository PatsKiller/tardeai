#!/usr/bin/env python3
"""Optional cross-check of the Anthropic credit ledger against the Usage & Cost Admin API.

Presence-gated: when no ``ANTHROPIC_ADMIN_API_KEY`` environment variable exists,
the run is SKIPPED and that is not an error. The key value is used only as the request
header of one fixed first-party GET; it is never logged, written or returned.

    python3 scripts/anthropic_cost_verify.py            # dry run: what would be compared
    python3 scripts/anthropic_cost_verify.py --apply    # fetch and write the result file

The result (amounts and timestamps only) goes to
``<state root>/data/runtime/provider_cost/anthropic_admin_cost.json`` and is shown on
LLM Spend / Ops Controls through ``anthropic_monitoring.credit_config``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.anthropic_credit import CreditBook  # noqa: E402
from scripts.lib.anthropic_transport import _NoRedirect, load_policy  # noqa: E402

COST_PATH = "/v1/organizations/cost_report"


def _get(path: str, query: dict[str, Any], *, key: str, timeout: float = 30) -> dict:
    url = "https://api.anthropic.com" + path + "?" + urlencode(query, doseq=True)
    request = Request(url, method="GET", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        return json.loads(response.read(4_000_001))


def reported_usd(pages: list[dict]) -> Decimal:
    """Sum cost-report amounts. Amounts are decimal strings in cents (USD)."""
    cents = Decimal(0)
    for page in pages:
        for bucket in page.get("data") or []:
            for row in bucket.get("results") or []:
                if str(row.get("currency") or "USD").upper() != "USD":
                    continue
                try:
                    cents += Decimal(str(row.get("amount") or "0"))
                except InvalidOperation:
                    continue
    return cents / Decimal(100)


def verify(state_root: Path, policy: dict, *, env: dict[str, str] | None = None,
           fetch: Callable[..., dict] = _get, now: datetime | None = None, apply: bool = False) -> dict:
    cfg = policy.get("admin_cost_verification") or {}
    name = "ANTHROPIC_ADMIN_API_KEY"
    if env is None:
        key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")
        env = {name: key} if key else {}
    now = now or datetime.now(timezone.utc)
    if cfg.get("enabled") is not True or name not in env:
        return {"status": "SKIPPED_NO_KEY", "key_name": name, "verified_at": now.isoformat()}
    book = CreditBook(state_root, policy)
    credit = book.snapshot(now=now)
    start = book.period_start(now) or book.start
    out: dict[str, Any] = {"status": "DRY_RUN", "key_name": name, "window_start": start.isoformat(),
                           "ledger_usd": credit["credit_used_usd"], "verified_at": now.isoformat()}
    if not apply:
        return out
    pages, query = [], {"starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "bucket_width": "1d"}
    for _ in range(20):
        page = fetch(COST_PATH, query, key=str(env[name]))
        pages.append(page)
        if not page.get("has_more") or not page.get("next_page"):
            break
        query = dict(query, page=page["next_page"])
    reported = reported_usd(pages)
    delta = reported - Decimal(credit["credit_used_usd"])
    out.update(status="MATCH" if abs(delta) <= Decimal("0.50") else "MISMATCH",
               reported_usd=str(reported.quantize(Decimal("0.01"))), delta_usd=str(delta.quantize(Decimal("0.01"))))
    target = Path(state_root) / str(cfg.get("result_rel") or "data/runtime/provider_cost/anthropic_admin_cost.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="fetch the cost report and write the result")
    args = parser.parse_args(argv)
    from scripts.lib.anthropic_routing import state_root
    result = verify(state_root(), load_policy(), apply=args.apply)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
