"""news_articles has source_url, not url (2026-09-27).

symbol_thesis_evidence selected a non-existent `url` column; the query raised, the
error was swallowed, and NO approved news counted toward any symbol's thesis gate
from 2026-08-19 (2af981c2d) until this fix. ask_alerts had the same bug. Hermetic.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _news_selects(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    return [m.group(0) for m in re.finditer(r"SELECT[^;]*?FROM\s+news_articles", src, re.S | re.I)]


def test_no_bare_url_column_in_news_articles_selects():
    for rel in ("scripts/lib/symbol_thesis_evidence.py", "scripts/ask_alerts.py"):
        for sql in _news_selects(ROOT / rel):
            cols = sql.split("FROM")[0]
            assert not re.search(r"(?<![\w.])url(?!\w)(?!\s+AS)", cols.replace("source_url AS url", "")), (rel, sql)
    assert any("source_url AS url" in s for s in _news_selects(ROOT / "scripts/lib/symbol_thesis_evidence.py"))
