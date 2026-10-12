"""Monitor write admission: injected snapshots cannot become installed health proof."""

import json

import pytest

from scripts import n8n_momentum_lifecycle as cli


def test_fixture_cannot_write_health_even_with_a_dry_run_flag(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No input/admission/write may precede the source boundary")

    monkeypatch.setattr(cli, "load_admission", forbidden)
    monkeypatch.setattr(cli, "write_monitor", forbidden)
    for extra in ([], ["--dry-run"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(
                [
                    "--snapshot",
                    str(tmp_path / "fixture.json"),
                    "--code-root",
                    str(tmp_path / "code"),
                    "--state-root",
                    str(tmp_path / "state"),
                    "--write-monitor",
                    *extra,
                ]
            )
        assert exc.value.code == 2


def test_host_collector_gets_independent_code_admission_and_dry_run_never_writes(tmp_path, monkeypatch):
    code, state = tmp_path / "code", tmp_path / "state"
    candidate = code / "config/n8n_momentum_lifecycle_candidate.json"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(json.dumps({"enabled": True}))
    admission = object()
    calls, writes = [], []
    monkeypatch.setattr(cli, "load_admission", lambda root: admission if root == code else None)

    def collect(root, policy, **kwargs):
        calls.append((root, policy, kwargs))
        return {"products": {}}

    monkeypatch.setattr(cli, "collect_server_snapshot", collect)
    monkeypatch.setattr(cli, "evaluate", lambda *args, **kwargs: {"incidents": []})
    monkeypatch.setattr(cli, "plan_recovery", lambda *args, **kwargs: {"actions": []})
    monkeypatch.setattr(cli, "monitor_admitted", lambda value: value is admission)
    monkeypatch.setattr(cli, "write_monitor", lambda report, root: writes.append((report, root)))
    args = [
        "--host-snapshot",
        "--code-root",
        str(code),
        "--state-root",
        str(state),
        "--candidate",
        str(candidate),
        "--write-monitor",
        "--now",
        "2026-10-12T14:00:00+00:00",
    ]
    assert cli.main([*args, "--dry-run"]) == 0
    assert writes == []
    assert calls[0][0] == state
    assert calls[0][2]["admission"] is admission and calls[0][2]["code_root"] == code
    actual_args = args[: args.index("--now")]
    assert cli.main(actual_args) == 0
    assert len(writes) == 1 and writes[0][1] == state
    assert writes[0][0]["incidents"] == [] and writes[0][0]["recovery"] == {"actions": []}
    assert writes[0][0]["collection_source"] == "HOST_SNAPSHOT"
    assert writes[0][0]["candidate_sha256"] == cli.contract_body_digest({"enabled": True})


@pytest.mark.parametrize("extra", [["--candidate", "alternate.json"], ["--now", "2026-10-12T14:00:00+00:00"]])
def test_runtime_write_cannot_select_an_alternate_policy_or_clock(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(cli, "load_admission", lambda *args: pytest.fail("boundary must reject before collection"))
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "--host-snapshot",
                "--code-root",
                str(tmp_path / "code"),
                "--state-root",
                str(tmp_path / "state"),
                "--write-monitor",
                *extra,
            ]
        )
    assert exc.value.code == 2
