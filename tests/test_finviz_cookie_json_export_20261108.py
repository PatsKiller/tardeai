"""Operator 2026-11-08: a browser cookie-extension JSON export pasted into Admin must be accepted (synthetic values)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "secrets"))
from resolve_secret import normalize_finviz_cookie_value, validate_finviz_cookie_value  # noqa: E402

AUTH = "A" * 120
EXPORT = json.dumps([
    {"domain": ".finviz.com", "name": "chartsTheme", "value": "dark"},
    {"domain": "elite.finviz.com", "name": ".AspNetCore.Session", "value": "SESSIONSYNTH"},
    {"domain": ".example.com", "name": "tracker", "value": "nope"},
    {"domain": ".finviz.com", "name": ".ASPXAUTH", "value": AUTH},
], indent=2)


def test_json_export_becomes_cookie_header_and_validates():
    out = normalize_finviz_cookie_value(EXPORT)
    assert out == f"chartsTheme=dark; .AspNetCore.Session=SESSIONSYNTH; .ASPXAUTH={AUTH}"
    validate_finviz_cookie_value(out)


def test_header_string_unchanged():
    h = f"  chartsTheme=dark; .ASPXAUTH={AUTH}  "
    assert normalize_finviz_cookie_value(h) == h.strip()


def test_json_without_auth_still_rejected():
    out = normalize_finviz_cookie_value(json.dumps([{"domain": ".finviz.com", "name": "x", "value": "y" * 80}]))
    try:
        validate_finviz_cookie_value(out)
    except ValueError as e:
        assert ".ASPXAUTH=" in str(e) and "y" * 10 not in str(e)
    else:
        raise AssertionError("must reject")


def test_bad_json_passes_through():
    assert normalize_finviz_cookie_value("[not json") == "[not json"
