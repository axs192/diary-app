"""Colours: the app accent colour and the palette for people.

Everything here is a fixed constant, so colour values are safe to write
straight into the page's CSS (no user-supplied text ever reaches a style).
"""

from typing import NamedTuple


class AppColour(NamedTuple):
    """One selectable app colour.

    Attributes:
        main: Buttons, header mark and highlights.
        tint: Soft background for the selected tab.
        dark: Text on the tint, and hover state.
    """

    main: str
    tint: str
    dark: str


APP_COLOURS: dict[str, AppColour] = {
    "Green": AppColour("#2F7D4F", "#E4F1E8", "#1F5A37"),
    "Blue": AppColour("#24508F", "#E3ECF8", "#1B3D6E"),
    "Teal": AppColour("#0F5E5E", "#DDF1EF", "#0A4545"),
    "Purple": AppColour("#5B2E86", "#F1E9F7", "#45216A"),
    "Pink": AppColour("#A3245E", "#F9E3ED", "#7E1A48"),
    "Orange": AppColour("#B04A17", "#FBE6DC", "#8A3810"),
    "Slate": AppColour("#3F4844", "#ECEEEA", "#2A302D"),
}
DEFAULT = "Green"

# Colours a person can be given. All meet 4.5:1 against white text.
PERSON_COLOURS: dict[str, str] = {
    "#24508F": "Blue",
    "#0F5E5E": "Teal",
    "#2F7D4F": "Green",
    "#5B2E86": "Purple",
    "#A3245E": "Pink",
    "#B04A17": "Orange",
    "#8A5A00": "Amber",
    "#3F4844": "Slate",
}


def app_colour_names() -> list[str]:
    """Returns the selectable app colour names, in display order."""
    return list(APP_COLOURS)


def css(name: str) -> str:
    """Returns the CSS rules that apply an app colour.

    Written into each page by the server, so the iPad needs no script
    to pick up the colour.

    Args:
        name: An app colour name; an unknown name uses the default.

    Returns:
        CSS text (no ``<style>`` tags).
    """
    colour = APP_COLOURS.get(name, APP_COLOURS[DEFAULT])
    return (
        f"a {{ color: {colour.main}; }}\n"
        f"a:hover {{ color: {colour.dark}; }}\n"
        f".accent-bg {{ background: {colour.main}; }}\n"
        f".accent-text {{ color: {colour.main}; }}\n"
        f'.nav-item[aria-current="page"] {{ background: {colour.tint};'
        f" color: {colour.dark}; }}\n"
        f".panel-accent {{ background: {colour.main}; color: #FFFFFF; }}\n"
    )


def is_person_colour(value: str) -> bool:
    """Tells whether ``value`` is one of the allowed person colours.

    Args:
        value: A candidate colour such as ``"#B04A17"``.

    Returns:
        True only for colours in ``PERSON_COLOURS``.
    """
    return value in PERSON_COLOURS


# Recipe tag chips: (background, text). Text meets 4.5:1 on its background.
TAG_COLOURS: dict[str, tuple[str, str]] = {
    "Oily fish": ("#DDEBF7", "#1B3D6E"),
    "Veg-led": ("#E4F1E8", "#1F5A37"),
    "Lean protein": ("#F1E9F7", "#45216A"),
    "Wholegrain": ("#F6EAD2", "#6B4500"),
    "Treat night": ("#F9E3ED", "#7E1A48"),
    "Batch cook": ("#DDF1EF", "#0A4545"),
    "Quick": ("#FBE6DC", "#8A3810"),
    "Kid-friendly": ("#FFF3C4", "#6B5200"),
}
_NEUTRAL_TAG = ("#ECEEEA", "#2A302D")


def tag_style(tag: str) -> str:
    """Returns inline CSS colouring a recipe tag chip.

    Args:
        tag: A tag name; an unknown one gets a neutral grey.

    Returns:
        A ``style`` attribute value built only from fixed colours, so it is
        safe to write into a page whatever the tag text was.
    """
    background, text = TAG_COLOURS.get(tag, _NEUTRAL_TAG)
    return f"background: {background}; color: {text}"
