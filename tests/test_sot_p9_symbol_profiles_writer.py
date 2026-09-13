"""One Source of Truth, Phase 9 -- symbol_profiles has ONE write module.

Eight producer files carried their own INSERT/UPDATE for symbol_profiles on
2026-09-13 (config/data_source_authority_baseline.json: writers.symbol_profiles
= 8). Column ownership per lane is by design; eight SQL paths were the defect.
These tests are offline: a fake cursor records SQL + params, the identity
registry is pinned to a temp file, nothing touches a database.

For each legacy writer, the statement it used to issue is frozen here verbatim
(copied from origin/main) and the write module must issue an EQUIVALENT write:
same target columns, same conflict rule, same values after coercion, same
COALESCE/NOW() treatment. Equivalence is checked structurally, so whitespace,
casing and parameter-vs-literal spelling of the same value do not matter but a
dropped column, a changed NULL rule or a different value does.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib.writers import symbol_profiles_writer as w  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
BASELINE = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())

LEGACY_WRITER_FILES = (
    "scripts/build_symbol_profiles.py", "scripts/earnings_enrich.py", "scripts/classify_instruments.py",
    "scripts/etf_analyst_enrich.py", "scripts/validate_expense_ratios.py", "scripts/fund_technicals_enrich.py",
    "scripts/distributions_enrich.py", "scripts/etf_performance_enrich.py",
)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Rule (d): no test here may read the production identity registry."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))


class FakeCursor:
    """Records every execute; never talks to a database."""

    def __init__(self, rowcount: int = 1):
        self.calls: list[tuple[str, tuple]] = []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.calls.append((sql, tuple(params or ())))

    @property
    def only(self) -> tuple[str, tuple]:
        assert len(self.calls) == 1, self.calls
        return self.calls[0]


# ── structural SQL reader ────────────────────────────────────────────────────
def _split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _value(expr: str, params: list, columns: dict | None = None):
    e = expr.strip()
    if e == "%s":
        return params.pop(0)
    if e.lower() == "now()":
        return "NOW()"
    m = re.fullmatch(r"COALESCE\(\s*%s\s*,\s*(\w+)\s*\)", e, re.I)
    if m:
        return ("COALESCE", m.group(1), params.pop(0))
    m = re.fullmatch(r"EXCLUDED\.(\w+)", e, re.I)
    if m and columns is not None:
        return columns[m.group(1)]
    m = re.fullmatch(r"'([^']*)'", e)
    if m:
        return m.group(1)
    raise AssertionError(f"unreadable expression {expr!r}")


def effective_write(sql: str, params: tuple) -> dict:
    """Reduce an INSERT ... ON CONFLICT or UPDATE ... WHERE to what it does."""
    s = re.sub(r"\s+", " ", sql).strip()
    p = list(params)
    m = re.fullmatch(r"INSERT INTO (\w+) \((.*?)\) VALUES \((.*?)\) ON CONFLICT \((\w+)\) DO UPDATE SET (.*)", s, re.I)
    if m:
        table, cols, vals, key, setc = m.groups()
        cols = [c.strip() for c in cols.split(",")]
        vals = _split_top(vals)
        assert len(cols) == len(vals), (cols, vals)
        columns = {c: _value(v, p) for c, v in zip(cols, vals)}
        on_conflict = {}
        for a in _split_top(setc):
            col, expr = a.split("=", 1)
            on_conflict[col.strip()] = _value(expr, p, columns)
        assert not p, f"unused params {p}"
        return {"kind": "upsert", "table": table.lower(), "columns": columns, "conflict_key": key.lower(),
                "on_conflict_set": on_conflict}
    m = re.fullmatch(r"UPDATE (\w+) SET (.*?) WHERE (.*)", s, re.I)
    if m:
        table, setc, where = m.groups()
        assigned = {}
        for a in _split_top(setc):
            col, expr = a.split("=", 1)
            assigned[col.strip()] = _value(expr, p)
        where_n = re.sub(r"\s", "", where).lower()
        assert where_n == "upper(symbol)=%s", where
        assert len(p) == 1, f"where params {p}"
        return {"kind": "update", "table": table.lower(), "set": assigned, "where_symbol": p[0]}
    raise AssertionError(f"unreadable statement {sql!r}")


def _same_write(legacy: tuple[str, tuple], new: tuple[str, tuple]) -> None:
    a, b = effective_write(*legacy), effective_write(*new)
    assert a == b, f"\nlegacy={json.dumps(a, default=str, indent=1)}\nnew={json.dumps(b, default=str, indent=1)}"


def test_effective_write_reader_distinguishes_real_differences():
    """The reader is only worth anything if it can tell two writes apart."""
    a = ("UPDATE symbol_profiles SET a=%s, b=COALESCE(%s, b) WHERE upper(symbol)=%s", (1, None, "X"))
    b = ("UPDATE symbol_profiles SET a=%s, b=%s WHERE upper(symbol)=%s", (1, None, "X"))
    assert effective_write(*a) != effective_write(*b)          # a dropped COALESCE is a different write
    c = ("UPDATE symbol_profiles SET a=%s WHERE upper(symbol)=%s", (1, "X"))
    assert effective_write(*a) != effective_write(*c)          # a dropped column is a different write
    d = ("UPDATE   symbol_profiles\n SET a=%s,\n b=COALESCE(%s,b) WHERE upper(symbol) = %s", (1, None, "X"))
    assert effective_write(*a) == effective_write(*d)          # whitespace is not


# ── golden: legacy writer ≡ write module, one per migrated file ──────────────
# build_symbol_profiles.py -- yfinance / finviz path (origin/main line 128)
LEGACY_BUILD_MAIN = """INSERT INTO symbol_profiles (symbol, description_1s, sector, industry, source, updated_at)
                       VALUES (%s,%s,%s,%s,%s,now())
                       ON CONFLICT (symbol) DO UPDATE SET description_1s=EXCLUDED.description_1s,
                         sector=EXCLUDED.sector, industry=EXCLUDED.industry, source=EXCLUDED.source, updated_at=now()"""
# build_symbol_profiles.py -- proxy_label path (origin/main line 97): industry NOT in the conflict set
LEGACY_BUILD_PROXY = """INSERT INTO symbol_profiles (symbol, description_1s, sector, industry, source, updated_at)
                           VALUES (%s,%s,%s,%s,'proxy_label',now())
                           ON CONFLICT (symbol) DO UPDATE SET description_1s=EXCLUDED.description_1s,
                             sector=EXCLUDED.sector, source='proxy_label', updated_at=now()"""
LEGACY_EARNINGS = """UPDATE symbol_profiles SET next_earnings_date=%s, last_earnings_date=%s,
                             last_eps_estimate=%s, last_eps_actual=%s, last_eps_surprise_pct=%s,
                             earnings_updated_at=NOW() WHERE upper(symbol)=%s"""
LEGACY_CLASSIFY = """UPDATE symbol_profiles SET instrument_type=%s, direction_hint=%s,
                         expense_ratio=COALESCE(%s, expense_ratio), quote_type=COALESCE(%s, quote_type)
                       WHERE upper(symbol)=%s"""
LEGACY_EXPENSE = "UPDATE symbol_profiles SET expense_ratio=%s WHERE upper(symbol)=%s"
LEGACY_TECHNICALS = """UPDATE symbol_profiles SET rsi14=%s, perf_week_pct=%s, perf_month_pct=%s,
                             ytd_return_pct=COALESCE(%s, ytd_return_pct), sma50_pct=%s, technicals_updated_at=NOW()
                           WHERE upper(symbol)=%s"""
LEGACY_DISTRIBUTIONS = """UPDATE symbol_profiles SET last_distribution_date=%s, last_distribution_amount=%s,
                             distribution_cadence=%s, next_distribution_est=%s, ttm_distribution_amount=%s,
                             distributions_updated_at=NOW() WHERE upper(symbol)=%s"""
LEGACY_PERFORMANCE = """UPDATE symbol_profiles SET ytd_return_pct=%s, dividend_yield_pct=%s,
                             ttm_dividend=%s, perf_updated_at=now() WHERE upper(symbol)=%s"""
LEGACY_ANALYST = "UPDATE symbol_profiles SET analyst_look_through_pct=%s, analyst_basis=%s WHERE upper(symbol)=%s"


def test_golden_build_symbol_profiles_yfinance_and_finviz_paths():
    for source in ("yfinance", "finviz"):
        cur = FakeCursor()
        desc, sector, industry = "Northrop Grumman builds aircraft. It also builds satellites.", "Industrials", "Aerospace & Defense"
        r = w.upsert_profile(cur, "NOC", {"description_1s": desc, "sector": sector, "industry": industry}, source=source)
        _same_write((LEGACY_BUILD_MAIN, ("NOC", desc, sector, industry, source)), cur.only)
        assert r.rows_written == 1 and r.rows_rejected == 0
        eff = effective_write(*cur.only)
        assert eff["conflict_key"] == "symbol" and eff["columns"]["source"] == source


def test_golden_build_symbol_profiles_proxy_label_leaves_industry_alone():
    cur = FakeCursor()
    etf, label, sym = "SCHD", "Dividend Equity", "3905"
    desc = f"Retirement-plan fund — {label} (tracked via {etf} proxy)."
    w.upsert_profile(cur, sym, {"description_1s": desc, "sector": label}, source="proxy_label")
    _same_write((LEGACY_BUILD_PROXY, (sym, desc, label, None)), cur.only)
    eff = effective_write(*cur.only)
    assert eff["columns"]["industry"] is None                       # inserted NULL for a new row
    assert "industry" not in eff["on_conflict_set"]                 # never overwrites an existing industry
    assert eff["on_conflict_set"]["source"] == "proxy_label"


def test_golden_earnings_enrich():
    cur = FakeCursor()
    nd, ld, est, act, sur = dt.date(2026, 10, 22), dt.date(2026, 7, 23), 6.71, 7.01, 4.47
    r = w.write_earnings(cur, "NOC", state=w.EARNINGS_SCHEDULED, next_earnings_date=nd, last_earnings_date=ld,
                         last_eps_estimate=est, last_eps_actual=act, last_eps_surprise_pct=sur)
    _same_write((LEGACY_EARNINGS, (nd, ld, est, act, sur, "NOC")), cur.only)
    assert effective_write(*cur.only)["set"]["earnings_updated_at"] == "NOW()"
    assert r.rows_written == 1


def test_golden_earnings_enrich_none_scheduled_writes_null_date_with_fresh_stamp():
    """Legacy: an answered provider with no future date wrote NULL + NOW(). Same here, and only for NONE."""
    cur = FakeCursor()
    ld, est, act, sur = dt.date(2026, 7, 23), 6.71, 7.01, 4.47
    w.write_earnings(cur, "NOC", state=w.EARNINGS_NONE, next_earnings_date=None, last_earnings_date=ld,
                     last_eps_estimate=est, last_eps_actual=act, last_eps_surprise_pct=sur)
    _same_write((LEGACY_EARNINGS, (None, ld, est, act, sur, "NOC")), cur.only)


def test_golden_classify_instruments_with_and_without_cached_values():
    for exp, qt in ((None, None), (0.0074, "MUTUALFUND")):
        cur = FakeCursor()
        w.upsert_profile(cur, "FCNTX", {"instrument_type": "fund", "direction_hint": "long", "expense_ratio": exp, "quote_type": qt},
                         source="classify_instruments", keep_existing_if_null=("expense_ratio", "quote_type"))
        _same_write((LEGACY_CLASSIFY, ("fund", "long", exp, qt, "FCNTX")), cur.only)
        eff = effective_write(*cur.only)
        assert eff["set"]["expense_ratio"] == ("COALESCE", "expense_ratio", exp)


def test_golden_validate_expense_ratios():
    cur = FakeCursor()
    w.upsert_profile(cur, "FCNTX", {"expense_ratio": round(0.0074, 6)}, source="validate_expense_ratios")
    _same_write((LEGACY_EXPENSE, (round(0.0074, 6), "FCNTX")), cur.only)


def test_golden_fund_technicals_enrich():
    cur = FakeCursor()
    rsi, pw, pm, ytd, sma = 58.12, 1.2, -0.4, None, 3.3
    w.upsert_profile(cur, "AMANX", {"rsi14": rsi, "perf_week_pct": pw, "perf_month_pct": pm, "ytd_return_pct": ytd, "sma50_pct": sma},
                     source="fund_technicals_enrich", keep_existing_if_null=("ytd_return_pct",))
    _same_write((LEGACY_TECHNICALS, (rsi, pw, pm, ytd, sma, "AMANX")), cur.only)


def test_golden_distributions_enrich():
    cur = FakeCursor()
    ld, amt, cad, nxt, ttm = dt.date(2026, 6, 25), 0.2637, "quarterly", dt.date(2026, 9, 24), 1.05
    w.upsert_profile(cur, "SCHD", {"last_distribution_date": ld, "last_distribution_amount": amt, "distribution_cadence": cad,
                                   "next_distribution_est": nxt, "ttm_distribution_amount": ttm}, source="distributions_enrich")
    _same_write((LEGACY_DISTRIBUTIONS, (ld, amt, cad, nxt, ttm, "SCHD")), cur.only)


def test_golden_etf_performance_enrich():
    cur = FakeCursor()
    ytd, dy, div = 4.21, 3.65, 1.05
    w.upsert_profile(cur, "SCHD", {"ytd_return_pct": ytd, "dividend_yield_pct": dy, "ttm_dividend": div}, source="etf_performance_enrich")
    _same_write((LEGACY_PERFORMANCE, (ytd, dy, div, "SCHD")), cur.only)


def test_golden_etf_analyst_enrich_including_the_null_basis_row():
    for final, basis in ((7.3, "holdings look-through (9 constituents)"), (None, None)):
        cur = FakeCursor()
        w.upsert_profile(cur, "XLK", {"analyst_look_through_pct": final, "analyst_basis": basis}, source="etf_analyst_enrich")
        _same_write((LEGACY_ANALYST, (final, basis, "XLK")), cur.only)


# ── column ownership: the allow-list ─────────────────────────────────────────
def test_foreign_column_is_rejected_not_written():
    cur = FakeCursor()
    r = w.upsert_profile(cur, "NOC", {"next_earnings_date": dt.date(2026, 10, 22), "sector": "Industrials"}, source="earnings_enrich")
    assert cur.calls == []
    assert r.rows_written == 0 and r.rows_rejected == 1
    assert "sector" in r.rejected[0]["reason"] and "earnings_enrich" in r.rejected[0]["reason"]


def test_every_lane_owns_only_columns_the_schema_declares():
    """The allow-list must not invent columns: each one is created by the DDL or a producer's ALTER."""
    declared = set(re.findall(r"^\s*(\w+)\s+TEXT", (ROOT / "migrations" / "2026_06_12_symbol_profiles.sql").read_text(), re.M))
    for rel in LEGACY_WRITER_FILES:
        src = (ROOT / rel).read_text()
        declared |= set(re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", src))
        # etf_performance_enrich.py declares its four columns as ("name", "type") tuples fed to one f-string ALTER
        declared |= set(re.findall(r'\("(\w+)",\s*"(?:numeric|text|date|timestamptz)"\)', src))
    missing = sorted(w.ALL_COLUMNS - declared)
    assert missing == [], f"lane columns with no schema declaration: {missing}"
    stamps = {lane.stamp for lane in w.LANES.values() if lane.stamp}
    assert stamps - declared - {"updated_at"} == set()


def test_unknown_lane_is_rejected():
    cur = FakeCursor()
    r = w.upsert_profile(cur, "NOC", {"sector": "x"}, source="some_new_script")
    assert cur.calls == [] and r.rows_rejected == 1 and "unknown source lane" in r.rejected[0]["reason"]


def test_keep_existing_if_null_must_name_a_supplied_column():
    cur = FakeCursor()
    r = w.upsert_profile(cur, "NOC", {"expense_ratio": 0.01}, source="classify_instruments", keep_existing_if_null=("quote_type",))
    assert cur.calls == [] and r.rows_rejected == 1


# ── plausibility rails ───────────────────────────────────────────────────────
@pytest.mark.parametrize("lane,fields,fragment", [
    ("validate_expense_ratios", {"expense_ratio": 1.47}, "expense_ratio off rail"),      # FCNTX mis-scale, 2026-06-21
    ("validate_expense_ratios", {"expense_ratio": 0.0}, "expense_ratio off rail"),
    ("fund_technicals_enrich", {"rsi14": 140.0}, "rsi14 off rail"),
    ("classify_instruments", {"instrument_type": "crypto", "direction_hint": "long"}, "instrument_type off vocabulary"),
    ("classify_instruments", {"instrument_type": "etf", "direction_hint": "sideways"}, "direction_hint off vocabulary"),
    ("distributions_enrich", {"ttm_distribution_amount": -1.0}, "negative"),
    ("etf_performance_enrich", {"dividend_yield_pct": float("nan")}, "not finite"),
    ("distributions_enrich", {"last_distribution_date": "not-a-date"}, "not an ISO date"),
    ("etf_analyst_enrich", {"analyst_basis": 42}, "not text"),
])
def test_off_rail_value_is_returned_with_a_reason_and_never_written(lane, fields, fragment):
    cur = FakeCursor()
    r = w.upsert_profile(cur, "FCNTX", fields, source=lane)
    assert cur.calls == [], "an off-rail row must not reach the database"
    assert r.rows_in == 1 and r.rows_written == 0 and r.rows_rejected == 1
    assert fragment in r.rejected[0]["reason"], r.rejected[0]["reason"]
    assert r.rejected[0]["symbol"] == "FCNTX" and r.rejected[0]["fields"] == fields


def test_coercions_are_narrow_and_recorded():
    cur = FakeCursor()
    w.upsert_profile(cur, " schd ", {"quote_type": " etf ", "expense_ratio": "0.0006", "instrument_type": "etf", "direction_hint": "long"},
                     source="classify_instruments")
    eff = effective_write(*cur.only)
    assert eff["where_symbol"] == "SCHD"
    assert eff["set"]["quote_type"] == "ETF" and eff["set"]["expense_ratio"] == 0.0006


def test_batch_receipt_keeps_every_rejected_row():
    cur = FakeCursor()
    rows = [{"symbol": "SCHD", "expense_ratio": 0.0006}, {"symbol": "BAD", "expense_ratio": 9.9}, {"symbol": "", "expense_ratio": 0.001}]
    r = w.write_symbol_profiles(cur, rows, source="validate_expense_ratios", run_id="t-1")
    assert (r.rows_in, r.rows_written, r.rows_rejected) == (3, 1, 2)
    assert [x["symbol"] for x in r.rejected] == ["BAD", ""] and r.run_id == "t-1"
    assert r.table == "symbol_profiles" and r.source == "validate_expense_ratios"
    assert len(cur.calls) == 1


# ── earnings: three states, UNKNOWN fails closed ─────────────────────────────
def test_earnings_constants_match_the_provider_that_reads_them():
    import earnings_provider as ep
    assert (w.EARNINGS_SCHEDULED, w.EARNINGS_NONE, w.EARNINGS_UNKNOWN) == (ep.SCHEDULED, ep.NONE_SCHEDULED, ep.UNKNOWN)


def test_unknown_is_never_coerced_to_none():
    """The 2026-07-20 defect: 'no data' persisted as 'no earnings' and every gate failed open.

    A NULL next_earnings_date beside a fresh earnings_updated_at is exactly what
    earnings_provider reads as NONE_SCHEDULED, so UNKNOWN must produce no write.
    """
    cur = FakeCursor()
    r = w.write_earnings(cur, "NOC", state=w.EARNINGS_UNKNOWN)
    assert cur.calls == [], "UNKNOWN reached the database as a NULL date -- that is NONE_SCHEDULED to the reader"
    assert r.rows_written == 0 and r.rows_rejected == 1
    assert "UNKNOWN" in r.rejected[0]["reason"] and "NONE_SCHEDULED" in r.rejected[0]["reason"]
    assert r.rejected[0]["fields"]["state"] == "UNKNOWN"


def test_scheduled_without_a_date_is_refused_not_downgraded():
    cur = FakeCursor()
    r = w.write_earnings(cur, "NOC", state="SCHEDULED", next_earnings_date=None)
    assert cur.calls == [] and r.rows_rejected == 1 and "not coerced to NONE_SCHEDULED" in r.rejected[0]["reason"]


def test_none_with_a_date_is_a_contradiction():
    cur = FakeCursor()
    r = w.write_earnings(cur, "NOC", state="NONE", next_earnings_date=dt.date(2026, 10, 22))
    assert cur.calls == [] and r.rows_rejected == 1


def test_garbage_state_is_refused():
    cur = FakeCursor()
    r = w.write_earnings(cur, "NOC", state="CLEAR")
    assert cur.calls == [] and r.rows_rejected == 1


def test_earnings_state_for_mirrors_the_legacy_derivation():
    assert w.earnings_state_for(None, provider_answered=False) == "UNKNOWN"
    assert w.earnings_state_for(dt.date(2026, 10, 22), provider_answered=False) == "UNKNOWN"   # no answer is no answer
    assert w.earnings_state_for(dt.date(2026, 10, 22), provider_answered=True) == "SCHEDULED"
    assert w.earnings_state_for(None, provider_answered=True) == "NONE_SCHEDULED"


# ── identity ─────────────────────────────────────────────────────────────────
def test_symbol_only_row_round_trips_to_the_guid_it_has_today():
    """Rule (c): ticker is an alias, and the alias GUID is defined in exactly one place."""
    from scripts.lib import identity_registry as reg
    from scripts.lib.memory_fact import subject_from_security
    guid, basis = w.resolve_subject_guid({"symbol": "schd"})
    assert guid == reg.ticker_alias_guid("SCHD") == subject_from_security(symbol="SCHD")["subject_guid"]
    assert basis.startswith("spine:")
    cur = FakeCursor()
    r = w.upsert_profile(cur, "SCHD", {"sector": "Dividend Equity"}, source="yfinance")
    assert r.written[0]["subject_guid"] == guid


def test_company_row_derives_the_issuer_guid_never_the_alias():
    from scripts.lib import identity_registry as reg
    from scripts.lib.security_identity import resolve_identity_spine
    row = {"symbol": "NOC", "company": "Northrop Grumman Corporation"}
    guid, basis = w.resolve_subject_guid(row)
    assert guid == reg.subject_guid_of(resolve_identity_spine(row), "NOC")
    assert guid != reg.ticker_alias_guid("NOC") and basis == "spine:CANDIDATE"
    cik_guid, _ = w.resolve_subject_guid({"symbol": "NOC", "cik": "1133421"})
    assert cik_guid != guid  # CIK-derived issuer beats name-derived issuer; both are real, neither invented


def test_registered_entity_wins_and_supersede_chains_are_followed(tmp_path, monkeypatch):
    """Rule (b): registry-first. A symbol the registry has minted resolves to the
    registry's ACTIVE guid, even if the by_symbol pointer is a superseded one."""
    from scripts.lib import identity_registry as reg
    path = tmp_path / "reg.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(path))
    doc = reg.empty_registry()
    reg.register(doc, {"symbol": "NOC", "company": "Northrop Grumman"})              # CANDIDATE
    old = doc["by_symbol"]["NOC"]
    reg.register(doc, {"symbol": "NOC", "cik": "1133421", "identifiers": {"cusip": "666807102"}})  # CONFIRMED, supersedes
    new = doc["by_symbol"]["NOC"]
    assert old != new and doc["entities"][old]["superseded_by"] == new
    doc["by_symbol"]["NOC"] = old                                                    # a stale pointer must still resolve forward
    reg.save(doc)
    guid, basis = w.resolve_subject_guid({"symbol": "NOC"})
    assert guid == new == reg.resolve_guid(doc, old) and basis == "registry:CONFIRMED"
    cur = FakeCursor()
    r = w.upsert_profile(cur, "NOC", {"instrument_type": "stock", "direction_hint": "long"}, source="classify_instruments")
    assert r.written[0]["subject_guid"] == new


def test_write_module_never_writes_null_identity_for_a_real_symbol():
    cur = FakeCursor()
    r = w.write_symbol_profiles(cur, [{"symbol": s, "sector": "x"} for s in ("SCHD", "NOC", "3905", "FCNTX")], source="yfinance")
    assert r.rows_written == 4 and all(x["subject_guid"] for x in r.written)


def test_write_module_does_not_mint_into_the_registry(tmp_path):
    """Read-only against the registry: resolving identity for a write never creates the file."""
    from scripts.lib import identity_registry as reg
    w.upsert_profile(FakeCursor(), "NEWCO", {"sector": "x"}, source="yfinance")
    assert not reg.registry_path().exists()


def test_table_has_no_guid_column_and_the_module_does_not_add_one():
    """Rule (e), stated as a test so a future migration has to change it deliberately."""
    ddl = (ROOT / "migrations" / "2026_06_12_symbol_profiles.sql").read_text()
    assert "guid" not in ddl.lower()
    assert not any(c.endswith("_guid") for c in w.ALL_COLUMNS)
    src = (ROOT / "scripts" / "lib" / "writers" / "symbol_profiles_writer.py").read_text()
    assert "ALTER TABLE" not in src


# ── the reduction, documented ────────────────────────────────────────────────
def test_negative_control_baseline_had_many_writers_and_now_there_is_one():
    assert BASELINE["writers"]["symbol_profiles"] > 1, "baseline must record the pre-consolidation ceiling"
    assert BASELINE["writers"]["symbol_profiles"] == 8
    now = gate.count_writers(AUTH, gate._files())["symbol_profiles"]
    assert now == 1, f"symbol_profiles writer files: {now}"


def test_the_one_writer_is_the_module_and_every_legacy_file_calls_it():
    pat = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+symbol_profiles\b", re.I)
    module = ROOT / "scripts" / "lib" / "writers" / "symbol_profiles_writer.py"
    assert pat.search(module.read_text())
    for rel in LEGACY_WRITER_FILES:
        src = (ROOT / rel).read_text()
        assert not pat.search(src), f"{rel} still carries its own SQL"
        assert "symbol_profiles_writer" in src, f"{rel} does not call the write module"


def test_registry_writer_target_re_exports_the_module():
    import build_symbol_profiles as target
    assert target.upsert_profile is w.upsert_profile and target.write_earnings is w.write_earnings
    domain = next(d for d in AUTH["domains"] if d["domain"] == "symbol_identity")
    # At integration the registry promoted the target to the single declared writer.
    assert domain.get("writer") == "scripts/lib/writers/symbol_profiles_writer.py"
    assert domain.get("writer_facade") == "scripts/build_symbol_profiles.py"
    assert domain.get("writer_status") != "UNCONSOLIDATED"


def test_lazy_db_producers_import_without_a_database():
    """These four import db_adapter lazily, so importing them is a pure check that the wiring resolves."""
    import distributions_enrich, earnings_enrich, fund_technicals_enrich, validate_expense_ratios  # noqa: F401
    assert earnings_enrich.write_earnings is w.write_earnings
    assert validate_expense_ratios.SANITY_MAX == w.EXPENSE_RATIO_MAX == 0.025
