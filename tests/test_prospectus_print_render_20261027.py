"""Prospectus print fidelity: PDF via Chromium and DOCX via LibreOffice from the same HTML report (synthetic data).

Unit tests run everywhere; the end-to-end renders skip with a reason when Chromium (playwright browsers) or
LibreOffice is absent, as on CI. The local proof (scripts/prospectus_print_fidelity.py) covers those hosts.
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import print_render as P, render  # noqa: E402

FIXTURE = ROOT / "apps/command-center-v3/e2e/fixtures/prospectus-fund.json"
FACT_ID = re.compile(r"\[F\d+|data-fact-id|pc-fn|fn-\d")


def fund_doc() -> dict:
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["doc"])


def _fail(*_a, **_k):
    raise AssertionError("fallback must not be called")


_READY: list = []


def _chromium_ready() -> str | None:
    """None when a headless Chromium actually launches here (memoised), else the skip reason."""
    if _READY:
        return _READY[0]
    import os
    added = "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and "PLAYWRIGHT_BROWSERS_PATH" in P.browser_env()
    if added:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = P.browser_env()["PLAYWRIGHT_BROWSERS_PATH"]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        why = None
    except ImportError:
        why = "python playwright not installed"
    except Exception as exc:  # noqa: BLE001
        why = f"playwright Chromium not launchable here (CI: browsers not installed; local proof covers it): {str(exc)[:80]}"
    finally:
        if added:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    _READY.append(why)
    return why


def _e2e_skip() -> str | None:
    why = _chromium_ready()
    if why:
        return why
    if not shutil.which("soffice"):
        return "LibreOffice (soffice) not installed (CI): local proof covers it"
    return None


# ── citations and the print stylesheet ───────────────────────────────────────────────────────────────────────────
def test_strip_citations_removes_every_marker():
    html = ('<p>Yield 3%<sup class="pc-fn"><a href="#fn-1" data-fact-id="F7">1</a></sup> and [F8, F9].</p>'
            '<details class="pc-srcs"><summary>Sources (1)</summary><ol><li>x</li></ol></details>'
            '<section id="sources" class="pc-appendix"><h2>Sources</h2><ol><li data-fact-id="F7">a</li></ol></section>'
            '<script>alert(1)</script><span data-fact-id="F2">keep</span>')
    out = P.strip_citations(html)
    assert out == "<p>Yield 3% and.</p><span>keep</span>"


def test_print_html_same_report_no_citations_and_page_break_css():
    doc = fund_doc()
    html = P.print_html(doc, paper="A4")
    assert not FACT_ID.search(html.split("</style>", 1)[1])
    assert "<script" not in html and "<details" not in html and 'id="sources"' not in html
    assert 'data-theme="light"' in html
    for rule in ("@page{size:A4}", "thead{display:table-header-group}", "figure,svg,img,.pc-kpis",
                 "break-inside:avoid", "break-after:avoid", "print-color-adjust:exact"):
        assert rule in html, rule
    # the same report: every section title of the reader's HTML is in the print HTML
    reader = render.html(doc)
    for title in re.findall(r"<h2>(.*?)</h2>", reader):
        if "Sources" not in title:
            assert title in html


def test_header_footer_templates_symbol_version_and_page_numbers():
    doc = fund_doc()
    head, foot = P._hf_templates(doc, P.settings({}))
    assert doc["symbol"] in head and P.version_date(doc) in head
    assert 'class="pageNumber"' in foot and 'class="totalPages"' in foot


def test_version_date_formats():
    assert P.version_date({"version": "20261026T180950Z"}) == "2026-10-26"
    assert P.version_date({"generated_at": "2026-10-27T01:02:03Z"}) == "2026-10-27"


def test_word_html_is_libreoffice_shaped():
    doc = fund_doc()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1280).to_bytes(4, "big") + (520).to_bytes(4, "big") + b"\x08\x02"
    html = P.word_html(doc, {"price_1y": png}, width_px=600)
    assert "var(--" not in html and "<svg" not in html and "<section" not in html
    assert not FACT_ID.search(html)
    assert 'src="data:image/png;base64,' in html and 'width="600" height="244"' in html
    assert "<thead>" in html and 'bgcolor="' in html
    assert 'class="pc-kpis"' not in html and 'class="pc-meta"' in html


def test_settings_merge_config_and_ignore_notes():
    s = P.settings({"print": {"_note": "x", "paper": "A4", "margin_in": {"top": 1.0}}})
    assert s["paper"] == "A4" and s["margin_in"]["top"] == 1.0 and s["margin_in"]["left"] == 0.6
    assert "_note" not in s
    cfg = json.loads((ROOT / "config/prospectus_print.json").read_text(encoding="utf-8"))
    assert cfg["enabled"] is True and cfg["paper"] in ("Letter", "A4")
    live = P.settings()
    assert live["paper"] == cfg["paper"] and "schema" not in live


# ── hook and fallbacks ────────────────────────────────────────────────────────────────────────────────────────────
def test_render_all_routes_pdf_and_docx_through_print_render(monkeypatch):
    seen = {}

    def fake(doc, pngs, *, fallback_pdf, fallback_docx, **_k):
        seen["fallbacks"] = (fallback_pdf, fallback_docx)
        return {"prospectus.pdf": b"%PDF-x", "prospectus.docx": b"PK-x"}

    monkeypatch.setattr(P, "render_print", fake)
    files = render.render_all(fund_doc())
    assert files["prospectus.pdf"] == b"%PDF-x" and files["prospectus.docx"] == b"PK-x"
    assert seen["fallbacks"] == (render.pdf, render.docx)
    assert "prospectus.html" in files


def test_no_chromium_falls_back_for_both_with_reason(monkeypatch, caplog):
    monkeypatch.setattr(P, "chromium_available", lambda: "python playwright not installed")
    rep: dict = {}
    files = P.render_print(fund_doc(), {}, fallback_pdf=lambda d, p: b"%PDF-old", fallback_docx=lambda d, p: b"PK-old",
                           cfg={}, report=rep)
    assert files == {"prospectus.pdf": b"%PDF-old", "prospectus.docx": b"PK-old"}
    assert rep["pdf"] == rep["docx"] == "fallback"
    assert any("playwright" in r for r in rep["reasons"])
    assert "playwright" in caplog.text


def test_chromium_error_falls_back(monkeypatch):
    monkeypatch.setattr(P, "chromium_available", lambda: None)
    monkeypatch.setattr(P, "run_chromium", lambda job, t: {"ok": False, "error": "chromium timeout after 1s"})
    rep: dict = {}
    files = P.render_print(fund_doc(), {}, fallback_pdf=lambda d, p: b"%PDF-old", fallback_docx=lambda d, p: b"PK-old",
                           cfg={}, report=rep)
    assert files["prospectus.pdf"] == b"%PDF-old" and "timeout" in rep["reasons"][0]


def test_pdf_ok_docx_falls_back_when_soffice_missing(monkeypatch):
    def fake_chromium(job, t):
        Path(job["pdf_path"]).write_bytes(b"%PDF-new")
        return {"ok": True}

    monkeypatch.setattr(P, "chromium_available", lambda: None)
    monkeypatch.setattr(P, "run_chromium", fake_chromium)
    monkeypatch.setattr(P, "soffice_path", lambda s: None)
    rep: dict = {}
    files = P.render_print(fund_doc(), {}, fallback_pdf=_fail, fallback_docx=lambda d, p: b"PK-old", cfg={}, report=rep)
    assert files == {"prospectus.pdf": b"%PDF-new", "prospectus.docx": b"PK-old"}
    assert rep == {"reasons": ["docx fallback: RuntimeError: soffice not found"], "blocked_requests": 0,
                   "pdf": "chromium", "docx": "fallback"}


def test_disabled_in_config_uses_fallbacks(monkeypatch):
    monkeypatch.setattr(P, "run_chromium", _fail)
    rep: dict = {}
    files = P.render_print(fund_doc(), {}, fallback_pdf=lambda d, p: b"%PDF-old", fallback_docx=lambda d, p: None,
                           cfg={"print": {"enabled": False}}, report=rep)
    assert files == {"prospectus.pdf": b"%PDF-old"} and "disabled" in rep["reasons"][0]


def test_unexpected_error_never_fails_the_report(monkeypatch):
    monkeypatch.setattr(P, "_render_locked", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    rep: dict = {}
    files = P.render_print(fund_doc(), {}, fallback_pdf=lambda d, p: b"%PDF-old", fallback_docx=lambda d, p: b"PK",
                           cfg={}, report=rep)
    assert files["prospectus.pdf"] == b"%PDF-old" and "ValueError: boom" in rep["reasons"][0]


def test_host_lock_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(P.tempfile, "gettempdir", lambda: str(tmp_path))
    with P._host_lock(0) as first:
        assert first
        with P._host_lock(0) as second:
            assert not second


def test_lock_busy_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(P.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(P, "run_chromium", _fail)
    rep: dict = {}
    with P._host_lock(0):
        P.render_print(fund_doc(), {}, fallback_pdf=lambda d, p: b"%PDF", fallback_docx=lambda d, p: b"PK",
                       cfg={"print": {"lock_wait_s": 0}}, report=rep)
    assert "lock busy" in rep["reasons"][0]


def test_timeout_kills_the_process_group():
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        P._run([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)
    assert time.time() - t0 < 10


def test_worker_reports_errors_as_json(tmp_path):
    cp = subprocess.run([sys.executable, str(P.WORKER), str(tmp_path / "missing.json")], capture_output=True, text=True,
                        timeout=60)
    assert cp.returncode == 1 and json.loads(cp.stdout)["ok"] is False


# ── DOCX post-processing ──────────────────────────────────────────────────────────────────────────────────────────
def test_postprocess_docx_header_footer_fonts_and_repeat_header():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    p = d.add_paragraph()
    p.add_run("Body").font.name = "Calibri;Segoe UI;Arial;sans-serif"
    t = d.add_table(rows=3, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "MEASURE", "VALUE"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Yield", "3%"
    buf = io.BytesIO()
    d.save(buf)
    out = P.postprocess_docx(buf.getvalue(), fund_doc(), P.settings({}))
    z = zipfile.ZipFile(io.BytesIO(out))
    xml = z.read("word/document.xml").decode()
    assert "<w:tblHeader" in xml and "<w:cantSplit" in xml
    assert "Calibri;Segoe" not in xml
    footer = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("word/footer"))
    header = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("word/header"))
    assert " PAGE " in footer and " NUMPAGES " in footer
    assert fund_doc()["symbol"] in header
    assert P.version_date(fund_doc()) in header
    assert 'w:family w:val="swiss"' in z.read("word/fontTable.xml").decode() or "Calibri" not in z.read("word/fontTable.xml").decode()


# ── end to end (local hosts with Chromium + LibreOffice) ─────────────────────────────────────────────────────────
@pytest.mark.skipif(bool(_e2e_skip()), reason=str(_e2e_skip()))
def test_end_to_end_pdf_and_docx_match_the_report(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(P.tempfile, "tempdir", str(tmp_path))
    doc = fund_doc()
    rep: dict = {}
    files = P.render_print(doc, {}, fallback_pdf=_fail, fallback_docx=_fail, cfg={}, report=rep)
    assert rep["pdf"] == "chromium" and rep["docx"] == "libreoffice", rep
    assert files["prospectus.pdf"][:4] == b"%PDF"
    assert b"/Count " in files["prospectus.pdf"]
    z = zipfile.ZipFile(io.BytesIO(files["prospectus.docx"]))
    xml = z.read("word/document.xml").decode()
    assert "<w:tbl>" in xml and "<w:drawing>" in xml
    assert [n for n in z.namelist() if n.startswith("word/media/")]
    text = re.sub(r"<[^>]+>", "", xml)
    assert not re.search(r"\[F\d", text) and "Sources (" not in text
    for t in doc["sections"]:
        assert t["title"] in text
    assert "Fund structure &amp; holdings" in xml


@pytest.mark.skipif(bool(_chromium_ready()), reason=str(_chromium_ready()))
def test_print_page_blocks_all_network(tmp_path):
    page = tmp_path / "p.html"
    page.write_text('<html><body><img src="https://example.invalid/x.png"><link rel="stylesheet" '
                    'href="http://example.invalid/a.css"><p>x</p></body></html>', encoding="utf-8")
    res = P.run_chromium({"_dir": str(tmp_path), "html_path": str(page), "pdf_path": str(tmp_path / "p.pdf")}, 60)
    assert res["ok"] and res["blocked_requests"] >= 2
    assert (tmp_path / "p.pdf").read_bytes()[:4] == b"%PDF"
