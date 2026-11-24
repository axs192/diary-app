"""Helpers shared by the web tests."""

import re
import unittest

APP_SCRIPT_TAG = '<script src="/static/app.js">'


def assert_only_app_script(
    test: unittest.TestCase, markup: str, name: str
) -> None:
    """Asserts the only script a page may load is ``/static/app.js``.

    The kitchen iPad runs iOS 9 Safari, so the app ships one hand-written ES5
    file and nothing else: no inline scripts, no other files.

    Args:
        test: The test case to report failures through.
        markup: The page (or stylesheet) text to check.
        name: What is being checked, shown in the failure message.
    """
    for tag in re.findall(r"<script\b[^>]*>", markup):
        test.assertEqual(tag, APP_SCRIPT_TAG, name)
