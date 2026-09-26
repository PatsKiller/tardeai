"""Redacted options runtime export for the Drive mirror (operator 2026-09-26: REDACTED).

No account names and no dollar amounts leave the machine: the exporter copies a
strict allowlist, scrubs free text, and refuses to write when anything
account-number-like survives. The sync maps the export dir to runtime/options/ and
never deletes the Drive copy when an export is missing.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_options_runtime_snapshot.py"
SYNC = ROOT / "scripts" / "sync-docs-to-drive.sh"


def _load():
    spec = importlib.util.spec_from_file_location("_opt_export", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GUID_A = "962917b5-eba2-5210-920b-89045312a9cc"
GUID_B = "a8392593-832b-592a-987e-7dfe90752208"
TERMS = ["schwab_taxable", "schwab_rollover_ira", "schwab_roth_ira"]


def _version(guid, v, symbol="DELL", recorded="2026-09-26T15:00:00+00:00", **extra):
    rec = {
        "schema": "OptionsThesisRecord@v1", "event_type": "OPTIONS_THESIS_VERSION",
        "position_guid": guid, "symbol": symbol, "strategy_type": "cash_secured_put",
        "proposal_id": f"opt_cash_secured_put_{symbol}_schwab_taxable_490p0000_20261120_d20260926",
        "investment_thesis": {"summary": f"{symbol} thesis v{v}; premium $2,157 in schwab_taxable account"},
        "catalysts": ["earnings 2026-11-04"], "exit_criteria": ["close below 200-day"],
        "risk_factors": ["Max loss per contract $46,843.0"],
        "entry_criteria": {"strike": 490.0, "expiration": "2026-11-20", "dte": 55, "premium": 21.57,
                           "breakeven": 468.43, "underlying_price": 524.14},
        "portfolio_impact": {"account": "schwab_taxable", "max_loss": 46843.0, "capital_required": 2157.0},
        "premium_total": 2157.0, "contracts": 1, "bid": 21.4, "ask": 21.7, "cash": 90000,
        "missing_required": [], "thesis_gate_state": "CURRENT", "version": v,
        "pin": f"opt_{guid}@v{v}", "supersedes": (f"opt_{guid}@v{v-1}" if v > 1 else None),
        "recorded_at": recorded,
    }
    rec.update(extra)
    return rec


def _events():
    return [
        _version(GUID_A, 1, recorded="2026-09-26T15:00:00+00:00"),
        _version(GUID_B, 1, symbol="HOOD", recorded="2026-09-26T15:10:00+00:00"),
        _version(GUID_A, 2, recorded="2026-09-26T16:00:00+00:00"),
        {"event_type": "OPTIONS_THESIS_DECISION", "position_guid": GUID_A, "decision_guid": "dec_1",
         "outcome": "MORE_RESEARCH", "confidence": "MEDIUM",
         "review": {"reasoning": "Premium $228 against $10,972 max loss; max loss of 10,972 in schwab_rollover_ira.",
                    "concerns": ["thin premium ($228)"], "unknowns": ["no thesis"],
                    "evidence_for": ["Defined max loss of 10,972"]},
         "model": {"cost_estimate": 0.0004}, "recorded_at": "2026-09-26T17:00:00+00:00"},
        {"event_type": "OPTIONS_THESIS_FOLLOWUP_REQUESTED", "position_guid": GUID_A,
         "deliverables": [{"intent": "thesis", "text": "Author a DELL thesis"}],
         "due_at": "2026-09-27T17:00:00+00:00", "recorded_at": "2026-09-26T17:05:00+00:00"},
        {"event_type": "OPTIONS_VALIDATED", "position_guid": GUID_A, "status": "CHANGED",
         "material_changes": ["premium 21.57 -> 19 (-11.9%)", "no two-sided quote"],
         "live": {"bid": 18.9, "ask": 19.1}, "recomputed": {"max_loss": 47100.0},
         "validated_at": "2026-09-26T17:10:00+00:00", "recorded_at": "2026-09-26T17:10:01+00:00"},
    ]


def _cfg(mod, **over):
    cfg = dict(mod.DEFAULTS, use_db=False)
    cfg.update(over)
    return cfg


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_allowlist_and_redaction():
    mod = _load()
    res = mod.build(_cfg(mod), events=_events(), db_rows=[], terms=TERMS, generated_at="T")
    assert res["violations"] == []
    everything = "".join(res["files"].values())
    for bad in ("schwab_", "$2", "$1", "$4", "46843", "46,843", "10,972", "2157", "21.57", "524.14", "468.43",
                "90000", "cost_estimate", "proposal_id"):
        assert bad not in everything, bad
    for name, text in res["files"].items():
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                keys = set(_walk_keys(json.loads(line)))
                forbidden = {k for k in keys if k in mod.FORBIDDEN_KEYS or k.endswith("_total")}
                assert not forbidden, (name, forbidden)
    thesis = [json.loads(x) for x in res["files"]["options_theses_latest.jsonl"].splitlines()]
    a = next(t for t in thesis if t["position_guid"] == GUID_A)
    assert a["strike"] == 490.0 and a["expiration"] == "2026-11-20" and a["dte"] == 55
    assert "[account]" in a["investment_thesis"] and "$[redacted]" in a["investment_thesis"]
    assert a["validation"] == {"status": "CHANGED", "material_changes": ["premium (-11.9%)", "no two-sided quote"],
                               "validated_at": "2026-09-26T17:10:00+00:00"}
    assert a["followup"]["deliverables"] == ["Author a DELL thesis"]
    assert a["lifecycle_stage"] == "CIO_FOLLOWUP_RESEARCH"
    assert a["latest_decision"]["decision_guid"] == "dec_1"


def test_latest_version_per_guid():
    mod = _load()
    res = mod.build(_cfg(mod), events=_events(), db_rows=[], terms=TERMS, generated_at="T")
    thesis = [json.loads(x) for x in res["files"]["options_theses_latest.jsonl"].splitlines()]
    assert len(thesis) == 2
    a = next(t for t in thesis if t["position_guid"] == GUID_A)
    assert a["version"] == 2 and a["pin"] == f"opt_{GUID_A}@v2" and a["supersedes"] == f"opt_{GUID_A}@v1"


def test_decisions_merge_db_and_cap(monkeypatch):
    mod = _load()
    rows = [{"decision_id": "dec_1", "symbol": "DELL", "action": "MORE_RESEARCH", "status": "proposed",
             "created_at": "2026-09-26T17:00:00+00:00",
             "metadata": json.dumps({"position_guid": GUID_A, "review": {"outcome": "MORE_RESEARCH"}})},
            {"decision_id": "dec_0", "symbol": "HOOD", "action": "REJECT", "status": "proposed",
             "created_at": "2026-09-25T10:00:00+00:00", "metadata": {"review": {"reasoning": "cash $5,000"}}}]
    res = mod.build(_cfg(mod), events=_events(), db_rows=rows, terms=TERMS, generated_at="T")
    dec = [json.loads(x) for x in res["files"]["cio_options_decisions_latest.jsonl"].splitlines()]
    assert [d["decision_guid"] for d in dec] == ["dec_1", "dec_0"]  # newest first, deduped
    assert dec[0]["status"] == "proposed" and dec[0]["reviewed_pin"] is None
    res1 = mod.build(_cfg(mod, decisions_max=1), events=_events(), db_rows=rows, terms=TERMS, generated_at="T")
    assert len(res1["files"]["cio_options_decisions_latest.jsonl"].splitlines()) == 1
    monkeypatch.setenv("TRADEAI_OPTIONS_EXPORT_DECISIONS_MAX", "7")
    assert mod.settings()["decisions_max"] == 7


def test_stable_filenames_have_no_dates():
    mod = _load()
    res = mod.build(_cfg(mod), events=_events(), db_rows=[], terms=TERMS, generated_at="T")
    assert sorted(res["files"]) == ["cio_options_decisions_latest.jsonl", "cio_options_decisions_latest.md",
                                    "options_theses_latest.jsonl", "options_theses_latest.md"]


def _write_source(tmp_path: Path) -> Path:
    rt = tmp_path / "rt"
    (rt / "data" / "cio").mkdir(parents=True)
    (rt / "data" / "cio" / "options_theses.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in _events()), encoding="utf-8")
    (rt / "config").mkdir()
    (rt / "config" / "account_capabilities.json").write_text(
        json.dumps({"accounts": {t: {} for t in TERMS}}), encoding="utf-8")
    return rt


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    mod = _load()
    rt = _write_source(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setenv("TRADEAI_RUNTIME_ROOT", str(rt))
    monkeypatch.setenv("TRADEAI_RUNTIME_EXPORT_ROOT", str(out))
    assert mod.main(["--no-db"]) == 0
    assert not out.exists()
    assert '"mode": "dry_run"' in capsys.readouterr().out


def test_apply_writes_atomically(tmp_path, monkeypatch):
    mod = _load()
    rt = _write_source(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setenv("TRADEAI_RUNTIME_ROOT", str(rt))
    monkeypatch.setenv("TRADEAI_RUNTIME_EXPORT_ROOT", str(out))
    replaced = []
    real = mod.os.replace
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (replaced.append((a, b)), real(a, b)))
    assert mod.main(["--apply", "--no-db"]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["cio_options_decisions_latest.jsonl", "cio_options_decisions_latest.md",
                     "options_theses_latest.jsonl", "options_theses_latest.md"]  # no tmp left behind
    assert len(replaced) == 4 and all(Path(a).parent == out and Path(a).name.endswith(".tmp") for a, _ in replaced)
    md = (out / "options_theses_latest.md").read_text(encoding="utf-8")
    assert "| Symbol |" in md and "DELL" in md
    for t in TERMS:
        assert t not in md
    assert "$2" not in md and "$4" not in md


def test_refuses_account_number_like_values(tmp_path):
    mod = _load()
    ev = _events()
    ev[2]["catalysts"] = ["wire from acct 12345678 pending"]
    res = mod.build(_cfg(mod), events=ev, db_rows=[], terms=TERMS, generated_at="T")
    assert any("account-number-like" in v for v in res["violations"])
    with pytest.raises(RuntimeError):
        mod.write(res, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_guids_and_timestamps_are_not_account_numbers():
    mod = _load()
    cfg = _cfg(mod)
    ok = {"g": GUID_A, "t": "2026-09-26T17:10:00.123456+00:00", "p": f"opt_{GUID_A}@v12", "x": "rvol 0.16"}
    assert mod.find_violations(ok, cfg, TERMS) == []


# ── sync integration ──

def _between(body: str, start: str, end: str) -> str:
    a = body.index(start)
    b = body.index(end, a)
    return body[a:b]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_sync_maps_runtime_exports_and_preserves_them(tmp_path):
    body = SYNC.read_text(encoding="utf-8")
    block = _between(body, "# ── Runtime exports (outside the release tree) ──", "# ── Preserved captures ──")
    preserved = _between(body, "is_preserved_capture() {", "\n}\n") + "\n}\n"
    exp = tmp_path / "exports"
    harness = f"""
set -euo pipefail
SRC="{tmp_path}/src"
export TRADEAI_RUNTIME_EXPORT_ROOT="{exp}"
{block}
{preserved}
echo "$(candidate_relpath "{exp}/options_theses_latest.md")"
echo "$(candidate_relpath "$SRC/docs/A.md")"
is_preserved_capture runtime/options/options_theses_latest.md && echo PRESERVED
is_preserved_capture docs/A.md || echo NOT_PRESERVED
"""
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "runtime/options/options_theses_latest.md",
        "docs/A.md",
        "PRESERVED",
        "NOT_PRESERVED",
    ]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_missing_runtime_export_is_kept_by_cleanup(tmp_path):
    """The real cleanup pass, gog stubbed: a missing export is never removed from Drive."""
    body = SYNC.read_text(encoding="utf-8")
    block = _between(body, "# ── Runtime exports (outside the release tree) ──", "# ── Preserved captures ──")
    preserved = _between(body, "is_preserved_capture() {", "\n}\n") + "\n}\n"
    excluded = _between(body, "is_runtime_dump_excluded() {", "\n}\n") + "\n}\n"
    cleanup = body[body.index("# ── Cleanup: remove Drive files whose local source was deleted ──"):]
    src = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    exp = tmp_path / "exports"
    exp.mkdir()
    (exp / "cio_options_decisions_latest.md").write_text("x", encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    lines = ["runtime/options/options_theses_latest.md|abc", "runtime/options/cio_options_decisions_latest.md|def"]
    manifest.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
    log = tmp_path / "log"
    rm_calls = tmp_path / "rm"
    harness = f"""
SRC="{src}"
MANIFEST="{manifest}"
LOG="{log}"
DRIVE_FOLDER_ID=root
GOG_ACCOUNT=test
export TRADEAI_RUNTIME_EXPORT_ROOT="{exp}"
log() {{ echo "$1" >> "$LOG"; }}
resolve_existing_folder() {{ echo parent; }}
gog() {{
  if [ "$2" = "ls" ]; then echo '{{"files":[{{"id":"ID1","name":"x","mimeType":"text/plain"}}]}}';
  elif [ "$2" = "rm" ]; then echo "$3" >> "{rm_calls}"; fi
}}
{block}
{preserved}
{excluded}
{cleanup}
"""
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert not rm_calls.exists()
    kept = manifest.read_text(encoding="utf-8").splitlines()
    assert kept == lines  # missing one preserved, present one untouched
    assert "kept 1 preserved capture" in log.read_text(encoding="utf-8")
