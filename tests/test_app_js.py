"""Tests for /static/app.js, the one script the iOS 9 iPad runs."""

import pathlib
import re
import tempfile
import unittest

import pydantic
from fastapi import testclient

from diary_app import app as diary_app
from diary_app import config
from tests import support

_PIN = "4321"
_SESSION_SECRET = "app-js-test-session-secret-0123456789"  # noqa: S105

# Syntax and APIs that iOS 9 Safari lacks. Each is (name, pattern).
_NOT_ES5 = (
    ("arrow function", r"=>"),
    ("let/const", r"\b(?:let|const)\b"),
    ("template literal", r"`"),
    ("class", r"\bclass\s+[A-Za-z_$]"),
    ("async/await", r"\b(?:async|await)\b"),
    ("for...of", r"\bfor\s*\([^)]*\bof\b"),
    ("spread/rest", r"\.\.\."),
    ("fetch", r"\bfetch\s*\("),
    ("Element.closest", r"\.closest\s*\("),
    ("includes", r"\.includes\s*\("),
    ("startsWith/endsWith", r"\.(?:startsWith|endsWith)\s*\("),
    ("Object.entries/values", r"\bObject\.(?:entries|values)\b"),
    ("NodeList.forEach", r"\.forEach\s*\("),
    ("Promise.finally", r"\.finally\s*\("),
)


def _es5_violations(source: str) -> list[str]:
    """Names the non-ES5 features used by ``source`` (comments ignored)."""
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    return [name for name, pattern in _NOT_ES5 if re.search(pattern, code)]


class _AppJsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = config.Settings(
            household_pin=pydantic.SecretStr(_PIN),
            session_secret=pydantic.SecretStr(_SESSION_SECRET),
            database_path=pathlib.Path(tmp.name) / "diary.db",
        )
        self.client = testclient.TestClient(
            diary_app.create_app(settings), follow_redirects=False
        )


class ServedScriptTest(_AppJsTestCase):
    """Every page loads the script, and the script is served."""

    def test_the_script_is_served_as_javascript(self) -> None:
        response = self.client.get("/static/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])

    def test_every_page_loads_it_exactly_once(self) -> None:
        # The login page is only shown to someone who is logged out.
        pages = [("/login", self.client.get("/login").text)]
        self.client.post("/login", data={"pin": _PIN})
        for page in ("/home", "/meals", "/settings"):
            pages.append((page, self.client.get(page).text))
        for page, html in pages:
            self.assertEqual(html.count(support.APP_SCRIPT_TAG), 1, page)
            support.assert_only_app_script(self, html, page)

    def test_it_only_hands_same_origin_links_to_the_page(self) -> None:
        source = self.client.get("/static/app.js").text
        self.assertIn("location.href", source)
        self.assertIn("target", source)  # target=_blank links are left alone
        self.assertIn("download", source)  # so are downloads


class OnlyAppScriptHelperTest(unittest.TestCase):
    """The shared check must not be fooled by how a script tag is written."""

    def test_other_scripts_are_caught_whatever_their_case(self) -> None:
        for markup in (
            "<script>alert(1)</script>",
            "<SCRIPT>alert(1)</SCRIPT>",
            '<ScRiPt src="/evil.js">',
            "<script >x</script >",
        ):
            with self.assertRaises(AssertionError, msg=markup):
                support.assert_only_app_script(self, markup, "x")

    def test_the_app_script_passes(self) -> None:
        support.assert_only_app_script(
            self, f"<p>{support.APP_SCRIPT_TAG}</script></p>", "x"
        )


class Es5GuardTest(_AppJsTestCase):
    """The iPad's Safari 9 cannot run modern JavaScript."""

    def test_the_script_is_plain_es5(self) -> None:
        response = self.client.get("/static/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_es5_violations(response.text), [])

    def test_the_guard_catches_modern_code(self) -> None:
        modern = (
            "const f = (x) => `${x}`;\n"
            "class A {}\n"
            "async function g() { await fetch('/x'); }\n"
            "for (const a of b) { c(...a); }\n"
            "e.closest('a'); s.includes('x'); Object.entries(o);\n"
        )
        found = _es5_violations(modern)
        for name in (
            "arrow function",
            "let/const",
            "template literal",
            "class",
            "async/await",
            "for...of",
            "spread/rest",
            "fetch",
            "Element.closest",
            "includes",
            "Object.entries/values",
        ):
            self.assertIn(name, found)

    def test_the_guard_ignores_comments(self) -> None:
        self.assertEqual(
            _es5_violations("/* const x = () => 1; */\n// fetch(1)\nvar a;"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
