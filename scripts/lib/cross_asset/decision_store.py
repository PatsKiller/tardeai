"""Single writer for immutable CADI history and its rebuildable projection.

Explicit paths only: importing or constructing this object never activates a
production store. SQLite transactions couple history and projection writes;
schema setup is additive, and a failed write rolls back both tables.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .canonical_decision import (
    AUTHORITY,
    ERROR_SCHEMA,
    SCHEMA,
    adapt_decision,
    canonical_json,
    error_receipt,
    validate_decision,
    validate_error_receipt,
)

PROJECTION_SCHEMA = "CrossAssetDecisionProjection@v1"
STORE_RELATIVE = Path("data") / "cio" / "cross_asset_decisions.sqlite"
NO_CONSUMER_REASON = (
    "DecisionStore consumes canonical v2 decisions and error receipts; the projection is read by latest() "
    "and rebuilt by rebuild_projections(). The existing operator-artifacts audit reader is approval-gated; "
    "CADI-07 adds the dedicated comparison/ranking surface, not this foundation ticket."
)


class DecisionStore:
    """Authoritative derived data, never investment or execution authority."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS cross_asset_evaluation_history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_id TEXT NOT NULL UNIQUE,
                schema_name TEXT NOT NULL,
                symbol TEXT,
                as_of TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS cadi_history_no_update
                BEFORE UPDATE ON cross_asset_evaluation_history
                BEGIN SELECT RAISE(ABORT, 'immutable CADI history'); END;
            CREATE TRIGGER IF NOT EXISTS cadi_history_no_delete
                BEFORE DELETE ON cross_asset_evaluation_history
                BEGIN SELECT RAISE(ABORT, 'immutable CADI history'); END;
            CREATE TRIGGER IF NOT EXISTS cadi_history_no_replace
                BEFORE INSERT ON cross_asset_evaluation_history
                WHEN EXISTS (SELECT 1 FROM cross_asset_evaluation_history
                             WHERE evaluation_id=NEW.evaluation_id OR sequence=NEW.sequence)
                BEGIN SELECT RAISE(ABORT, 'immutable CADI history'); END;
            CREATE TABLE IF NOT EXISTS cross_asset_decision_projection (
                subject_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                evaluation_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (evaluation_id) REFERENCES cross_asset_evaluation_history(evaluation_id)
            );
        """)
        return db

    @staticmethod
    def _project(db: sqlite3.Connection, obj: dict[str, Any]) -> None:
        ident = obj["identity"]
        key = ident.get("security_guid") or ident.get("subject_guid") or ("symbol:" + ident["symbol"])
        prior = db.execute(
            "SELECT as_of,evaluation_id FROM cross_asset_decision_projection WHERE subject_key=?", (key,)
        ).fetchone()
        if prior:
            # Exact aware datetimes preserve submillisecond ordering; SQLite's
            # julianday rounds it away and can select an older observation.
            instant = datetime.fromisoformat(obj["as_of"].replace("Z", "+00:00"))
            prior_instant = datetime.fromisoformat(prior[0].replace("Z", "+00:00"))
            if (instant, obj["evaluation_id"]) <= (prior_instant, prior[1]):
                return
        db.execute(
            """
            INSERT INTO cross_asset_decision_projection (subject_key, symbol, evaluation_id, as_of, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(subject_key) DO UPDATE SET symbol=excluded.symbol, evaluation_id=excluded.evaluation_id,
                as_of=excluded.as_of, payload=excluded.payload
        """,
            (key, ident["symbol"], obj["evaluation_id"], obj["as_of"], canonical_json(obj)),
        )

    def _append(self, obj: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
        text = canonical_json(obj)
        symbol = obj.get("symbol") if is_error else obj["identity"]["symbol"]
        if is_error and not isinstance(symbol, (str, type(None))):
            symbol = None  # Invalid raw identity remains preserved in payload.
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT payload FROM cross_asset_evaluation_history WHERE evaluation_id=?", (obj["evaluation_id"],)
            ).fetchone()
            if prior:
                if prior[0] != text:
                    raise ValueError("EVALUATION_ID_CONTENT_CONFLICT")
                return {"state": "DUPLICATE_IGNORED", "evaluation_id": obj["evaluation_id"]}
            db.execute(
                """INSERT INTO cross_asset_evaluation_history
                (evaluation_id, schema_name, symbol, as_of, payload) VALUES (?, ?, ?, ?, ?)""",
                (obj["evaluation_id"], obj["schema"], symbol, obj["as_of"], text),
            )
            if not is_error:
                self._project(db, obj)
        return {"state": "APPENDED", "evaluation_id": obj["evaluation_id"]}

    def append(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Persist SymbolDecisionObject@v2 without duplicating the history writer."""
        errors = validate_decision(obj)
        if errors:
            raise ValueError("INVALID_DECISION:" + ",".join(errors))
        return self._append(obj, is_error=False)

    def append_error(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Persist CrossAssetDecisionError@v1 in the same immutable history."""
        if validate_error_receipt(receipt):
            raise ValueError("INVALID_ERROR_RECEIPT")
        return self._append(receipt, is_error=True)

    def history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            if limit is not None:
                if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                    raise ValueError("HISTORY_LIMIT_REQUIRED")
                rows = db.execute(
                    "SELECT payload FROM cross_asset_evaluation_history ORDER BY sequence DESC LIMIT ?", (limit,)
                ).fetchall()
                return [json.loads(row[0]) for row in reversed(rows)]
            return [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM cross_asset_evaluation_history ORDER BY sequence")
            ]

    def latest(self, symbol: str, *, security_guid: str | None = None) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT payload FROM cross_asset_decision_projection WHERE symbol=?", (symbol.strip().upper(),)
            ).fetchall()
        decisions = [json.loads(row[0]) for row in rows]
        if any(validate_decision(obj) for obj in decisions):
            raise ValueError("INVALID_PROJECTION")
        if security_guid:
            decisions = [obj for obj in decisions if obj["identity"].get("security_guid") == security_guid]
        if len(decisions) > 1:
            raise ValueError("PROJECTION_IDENTITY_CONFLICT")
        return decisions[0] if decisions else None

    def projection(self, symbol: str) -> dict[str, Any]:
        """Build a CrossAssetDecisionProjection@v1 from read-only durable state."""
        obj = self.latest(symbol)
        return {
            "schema": PROJECTION_SCHEMA,
            "authority": AUTHORITY,
            "financial_action": False,
            "symbol": symbol.strip().upper(),
            "as_of": obj["as_of"] if obj else None,
            "status": "AVAILABLE" if obj else "UNAVAILABLE",
            "decision": obj,
        }

    def rebuild_projections(self) -> dict[str, Any]:
        count = 0
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # Projections are derived, not immutable; history is never removed.
            db.execute("DELETE FROM cross_asset_decision_projection")
            for row in db.execute(
                "SELECT payload FROM cross_asset_evaluation_history WHERE schema_name=? ORDER BY sequence", (SCHEMA,)
            ):
                obj = json.loads(row[0])
                errors = validate_decision(obj)
                if errors:
                    raise ValueError("INVALID_HISTORY:" + ",".join(errors))
                self._project(db, obj)
                count += 1
        return {"decisions": count, "state": "REBUILT"}

    def import_legacy(self, path: Path | str) -> dict[str, Any]:
        """Explicit, additive import; source bytes and original records survive."""
        evaluated = failed = duplicates = 0
        source = str(Path(path))
        file_time = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
        with Path(path).open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                original = None
                try:
                    original = json.loads(line)
                    obj = adapt_decision(original)
                except (ValueError, TypeError, KeyError) as exc:
                    raw = original if isinstance(original, dict) else {}
                    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
                    signal = raw.get("signal_state") if isinstance(raw.get("signal_state"), dict) else {}
                    from .canonical_decision import _error_value

                    receipt = error_receipt(
                        symbol=_error_value(identity.get("symbol") or raw.get("symbol")),
                        raw_action=_error_value(signal.get("raw_action", signal.get("action", signal.get("kind")))),
                        source=_error_value(signal.get("source") or signal.get("lane") or raw.get("source") or source),
                        as_of=file_time,
                        error_code="INVALID_LEGACY_ROW",
                        detail=f"file={source}; line={number}; {exc}; original_line={line.rstrip()}",
                    )
                    # The source-file observation time is reproducible, but
                    # not a fabricated historical investment timestamp.
                    receipt["timestamp_status"] = "SOURCE_FILE_MTIME_NOT_DECISION_TIME"
                    result = self.append_error(receipt)
                    failed += 1
                else:
                    result = self.append(obj)
                    evaluated += 1
                duplicates += result["state"] == "DUPLICATE_IGNORED"
        return {"evaluated": evaluated, "failed": failed, "duplicates": duplicates}
