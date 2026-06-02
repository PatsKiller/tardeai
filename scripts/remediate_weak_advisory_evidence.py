#!/usr/bin/env python3
"""Remediate weak evidence in dual-opinion advisory records via SearXNG."""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def search_evidence(symbol, query_suffix="stock news catalyst"):
    """Quick SearXNG search for evidence."""
    query = f"{symbol} {query_suffix}"
    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": "news", "time_range": "week"})
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}?{params}", method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return [{"title": r.get("title", "")[:100], "url": r.get("url", ""), "content": r.get("content", "")[:150]}
                for r in data.get("results", [])[:3]]
    except Exception as e:
        return [{"error": str(e)[:100]}]


def remediate(max_cases=10):
    """Find weak opinions and research evidence."""
    from generate_dual_opinion_advisory import generate_dual_opinions
    from generate_journal_dual_opinions import generate_journal_opinions, generate_backtest_opinions

    all_ops = generate_dual_opinions(15)["opinions"] + generate_journal_opinions(10) + generate_backtest_opinions(10)
    weak = [o for o in all_ops if o["hermes_audit"]["risk_flags"] or o["hermes_audit"]["missing_context"]][:max_cases]

    results = []
    for o in weak:
        sym = o.get("symbol")
        if not sym:
            results.append({"opinion_id": o.get("object_id"), "status": "skipped", "reason": "no symbol"})
            continue

        print(f"  Researching {sym}...", end=" ", flush=True)
        sources = search_evidence(sym)
        valid_sources = [s for s in sources if not s.get("error")]

        improved = len(valid_sources) > 0
        results.append({
            "opinion_id": o.get("object_id"),
            "symbol": sym,
            "strategy": o.get("strategy"),
            "original_flags": len(o["hermes_audit"]["risk_flags"]),
            "original_missing": len(o["hermes_audit"]["missing_context"]),
            "sources_found": len(valid_sources),
            "sources": valid_sources,
            "evidence_improved": improved,
            "still_weak": not improved,
            "status": "improved" if improved else "still_weak",
        })
        print(f"{'improved' if improved else 'still_weak'} ({len(valid_sources)} sources)")

    improved_count = sum(1 for r in results if r.get("evidence_improved"))
    still_weak = sum(1 for r in results if r.get("still_weak"))

    output = {
        "timestamp": datetime.now().isoformat(),
        "cases_processed": len(results),
        "improved": improved_count,
        "still_weak": still_weak,
        "results": results,
    }

    out_dir = PROJECT_ROOT / "data" / "advisory" / "evidence_remediation"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    (out_dir / f"{today}_remediation_results.json").write_text(json.dumps(output, indent=2, default=str))
    return output


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()

    r = remediate(args.max)
    print(f"\nRemediation: {r['cases_processed']} processed, {r['improved']} improved, {r['still_weak']} still weak")
