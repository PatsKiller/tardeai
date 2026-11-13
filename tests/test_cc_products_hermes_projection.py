"""LQ-20261107-2595 phase 2 (b): the Hermes projection streaming reader and its Postgres ingest.

Parser tests are pure. Store tests run against a disposable initdb cluster (tests/support/isolated_pg.py), never the
production database, and apply the real migration file verbatim (as role trade_ai, which the cluster creates).
"""

from __future__ import annotations

import gc
import io
import json
import os
import random
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from scripts.lib.cc_products import hermes_projection as hp  # noqa: E402

# LQ-2646 (REVIEW-2606 F3): one migration for the whole precompute store; the hermes tables are its part 2.
MIGRATION = ROOT / "migrations" / "2026_11_12_cc_data_products.sql"


# ── streaming reader: property-style equality with json.loads ────────────────

_KEY_ALPHABET = ['a', 'Z', '0', '"', '\\', '{', '}', '[', ']', ':', ',', ' ', '\n', '\t', 'é', '€', '\U0001F600', '/']


def _rand_str(rng: random.Random, n: int = 6) -> str:
    return "".join(rng.choice(_KEY_ALPHABET) for _ in range(rng.randint(0, n)))


def _rand_scalar(rng: random.Random):
    k = rng.randrange(8)
    if k == 0:
        return rng.randint(-10**12, 10**12)
    if k == 1:
        return rng.choice([0.5, -1.25e-7, 3.0e21, 123.456, -0.0, 1e300])
    if k == 2:
        return rng.choice([True, False, None])
    return _rand_str(rng, 10)


def _rand_value(rng: random.Random, depth: int = 0):
    k = rng.randrange(6 if depth < 3 else 2)
    if k <= 1:
        return _rand_scalar(rng)
    if k <= 3:
        return {_rand_str(rng): _rand_value(rng, depth + 1) for _ in range(rng.randint(0, 4))}
    return [_rand_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]


def _rand_projection(rng: random.Random) -> dict:
    proj: dict = {}
    names = list(hp.MAPS) + ["updated_ts", "extra_scalar"]
    rng.shuffle(names)
    for name in names[: rng.randint(1, len(names))]:
        if name in hp.MAPS:
            proj[name] = {_rand_str(rng, 8) + str(i): _rand_value(rng) for i in range(rng.randint(0, 6))}
        else:
            proj[name] = _rand_value(rng)
    return proj


def _ws(rng: random.Random) -> str:
    return "".join(rng.choice(" \t\n\r") for _ in range(rng.randint(0, 3)))


def _dump_random_ws(v, rng: random.Random) -> str:
    """Serialise with random JSON whitespace between every token."""
    if isinstance(v, dict):
        parts = [_ws(rng) + json.dumps(k) + _ws(rng) + ":" + _ws(rng) + _dump_random_ws(x, rng) + _ws(rng)
                 for k, x in v.items()]
        return "{" + _ws(rng) + ",".join(parts) + "}"
    if isinstance(v, list):
        return "[" + _ws(rng) + ",".join(_ws(rng) + _dump_random_ws(x, rng) + _ws(rng) for x in v) + "]"
    return json.dumps(v, ensure_ascii=rng.random() < 0.5)


_FORMATS = [
    dict(indent=2),
    dict(indent=None),
    dict(indent=None, separators=(",", ":")),
    dict(indent=0),
    dict(indent=4, ensure_ascii=False),
    dict(indent="\t", separators=(" ,  ", " :\n ")),
]


def _parse_back(data: bytes, chunk: int, fh=None) -> dict:
    reader = hp.ProjectionReader(fh or io.BytesIO(data), chunk)
    triples = list(reader.entries())
    out = dict(reader.top)
    for m in reader.maps_seen:
        out[m] = {}
    for m, k, v in triples:
        out[m][k] = v
    assert reader.bytes_read == len(data)
    return out


@pytest.mark.parametrize("chunk", [1, 2, 7, 64])
def test_streaming_reader_equals_json_loads(chunk):
    rng = random.Random(2595 + chunk)
    n = 0
    for _ in range(25):
        proj = _rand_projection(rng)
        docs = [json.dumps(proj, **fmt).encode("utf-8") for fmt in _FORMATS]
        docs.append((_ws(rng) + _dump_random_ws(proj, rng) + _ws(rng)).encode("utf-8"))
        for data in docs:
            assert _parse_back(data, chunk) == json.loads(data), data[:200]
            n += 1
    assert n == 25 * (len(_FORMATS) + 1)


def test_every_split_point_of_a_tricky_document():
    """Feed a document whose keys hold escaped quotes, braces and \\u escapes, split at every byte offset."""
    proj = {
        "by_research_id": {'k"}{\\': {"s": "}{\"]", "u": "é\U0001F600", "n": [1.5e-3, -20, 7]}},
        "updated_ts": "2026-11-12T00:00:00+00:00",
        "by_fingerprint_completed": {"€\\u0041": {"v": 12345.678e9}},
    }
    data = json.dumps(proj, indent=2, ensure_ascii=True).encode()

    class TwoPiece(io.BytesIO):
        def __init__(self, b, cut):
            super().__init__(b)
            self.cut = cut
            self.first = True

        def read(self, n=-1):
            if self.first:
                self.first = False
                return super().read(self.cut)
            return super().read(n)

    expect = json.loads(data)
    for cut in range(1, len(data)):
        assert _parse_back(data, len(data), TwoPiece(data, cut)) == expect, cut


@pytest.mark.parametrize("bad", [b'{"by_plan_id": {"a": 1}', b'{"by_plan_id": {"a": 1}} x', b'[1]',
                                 b'{"by_plan_id": {"a": 1,}}', b'{"by_plan_id": {"a" 1}}', b''])
def test_malformed_input_raises(bad):
    with pytest.raises(ValueError):
        list(hp.ProjectionReader(io.BytesIO(bad), 3).entries())


def test_peak_memory_is_bounded_by_the_largest_entry_not_the_file(tmp_path):
    rng = random.Random(7)
    big = {"research_id": "res_big", "symbol": "BIG", "blob": ["x" * 1000 for _ in range(256)]}
    proj = {
        "by_research_id": {f"res_{i:06d}": {"research_id": f"res_{i:06d}", "symbol": "S", "pad": "y" * rng.randint(200, 900)}
                           for i in range(9000)},
        "by_plan_id": {f"plan_{i}": {"open": [], "latest_result_id": f"rr_{i}"} for i in range(3000)},
        "by_fingerprint_open": {},
        "by_fingerprint_completed": {"fp_big": big},
        "updated_ts": "t",
    }
    path = tmp_path / "proj.json"
    path.write_text(json.dumps(proj, indent=2))
    del proj
    gc.collect()
    size = path.stat().st_size
    largest = len(json.dumps(big, indent=2))
    assert size > 5 * 1024 * 1024 and size > 15 * largest

    tracemalloc.start()
    try:
        n = 0
        for _m, _k, _v in hp.iter_entries(path, chunk_size=64 * 1024):
            n += 1
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert n == 9000 + 3000 + 1
    assert peak < 4 * largest, (peak, largest, size)


# ── isolated Postgres ────────────────────────────────────────────────────────

try:
    from support.isolated_pg import IsolatedPostgres, pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture(scope="module")
def pg():
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries on this host")
    cluster = IsolatedPostgres()
    try:
        cluster.start()
        cluster.verify_isolated()
        conn = psycopg2.connect(**_dsn(cluster))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE ROLE trade_ai NOLOGIN")
            cur.execute("GRANT CREATE, USAGE ON SCHEMA public TO trade_ai")
            cur.execute("SET ROLE trade_ai")  # the operator command: psql -c 'SET ROLE trade_ai' -f <file>
            cur.execute(MIGRATION.read_text())  # the migration, verbatim, as the operator would run it
            cur.execute("RESET ROLE")
        conn.close()
        yield cluster
    finally:
        cluster.stop()


def _dsn(cluster) -> dict:
    return dict(host=cluster.host, port=cluster.port, user=cluster.user, password=cluster.password,
                dbname=cluster.dbname)


@pytest.fixture
def db(pg):
    def connect():
        return psycopg2.connect(**_dsn(pg))

    c = connect()
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("TRUNCATE hermes_projection_entry, hermes_projection_meta")
    yield connect, c
    c.close()


def _count(c, where: str = "TRUE") -> int:
    with c.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM hermes_projection_entry WHERE {where}")
        return cur.fetchone()[0]


def _projection(n_research: int = 4, tag: str = "v1") -> dict:
    by_rid = {}
    for i in range(n_research):
        rid = f"res_{i:05d}"
        by_rid[rid] = {"research_id": rid, "plan_id": f"plan_{i % 3}", "symbol": ["aapl", "MSFT", "Aapl"][i % 3],
                       "status": "completed", "created_ts": f"2026-11-{(i % 28) + 1:02d}T00:00:{i % 60:02d}",
                       "latest_result_id": f"rr_{i}", "tag": tag}
    return {
        "by_research_id": by_rid,
        "by_plan_id": {f"plan_{j}": {"open": [f"res_{j:05d}"], "latest_result_id": f"rr_{j}",
                                     "latest_as_of": f"2026-11-0{j + 1}", "tag": tag} for j in range(3)},
        "updated_ts": f"2026-11-12T23:00:00+00:00/{tag}",
        "by_fingerprint_open": {"fp_open": {"research_id": "res_00000", "plan_id": "plan_0", "symbol": "AAPL",
                                            "status": "queued"}},
        "by_fingerprint_completed": {"sha256:done": {"result_id": "rr_1", "plan_id": "plan_1", "symbol": "MSFT",
                                                     "summary": "nul\u0000here", "tag": tag}},
    }


def _write(path: Path, proj: dict) -> Path:
    path.write_text(json.dumps(proj, indent=2, default=str))
    return path


def test_ingest_then_read_each_map(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection(7))
    r = hp.ingest(connect, src, dry_run=False, chunk_size=97)
    assert r["outcome"] == "OK", r
    assert r["entries"] == {"by_research_id": 7, "by_plan_id": 3, "by_fingerprint_open": 1,
                            "by_fingerprint_completed": 1}
    assert r["sanitized"] == 1 and r["ingest_seq"] == 1 and r["bytes"] == src.stat().st_size
    assert r["peak_rss_kb"] and r["sha256"] and r["projection_updated_ts"].endswith("/v1")
    with c.cursor() as cur:
        assert hp.research_entry(cur, "res_00004")["symbol"] == "MSFT"
        assert hp.research_entry(cur, "nope") is None
        assert hp.plan_entry(cur, "plan_2") == {"open": ["res_00002"], "latest_result_id": "rr_2",
                                                "latest_as_of": "2026-11-03", "tag": "v1"}
        assert hp.fingerprint_entry(cur, "fp_open", completed=False)["status"] == "queued"
        assert hp.fingerprint_entry(cur, "fp_open", completed=True) is None
        assert hp.fingerprint_entry(cur, "sha256:done", completed=True)["summary"] == "nul�here"
        aapl = hp.research_for_symbol(cur, "AaPl")
        assert [x["research_id"] for x in aapl] == ["res_00006", "res_00005", "res_00003", "res_00002", "res_00000"]
        assert len(hp.research_for_symbol(cur, "aapl", limit=2)) == 2
        got = hp.latest_research_for_plan_from_store(cur, "plan_1", result_lookup=lambda rid: {"result_id": rid})
        assert got == {"plan_id": "plan_1", "open": ["res_00001"], "latest_result_id": "rr_1",
                       "latest_as_of": "2026-11-02", "latest_result": {"result_id": "rr_1"}}
        assert hp.latest_research_for_plan_from_store(cur, "plan_x") == {
            "plan_id": "plan_x", "open": [], "latest_result_id": None, "latest_as_of": None, "latest_result": None}
        m = hp.meta(cur)
        assert m["source_sha256"] == r["sha256"] and m["ingest_seq"] == 1 and m["entries"] == r["entries"]
        cur.execute("SELECT plan_id, symbol FROM hermes_projection_entry WHERE map='by_plan_id' AND entry_key='plan_0'")
        assert cur.fetchone() == ("plan_0", None)


def test_reingest_unchanged(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection())
    assert hp.ingest(connect, src, dry_run=False)["outcome"] == "OK"
    r = hp.ingest(connect, src, dry_run=False)
    assert r["outcome"] == "UNCHANGED" and r["ingest_seq"] == 1
    with c.cursor() as cur:
        assert hp.meta(cur)["ingest_seq"] == 1


def test_same_size_and_mtime_but_new_content_is_ingested(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection(tag="v1"))
    assert hp.ingest(connect, src, dry_run=False)["outcome"] == "OK"
    st = src.stat()
    _write(src, _projection(tag="v2"))  # same length tag, so the same size
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert src.stat().st_size == st.st_size and src.stat().st_mtime == st.st_mtime
    r = hp.ingest(connect, src, dry_run=False)
    assert r["outcome"] == "OK" and r["ingest_seq"] == 2
    with c.cursor() as cur:
        assert hp.plan_entry(cur, "plan_0")["tag"] == "v2"


def test_entry_removed_in_source_is_deleted(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection(5))
    assert hp.ingest(connect, src, dry_run=False)["outcome"] == "OK"
    proj = _projection(5)
    del proj["by_research_id"]["res_00003"]
    proj["by_fingerprint_open"] = {}
    _write(src, proj)
    r = hp.ingest(connect, src, dry_run=False)
    assert r["outcome"] == "OK" and r["deleted"] == 2
    with c.cursor() as cur:
        assert hp.research_entry(cur, "res_00003") is None
        assert hp.fingerprint_entry(cur, "fp_open", completed=False) is None
        assert hp.research_entry(cur, "res_00004") is not None
    assert _count(c) == 4 + 3 + 1


def test_failure_mid_ingest_keeps_the_previous_state(db, tmp_path, monkeypatch):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection(1600, tag="v1"))
    assert hp.ingest(connect, src, dry_run=False)["outcome"] == "OK"
    total = _count(c)
    with c.cursor() as cur:
        before = hp.meta(cur)

    real = hp._upsert_batch
    calls = {"n": 0}

    def boom(cur, rows):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected after 2 batches")
        return real(cur, rows)

    monkeypatch.setattr(hp, "_upsert_batch", boom)
    proj = _projection(1200, tag="v2")
    _write(src, proj)
    r = hp.ingest(connect, src, dry_run=False)
    assert r["outcome"] == "FAILED" and "injected" in r["error"] and calls["n"] == 3
    assert _count(c) == total
    assert _count(c, "body->>'tag' = 'v2'") == 0
    with c.cursor() as cur:
        assert hp.meta(cur) == before


def test_lock_busy_skips(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection())
    holder = connect()
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (hp.LOCK_KEY,))
        r = hp.ingest(connect, src, dry_run=False)
        assert r["outcome"] == "SKIPPED_BUSY"
        assert _count(c) == 0
    finally:
        holder.close()
    assert hp.ingest(connect, src, dry_run=False)["outcome"] == "OK"


def test_dry_run_writes_nothing(db, tmp_path):
    connect, c = db
    src = _write(tmp_path / "p.json", _projection(5))
    r = hp.ingest(connect, src, dry_run=True, chunk_size=13)
    assert r["outcome"] == "DRY_RUN"
    assert r["entries"] == {"by_research_id": 5, "by_plan_id": 3, "by_fingerprint_open": 1,
                            "by_fingerprint_completed": 1}
    assert r["entries_total"] == 10 and r["bytes"] == src.stat().st_size
    import hashlib

    assert r["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert _count(c) == 0
    with c.cursor() as cur:
        assert hp.meta(cur) is None


def test_cli_dry_run_prints_receipt(tmp_path):
    src = _write(tmp_path / "p.json", _projection(3))
    out = subprocess.run(
        [sys.executable, "-m", "scripts.lib.cc_products.hermes_projection", "--dry-run", "--path", str(src),
         "--dsn", "host=127.0.0.1 port=1 dbname=none connect_timeout=1"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert out.returncode == 0, out.stderr
    rec = json.loads(out.stdout)
    assert rec["outcome"] == "DRY_RUN" and rec["entries_total"] == 3 + 3 + 1 + 1
    assert rec["rlimit_as_bytes"] == hp.INGEST_RLIMIT_AS_BYTES
