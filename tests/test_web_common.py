"""Tests for the redirect helper in diary_app.web.common."""

import unittest

from diary_app.web import common


class BackToTest(unittest.TestCase):
    """back_to only ever redirects within this site."""

    def test_redirects_to_a_local_path_with_303(self) -> None:
        response = common.back_to("/meals?week=2030-01-07")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/meals?week=2030-01-07")

    def test_backslashes_are_removed_so_they_cannot_act_as_slashes(
        self,
    ) -> None:
        # Browsers read "/\\host" like "//host", so the backslash is dropped
        # and what is left is a path on this site, never another host.
        response = common.back_to("/\\evil.example/")
        self.assertEqual(response.headers["location"], "/evil.example/")

    def test_refuses_addresses_that_leave_the_site(self) -> None:
        for url in (
            "https://evil.example/",
            "//evil.example/",
            "/\\/evil.example/",  # the backslash goes, leaving "//host"
            "\\\\evil.example/",
            "evil.example",
            "",
        ):
            with self.assertRaises(ValueError, msg=url):
                common.back_to(url)


if __name__ == "__main__":
    unittest.main()
