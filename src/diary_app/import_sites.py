"""The recipe sites the importer may fetch from.

The built-in sites (``recipe_import.ALLOWED_HOSTS``) are always allowed.
The household can add more in Settings. Only the host name is kept, so a
pasted address can never make the server request anything else, and the
importer's private-network, robots.txt, size and redirect limits still
apply to every added site.
"""

import ipaddress
import re
import sqlite3
import urllib.parse

from diary_app import recipe_import

MAX_EXTRA = 20
_KEY = "import_hosts"
_MAX_HOST_LENGTH = 253
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# At least two labels, so single names like "localhost" are not accepted.
_HOST = re.compile(rf"^{_LABEL}(?:\.{_LABEL})+$")


class InvalidSiteError(ValueError):
    """Raised when a site cannot be added."""


def allowed(conn: sqlite3.Connection) -> frozenset[str]:
    """Returns every host the importer may fetch from.

    Args:
        conn: Open database connection.

    Returns:
        The built-in hosts plus any the household added.
    """
    return recipe_import.ALLOWED_HOSTS | frozenset(added(conn))


def added(conn: sqlite3.Connection) -> list[str]:
    """Returns the hosts the household added, in the order added.

    Args:
        conn: Open database connection.

    Returns:
        Added host names (never the built-in ones).
    """
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (_KEY,))
    found = row.fetchone()
    return found["value"].split() if found else []


def add(conn: sqlite3.Connection, text: str) -> str:
    """Allows a recipe site.

    Args:
        conn: Open database connection.
        text: A host name such as ``www.example.com``, or a pasted web
            address (only its host is kept).

    Returns:
        The host that is now allowed. Adding a built-in or already added
        host changes nothing.

    Raises:
        InvalidSiteError: If it isn't a usable host name (IP addresses,
            single names such as ``localhost`` and ports are refused), or
            the list is full.
    """
    host = _host_of(text)
    current = added(conn)
    if host in recipe_import.ALLOWED_HOSTS or host in current:
        return host
    if len(current) >= MAX_EXTRA:
        msg = f"You can add up to {MAX_EXTRA} extra sites. Remove one first."
        raise InvalidSiteError(msg)
    _save(conn, [*current, host])
    return host


def remove(conn: sqlite3.Connection, host: str) -> None:
    """Stops allowing an added site. Built-in sites cannot be removed.

    Args:
        conn: Open database connection.
        host: The host name to remove; an unknown one is ignored.
    """
    current = added(conn)
    if host in current:
        _save(conn, [h for h in current if h != host])


def _save(conn: sqlite3.Connection, hosts: list[str]) -> None:
    conn.execute(
        "INSERT INTO setting (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_KEY, " ".join(hosts)),
    )


def _host_of(text: str) -> str:
    text = text.strip().lower()
    if "://" in text:
        parts = urllib.parse.urlsplit(text)
        if parts.username or parts.password or parts.port:
            raise _invalid()
        text = parts.hostname or ""
    elif "/" in text or "?" in text or "#" in text:
        text = urllib.parse.urlsplit("//" + text).hostname or ""
    if len(text) > _MAX_HOST_LENGTH or not _HOST.match(text):
        raise _invalid()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return text
    raise _invalid()


def _invalid() -> InvalidSiteError:
    return InvalidSiteError(
        "Enter a site name such as www.example.com (not an IP address)."
    )
