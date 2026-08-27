from __future__ import annotations


def test_legacy_morning_bundle_is_blocked_when_canonical_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CANONICAL_OPERATOR_BRIEF", "0")

    import morning_command_digest as mod

    def _must_not_send(*args, **kwargs):
        raise AssertionError("legacy morning path attempted Telegram delivery")

    monkeypatch.setattr(mod, "archive_sections", _must_not_send)
    assert mod.send_morning_command_bundle({"portfolio": "stale data"}, tmp_path) is False


def test_canonical_morning_path_remains_selected_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CANONICAL_OPERATOR_BRIEF", raising=False)

    import morning_command_digest as mod

    calls = {}

    class _Renderer:
        @staticmethod
        def deliver_morning(**kwargs):
            calls.update(kwargs)
            return {"handled": True, "published": True, "key": "morning:test"}

    monkeypatch.setitem(__import__("sys").modules, "lib.cio_operator_renderers", _Renderer)
    assert mod.send_morning_command_bundle({"health": "ok"}, tmp_path) is True
    assert calls["root"] == tmp_path
    assert calls["send"] is True
