"""Tests for the diary_app.import_sites public interface."""

import unittest

from diary_app import db, import_sites, recipe_import


class ImportSitesTest(unittest.TestCase):
    """import_sites holds the recipe sites the importer may fetch from."""

    def setUp(self) -> None:
        self.conn = db.connect(":memory:")

    def test_a_new_database_allows_only_the_built_in_sites(self) -> None:
        self.assertEqual(
            import_sites.allowed(self.conn), recipe_import.ALLOWED_HOSTS
        )
        self.assertEqual(import_sites.added(self.conn), [])

    def test_added_site_is_allowed_and_listed(self) -> None:
        added = import_sites.add(self.conn, "www.example.com")
        self.assertEqual(added, "www.example.com")
        self.assertEqual(import_sites.added(self.conn), ["www.example.com"])
        self.assertIn("www.example.com", import_sites.allowed(self.conn))
        self.assertGreaterEqual(
            import_sites.allowed(self.conn), recipe_import.ALLOWED_HOSTS
        )

    def test_a_pasted_address_is_reduced_to_its_host(self) -> None:
        added = import_sites.add(
            self.conn, "  HTTPS://Www.Example.com/recipes/1?x=2 "
        )
        self.assertEqual(added, "www.example.com")

    def test_adding_twice_stores_it_once(self) -> None:
        import_sites.add(self.conn, "www.example.com")
        import_sites.add(self.conn, "www.example.com")
        self.assertEqual(import_sites.added(self.conn), ["www.example.com"])

    def test_adding_a_built_in_site_changes_nothing(self) -> None:
        import_sites.add(self.conn, "www.bbcgoodfood.com")
        self.assertEqual(import_sites.added(self.conn), [])

    def test_sites_are_kept_in_the_order_added(self) -> None:
        import_sites.add(self.conn, "www.zebra.com")
        import_sites.add(self.conn, "www.apple.com")
        self.assertEqual(
            import_sites.added(self.conn), ["www.zebra.com", "www.apple.com"]
        )

    def test_remove_drops_an_added_site(self) -> None:
        import_sites.add(self.conn, "www.example.com")
        import_sites.remove(self.conn, "www.example.com")
        self.assertEqual(import_sites.added(self.conn), [])
        self.assertNotIn("www.example.com", import_sites.allowed(self.conn))

    def test_built_in_sites_cannot_be_removed(self) -> None:
        import_sites.remove(self.conn, "www.bbcgoodfood.com")
        self.assertIn("www.bbcgoodfood.com", import_sites.allowed(self.conn))

    def test_removing_an_unknown_site_is_harmless(self) -> None:
        import_sites.remove(self.conn, "www.nothing.example")

    def test_bad_sites_are_refused(self) -> None:
        for bad in (
            "",
            "   ",
            "localhost",
            "intranet",
            "192.168.1.1",
            "http://10.0.0.5/x",
            "[::1]",
            "exa mple.com",
            "example.com:8080",
            "user@example.com",
            "-bad.example.com",
            "ex_ample.com",
            "x" * 300 + ".com",
            "javascript:alert(1)",
        ):
            with self.assertRaises(import_sites.InvalidSiteError, msg=bad):
                import_sites.add(self.conn, bad)
        self.assertEqual(import_sites.added(self.conn), [])

    def test_too_many_sites_are_refused(self) -> None:
        for i in range(import_sites.MAX_EXTRA):
            import_sites.add(self.conn, f"www.site{i}.example")
        with self.assertRaises(import_sites.InvalidSiteError):
            import_sites.add(self.conn, "www.one-too-many.example")


if __name__ == "__main__":
    unittest.main()
