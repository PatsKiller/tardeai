"""Ollama → governed DeepSeek Flash failover (no live network)."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from hermes_llm_failover import HermesLlmError, chat_json, failover_enabled, primary_provider


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_failover_enabled_default(monkeypatch):
    monkeypatch.delenv("HERMES_OLLAMA_FAILOVER", raising=False)
    monkeypatch.delenv("HERMES_LLM_PRIMARY", raising=False)
    assert failover_enabled() is True
    assert primary_provider() == "bridge_flash"
    monkeypatch.setenv("HERMES_OLLAMA_FAILOVER", "0")
    assert failover_enabled() is False


def test_flash_primary_success(monkeypatch):
    monkeypatch.delenv("HERMES_LLM_PRIMARY", raising=False)

    def _urlopen(req, timeout=None):
        url = getattr(req, "full_url", None) or str(req)
        if "8766/v1/chat/completions" in url:
            return _Resp(json.dumps({
                "choices": [{"message": {"content": '{"ok":true,"src":"flash"}'}}],
            }).encode())
        raise AssertionError(f"ollama should not be called: {url}")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    pack = chat_json("hi", ollama_model="gemma3:12b", ollama_timeout_s=5)
    assert pack["failover"] is False
    assert pack["provider"] == "bridge_flash"
    assert pack["model"] == "deepseek-v4-flash"
    assert json.loads(pack["content"])["src"] == "flash"


def test_flash_primary_falls_to_ollama(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PRIMARY", "bridge_flash")
    ollama_body = json.dumps({"message": {"content": '{"ok":true,"src":"ollama"}'}}).encode()

    def _urlopen(req, timeout=None):
        url = getattr(req, "full_url", None) or str(req)
        if "8766" in url:
            raise TimeoutError("bridge busy")
        if "11434/api/tags" in url:
            return _Resp(b'{"models":[]}')
        if "11434/api/chat" in url:
            return _Resp(ollama_body)
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    pack = chat_json("hi", ollama_model="gemma3:12b", ollama_timeout_s=5)
    assert pack["failover"] is True
    assert pack["provider"] == "ollama"
    assert "bridge_flash_error" in (pack["reason"] or "")
    assert json.loads(pack["content"])["src"] == "ollama"


def test_ollama_primary_success(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PRIMARY", "ollama")
    ollama_body = json.dumps({"message": {"content": '{"summary":"ok","ok":true}'}}).encode()

    def _urlopen(req, timeout=None):
        url = getattr(req, "full_url", None) or str(req)
        if "11434/api/tags" in url:
            return _Resp(b'{"models":[]}')
        if "11434/api/chat" in url:
            return _Resp(ollama_body)
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    pack = chat_json("hi", ollama_model="gemma3:12b", ollama_timeout_s=5)
    assert pack["failover"] is False
    assert pack["provider"] == "ollama"
    assert json.loads(pack["content"])["ok"] is True


def test_ollama_primary_unhealthy_uses_flash(monkeypatch):
    monkeypatch.setenv("HERMES_LLM_PRIMARY", "ollama")

    def _urlopen(req, timeout=None):
        url = getattr(req, "full_url", None) or str(req)
        if "11434" in url:
            raise TimeoutError("ollama down")
        if "8766/v1/chat/completions" in url:
            return _Resp(json.dumps({
                "choices": [{"message": {"content": '{"summary":"flash","ok":true}'}}],
            }).encode())
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    pack = chat_json("hi", ollama_model="gemma3:12b", ollama_timeout_s=5)
    assert pack["failover"] is True
    assert pack["provider"] == "bridge_flash"
    assert "ollama" in (pack["reason"] or "")
    assert json.loads(pack["content"])["ok"] is True


def test_failover_off_raises(monkeypatch):
    monkeypatch.setenv("HERMES_OLLAMA_FAILOVER", "0")
    monkeypatch.setenv("HERMES_LLM_PRIMARY", "bridge_flash")

    def _urlopen(req, timeout=None):
        raise TimeoutError("down")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    with pytest.raises(HermesLlmError):
        chat_json("hi", ollama_model="gemma3:12b", ollama_timeout_s=1, probe_first=False)
