"""SQLite access: one function that returns a ready, migrated connection.

Schema changes are plain SQL files named ``NNNN_description.sql`` in
``diary_app/migrations/``. They run once each, in numeric order, and the
highest applied number is stored in SQLite's ``user_version`` pragma. To
change the schema, add a new file; never edit one that has shipped.
"""

import logging
import pathlib
import sqlite3

_logger = logging.getLogger(__name__)

_DEFAULT_MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
_BUSY_TIMEOUT_MS = 5000


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

    Args:
        path: Database file, or ``":memory:"`` for a throwaway database.
        migrations_dir: Folder of ``NNNN_*.sql`` files. Defaults to the
            migrations packaged with the app.

    Returns:
        An open connection with every pending migration applied.

    Raises:
        MigrationError: If a migration script fails.
    """
    # A web request's connection can be opened and used on different worker
    # threads, but only one at a time, so SQLite's thread check is not needed.
    conn = sqlite3.connect(
        str(path), isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    try:
        _migrate(conn, migrations_dir or _DEFAULT_MIGRATIONS)
    except Exception:
        conn.close()
        raise
    return conn


def _migrate(conn: sqlite3.Connection, folder: pathlib.Path) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    scripts = sorted(folder.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    for script in scripts:
        version = int(script.name.split("_", 1)[0])
        if version <= current:
            continue
        _logger.info("Applying migration %s", script.name)
        _apply(conn, script, version)


def _apply(
    conn: sqlite3.Connection, script: pathlib.Path, version: int
) -> None:
    # SQLite DDL is transactional, so a failure part-way leaves no trace.
    sql = script.read_text(encoding="utf-8")
    try:
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};")
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        msg = f"Migration {script.name} failed: {exc}"
        raise MigrationError(msg) from exc


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
