"""Design v000 capture (design/README.md, AGENTS.md §28.8, §28.13): guards, ingest, privacy. Hermetic.

The guard refuses production 04:00-16:15 ET Mon-Fri and gates every page on portfolio-server memory (< 1.2 GB ok,
>= 1.2 GB wait, >= 1.3 GB or unreadable abort). Ingest turns a capture manifest into BASELINE status.json
fingerprints only (no image bytes, no host paths), skips needs_reader pages, and leaves design/ valid.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from scripts import design_capture_ingest as ing
from scripts.lib import design_capture_guard as g
from scripts.lib import design_pages as dp

ROOT = Path(__file__).resolve().parents[1]
PROD = "http://127.0.0.1:7777"


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=g.ET)


@pytest.mark.parametrize("when,refused", [
    (et(2026, 10, 26, 3, 59), False),   # Monday before 04:00
    (et(2026, 10, 26, 4, 0), True),     # Monday 04:00
    (et(2026, 10, 26, 12, 0), True),
    (et(2026, 10, 26, 16, 14), True),
    (et(2026, 10, 26, 16, 15), False),  # Monday 16:15 allowed
    (et(2026, 10, 25, 12, 0), False),   # Sunday
    (et(2026, 10, 31, 10, 0), False),   # Saturday
])
def test_market_window(when, refused):
    assert (g.window_refusal(PROD, when) is not None) is refused


def test_non_production_base_is_never_refused():
    assert g.window_refusal("http://127.0.0.1:4173", et(2026, 10, 26, 12, 0)) is None
    assert g.memory_verdict("http://127.0.0.1:4173", lambda: None)[0] == g.OK
    assert g.is_production("https://ms01-openclaw.tail163d14.ts.net/")


@pytest.mark.parametrize("mem,code", [(400_000_000, g.OK), (1_199_999_999, g.OK), (1_200_000_000, g.WAIT),
                                      (1_299_999_999, g.WAIT), (1_300_000_000, g.ABORT), (None, g.ABORT)])
def test_memory_gate(mem, code):
    assert g.memory_verdict(PROD, lambda: mem)[0] == code


def test_wrapper_refuses_before_starting_a_browser(tmp_path):
    # A fake clock is not injectable into bash; prove the wrapper consults the guard first and stops on its refusal.
    script = (ROOT / "scripts/design_capture.sh").read_text(encoding="utf-8")
    assert script.index("design_capture_guard.py") < script.index("node --experimental-strip-types")
    assert "${TMPDIR}" in script and "/tmp/" not in script.replace("/tmp/ (", "")
    ts = (ROOT / "apps/command-center-v3/e2e-live/design-capture.ts").read_text(encoding="utf-8")
    assert "['GET', 'HEAD', 'OPTIONS'].includes(req.method())" in ts and "abort('blockedbyclient')" in ts
    assert "refusing to write captures inside the repository" in ts
    assert ".config/tradeai" not in ts.replace("never reads credentials, ~/.config/tradeai", "")


def _copy_repo_design(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "design", tmp_path / "design")
    return tmp_path


def _manifest(store: Path, *, needs_reader=False):
    shots = []
    for width in (1440, 412, 390):
        for tab in ("default", "t01"):
            rel = f"v000/capture/home-{tab}-{width}.png"
            data = f"fake-png-{width}-{tab}".encode()
            (store / "pages/home" / rel).parent.mkdir(parents=True, exist_ok=True)
            (store / "pages/home" / rel).write_bytes(data)
            shots.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "role": "capture",
                          "width": width, "tab": tab})
    return {"schema": "DesignCaptureManifest@v1", "base": PROD, "version": "v000", "started_at": "2026-10-25T19:10:00Z",
            "finished_at": "2026-10-25T19:40:00Z", "aborted": None, "widths": [1440, 412, 390], "reader_identity": "none",
            "pages": [
                {"page": "home", "route": "/", "shots": shots, "tabs": ["Holdings"], "needs_reader": False, "auth_refusals": [],
                 "shell_refusals": ["403 /api/v2/cio/asks/tracked AGENT_CALLER_REFUSED"], "blocked_writes": [],
                 "blocked_side_effects": [], "errors": [], "memory": [{"bytes": 400_000_000, "verdict": "ok"}]},
                {"page": "approvals", "route": "/approvals", "shots": shots[:1], "tabs": [], "needs_reader": True,
                 "auth_refusals": ["403 /api/v2/governance/approvals AUTHENTICATED_READER_REQUIRED"], "shell_refusals": [],
                 "blocked_writes": [], "blocked_side_effects": [], "errors": [], "memory": []},
            ]}


def test_ingest_writes_valid_baseline_fingerprints_only(tmp_path):
    root = _copy_repo_design(tmp_path)
    store = tmp_path / "store"
    report = ing.ingest(_manifest(store), root=root, store=store)
    assert report["baseline"] == ["home"] and report["needs_reader"] == ["approvals"] and report["shots"] == 6
    assert dp.validate(root) == []
    status = json.loads((root / "design/pages/home/versions/v000/status.json").read_text(encoding="utf-8"))
    assert status["state"] == "BASELINE" and status["approval"] is None
    assert {f["role"] for f in status["private_assets"]["files"]} == {"capture"}
    assert status["capture"]["shell_refusals"] == ["403 /api/v2/cio/asks/tracked AGENT_CALLER_REFUSED"]
    reg = json.loads((root / "design/registry.json").read_text(encoding="utf-8"))
    home = next(p for p in reg["pages"] if p["id"] == "home")
    appr = next(p for p in reg["pages"] if p["id"] == "approvals")
    assert home["baseline_version"] == "v000" and [v["version"] for v in home["versions"]] == ["v000", "v001"]
    assert appr["baseline_version"] is None and appr["baseline_pending"] == "needs_reader"
    assert not (root / "design/pages/approvals/versions/v000").exists()
    assert "| v000 | BASELINE |" in (root / "design/pages/home/PAGE.md").read_text(encoding="utf-8")
    # nothing but text landed in the repo copy; no PNG and no host path
    for f in (root / "design").rglob("*"):
        assert f.suffix != ".png"
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            assert str(store) not in text and "/home/" not in text
    # idempotent
    before = (root / "design/pages/home/PAGE.md").read_text(encoding="utf-8")
    ing.ingest(_manifest(store), root=root, store=store)
    assert (root / "design/pages/home/PAGE.md").read_text(encoding="utf-8") == before


def test_ingest_refuses_changed_private_file_and_bad_paths(tmp_path):
    root = _copy_repo_design(tmp_path)
    store = tmp_path / "store"
    m = _manifest(store)
    (store / "pages/home" / m["pages"][0]["shots"][0]["path"]).write_bytes(b"tampered")
    with pytest.raises(ing.IngestError, match="changed"):
        ing.ingest(m, root=root, store=store)
    m = _manifest(store)
    m["pages"][0]["shots"][0]["path"] = "../../../etc/x.png"
    with pytest.raises(ing.IngestError, match="unexpected capture path"):
        ing.ingest(m, root=root, store=store, dry_run=True)


def test_baseline_may_hold_only_captures_with_widths(tmp_path):
    root = _copy_repo_design(tmp_path)
    store = tmp_path / "store"
    ing.ingest(_manifest(store), root=root, store=store)
    p = root / "design/pages/home/versions/v000/status.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    s["private_assets"]["files"][0]["width"] = 800
    s["private_assets"]["files"][1]["role"] = "mockups"
    p.write_text(json.dumps(s), encoding="utf-8")
    errs = dp.validate(root)
    assert any("names its width" in e for e in errs) and any("holds only captures" in e for e in errs)


def test_guard_cli_reports_json():
    out = subprocess.run(["python3", str(ROOT / "scripts/lib/design_capture_guard.py"), "window", "--base", "http://127.0.0.1:4173"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and json.loads(out.stdout)["allowed"] is True


def test_partial_page_from_an_aborted_run_is_not_a_baseline(tmp_path):
    root = _copy_repo_design(tmp_path)
    store = tmp_path / "store"
    m = _manifest(store)
    m["pages"][0]["shots"] = [x for x in m["pages"][0]["shots"] if x["width"] == 1440]
    report = ing.ingest(m, root=root, store=store)
    assert report["incomplete"] == ["home"] and report["baseline"] == []
    reg = json.loads((root / "design/registry.json").read_text(encoding="utf-8"))
    assert next(p for p in reg["pages"] if p["id"] == "home")["baseline_pending"] == "incomplete capture"
    assert dp.validate(root) == []


def test_tab_labels_never_reach_the_repo(tmp_path):
    # A label can be a ticker or a count ("Held 9"); a label-derived file name is refused.
    root = _copy_repo_design(tmp_path)
    store = tmp_path / "store"
    m = _manifest(store)
    m["pages"][0]["shots"][1]["path"] = "v000/capture/home-zzqx-1440.png"
    m["pages"][0]["shots"][1]["tab"] = "ZZQX"
    with pytest.raises(ing.IngestError, match="keyed default/tNN"):
        ing.ingest(m, root=root, store=store, dry_run=True)
    ing.ingest(_manifest(store), root=root, store=store)
    text = (root / "design/pages/home/versions/v000/status.json").read_text(encoding="utf-8")
    assert "Holdings" not in text and '"tab_count": 1' in text
