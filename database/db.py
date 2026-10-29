
"""SQLite connection, schema initialization, and transaction helpers."""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = ROOT / "database" / "workflow.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Create a SQLite connection with row access and foreign keys enabled."""
    database_path = Path(path) if path is not None else DATABASE_PATH

    # Ensure the database directory exists.
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(database_path),
        timeout=30.0,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    return connection


def initialize(path: str | Path | None = None) -> None:
    """Initialize the database using the project's SQL schema."""
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(
            f"Database schema file not found: {SCHEMA_PATH}"
        )

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with closing(connect(path)) as connection:
        try:
            # Execute schema statements within an explicit transaction.
            connection.execute("BEGIN")
            connection.executescript(
                "BEGIN;\n"
                + schema_sql
                + "\nCOMMIT;"
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


@contextmanager
def transaction(
    path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a connection and commit on success or roll back on failure."""
    connection = connect(path)

    try:
        with connection:
            yield connection
    finally:
        connection.close()
