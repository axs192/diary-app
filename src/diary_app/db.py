"""SQLite access: one function that returns a ready, migrated connection.

Schema changes are plain SQL files named ``NNNN_description.sql`` in
``diary_app/migrations/``. They run once each, in numeric order, and the
highest applied number is stored in SQLite's ``user_version`` pragma. To
change the schema, add a new file; never edit one that has shipped.
"""

import contextlib
import logging
import pathlib
import sqlite3
import time
from collections.abc import Iterator

_logger = logging.getLogger(__name__)

_DEFAULT_MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
_BUSY_TIMEOUT_MS = 5000
_WAL_ATTEMPTS = 100
_WAL_RETRY_SECONDS = 0.05


class MigrationError(Exception):
    """Raised when a migration script fails; the database is left unchanged."""


def connect(
    path: pathlib.Path | str,
    migrations_dir: pathlib.Path | None = None,
) -> sqlite3.Connection:
    """Opens the database and brings its schema up to date.

    The web process and the timer-run jobs open the same file, so file
    databases use write-ahead logging and wait briefly on a locked database
    rather than failing. Rows are returned as ``sqlite3.Row`` (indexable by
    column name). The connection is in autocommit mode: call
    ``conn.execute("BEGIN")`` and ``conn.commit()`` to group statements.
    The database's parent folder is created if missing. Several processes or
    threads may call this at once on an out-of-date database: whichever
    applies a migration first wins and the others carry on.

    Args:
        path: Database file, or ``":memory:"`` for a throwaway database.
        migrations_dir: Folder of ``NNNN_*.sql`` files. Defaults to the
            migrations packaged with the app.

    Returns:
        An open connection with every pending migration applied.

    Raises:
        MigrationError: If a migration script fails.
    """
    if str(path) != ":memory:":
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    # A web request's connection can be opened and used on different worker
    # threads, but only one at a time, so SQLite's thread check is not needed.
    conn = sqlite3.connect(
        str(path), isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    if str(path) != ":memory:":
        _enable_wal(conn)
    try:
        _migrate(conn, migrations_dir or _DEFAULT_MIGRATIONS)
    except Exception:
        conn.close()
        raise
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    # Switching a fresh database to WAL needs an exclusive lock and SQLite
    # does not wait for it (busy_timeout is ignored), so concurrent first
    # connections can see "database is locked". Retry briefly instead.
    for attempt in range(_WAL_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            if attempt == _WAL_ATTEMPTS - 1:
                raise
            time.sleep(_WAL_RETRY_SECONDS)
        else:
            return


def _schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _migrate(conn: sqlite3.Connection, folder: pathlib.Path) -> None:
    scripts = sorted(folder.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    for script in scripts:
        version = int(script.name.split("_", 1)[0])
        # Read fresh each time: another connection may have just migrated.
        if version <= _schema_version(conn):
            continue
        _logger.info("Applying migration %s", script.name)
        _apply(conn, script, version)


def _apply(
    conn: sqlite3.Connection, script: pathlib.Path, version: int
) -> None:
    sql = script.read_text(encoding="utf-8")
    try:
        # IMMEDIATE takes the write lock now (waiting for other writers), so
        # the version check below cannot be outdated by a concurrent migrator.
        conn.execute("BEGIN IMMEDIATE")
        if _schema_version(conn) >= version:
            conn.execute("ROLLBACK")  # another connection already did it
            return
        for statement in _statements(sql):
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        # SQLite DDL is transactional, so a failure leaves no trace.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        msg = f"Migration {script.name} failed: {exc}"
        raise MigrationError(msg) from exc


def _statements(sql: str) -> list[str]:
    """Splits a script into single statements (``execute`` takes one)."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        statements.append(buffer)
    return statements


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    """Reads a stored preference.

    Args:
        conn: Open database connection.
        key: Setting name, e.g. ``"app_colour"``.
        default: Returned when the setting has never been saved.

    Returns:
        The saved value, or ``default``.
    """
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,))
    found = row.fetchone()
    return found["value"] if found else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Saves a preference, replacing any earlier value.

    Args:
        conn: Open database connection.
        key: Setting name.
        value: Text to store.
    """
    conn.execute(
        "INSERT INTO setting (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Makes the changes inside the ``with`` block all happen or none.

    The connection is in autocommit mode, so a function that changes several
    rows wraps them in this. It takes the write lock at once (waiting for
    other writers), so a read-then-write inside cannot be overtaken.

    If a transaction is already open (a caller wrapped this call in its own),
    the block simply joins it: the outermost block commits or rolls back.

    Args:
        conn: Open database connection.

    Yields:
        Nothing; commits when the block ends, and rolls back, re-raising, if
        it raises.
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
