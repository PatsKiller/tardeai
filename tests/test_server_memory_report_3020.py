"""LQ-20261113-3020: the memory-series summarizer, on synthetic JSONL (v2 and the lead's interim v1)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ops import server_memory_report as rp  # noqa: E402


def row(ts, cur=1_000_000_000, high=0, pid=1, rel="a", threads=60, close_wait=0, psi=0.0, reaped=None, markers=None):
    r = {"ts": ts, "pid": pid, "release": rel, "cg_current_b": cur, "cg_events_delta": {"high": high},
         "proc": {"rss_kb": cur // 1024, "hwm_kb": cur // 1024, "threads": threads},
         "tcp7777": {"est": 1, "close_wait": close_wait},
         "cg_pressure": f"some avg10={psi} avg60=0 avg300=0 total=1 | full avg10=0.00 avg60=0 avg300=0 total=1"}
    if reaped is not None:
        r["app_log"] = {"reaped": reaped}
    if markers:
        r["markers"] = markers
    return r


def write(tmp_path, rows, extra=""):
    p = tmp_path / "s.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)
    return p


def test_peaks_gap_and_bursts(tmp_path):
    rows = [row(t) for t in range(0, 20, 2)]
    rows[3] = row(6, cur=2_800_000_000, high=5, threads=140, close_wait=9, psi=12.5)
    rows[4] = row(8, cur=2_600_000_000, high=3, threads=120)
    rows[8] = row(16, high=1)
    rows = [r for r in rows if r["ts"] != 12]   # a stall: 10 -> 14 is a 4 s gap
    rep = rp.report(*rp.load(write(tmp_path, rows)))
    assert {k: rep["peaks"]["cg_current_b"][k] for k in ("value", "ts")} == {"value": 2_800_000_000, "ts": 6}
    assert rep["peaks"]["threads"]["value"] == 140 and rep["peaks"]["tcp_close_wait"]["value"] == 9
    assert rep["peaks"]["psi_some10"]["value"] == 12.5
    assert rep["span"]["max_gap_s"] == 4 and rep["span"]["max_gap_at"] == 10
    assert [(b["start"], b["end"], b["high_events"]) for b in rep["high_bursts"]] == [(6, 8, 8), (16, 16, 1)]
    assert rep["high_bursts"][0]["max_threads"] == 140


def test_pid_and_release_changes(tmp_path):
    rows = [row(1), row(3), row(5, pid=2, rel="b"), row(7, pid=2, rel="b")]
    rep = rp.report(*rp.load(write(tmp_path, rows)))
    assert [{k: v for k, v in c.items() if k != "ts_et"} for c in rep["pid_changes"]] == [{"ts": 5, "from": 1, "to": 2, "release_from": "a", "release_to": "b"}]
    assert [{k: v for k, v in c.items() if k != "ts_et"} for c in rep["release_changes"]] == [{"ts": 5, "from": "a", "to": "b"}]


def test_correlation_window_counts_reaped_lines(tmp_path):
    rows = [row(t, reaped=0) for t in range(0, 60, 2)]
    rows[5] = row(10, cur=3_000_000_000, high=2, reaped=2)
    rows[6] = row(12, reaped=1)
    rows[25] = row(50, reaped=7)   # far outside the window
    rep = rp.report(*rp.load(write(tmp_path, rows)), window_s=4)
    peak = next(c for c in rep["correlation"] if c["what"] == "peak_cg_current")
    assert peak["reaped_log_lines"] == 3 and peak["max_cg_current_b"] == 3_000_000_000
    assert any(c["what"] == "high_burst" for c in rep["correlation"])


def test_interim_v1_rows_and_junk_lines(tmp_path):
    v1 = {"ts": 5.0, "pid": 1, "cg_current_b": 10, "cg_events_delta": {"high": 0}, "proc": {"rss_kb": 1}}
    p = write(tmp_path, [v1, row(7)], extra="not json\n[1]\n" + json.dumps({"ts": 9, "markers": ["stopped_at_cap"]}) + "\n")
    rows, bad = rp.load(p)
    assert len(rows) == 2 and bad == 2
    rep = rp.report(rows, bad)
    assert rep["peaks"]["psi_some10"]["value"] == 0.0   # present on v2 row only; v1's absence is not 0


def test_recreated_marker_listed(tmp_path):
    rep = rp.report(*rp.load(write(tmp_path, [row(1), row(3, markers=["cgroup_recreated"])])))
    assert rep["recreated"] == [3]


def test_empty_and_missing_file(tmp_path, capsys):
    assert rp.report([], 0)["samples"] == 0
    assert rp.main([str(tmp_path / "none.jsonl")]) == 2
    p = write(tmp_path, [row(1)])
    assert rp.main([str(p)]) == 0 and '"samples": 1' in capsys.readouterr().out


def test_rework_a_failed_unit_read_is_not_a_pid_change_in_the_report(tmp_path):
    rows = [row(1, pid=100), row(3, pid=None, markers=["unit_read_failed"]), row(5, pid=100), row(7, pid=101)]
    rep = rp.report(*rp.load(write(tmp_path, rows)))
    assert [(c["from"], c["to"]) for c in rep["pid_changes"]] == [(100, 101)]
    assert [f["ts"] for f in rep["unit_read_failures"]] == [3]


def test_rework_times_carry_an_eastern_string(tmp_path):
    rep = rp.report(*rp.load(write(tmp_path, [row(1_794_600_000), row(1_794_600_002, cur=2_000_000_000)])))
    assert rep["peaks"]["cg_current_b"]["ts_et"] == rp.et(1_794_600_002) and rep["span"]["first_ts_et"].endswith(("-05:00", "-04:00"))
    assert rp.et(None) is None


def test_rework_a_stopped_on_error_line_is_a_marker_not_a_sample(tmp_path):
    p = write(tmp_path, [row(1)], extra=json.dumps({"ts": 2, "markers": ["stopped_on_error"]}) + "\n")
    rows, bad = rp.load(p)
    assert len(rows) == 1 and bad == 0
