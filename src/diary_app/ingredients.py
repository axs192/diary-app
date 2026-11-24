"""Amounts and names for the shopping list and the pantry.

Recipes write ingredients as free text in whatever units the author liked
("8oz mince", "2 x 400g tins chopped tomatoes", "1 tbsp oil"). This module is
the only place that knows how to read those lines and compare them.

* ``Amount`` is a quantity in one *base unit*: grams, millilitres, or a count
  (plain items, or tins, jars, bunches and so on). Imperial and spoon
  measures are converted to metric on the way in, so amounts of the same
  ingredient from different recipes add up.
* ``parse`` reads a recipe line. A line it cannot make sense of has no
  amount and is listed as written, rather than guessed at.
* ``item_key``, ``same_item`` and ``aisle`` decide when two names are the
  same thing and where it is found in the shop. They work on words, not
  meaning, so they are deliberately simple.

Conversions: 1 oz = 28.35 g, 1 lb = 453.6 g, 1 UK fl oz = 28.41 ml, 1 UK
pint = 568 ml, 1 cup = 250 ml (the metric cup), 1 tbsp = 15 ml, 1 tsp = 5 ml.
"""

import dataclasses
import re
import unicodedata
from fractions import Fraction

_MAX_AMOUNT = 1_000_000
_KILO = 1000
_MAX_AMOUNT_TEXT = 12  # stops "1e999999999" from being worked out

_GLYPHS = {
    Fraction(1, 2): "½",
    Fraction(1, 4): "¼",
    Fraction(3, 4): "¾",
    Fraction(1, 3): "⅓",
    Fraction(2, 3): "⅔",
}
_GLYPH_VALUES = {glyph: value for value, glyph in _GLYPHS.items()}

# Counted things, by base unit, with their plural when it is not "+s".
_COUNT_UNITS = (
    "tin",
    "jar",
    "pack",
    "bag",
    "bottle",
    "pot",
    "bunch",
    "clove",
    "pinch",
    "handful",
    "slice",
    "sprig",
    "head",
)
_PLURALS = {"bunch": "bunches", "pinch": "pinches"}
_CONTAINERS = frozenset({"tin", "jar", "pack", "bag", "bottle", "pot"})

# What the forms offer. "items" is a plain count.
UNIT_CHOICES = (
    "items",
    "g",
    "kg",
    "ml",
    "l",
    "tin",
    "jar",
    "pack",
    "bag",
    "bottle",
    "pot",
    "bunch",
)


def _build_units() -> dict[str, tuple[Fraction, str]]:
    """Maps every spelling of a unit to (factor, base unit)."""
    units: dict[str, tuple[Fraction, str]] = {
        "": (Fraction(1), ""),
        "item": (Fraction(1), ""),
        "items": (Fraction(1), ""),
    }

    def add(base: str, factor: str, *names: str) -> None:
        for name in names:
            units[name] = (Fraction(factor), base)

    add("g", "1", "g", "gram", "grams", "gr")
    add("g", "1000", "kg", "kilo", "kilos", "kilogram", "kilograms")
    add("g", "28.35", "oz", "ounce", "ounces")
    add("g", "453.6", "lb", "lbs", "pound", "pounds")
    add(
        "ml",
        "1",
        "ml",
        "millilitre",
        "millilitres",
        "milliliter",
        "milliliters",
    )
    add("ml", "10", "cl")
    add("ml", "100", "dl")
    add("ml", "1000", "l", "litre", "litres", "liter", "liters")
    add("ml", "5", "tsp", "teaspoon", "teaspoons")
    add("ml", "15", "tbsp", "tablespoon", "tablespoons")
    add("ml", "28.41", "fl oz")
    add("ml", "568", "pint", "pints", "pt")
    add("ml", "250", "cup", "cups")
    for base in _COUNT_UNITS:
        add(base, "1", base, _PLURALS.get(base, base + "s"))
    add("tin", "1", "can", "cans")
    add("pack", "1", "packet", "packets")
    return units


_UNITS = _build_units()
_BASE_UNITS = frozenset(base for _factor, base in _UNITS.values())


@dataclasses.dataclass(frozen=True)
class Amount:
    """A quantity in a base unit.

    Attributes:
        value: How much, as an exact fraction (so 1/3 + 1/3 + 1/3 is 1).
        unit: ``"g"``, ``"ml"``, ``""`` for a plain count, or a counted unit
            such as ``"tin"`` or ``"jar"``. Only amounts with the same unit
            can be added or compared; use ``from_unit`` to convert kilograms,
            ounces, spoons and so on.

    Raises:
        ValueError: If ``unit`` is not a base unit.
    """

    value: Fraction
    unit: str = ""

    def __post_init__(self) -> None:
        """Refuses a unit that is not a base unit."""
        if self.unit not in _BASE_UNITS:
            msg = f"Unknown unit: {self.unit!r}"
            raise ValueError(msg)

    @classmethod
    def from_unit(cls, value: Fraction, unit_text: str) -> "Amount":
        """Makes an amount from a number and any spelling of a unit.

        Args:
            value: The number.
            unit_text: For example ``"kg"``, ``"tbsp"``, ``"tins"``,
                ``"items"`` or ``""`` (a plain count).

        Returns:
            The amount in its base unit (2 kg is 2000 g).

        Raises:
            ValueError: If the unit is not known.
        """
        found = _UNITS.get(unit_text.strip().lower())
        if found is None:
            msg = f"Unknown unit: {unit_text!r}"
            raise ValueError(msg)
        factor, base = found
        return cls(value * factor, base)

    @property
    def is_zero(self) -> bool:
        """True when there is none of it."""
        return self.value == 0

    @property
    def step(self) -> "Amount":
        """A sensible amount for a plus or minus button: 100 g or ml, or 1."""
        return Amount(
            Fraction(100 if self.unit in ("g", "ml") else 1), self.unit
        )

    def comparable(self, other: "Amount") -> bool:
        """True when ``other`` is in the same unit."""
        return self.unit == other.unit

    def __add__(self, other: "Amount") -> "Amount":
        """Adds an amount in the same unit (``ValueError`` otherwise)."""
        self._require_same_unit(other)
        return Amount(self.value + other.value, self.unit)

    def minus(self, other: "Amount") -> "Amount":
        """Takes ``other`` away, stopping at zero.

        Args:
            other: An amount in the same unit.

        Returns:
            What is left, never below zero.

        Raises:
            ValueError: If the units differ.
        """
        self._require_same_unit(other)
        return Amount(max(self.value - other.value, Fraction(0)), self.unit)

    def _require_same_unit(self, other: "Amount") -> None:
        if not self.comparable(other):
            msg = f"Cannot combine {self.unit!r} with {other.unit!r}"
            raise ValueError(msg)

    def format(self) -> str:
        """Writes the amount the way a person would: ``1.6 kg``, ``2 tins``."""
        if self.unit in ("g", "ml") and self.value >= _KILO:
            big = "kg" if self.unit == "g" else "l"
            return f"{_decimal(self.value / _KILO)} {big}"
        if self.unit in ("g", "ml"):
            return f"{round(self.value)} {self.unit}"
        number = _fraction_text(self.value)
        if not self.unit:
            return number
        plural = self.value > 1 or self.value == 0
        unit = _PLURALS.get(self.unit, self.unit + "s") if plural else self.unit
        return f"{number} {unit}"


def _decimal(value: Fraction) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _fraction_text(value: Fraction) -> str:
    whole, part = divmod(value, 1)
    if part == 0:
        return str(int(whole))
    glyph = _GLYPHS.get(part)
    if glyph:
        return f"{int(whole) or ''}{glyph}"
    return _decimal(value)


def parse_amount(number_text: str, unit_text: str) -> Amount:
    """Reads what someone typed into an amount box and a unit choice.

    Args:
        number_text: A number such as ``"4"``, ``"1.5"`` or ``"1/2"``.
        unit_text: One of ``UNIT_CHOICES`` (or any spelling ``from_unit``
            knows).

    Returns:
        The amount, in its base unit.

    Raises:
        ValueError: If the number is blank, not a number, negative or
            absurdly large, or the unit is unknown.
    """
    text = number_text.strip()
    if not text or len(text) > _MAX_AMOUNT_TEXT:
        msg = "Enter an amount as a number."
        raise ValueError(msg)
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        msg = "Enter an amount as a number."
        raise ValueError(msg) from exc
    if value < 0 or value > _MAX_AMOUNT:
        msg = "That amount is not sensible."
        raise ValueError(msg)
    try:
        return Amount.from_unit(value, unit_text)
    except ValueError as exc:
        msg = "Pick one of the units."
        raise ValueError(msg) from exc


@dataclasses.dataclass(frozen=True)
class Ingredient:
    """One recipe line, read.

    Attributes:
        text: The line as written.
        name: What it is, lower case, without the amount ("chopped
            tomatoes"). For a line that could not be read this is the whole
            line.
        amount: How much, or None when the line could not be read.
    """

    text: str
    name: str
    amount: Amount | None


_NUM = r"(?:\d+\s+\d+/\d+|\d+[½¼¾⅓⅔]|\d+/\d+|[½¼¾⅓⅔]|\d+(?:\.\d+)?)"
_LINE = re.compile(
    r"^(?:(?P<mult>\d+)\s*[x\u00d7]\s*(?=\d))?"
    rf"(?P<lo>{_NUM})(?:\s*(?:-|\u2013|to)\s*(?P<hi>{_NUM}))?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_UNIT_WORD = re.compile(
    r"^(fl\.?\s*oz\b|[a-z]+)\.?\s*(?:of\s+)?(?P<name>.*)$", re.I
)
_CONTAINER_WORD = re.compile(
    r"^(?P<unit>tins?|cans?|jars?|packs?|packets?|bags?|bottles?|pots?)\b"
    r"\s*(?:of\s+)?(?P<name>.*)$",
    re.IGNORECASE,
)
_PINCH = re.compile(
    r"^(?:an?\s+)?(?P<unit>pinch|handful|bunch|sprig)(?:es|s)?\s+(?:of\s+)?(?P<name>.+)$",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\([^)]*\)")
# "400g/14oz": the second measure after a slash that follows a unit.
_ALTERNATIVE = re.compile(r"(?<=[a-zA-Z])\s*/\s*[0-9½¼¾⅓⅔.]+\s*[a-zA-Z]*")
_DESCRIPTORS = frozenset({"large", "small", "medium", "big", "fresh", "ripe"})


def _number(text: str) -> Fraction:
    glued = re.fullmatch(r"(\d+)?\s*([½¼¾⅓⅔])", text.strip())
    if glued:
        return Fraction(glued.group(1) or 0) + _GLYPH_VALUES[glued.group(2)]
    return sum((Fraction(part) for part in text.split()), Fraction(0))


def _clean_name(name: str) -> str:
    words = " ".join(name.lower().split()).strip(" .:;")
    while True:
        first, _, rest = words.partition(" ")
        if first in _DESCRIPTORS and rest:
            words = rest
        else:
            return words


def parse(line: str) -> Ingredient:
    """Reads one recipe ingredient line.

    Understands numbers written as ``2``, ``1.5``, ``1/2``, ``½``, ``1½`` or
    ``1 1/2`` (a range such as ``2-3`` takes the larger), metric and imperial
    units, spoons and cups, ``2 x 400g tins``, alternative measures such as
    ``400g/14oz`` or ``(9oz)``, and ``pinch of``. Anything after the first
    comma (the cooking instruction) is ignored.

    Args:
        line: The ingredient as written in the recipe.

    Returns:
        The ingredient. Its amount is None, and its name the whole line,
        when the line cannot be read ("salt and pepper", "juice of 1
        lemon"); such lines are listed as written, not guessed at.
    """
    text = line.strip()
    body = text.split(",", 1)[0]
    body = _ALTERNATIVE.sub(" ", _BRACKETS.sub(" ", body))
    body = " ".join(body.split())
    found = _read(body)
    if found is not None:
        return Ingredient(text, found[0], found[1])
    return Ingredient(text, text.lower(), None)


def _read(body: str) -> tuple[str, Amount] | None:
    pinch = _PINCH.match(body)
    if pinch:
        name = _clean_name(pinch.group("name"))
        unit = pinch.group("unit").lower()
        return (name, Amount(Fraction(1), unit)) if name else None
    head = _LINE.match(body)
    if not head:
        return None
    number = _number(head.group("hi") or head.group("lo"))
    times = Fraction(int(head.group("mult") or 1))
    word = _UNIT_WORD.match(head.group("rest"))
    unit_text = word.group(1).lower().replace(".", "") if word else ""
    unit_text = " ".join(unit_text.split())
    if word and unit_text in _UNITS:
        factor, base = _UNITS[unit_text]
        rest = word.group("name")
        container = _CONTAINER_WORD.match(rest) if base in ("g", "ml") else None
        if (
            container
        ):  # "400g can chopped tomatoes": count the can, not the size
            return _finish(
                container.group("name"), times, container.group("unit")
            )
        return _finish(rest, number * factor * times, base, converted=True)
    return _finish(head.group("rest"), number * times, "", converted=True)


def _finish(
    name: str, value: Fraction, unit: str, *, converted: bool = False
) -> tuple[str, Amount] | None:
    clean = _clean_name(name)
    if not clean:
        return None
    return clean, (
        Amount(value, unit) if converted else Amount.from_unit(value, unit)
    )


# --- names -----------------------------------------------------------------

_SKIPPED_WORDS = frozenset(
    {"large", "small", "medium", "big", "fresh", "ripe", "tinned", "canned"}
)


def _singular(word: str) -> str:
    if len(word) <= 3:  # noqa: PLR2004 - "gas", "yes": too short to trim
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    return word[:-1] if word.endswith("s") else word


def _words(name: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", name.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return [
        _singular(w)
        for w in re.findall(r"[a-z0-9]+", plain)
        if w not in _SKIPPED_WORDS
    ]


def item_key(name: str) -> str:
    """Makes a short id for an item, so "Onions" and "large onion" agree.

    Args:
        name: An item name or ingredient name.

    Returns:
        Lower-case words joined by hyphens, with accents, size words
        ("large", "fresh", "tinned") and simple plurals removed. Safe to use
        in an address or an HTML id.
    """
    return "-".join(_words(name))


def same_item(pantry_name: str, ingredient_name: str) -> bool:
    """Says whether a pantry item is what an ingredient calls for.

    True when every word of the pantry name appears in the ingredient
    ("Onions" covers "2 large red onions"; "Red onions" does not cover
    "onions"). Matching is by words, not meaning, so "Milk" also covers
    "coconut milk"; the shopping list shows covered items so that a wrong
    match can be noticed.

    Args:
        pantry_name: What the pantry calls it.
        ingredient_name: What the recipe calls it.

    Returns:
        True if the pantry item covers the ingredient.
    """
    wanted = set(_words(pantry_name))
    return bool(wanted) and wanted <= set(_words(ingredient_name))


# --- aisles ----------------------------------------------------------------

AISLES = (
    "Fruit & veg",
    "Meat & fish",
    "Dairy & eggs",
    "Bakery",
    "Tins & dry goods",
    "Herbs & spices",
    "Frozen",
    "Other",
)
# Checked in this order, so specific things ("coconut milk", "green beans",
# "black pepper") win over the general word inside them. Keywords are
# singular and comma-separated; a keyword of several words is a phrase.
_AISLE_RULES = tuple(
    (aisle_name, tuple(k.strip() for k in keywords.split(",")))
    for aisle_name, keywords in (
        ("Frozen", "frozen, ice cream"),
        ("Fruit & veg", "green bean, french bean, runner bean"),
        (
            "Herbs & spices",
            "black pepper, white pepper, chilli flake, chilli powder,"
            " curry powder, mixed herb, garam masala",
        ),
        (
            "Tins & dry goods",
            "coconut, chopped tomato, passata, puree, paste, stock, lentil,"
            " chickpea, bean, pasta, spaghetti, penne, lasagne, rice, noodle,"
            " flour, sugar, oat, oil, vinegar, sauce, ketchup, honey,"
            " couscous, cereal, breadcrumb, peanut butter, jam",
        ),
        (
            "Herbs & spices",
            "salt, cumin, paprika, oregano, thyme, rosemary, sage, basil,"
            " parsley, coriander, cinnamon, turmeric, nutmeg, cardamom, mint,"
            " dill, chive, bay, herb, spice",
        ),
        (
            "Meat & fish",
            "chicken, beef, pork, lamb, turkey, mince, sausage, bacon, ham,"
            " steak, salmon, cod, haddock, tuna, prawn, fish, fillet,"
            " chorizo, duck",
        ),
        (
            "Dairy & eggs",
            "milk, cream, yoghurt, yogurt, cheese, cheddar, mozzarella,"
            " parmesan, feta, halloumi, butter, egg, creme fraiche, ricotta,"
            " mascarpone",
        ),
        (
            "Bakery",
            "bread, tortilla, wrap, pitta, naan, bun, bagel, baguette,"
            " crumpet, brioche",
        ),
        (
            "Fruit & veg",
            "onion, garlic, carrot, potato, pepper, spinach, leek, broccoli,"
            " cauliflower, lemon, lime, apple, banana, mushroom, courgette,"
            " tomato, cabbage, cucumber, lettuce, salad, ginger, chilli,"
            " celery, pea, sweetcorn, corn, aubergine, squash, kale, avocado,"
            " orange, berry, grape, pear, mango, beetroot, parsnip, swede,"
            " turnip, pumpkin, radish, shallot, rocket, watercress, fennel,"
            " asparagus, veg, fruit",
        ),
    )
)


def aisle(name: str) -> str:
    """Says where in the shop an item is found.

    Args:
        name: An item or ingredient name.

    Returns:
        One of ``AISLES``; "Other" when no keyword matches.
    """
    text = f" {' '.join(_words(name))} "
    for aisle_name, keywords in _AISLE_RULES:
        if any(f" {keyword} " in text for keyword in keywords):
            return aisle_name
    return "Other"
