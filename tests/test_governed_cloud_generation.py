import pytest

from scripts.lib.governed_cloud_generation import generate_cloud


class FakeLane:
    def __init__(self, available, responses):
        self.available_lanes = set(available)
        self.responses = dict(responses)
        self.calls = []

    def available(self, lane):
        return lane in self.available_lanes

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        value = self.responses[kwargs["lane"]]
        if isinstance(value, Exception):
            raise value
        return value


def test_cloud_helper_falls_between_governed_cloud_lanes(monkeypatch):
    fake = FakeLane({"grok", "chatgpt"}, {"grok": RuntimeError("down"), "chatgpt": "ok"})
    monkeypatch.setitem(__import__("sys").modules, "llm_lane", fake)
    text, lane = generate_cloud(
        "prompt", process_id="test_process", task_summary="test task",
    )
    assert (text, lane) == ("ok", "chatgpt")
    assert [call[1]["lane"] for call in fake.calls] == ["grok", "chatgpt"]
    assert all(call[1]["process_id"] == "test_process" for call in fake.calls)


def test_cloud_helper_rejects_local_lane_before_call(monkeypatch):
    fake = FakeLane({"local"}, {"local": "forbidden"})
    monkeypatch.setitem(__import__("sys").modules, "llm_lane", fake)
    with pytest.raises(RuntimeError, match="POLICY_LOCAL_GENERATIVE_FORBIDDEN"):
        generate_cloud(
            "prompt", process_id="test_process", task_summary="test task",
            lanes=("local",),
        )
    assert fake.calls == []


def test_cloud_helper_fails_closed_when_no_lane_available(monkeypatch):
    fake = FakeLane(set(), {})
    monkeypatch.setitem(__import__("sys").modules, "llm_lane", fake)
    with pytest.raises(RuntimeError, match="CLOUD_GENERATION_FAILED_CLOSED"):
        generate_cloud("prompt", process_id="test_process", task_summary="test task")
