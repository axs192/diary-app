"""Tests for the diary_app.db public interface: connect."""

import pathlib
import tempfile
import threading
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


class ConcurrencyAndPathTest(unittest.TestCase):
    """Parallel requests and fresh checkouts must not break connect."""

    def test_parallel_connects_on_a_fresh_database_all_succeed(self) -> None:
        workers = 8
        barrier = threading.Barrier(workers)
        errors: list[BaseException] = []

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "diary.db"

            def open_db() -> None:
                try:
                    barrier.wait()
                    db.connect(path).close()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=open_db) for _ in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            conn = db.connect(path)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            people = conn.execute("SELECT COUNT(*) FROM person").fetchone()[0]
            conn.close()

        self.assertEqual(errors, [])
        self.assertGreaterEqual(version, 2)
        self.assertEqual(people, 1)  # the seed row was inserted exactly once

    def test_connect_creates_a_missing_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "data" / "nested" / "diary.db"
            db.connect(path).close()
            self.assertTrue(path.exists())


class SettingTest(unittest.TestCase):
    """get_setting / set_setting store small key-value preferences."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def test_missing_setting_returns_the_default(self) -> None:
        self.assertEqual(
            db.get_setting(self.conn, "app_colour", "Green"), "Green"
        )

    def test_set_then_get_returns_the_value(self) -> None:
        db.set_setting(self.conn, "app_colour", "Blue")
        self.assertEqual(
            db.get_setting(self.conn, "app_colour", "Green"), "Blue"
        )

    def test_setting_again_overwrites(self) -> None:
        db.set_setting(self.conn, "app_colour", "Blue")
        db.set_setting(self.conn, "app_colour", "Teal")
        self.assertEqual(
            db.get_setting(self.conn, "app_colour", "Green"), "Teal"
        )


class ThreadingTest(unittest.TestCase):
    """A request's connection may be opened and used on different threads."""

    def test_connection_works_from_another_thread(self) -> None:
        conn = db.connect(":memory:")
        errors: list[BaseException] = []

        def use() -> None:
            try:
                conn.execute("SELECT 1").fetchone()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=use)
        thread.start()
        thread.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
