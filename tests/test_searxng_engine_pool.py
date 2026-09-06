"""Every engine in the pool was verified by query before being listed.

The pool reached 2026-09-05 with six declared engines and ONE that worked.
Four were blocked by anti-bot walls and one did not exist at all:

    brave         "too many requests"     (raises)
    duckduckgo    "CAPTCHA"               (raises)
    startpage     "Suspended: CAPTCHA"    (raises)
    google        0 results, NO error     (silent — hardest to see)
    yahoo finance FileNotFoundError at container start (engine module absent)

Google is the instructive one. It fails by returning a consent page that parses
to zero results, so it never appears in `unresponsive_engines` and reads as a
healthy second engine. It survived because nobody checked WHICH engine the
results came from — including, for two rounds, the author of this file.

Returning results is also not the bar. bing returns results and answered
"federal reserve policy" with federalpremium.com, an ammunition retailer.
Candidates were therefore ranked on a finance query, not merely probed for a
non-empty response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "infra" / "searxng" / "core-config" / "settings.yml"

#: Measured blocked on 2026-09-05. Each cost a request and a timeout per query
#: while contributing nothing.
MEASURED_BLOCKED = ("brave", "duckduckgo", "startpage", "google")

#: Verified by query on 2026-09-05, then ranked on "nvidia quarterly earnings".
VERIFIED_WORKING = ("seznam", "yep", "yandex")


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def by_name(cfg: dict) -> dict:
    return {e["name"]: e for e in cfg["engines"]}


@pytest.mark.parametrize("name", MEASURED_BLOCKED)
def test_measured_blocked_engines_are_disabled(by_name: dict, name: str):
    assert name in by_name, f"{name} left the config entirely — re-measure before re-adding"
    assert by_name[name].get("disabled") is True, (
        f"{name} was measured returning nothing; enabling it costs a request "
        "and a timeout on every query for no results")


@pytest.mark.parametrize("name", VERIFIED_WORKING)
def test_verified_engines_are_present_and_enabled(by_name: dict, name: str):
    assert name in by_name, f"{name} was verified working and should be in the pool"
    assert by_name[name].get("disabled") is not True


def test_the_pool_has_more_than_one_working_engine(by_name: dict):
    """The state this change exists to end: one engine, and the weakest one."""
    enabled = [n for n, e in by_name.items() if e.get("disabled") is not True]
    general = [n for n in enabled if n not in ("wikipedia",)]
    assert len(general) >= 3, f"only {general} would serve a general query"


def test_the_nonexistent_engine_is_gone(cfg: dict):
    """`engine: yahoo_finance` has no module in this image and failed to load on
    every container start. A declared engine that cannot load is worse than an
    absent one: it reads as coverage that does not exist."""
    engines = [e.get("engine") for e in cfg["engines"]]
    assert "yahoo_finance" not in engines


def test_every_entry_names_an_engine_and_a_shortcut(cfg: dict):
    for e in cfg["engines"]:
        assert e.get("engine"), f"{e.get('name')} declares no engine module"
        assert e.get("shortcut"), f"{e.get('name')} declares no shortcut"


def test_shortcuts_are_unique(cfg: dict):
    """A duplicate shortcut silently shadows one engine's bang."""
    shortcuts = [e["shortcut"] for e in cfg["engines"]]
    assert len(shortcuts) == len(set(shortcuts)), f"duplicate shortcut in {shortcuts}"


def test_the_server_block_survives(cfg: dict):
    """Guard the surrounding config: this file is rewritten by SearXNG itself on
    startup, and an edit that loses these lines takes the service down."""
    assert cfg.get("use_default_settings") is True
    assert cfg["server"]["port"] == 8080
    assert cfg["server"]["bind_address"] == "0.0.0.0"


def test_the_measurement_is_recorded_beside_each_decision():
    """A disabled engine with no stated reason gets re-enabled by the next
    person who notices the pool is small."""
    text = SETTINGS.read_text(encoding="utf-8")
    for marker in ("2026-09-05", "unresponsive_engines", "consent"):
        assert marker in text, f"the config does not record {marker!r}"
    assert "federalpremium" in text or "ammunition" in text, (
        "the reason results-count is not the bar is not recorded")


def test_yandex_is_flagged_rather_than_quietly_included():
    """It returned the best finance results and is Russian-operated. That is an
    operator call, and the config must say so rather than slipping it in."""
    text = SETTINGS.read_text(encoding="utf-8")
    assert "sovereignty" in text.lower() or "russian" in text.lower()


# ── the paid Brave API, and the secret that must not be committed ───────────

def test_braveapi_is_present_and_distinct_from_the_scraper(by_name: dict):
    """`brave` scrapes search.brave.com and is rate-limited to nothing.
    `braveapi` calls api.search.brave.com — the product this project pays for,
    measured at 50 req/sec with an unmetered monthly window."""
    assert "braveapi" in by_name
    assert by_name["braveapi"]["engine"] == "braveapi"
    assert by_name["brave"]["engine"] == "brave"


def test_no_api_key_is_committed(cfg: dict):
    """THIS REPOSITORY IS PUBLIC. A literal key here is a published credential.

    SearXNG performs no environment substitution in settings.yml — the loader
    only reads SEARXNG_SETTINGS_PATH — so the key cannot be indirected here and
    must be injected on the host.
    """
    for e in cfg["engines"]:
        key = e.get("api_key")
        if key is None:
            continue
        assert key == "", (
            f"{e['name']} carries a literal api_key in a public repository")


def test_braveapi_ships_disabled_so_a_keyless_engine_never_runs(by_name: dict):
    """A keyed engine enabled without its key fails on every query — another
    silent contributor of zero results, which is the defect this file exists to
    stop repeating."""
    assert by_name["braveapi"].get("disabled") is True


def test_the_host_side_enable_procedure_is_written_down():
    text = SETTINGS.read_text(encoding="utf-8")
    for marker in ("BRAVE_SEARCH_API_KEY", "PUBLIC", "docker restart searxng"):
        assert marker in text, f"enabling instructions omit {marker!r}"


def test_the_budget_bypass_is_disclosed():
    """braveapi calls the provider directly, so lib/search_budget does not count
    them. Enabling it silently would reopen the unbudgeted-caller problem that
    search_budget was built to close."""
    text = SETTINGS.read_text(encoding="utf-8")
    assert "search_budget" in text and "NOT counted" in text


# ── `inactive` is a separate gate from `disabled` ───────────────────────────
# Measured 2026-09-06: braveapi and `yahoo news` installed cleanly, passed YAML
# validation, and were ABSENT from the running config with no error and no log
# line. SearXNG's defaults ship both with `inactive: true`, which means "never
# registered" — not "registered but off". Clearing only `disabled` leaves the
# engine a ghost: configured, invisible, silent.

def test_no_enabled_engine_is_left_inactive(cfg: dict):
    """The exact defect. An engine both enabled and inactive is configured to do
    nothing, and says nothing about it."""
    ghosts = [e["name"] for e in cfg["engines"]
              if not e.get("disabled") and e.get("inactive") is True]
    assert not ghosts, f"enabled but inactive, will never register: {ghosts}"


def test_engines_that_default_to_inactive_override_it_explicitly(by_name: dict):
    """braveapi ships inactive in SearXNG's defaults, so the entry must say
    inactive: false or it silently does not exist."""
    assert by_name["braveapi"].get("inactive") is False, (
        "braveapi inherits inactive: true from SearXNG defaults and will not register")


def test_the_installer_validates_the_inactive_gate():
    """The dry run passed while shipping two ghost engines, because it checked
    `disabled` and not `inactive`. That gap is closed."""
    src = (ROOT / "scripts" / "install_searxng_config.sh").read_text(encoding="utf-8")
    assert 'e.get("inactive") is True' in src, "installer does not check the inactive gate"
    assert "enabled but inactive" in src


def test_the_installer_verifies_engines_actually_registered():
    """Config-says-so is not registered-in-fact. The installer now compares its
    intended set against /config and names anything missing."""
    src = (ROOT / "scripts" / "install_searxng_config.sh").read_text(encoding="utf-8")
    assert "MISSING FROM RUNNING CONFIG" in src
    assert "/config" in src
