"""The live Hermes factor weights — Postgres first, persistent-state mirror, release seed last.

WHY THIS MODULE EXISTS (LQ-20261107-55, 2026-11-07)

``hermes_autonomous_self_tune`` learned factor weights from the outcome ledger and wrote them
into ``config/hermes_score_weights.yaml`` — a file inside the release directory. Every release
promotes a fresh tree from git, so every graft was overwritten by the v9 seed: the 11-01 graft
left the live file at v20, while the scorer kept reading v9 from 2026-08-13. Forty-two audited
grafts were lost that way.

The operator rules of 2026-11-07 settle where runtime state belongs:

  * "DATABASE IS THE SYSTEM OF RECORD": a lane writes Postgres first; any JSON/YAML it writes is
    a backup mirror, never the thing an API, page or message reads while the DB is up.
  * runtime state must survive a release: nothing an agent learns may live only in a tree that a
    promote replaces.

The store ladder, therefore:

  1. ``config_documents`` (config_key ``hermes_score_weights``) — SYSTEM OF RECORD. The same
     DB-first config store (``scripts/config_db_loader.py``) that already serves the other 38
     runtime configs, with a ``config_document_history`` row on every change.
  2. ``<persistent-state>/data/hermes/hermes_score_weights.yaml`` — the backup mirror, read only
     when the DB is unreachable. Written immediately after the DB write so a DB outage cannot
     cost another graft.
  3. ``config/hermes_score_weights.yaml`` inside the code root — the git seed (v9). Last resort,
     and NEVER written. It is the copy every release resets, which is exactly why it cannot be
     the live store.

``load`` never flattens an unreadable source into a plausible default: a tier that fails
validation is skipped and named, and the caller can see which tier answered.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

CONFIG_KEY = "hermes_score_weights"
CONFIG_TYPE = "runtime_state"

#: Pin the backup mirror (tests, canary runs). The DB tier is unaffected.
MIRROR_ENV = "HERMES_SCORE_WEIGHTS_FILE"
#: ``0`` disables the DB tier — unit tests must never reach the live config store.
DB_ENV = "HERMES_SCORE_WEIGHTS_DB"

CODE_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_REL = Path("config") / "hermes_score_weights.yaml"
MIRROR_REL = Path("data") / "hermes" / "hermes_score_weights.yaml"

SOURCE_DB = "config_documents"
SOURCE_MIRROR = "persistent_state"
SOURCE_SEED = "release_seed"


# ── paths ─────────────────────────────────────────────────────────────────────
def seed_file(code_root: Path | str | None = None) -> Path:
    """The git seed inside the code root. Read-only by contract."""
    return Path(code_root or CODE_ROOT) / SEED_REL


def state_root() -> Path:
    """The persistent state root (``lib.canonical_store_registry``), or raise.

    ``production_state_root`` falls back to ``portfolio-server/CURRENT`` when it finds no marker.
    That fallback is a release directory, and a mirror written there would be lost on the next
    promote — the exact defect this module exists to end. Refuse instead of resolving quietly.
    """
    from lib.canonical_store_registry import is_release_dir, production_state_root

    root = Path(production_state_root())
    if is_release_dir(root):
        raise RuntimeError(
            f"persistent state root resolved to a release directory ({root}); "
            f"set TRADEAI_STATE_ROOT / TRADEAI_PERSISTENT_STATE_ROOT"
        )
    return root


def mirror_file(root: Path | str | None = None) -> Path:
    pinned = os.environ.get(MIRROR_ENV, "").strip()
    if pinned:
        return Path(pinned)
    return Path(root or state_root()) / MIRROR_REL


# ── validation ────────────────────────────────────────────────────────────────
def normalise(content):
    """A usable weights document, or None. Never a silently-empty dict."""
    if isinstance(content, (str, bytes)):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return None
    if not isinstance(content, dict):
        return None
    weights = content.get("weights")
    if not isinstance(weights, dict) or not weights:
        return None
    try:
        parsed = {str(k): float(v) for k, v in weights.items()}
    except (TypeError, ValueError):
        return None
    if any(v < 0 or v != v for v in parsed.values()):  # negative or NaN
        return None
    doc = dict(content)
    doc["weights"] = parsed
    return doc


def checksum(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── DB tier ───────────────────────────────────────────────────────────────────
def db_enabled() -> bool:
    return os.environ.get(DB_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _db_get():
    """The config_documents row, or None when absent. Raises when the store is unreachable."""
    import config_db_loader

    return normalise(config_db_loader.fetch_config_document(CONFIG_KEY))


def _db_put(doc: dict, changed_by: str, notes: str | None) -> str:
    import config_db_loader

    return config_db_loader.upsert_config_document(
        CONFIG_KEY,
        doc,
        CONFIG_TYPE,
        source_path=str(mirror_file()),
        notes=notes,
        changed_by=changed_by,
    )


# ── mirror tier ───────────────────────────────────────────────────────────────
def _read_mirror(path: Path):
    import yaml

    if not path.is_file():
        return None
    return normalise(yaml.safe_load(path.read_text(encoding="utf-8")))


def _write_mirror(path: Path, doc: dict) -> Path:
    """Atomic write: a crash mid-write must not leave a half document a reader would trust."""
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False)
        os.replace(tmp, path)
    except BaseException as exc:
        try:
            os.unlink(tmp)
        except OSError as unlink_exc:
            # The write error is the one that must be reported; name the stray temp file on it
            # rather than leave a half document a reader could trust.
            exc.add_note(f"temp file {tmp} could not be removed: {unlink_exc}")
        raise
    return path


# ── public API ────────────────────────────────────────────────────────────────
def resolve(*, seed: Path | str | None = None, mirror: Path | str | None = None) -> dict:
    """``{doc, source, path, errors}`` — the first usable tier, with every failure named."""
    errors: list[str] = []
    if db_enabled():
        try:
            doc = _db_get()
            if doc is not None:
                return {"doc": doc, "source": SOURCE_DB, "path": f"config_documents:{CONFIG_KEY}", "errors": errors}
            errors.append("config_documents: no usable row")
        except Exception as exc:  # noqa: BLE001  -- the failure is recorded in errors[] and the next tier answers
            errors.append(f"config_documents: {type(exc).__name__}: {exc}")

    mirror_path = Path(mirror) if mirror else mirror_file()
    try:
        doc = _read_mirror(mirror_path)
        if doc is not None:
            return {"doc": doc, "source": SOURCE_MIRROR, "path": str(mirror_path), "errors": errors}
        errors.append(f"{mirror_path}: no usable document")
    except Exception as exc:  # noqa: BLE001  -- recorded in errors[], then the seed answers
        errors.append(f"{mirror_path}: {type(exc).__name__}: {exc}")

    seed_path = Path(seed) if seed else seed_file()
    try:
        doc = _read_mirror(seed_path)
        if doc is not None:
            return {"doc": doc, "source": SOURCE_SEED, "path": str(seed_path), "errors": errors}
        errors.append(f"{seed_path}: no usable document")
    except Exception as exc:  # noqa: BLE001  -- recorded in errors[], and resolve() then raises by name
        errors.append(f"{seed_path}: {type(exc).__name__}: {exc}")

    raise FileNotFoundError("hermes score weights: no usable tier — " + "; ".join(errors))


def load(*, seed: Path | str | None = None, mirror: Path | str | None = None) -> tuple[dict, str]:
    """``(document, source)`` — source is one of ``config_documents``/``persistent_state``/``release_seed``."""
    r = resolve(seed=seed, mirror=mirror)
    return r["doc"], r["source"]


def save(
    doc: dict,
    *,
    changed_by: str = "hermes_autonomous_self_tune",
    notes: str | None = None,
    seed: Path | str | None = None,
    mirror: Path | str | None = None,
) -> dict:
    """Write Postgres first, then the mirror. The release seed is never written.

    Returns ``{db, db_error, mirror, mirror_error, checksum}``. A failing tier is named, not
    swallowed; if both tiers fail the save raises — a graft that reached neither store did not
    happen, and the caller's audit row must not claim otherwise.
    """
    doc = normalise(doc)
    if doc is None:
        raise ValueError("refusing to store an unusable weights document")
    out = {
        "db": None,
        "db_error": None,
        "mirror": None,
        "mirror_error": None,
        "checksum": checksum(doc),
        "version": doc.get("version"),
    }

    try:
        if db_enabled():
            out["db"] = _db_put(doc, changed_by, notes)
        else:
            out["db"] = "disabled"
    except Exception as exc:  # noqa: BLE001  -- recorded in db_error; the mirror is the backup copy for exactly this
        out["db_error"] = f"{type(exc).__name__}: {exc}"

    mirror_path = Path(mirror) if mirror else mirror_file()
    try:
        _write_mirror(mirror_path, doc)
        out["mirror"] = str(mirror_path)
    except Exception as exc:  # noqa: BLE001  -- recorded in mirror_error; both tiers failing raises below
        out["mirror_error"] = f"{type(exc).__name__}: {exc}"

    if out["db_error"] and out["mirror_error"]:
        raise RuntimeError(
            f"weights store: neither tier accepted the document (db: {out['db_error']}; mirror: {out['mirror_error']})"
        )
    seed_path = Path(seed) if seed else seed_file()
    out["wrote_seed"] = False
    out["seed_path"] = str(seed_path)  # recorded so a caller can prove it was untouched
    return out
