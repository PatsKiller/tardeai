"""Fail-closed validation for the isolated agentic-runtime PostgreSQL LAB.

This module does not connect to PostgreSQL.  It validates an operator-supplied
LAB target and constructs explicit ``/usr/bin/psql`` argument vectors only
when every isolation invariant is satisfied.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Final, Sequence


DISPOSABLE_ACK: Final = "DISPOSABLE_LAB_NO_PRODUCTION_DATA"
EXPECTED_HOST: Final = "127.0.0.1"
EXPECTED_PORT: Final = 5433
EXPECTED_DATA_ROOT: Final = PurePosixPath("/home/johnclaw/tradeai-lab")
PRODUCTION_PORT: Final = 5432
FORBIDDEN_DATABASES: Final = frozenset({"trade_ai", "postgres", "template0", "template1"})
EXPECTED_ROLES: Final = {
    "migration_role": "agentic_lab_migrator",
    "reader_role": "trade_ai_shadow_ro",
    "writer_role": "agentic_runtime_lab_rw",
}


class LabPreflightError(ValueError):
    """Raised when a target fails one or more isolation invariants."""


@dataclass(frozen=True)
class LabTarget:
    host: str
    port: int
    database: str
    data_directory: str
    migration_role: str
    reader_role: str
    writer_role: str
    disposable_ack: str

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        database = self.database.strip().lower()
        data_directory = PurePosixPath(self.data_directory)

        if self.host != EXPECTED_HOST:
            errors.append(f"host must be explicit loopback {EXPECTED_HOST}")
        if self.port == PRODUCTION_PORT:
            errors.append("production PostgreSQL port 5432 is forbidden")
        elif self.port != EXPECTED_PORT:
            errors.append(f"LAB port must match the inventoried user-owned cluster on {EXPECTED_PORT}")
        if database in FORBIDDEN_DATABASES or "lab" not in database:
            errors.append("database must be an explicitly named disposable LAB database")
        if data_directory == PurePosixPath("/var/lib/postgresql/17/main"):
            errors.append("production PostgreSQL data directory is forbidden")
        try:
            data_directory.relative_to(EXPECTED_DATA_ROOT)
        except ValueError:
            errors.append(f"data directory must be beneath {EXPECTED_DATA_ROOT}")
        for field_name, expected in EXPECTED_ROLES.items():
            if getattr(self, field_name) != expected:
                errors.append(f"{field_name} must be {expected}")
        if self.disposable_ack != DISPOSABLE_ACK:
            errors.append("explicit disposable/no-production-data acknowledgement is required")
        return tuple(errors)

    def validate(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise LabPreflightError("; ".join(errors))

    def sanitized_summary(self) -> dict[str, object]:
        self.validate()
        summary = asdict(self)
        summary.pop("disposable_ack", None)
        summary["disposable_ack_verified"] = True
        summary["production_port_refused"] = True
        summary["production_database_refused"] = True
        summary["dsn_or_secret_included"] = False
        return summary


def psql_argv(target: LabTarget, *, role: str) -> tuple[str, ...]:
    """Return an explicit, alias-proof psql argv after validating the target.

    Passwords, DSNs and SQL are deliberately not accepted by this function.
    Authentication must be supplied through an approved non-repository path.
    """

    target.validate()
    allowed_roles = {
        target.migration_role,
        target.reader_role,
        target.writer_role,
    }
    if role not in allowed_roles:
        raise LabPreflightError("role is not one of the three approved LAB identities")
    return (
        "/usr/bin/psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        target.host,
        "-p",
        str(target.port),
        "-d",
        target.database,
        "-U",
        role,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an isolated agentic PostgreSQL LAB target")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--data-directory", required=True)
    parser.add_argument("--migration-role", required=True)
    parser.add_argument("--reader-role", required=True)
    parser.add_argument("--writer-role", required=True)
    parser.add_argument("--disposable-ack", required=True)
    parser.add_argument("--print-argv-for", choices=("migration", "reader", "writer"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    target = LabTarget(
        host=args.host,
        port=args.port,
        database=args.database,
        data_directory=args.data_directory,
        migration_role=args.migration_role,
        reader_role=args.reader_role,
        writer_role=args.writer_role,
        disposable_ack=args.disposable_ack,
    )
    try:
        payload: dict[str, object] = {"ok": True, "target": target.sanitized_summary()}
        if args.print_argv_for:
            role = {
                "migration": target.migration_role,
                "reader": target.reader_role,
                "writer": target.writer_role,
            }[args.print_argv_for]
            payload["psql_argv"] = psql_argv(target, role=role)
    except LabPreflightError as exc:
        print(json.dumps({"ok": False, "errors": target.validation_errors()}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
