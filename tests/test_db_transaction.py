"""Tests for db.transaction."""

import unittest

from diary_app import db


class TransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.conn.execute("CREATE TABLE t (n INTEGER)")

    def rows(self) -> list[int]:
        return [r["n"] for r in self.conn.execute("SELECT n FROM t ORDER BY n")]

    def test_the_changes_are_kept_when_the_block_ends(self) -> None:
        with db.transaction(self.conn):
            self.conn.execute("INSERT INTO t VALUES (1)")
            self.conn.execute("INSERT INTO t VALUES (2)")
        self.assertEqual(self.rows(), [1, 2])
        self.assertFalse(self.conn.in_transaction)

    def test_none_of_the_changes_are_kept_when_the_block_raises(self) -> None:
        with self.assertRaises(RuntimeError), db.transaction(self.conn):
            self.conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError
        self.assertEqual(self.rows(), [])
        self.assertFalse(self.conn.in_transaction)

    def test_a_block_inside_another_joins_it(self) -> None:
        with db.transaction(self.conn):
            self.conn.execute("INSERT INTO t VALUES (1)")
            with db.transaction(self.conn):
                self.conn.execute("INSERT INTO t VALUES (2)")
            self.assertTrue(self.conn.in_transaction)  # inner did not commit
        self.assertEqual(self.rows(), [1, 2])

    def test_the_outer_block_rolls_back_what_the_inner_one_did(self) -> None:
        with self.assertRaises(RuntimeError), db.transaction(self.conn):
            with db.transaction(self.conn):
                self.conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
