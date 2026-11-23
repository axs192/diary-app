"""Household PIN check and the login guard for protected pages."""

import enum
import hmac
import logging
import threading
import time
from collections.abc import Callable

import fastapi

_logger = logging.getLogger(__name__)


class PinResult(enum.Enum):
    """Outcome of a PIN attempt."""

    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"


class NotLoggedInError(Exception):
    """Raised by ``require_login``; the app turns it into a redirect."""


class PinChecker:
    """Checks the household PIN and throttles guessing.

    After ``max_failures`` wrong attempts in a row, every attempt (even the
    right PIN) is refused for ``lockout_seconds``. The count is global, not
    per client: this is one household on a home network, and a global limit
    needs no trust in client addresses. State is in memory, so a restart
    clears it.
    """

    def __init__(
        self,
        pin: str,
        max_failures: int = 5,
        lockout_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Creates a checker.

        Args:
            pin: The correct PIN.
            max_failures: Consecutive wrong attempts that trigger a lockout.
            lockout_seconds: How long a lockout lasts.
            clock: Source of seconds; injectable so tests need not sleep.
        """
        self._pin = pin.encode()
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0
        self._lock = threading.Lock()

    def check(self, candidate: str) -> PinResult:
        """Tests one PIN attempt.

        Args:
            candidate: What the user typed.

        Returns:
            ``OK`` if correct, ``WRONG`` if not, ``LOCKED`` if attempts are
            currently refused (the candidate is not even compared).
        """
        with self._lock:
            now = self._clock()
            if now < self._locked_until:
                return PinResult.LOCKED
            if hmac.compare_digest(candidate.encode(), self._pin):
                self._failures = 0
                return PinResult.OK
            self._failures += 1
            if self._failures >= self._max_failures:
                self._failures = 0
                self._locked_until = now + self._lockout_seconds
                _logger.warning(
                    "PIN lockout started: %d wrong attempts in a row; "
                    "login refused for %d seconds",
                    self._max_failures,
                    self._lockout_seconds,
                )
            return PinResult.WRONG


def require_login(request: fastapi.Request) -> None:
    """FastAPI dependency: lets logged-in requests through.

    Args:
        request: The incoming request.

    Raises:
        NotLoggedInError: If the session has not logged in with the PIN.
    """
    if not request.session.get("logged_in"):
        raise NotLoggedInError
