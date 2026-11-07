"""LQ-20261107-55 — the learned Hermes weights must survive a release.

The tuner wrote its outcome-ledger grafts into ``config/hermes_score_weights.yaml`` inside the
release directory. Every promote replaces that tree with a fresh checkout of git's v9 seed, so all
42 audited grafts were lost: the served file was v9 (2026-08-13) while the last surviving learned
state was v20 (2026-11-01), and the scorer ranked the whole watchlist on three-month-old weights.

Postgres is the system of record (operator rule 2026-11-07-09:10): the graft goes to
``config_documents`` first, the persistent-state mirror second, and the release seed is never
written. Every fixture here is synthetic — the fake ``config_db_loader`` never touches a database.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import lib.hermes_score_weights as store  # noqa: E402

SEED_DOC = {
    "version": 9,
    "weights": {
        "technical_momentum": 0.06,
        "setup_quality": 0.008,
        "analyst": 0.44,
        "social_sentiment": 0.10,
        "sector_strength": 0.045,
        "news_catalyst": 0.10,
        "risk_reward": 0.09,
        "hermes_research": 0.055,
        "options_edge": 0.045,
        "thesis_outcome": 0.057,
    },
    "auto_grafted_at": "2026-08-13T16:30:00+00:00",
    "graft_source": "outcome_ledger",
}
#: The newest surviving learned document (persistent-state archive, 2026-11-01T22:00:01Z).
LEARNED_DOC = {
    "version": 20,
    "weights": {
        "technical_momentum": 0.0098,
        "setup_quality": 0.0098,
        "analyst": 0.4962,
        "social_sentiment": 0.0344,
        "sector_strength": 0.0861,
        "news_catalyst": 0.0898,
        "risk_reward": 0.1211,
        "hermes_research": 0.0536,
        "options_edge": 0.0438,
        "thesis_outcome": 0.0555,
    },
    "auto_grafted_at": "2026-11-01T22:00:01.559478+00:00",
    "graft_source": "outcome_ledger",
}


class FakeConfigStore:
    """The ``config_db_loader`` surface the store uses, with failure switches and a call log."""

    def __init__(self):
        self.row = None
        self.fail_get = False
        self.fail_put = False
        self.calls: list[tuple] = []
        self.mirror_existed_at_put: list[bool] = []
        self.mirror_path: Path | None = None

    def fetch_config_document(self, key):
        self.calls.append(("get", key))
        if self.fail_get:
            raise ConnectionError("could not connect to server: Connection refused")
        return self.row

    def upsert_config_document(
        self, key, content, config_type, source_path=None, notes=None, changed_by="migration_script"
    ):
        self.mirror_existed_at_put.append(bool(self.mirror_path and self.mirror_path.exists()))
        self.calls.append(("put", key, content, changed_by))
        if self.fail_put:
            raise RuntimeError("cannot execute INSERT in a read-only transaction")
        self.row = json.loads(json.dumps(content, default=str))
        return "updated" if self.row else "inserted"


@pytest.fixture
def db(monkeypatch, tmp_path):
    fake = FakeConfigStore()
    monkeypatch.setitem(sys.modules, "config_db_loader", fake)
    monkeypatch.delenv(store.DB_ENV, raising=False)
    monkeypatch.setenv(store.MIRROR_ENV, str(tmp_path / "mirror" / "hermes_score_weights.yaml"))
    return fake


@pytest.fixture
def seed(tmp_path):
    import yaml

    path = tmp_path / "config" / "hermes_score_weights.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(SEED_DOC, sort_keys=False), encoding="utf-8")
    return path


def _mirror(tmp_path) -> Path:
    return tmp_path / "mirror" / "hermes_score_weights.yaml"


# ── the store ladder ─────────────────────────────────────────────────────────
def test_load_prefers_the_db_over_the_mirror_and_the_seed(db, seed, tmp_path):
    import yaml

    db.row = LEARNED_DOC
    path = _mirror(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"version": 11, "weights": {"analyst": 0.45}}, sort_keys=False))

    doc, source = store.load(seed=seed)
    assert source == store.SOURCE_DB
    assert doc["version"] == 20
    assert doc["weights"]["analyst"] == pytest.approx(0.4962)


def test_a_db_outage_falls_back_to_the_mirror_and_names_the_failure(db, seed, tmp_path):
    import yaml

    db.fail_get = True
    path = _mirror(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(LEARNED_DOC, sort_keys=False))

    resolved = store.resolve(seed=seed)
    assert resolved["source"] == store.SOURCE_MIRROR
    assert resolved["doc"]["version"] == 20
    assert any("ConnectionError" in e for e in resolved["errors"]), resolved["errors"]


def test_an_empty_store_reads_the_release_seed(db, seed):
    doc, source = store.load(seed=seed)
    assert source == store.SOURCE_SEED
    assert doc["version"] == 9 and doc["weights"]["analyst"] == pytest.approx(0.44)


def test_a_corrupt_mirror_is_skipped_never_flattened_into_defaults(db, seed, tmp_path):
    path = _mirror(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("version: 12\nweights: not-a-mapping\n", encoding="utf-8")

    resolved = store.resolve(seed=seed)
    assert resolved["source"] == store.SOURCE_SEED
    assert any("mirror" in e for e in resolved["errors"]), resolved["errors"]


def test_save_writes_the_db_first_then_the_mirror_and_never_the_seed(db, seed, tmp_path):
    db.mirror_path = _mirror(tmp_path)
    before = seed.read_bytes()

    out = store.save(LEARNED_DOC, seed=seed, notes="unit test")

    assert [c[0] for c in db.calls] == ["put"], db.calls
    assert db.mirror_existed_at_put == [False], "the mirror was written before the DB"
    assert out["db"] == "updated" and out["db_error"] is None
    assert out["mirror"] == str(_mirror(tmp_path)) and Path(out["mirror"]).is_file()
    assert out["wrote_seed"] is False
    assert seed.read_bytes() == before, "the release seed was written — every release would re-clobber it"


def test_a_db_failure_still_mirrors_and_is_reported_not_swallowed(db, seed, tmp_path):
    db.fail_put = True

    out = store.save(LEARNED_DOC, seed=seed)

    assert out["db"] is None
    assert "read-only transaction" in out["db_error"]
    assert Path(out["mirror"]).is_file(), "the backup copy is exactly for the DB outage"


def test_both_tiers_failing_raises_and_leaves_the_seed_alone(db, seed, tmp_path):
    db.fail_put = True
    unwritable = tmp_path / "not-a-dir"
    unwritable.write_text("file", encoding="utf-8")

    with pytest.raises(RuntimeError, match="neither tier"):
        store.save(LEARNED_DOC, seed=seed, mirror=unwritable / "weights.yaml")
    assert json.loads(json.dumps(SEED_DOC))["version"] == 9


def test_an_unusable_document_is_refused_before_any_write(db, seed):
    with pytest.raises(ValueError, match="unusable"):
        store.save({"version": 21, "weights": {"analyst": "NaN-ish"}}, seed=seed)
    assert db.calls == []


# ── the tuner graft ──────────────────────────────────────────────────────────
class _Cur:
    def __init__(self, answers, log):
        import copy

        self.answers = copy.deepcopy(answers)
        self.log = log
        self._qs = ""

    def execute(self, sql, params=None):
        self._qs = " ".join(sql.split()).lower()
        self.log.append((self._qs, params))

    def fetchone(self):
        for needle, rows in self.answers.items():
            if needle in self._qs:
                return rows.pop(0) if rows else None
        return (0,)

    def fetchall(self):
        for needle, rows in self.answers.items():
            if needle in self._qs:
                return rows
        return []


GRAFTING = {
    "count(distinct created_at::date)": [(7,)],
    "jsonb_array_elements": [(0, 0)],
    "distinct on (factor)": [("analyst", 0.60, 0.42), ("risk_reward", 0.30, 0.20)],
}


@pytest.fixture
def tuner(db, seed, monkeypatch, tmp_path):
    import hermes_autonomous_self_tune as ST

    log = []
    monkeypatch.setattr(ST, "WEIGHTS_FILE", seed)
    monkeypatch.setattr(ST, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    monkeypatch.setattr(ST, "_LEARN_ONLY", False)
    monkeypatch.setenv(store.MIRROR_ENV, str(seed))  # the graft must land in the pinned mirror
    monkeypatch.setenv(store.DB_ENV, "0")
    return types.SimpleNamespace(mod=ST, log=log, seed=seed, cur=lambda: _Cur(dict(GRAFTING), log))


def test_the_graft_moves_from_the_learned_weights_not_the_v9_seed(tuner):
    # The DB is the live store... but DB is disabled in this fixture, so feed the mirror instead.
    import yaml

    tuner.seed.write_text(yaml.safe_dump(LEARNED_DOC, sort_keys=False), encoding="utf-8")

    result = tuner.mod.auto_graft_weights(tuner.cur(), apply=False)

    by_factor = {c["factor"]: c for c in result["changes"]}
    # analyst 0.4962 -> 0.60 clamped by HERMES_GRAFT_MAX_STEP 0.02 => 0.5162, not 0.44+0.02
    assert by_factor["analyst"]["from"] == pytest.approx(0.4962)
    assert by_factor["analyst"]["to"] == pytest.approx(0.5162)


def test_an_applied_graft_never_writes_the_release_config(tuner, monkeypatch, tmp_path):
    import yaml

    mirror = tmp_path / "persistent-state" / "hermes_score_weights.yaml"
    monkeypatch.setenv(store.MIRROR_ENV, str(mirror))
    before = tuner.seed.read_bytes()

    result = tuner.mod.auto_graft_weights(tuner.cur(), apply=True)

    assert result["status"] == "applied"
    assert tuner.seed.read_bytes() == before, "the release seed was written — a release would re-clobber it"
    assert yaml.safe_load(mirror.read_text(encoding="utf-8"))["version"] == 10  # v9 seed -> next graft


def test_a_graft_with_a_separate_seed_leaves_that_seed_untouched(db, seed, monkeypatch, tmp_path):
    import yaml
    import hermes_autonomous_self_tune as ST

    db.row = None
    monkeypatch.setitem(sys.modules, "config_db_loader", db)
    monkeypatch.delenv(store.DB_ENV, raising=False)
    monkeypatch.setenv(store.MIRROR_ENV, str(tmp_path / "mirror" / "w.yaml"))
    monkeypatch.setattr(ST, "WEIGHTS_FILE", seed)
    monkeypatch.setattr(ST, "GRAFT_ARCHIVE_DIR", tmp_path / "grafts")
    before = seed.read_bytes()

    result = ST.auto_graft_weights(_Cur(dict(GRAFTING), []), apply=True)

    assert result["status"] == "applied"
    assert seed.read_bytes() == before, "the release seed must never be a write target"
    mirrored = yaml.safe_load((tmp_path / "mirror" / "w.yaml").read_text())
    assert mirrored["version"] == 10  # v9 seed -> next graft
    assert db.row["version"] == 10


# ── the other readers follow the store ──────────────────────────────────────
def test_the_scorer_ranks_with_the_db_weights(db, seed, monkeypatch):
    import hermes_watchlist_scorer as scorer

    db.row = LEARNED_DOC
    monkeypatch.setenv(store.DB_ENV, "1")
    monkeypatch.setattr(scorer, "WEIGHTS_FILE", seed)

    weights = scorer._weights()
    assert weights["analyst"] == pytest.approx(0.4962)
    assert weights["technical_momentum"] == pytest.approx(0.0098)


def test_calibration_and_outcome_learning_read_the_same_weights(db, seed, monkeypatch):
    import hermes_outcome_learning as hol
    import hermes_score_calibration as cal

    db.row = LEARNED_DOC
    monkeypatch.setenv(store.DB_ENV, "1")
    monkeypatch.setattr(cal, "WEIGHTS_FILE", seed)
    monkeypatch.setattr(hol, "WEIGHTS_FILE", seed)

    assert cal._weights()["analyst"] == pytest.approx(0.4962)
    assert hol._live_weights()["analyst"] == pytest.approx(0.4962)


# ── recovery of the lost grafts ─────────────────────────────────────────────
def _write_archive(directory: Path, name: str, doc: dict) -> Path:
    import yaml

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_newest_archive_is_chosen_by_its_timestamp_not_its_filename(db, tmp_path, monkeypatch):
    import migrate_hermes_score_weights_to_store as mig

    archive = tmp_path / "grafts"
    _write_archive(archive, "hermes_score_weights.v20.20261020T210003Z.yaml", SEED_DOC)
    newer = _write_archive(archive, "hermes_score_weights.v20.20261101T220001Z.yaml", LEARNED_DOC)
    monkeypatch.setenv("HERMES_WEIGHT_GRAFT_ARCHIVE", str(archive))
    monkeypatch.setattr(mig, "PROJECT_ROOT", tmp_path / "code-root")

    assert mig.newest_archive() == newer


def test_recovery_dry_run_writes_nothing(db, tmp_path, monkeypatch):
    import migrate_hermes_score_weights_to_store as mig

    db.row = None
    src = _write_archive(tmp_path / "grafts", "hermes_score_weights.v20.20261101T220001Z.yaml", LEARNED_DOC)
    monkeypatch.setenv(store.MIRROR_ENV, str(tmp_path / "mirror" / "w.yaml"))

    assert mig.main(["--source", str(src)]) == 0

    assert db.calls == [("get", store.CONFIG_KEY)]
    assert not (tmp_path / "mirror" / "w.yaml").exists()


def test_recovery_apply_writes_db_then_mirror(db, tmp_path, monkeypatch, capsys):
    import migrate_hermes_score_weights_to_store as mig

    db.row = None
    src = _write_archive(tmp_path / "grafts", "hermes_score_weights.v20.20261101T220001Z.yaml", LEARNED_DOC)
    mirror = tmp_path / "mirror" / "w.yaml"
    monkeypatch.setenv(store.MIRROR_ENV, str(mirror))

    assert mig.main(["--source", str(src), "--apply", "--json"]) == 0

    assert [c[0] for c in db.calls] == ["get", "put"]
    assert db.row["version"] == 20 and db.row["weights"]["analyst"] == pytest.approx(0.4962)
    assert mirror.is_file()


def test_recovery_refuses_a_document_that_does_not_sum_to_one(db, tmp_path, monkeypatch):
    import migrate_hermes_score_weights_to_store as mig

    bad = dict(LEARNED_DOC, weights={"analyst": 0.10, "risk_reward": 0.10})
    src = _write_archive(tmp_path / "grafts", "hermes_score_weights.v21.20261102T220001Z.yaml", bad)
    monkeypatch.setenv(store.MIRROR_ENV, str(tmp_path / "mirror" / "w.yaml"))

    assert mig.main(["--source", str(src), "--apply"]) == 2
    assert db.calls == []


def test_recovery_refuses_to_downgrade_a_newer_store(db, tmp_path, monkeypatch):
    import migrate_hermes_score_weights_to_store as mig

    db.row = dict(LEARNED_DOC, version=25)
    old = dict(LEARNED_DOC, version=20)
    src = _write_archive(tmp_path / "grafts", "hermes_score_weights.v20.20261101T220001Z.yaml", old)
    monkeypatch.setenv(store.MIRROR_ENV, str(tmp_path / "mirror" / "w.yaml"))

    assert mig.main(["--source", str(src), "--apply"]) == 3
    assert [c[0] for c in db.calls] == ["get"]
