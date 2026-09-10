from scripts.gog_drive_safe import _parse_uploaded_id


def test_parse_nested_file_id():
    assert _parse_uploaded_id('{"file":{"id":"abc123","name":"x.md"}}') == "abc123"


def test_parse_top_level_id():
    assert _parse_uploaded_id('{"id":"topid"}') == "topid"


def test_parse_empty():
    assert _parse_uploaded_id("") is None
