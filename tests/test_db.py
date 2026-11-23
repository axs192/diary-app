"""Tests for the diary_app.db public interface: connect."""

import pathlib
import tempfile
import unittest

from diary_app import db


def _write_migrations(directory: pathlib.Path, scripts: dict[str, str]) -> None:
    for name, sql in scripts.items():
        (directory / name).write_text(sql, encoding="utf-8")


class ConnectTest(unittest.TestCase):
    """connect returns a ready-to-use, fully migrated connection."""

    def test_in_memory_connection_has_the_initial_schema(self) -> None:
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO setting (key, value) VALUES ('a', 'b')")
        row = conn.execute("SELECT value FROM setting WHERE key='a'").fetchone()
        self.assertEqual(row["value"], "b")

    def test_foreign_keys_are_enforced(self) -> None:
        conn = db.connect(":memory:")
        self.assertEqual(
            conn.execute("PRAGMA foreign_keys").fetchone()[0],
            1,
        )

    def test_reconnecting_keeps_data_and_does_not_rerun_migrations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "diary.db"
            first = db.connect(path)
            first.execute("INSERT INTO setting (key, value) VALUES ('a', 'b')")
            first.commit()
            first.close()

            second = db.connect(path)
            rows = second.execute("SELECT key, value FROM setting").fetchall()
            second.close()

        self.assertEqual([tuple(r) for r in rows], [("a", "b")])

    def test_migrations_run_in_filename_order_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            _write_migrations(
                folder,
                {
                    "0002_add_row.sql": "INSERT INTO t (n) VALUES (2);",
                    "0001_make_table.sql": "CREATE TABLE t (n INTEGER);",
                    "0003_add_row.sql": "INSERT INTO t (n) VALUES (3);",
                },
            )
            db_path = folder / "x.db"

            db.connect(db_path, migrations_dir=folder).close()
            conn = db.connect(db_path, migrations_dir=folder)
            values = [
                r["n"] for r in conn.execute("SELECT n FROM t ORDER BY rowid")
            ]
            conn.close()

        self.assertEqual(values, [2, 3])

    def test_failed_migration_rolls_back_and_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            _write_migrations(
                folder,
                {
                    "0001_bad.sql": (
                        "CREATE TABLE t (n INTEGER); SELECT * FROM missing;"
                    ),
                },
            )
            with self.assertRaises(db.MigrationError):
                db.connect(folder / "x.db", migrations_dir=folder)


if __name__ == "__main__":
    unittest.main()
