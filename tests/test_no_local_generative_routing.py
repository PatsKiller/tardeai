from scripts.audit_no_local_generative_routing import audit
from scripts.lib.llm_task_policy import allow_local_llm


def test_production_automatic_routing_has_no_local_generation():
    report = audit()
    assert report["violations"] == []


def test_runtime_flags_cannot_enable_generation(monkeypatch):
    monkeypatch.setenv("RESEARCH_ALLOW_LOCAL_LLM", "1")
    monkeypatch.setenv("LLM_ALLOW_LOCAL_JUDGMENT", "1")
    for task in ("math", "research", "sentiment", "thesis", "cio_synthesis"):
        assert allow_local_llm(task) is False


def test_embedding_contract_is_the_only_local_allowance():
    assert allow_local_llm("embed", local_model="nomic-embed-text") is True
    assert allow_local_llm("embed", local_model="unapproved") is False
