"""LQ-20261107-1188: n8n-data-plausibility-audit / n8n-gap-resolution-audit --dry-run exited 1 on FINDINGS (the legacy
CLI convention), so the 15:25 dry run graded both lanes exit_1. Lane contract (entry-script docstring): exit 0 = the run
completed, findings are output; non-zero = could not measure. The legacy systemd CLI keeps exit 1 on findings. Hermetic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _plaus(monkeypatch):
    import data_plausibility_monitor as m

    class Cur:
        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    block = {"status": "VIOLATION", "severity": "BLOCK", "table": "t", "column": "c", "rule": "null_rate",
             "violations": 9, "total": 10, "detail": "d", "samples": []}
    monkeypatch.setattr(m, "measure", lambda cur, doc: [block])
    return m, Conn


def test_plausibility_lane_dry_run_with_a_blocking_finding_exits_zero(monkeypatch, capsys):
    m, Conn = _plaus(monkeypatch)
    assert m.lane_main(["--dry-run"], connect=Conn) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_plausibility_legacy_cli_still_exits_one_on_a_blocking_finding(monkeypatch):
    m, Conn = _plaus(monkeypatch)
    args = m._parser().parse_args(["--dry-run"])
    assert not getattr(args, "lane", False)
    assert m._run(args, connect=Conn, deliver=lambda *a, **k: None) == 1


def _gap_report():
    f = {"RETIRED_RAN": [], "REFUSED_NOWHERE": [], "VECTOR_FAILING": [],
         "OPEN_NO_ATTEMPT": [{"gap_id": 1, "domain": "d", "subject": "S", "age_hours": 1.0, "origin": "gap_queue"}]}
    return {"findings": f, "finding_count": 1, "receipts": 0, "queued_gaps": 1, "research_gaps": 0, "search_denials": 0}


def test_gap_resolution_lane_dry_run_with_findings_exits_zero():
    import check_gap_resolution as g
    assert g.lane_main(["--dry-run"], collect_fn=_gap_report) == 0


def test_gap_resolution_legacy_cli_still_exits_one_on_findings():
    import check_gap_resolution as g
    args = g._parser().parse_args(["--dry-run"])
    assert g._run(args, collect_fn=_gap_report, deliver=lambda *a, **k: None) == 1


def test_a_collect_failure_still_fails_the_lane_dry_run():
    import check_gap_resolution as g

    def boom():
        raise RuntimeError("db down")
    assert g.lane_main(["--dry-run"], collect_fn=boom) == 2
