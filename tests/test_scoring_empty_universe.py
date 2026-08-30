from scripts.scoring import score_all


def test_empty_universe_does_not_crash_post_processing():
    assert score_all([], {}, project_root=".", use_llm=False) == []
