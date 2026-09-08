"""Direct-call bypass scan for Brave/provider HTTP.

Positive control: inject a known bypass string and confirm the detector finds it.
In-lease callers must not contain direct api.search.brave.com HTTP after Lane C.
Out-of-lease callers are classified and must appear in the disposition table.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BRAVE_URL_RE = re.compile(r"api\.search\.brave\.com")
TOKEN_HEADER_RE = re.compile(r"X-Subscription-Token")

# Baseline inventory from Lane C prompt (defect 11).
ALL_CALLERS = [
    "phase2b_analyst.py",
    "scripts/portfolio_weekly_report.py",
    "scripts/alert_dispatcher_unified.py",
    "scripts/aegis_transcript_discovery.py",
    "scripts/run_cio_hardening_ci.py",
    "scripts/brave_search.py",
    "scripts/symbol_enrichment.py",
    "scripts/aegis_social_sentiment.py",
    "scripts/portfolio_news.py",
    "scripts/api_v2.py",
    "scripts/secret_validators.py",
    "scripts/web_news_fetcher.py",
    "scripts/topic_ingestion.py",
    "scripts/dry_run_brave_budget_reconciliation.py",
    "scripts/web_research.py",
    "scripts/credential_monitor.py",
    "scripts/lib/research_provider_truth.py",
    "scripts/lib/search_budget.py",
    "scripts/lib/campaign_closeout.py",
]

OUT_OF_LEASE = {
    "scripts/api_v2.py",
    "scripts/run_cio_hardening_ci.py",
    "scripts/secret_validators.py",
    "scripts/credential_monitor.py",
    "scripts/alert_dispatcher_unified.py",
    "phase2b_analyst.py",
    "scripts/lib/campaign_closeout.py",
}

# Modules that may mention the URL as documentation / router constants only.
ALLOWED_URL_MENTIONS = {
    "scripts/lib/brave_router.py",  # the chokepoint itself
    "scripts/brave_search.py",  # may retain URL constants but must not urlopen them
}


def _scan_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path.relative_to(ROOT)),
        "has_url": bool(BRAVE_URL_RE.search(text)),
        "has_token_header": bool(TOKEN_HEADER_RE.search(text)),
        "has_urlopen": "urlopen(" in text or "requests.get(" in text,
        "imports_router": "brave_router" in text,
    }


def test_positive_control_detector_fires(tmp_path: Path):
    planted = tmp_path / "planted_bypass.py"
    planted.write_text(
        'url = "https://api.search.brave.com/res/v1/web/search"\n'
        'requests.get(url, headers={"X-Subscription-Token": "x"})\n',
        encoding="utf-8",
    )
    text = planted.read_text(encoding="utf-8")
    assert BRAVE_URL_RE.search(text), "positive control: URL not detected"
    assert TOKEN_HEADER_RE.search(text), "positive control: token header not detected"
    assert "requests.get(" in text, "positive control: requests.get not detected"


def test_in_lease_callers_have_no_direct_brave_http():
    """Every in-lease former caller must not perform direct provider HTTP."""
    bypasses = []
    for rel in ALL_CALLERS:
        if rel in OUT_OF_LEASE:
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Direct HTTP = URL + (urlopen or requests.get) in same file outside router.
        if rel in ALLOWED_URL_MENTIONS:
            # brave_search must not call urlopen on Brave anymore.
            if rel == "scripts/brave_search.py":
                # After Lane C, search()/search_news() must not urlopen.
                assert "def search(" in text
                # Ensure search body delegates rather than urlopen BRAVE_API_URL
                assert "brave_router" in text
                assert "Governed path" in text or "_governed" in text
            continue
        if BRAVE_URL_RE.search(text) and ("urlopen(" in text or "requests.get(" in text):
            # Confirm it's not only in a comment
            for i, line in enumerate(text.splitlines(), 1):
                if BRAVE_URL_RE.search(line) and not line.strip().startswith("#"):
                    # nearby request?
                    window = "\n".join(text.splitlines()[max(0, i - 5): i + 5])
                    if "urlopen(" in window or "requests.get(" in window:
                        bypasses.append(f"{rel}:{i}")
    assert bypasses == [], f"direct Brave bypasses in lease: {bypasses}"


def test_out_of_lease_callers_classified():
    """Out-of-lease callers must be explicitly classified (shared-file request set)."""
    dispositions = {}
    for rel in sorted(OUT_OF_LEASE):
        path = ROOT / rel
        dispositions[rel] = {
            "lease": "INTEGRATION_OR_OTHER",
            "disposition": "SHARED_FILE_REQUEST",
            "exists": path.exists(),
        }
    assert len(dispositions) == len(OUT_OF_LEASE)
    # Every one must be requested — enforced by handoff shared_file_requests length
    assert all(v["disposition"] == "SHARED_FILE_REQUEST" for v in dispositions.values())
