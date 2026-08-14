#!/usr/bin/env python3
"""Render the CIO Institutional Report from the LIVE capital plan / holdings.

Never uses a synthetic $100k book. READ_ONLY_ADVISORY. No broker / Telegram.

  python scripts/render_cio_live_report.py
  python scripts/render_cio_live_report.py --out data/audit/cio_live_report_dry/

Prints JSON:
  {html, pdf, docx, source_sha, synthetic:false, live:true}

PDF is written only when weasyprint / chromium / wkhtmltopdf is actually
present. Missing renderer → pdf=null and formats.pdf.status=missing (not ok).
If python-docx is importable, DOCX must be created.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

DEFAULT_OUT = REPO / "data" / "audit" / "cio_live_report_dry"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="CIO live report (holdings → capital plan → HTML/DOCX/PDF)",
    )
    parser.add_argument(
        "--holdings",
        default=None,
        help="Optional holdings.json path (default: canonical live book, else repo data/)",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Evidence directory (default: data/audit/cio_live_report_dry/)",
    )
    parser.add_argument(
        "--basename",
        default="cio_live_report",
        help="Output file prefix",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Do not attach live opportunity queue / sectors from DB",
    )
    args = parser.parse_args(argv)

    from scripts.lib.cio_live_report import render_live_report

    result = render_live_report(
        holdings_path=args.holdings,
        out_dir=args.out,
        basename=args.basename,
        attach_live_queue=not args.no_db,
        allow_ms_assemble=not args.no_db,
    )

    printed = {
        "html": result.get("html"),
        "pdf": result.get("pdf"),
        "docx": result.get("docx"),
        "source_sha": result.get("source_sha"),
        "synthetic": bool(result.get("synthetic")),
        "live": bool(result.get("live")),
        "formats": result.get("formats"),
        "portfolio_value_usd": result.get("portfolio_value_usd"),
        "plan_report_parity": (result.get("plan_report_parity") or {}).get("ok"),
        "production_formats_ok": result.get("production_formats_ok"),
        "error": result.get("error"),
        "authority": result.get("authority"),
    }
    print(json.dumps(printed, indent=2, default=str))

    if result.get("synthetic") or not result.get("live"):
        return 2
    if not result.get("html"):
        return 1
    # python-docx present ⇒ DOCX must exist
    docx_st = (result.get("formats") or {}).get("docx") or {}
    if docx_st.get("status") == "error":
        return 3
    # Missing PDF is an honest FAIL for production, but evidence is still written.
    # Exit 0 so the dry collector can be chained; production_formats_ok stays false.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
