"""Tests for the diary_app.security public interface: PinChecker."""

import unittest

from diary_app import security


class _Clock:
    """A controllable clock so lockout expiry needs no sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class PinCheckerTest(unittest.TestCase):
    """PinChecker validates a household PIN and throttles guessing."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.checker = security.PinChecker(
            "4321", max_failures=3, lockout_seconds=60, clock=self.clock
        )

    def test_correct_pin_is_accepted(self) -> None:
        self.assertEqual(self.checker.check("4321"), security.PinResult.OK)

    def test_wrong_pin_is_rejected(self) -> None:
        self.assertEqual(self.checker.check("0000"), security.PinResult.WRONG)

    def test_too_many_failures_lock_out_even_the_correct_pin(self) -> None:
        for _ in range(3):
            self.checker.check("0000")
        self.assertEqual(self.checker.check("4321"), security.PinResult.LOCKED)

    def test_lockout_ends_after_the_lockout_period(self) -> None:
        for _ in range(3):
            self.checker.check("0000")
        self.clock.now += 61
        self.assertEqual(self.checker.check("4321"), security.PinResult.OK)

    def test_success_resets_the_failure_count(self) -> None:
        self.checker.check("0000")
        self.checker.check("0000")
        self.checker.check("4321")
        self.checker.check("0000")
        self.checker.check("0000")
        self.assertEqual(self.checker.check("4321"), security.PinResult.OK)

    def test_attempts_while_locked_do_not_extend_the_lockout(self) -> None:
        for _ in range(3):
            self.checker.check("0000")
        self.clock.now += 30
        self.checker.check("0000")
        self.clock.now += 31
        self.assertEqual(self.checker.check("4321"), security.PinResult.OK)


if __name__ == "__main__":
    unittest.main()
