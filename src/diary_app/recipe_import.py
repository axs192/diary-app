"""Importing one recipe from a web page you choose.

Many recipe sites publish the recipe as schema.org JSON-LD in the page.
``draft_from_html`` reads it (no network, easy to test) and ``fetch_draft``
downloads a single page politely: it only follows public web addresses,
obeys robots.txt, and limits time, size and redirects. The result is a
``RecipeDraft`` for the user to review; nothing is stored here.

The address check is best effort: the name is resolved once here and again
when the connection is made. That is acceptable for a household app, but it
is not a hardened defence against a hostile DNS server.
"""

import dataclasses
import html
import html.parser
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.robotparser
from collections.abc import Callable, Collection, Iterator
from typing import Any

import httpx

from diary_app import recipes

USER_AGENT = "diary-app recipe importer"
_ROBOTS_AGENT = "diary-app"
_TIMEOUT_SECONDS = 10.0
_MAX_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_JSON_DEPTH = 6
_DEFAULT_MINS = 30
_QUICK_MINS = 30
_DEFAULT_SERVINGS = 4
_MAX_NAME = 100
# Only these sites can be fetched: the importer takes one page at a time from
# recipe sites the household uses, so a pasted address can never make the
# server request anything else (including other machines on the LAN).
ALLOWED_HOSTS = frozenset(
    {
        "www.bbcgoodfood.com",
        "www.allrecipes.com",
        "www.food.com",
        "www.epicurious.com",
    }
)
_KNOWN_SITES = {"bbcgoodfood.com": "BBC Good Food"}
_OILY_FISH = (
    "salmon",
    "mackerel",
    "sardine",
    "trout",
    "herring",
    "anchov",
    "kipper",
    "pilchard",
)
_CUISINES = {
    "Asian": (
        "asian",
        "chinese",
        "japanese",
        "thai",
        "korean",
        "vietnamese",
        "malaysian",
        "indonesian",
    ),
    "Mediterranean": (
        "mediterranean",
        "greek",
        "spanish",
        "turkish",
        "lebanese",
        "moroccan",
        "middle eastern",
    ),
    "British": ("british", "english", "scottish", "welsh", "irish"),
    "Italian": ("italian",),
    "Mexican": ("mexican", "tex-mex"),
    "Indian": ("indian",),
}
_DURATION = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", re.IGNORECASE
)
_TAGS_RE = re.compile(r"<[^>]+>")


class RecipeImportError(Exception):
    """Raised with a message fit to show the user when import fails."""


class _JsonLdFinder(html.parser.HTMLParser):
    """Collects the text of every ``application/ld+json`` script."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._inside = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "script" and ("type", "application/ld+json") in attrs:
            self._inside = True
            self.blocks.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.blocks[-1] += data


def draft_from_html(page: str, url: str) -> recipes.RecipeDraft:
    """Reads a recipe from a page's schema.org data.

    Args:
        page: The page's HTML.
        url: Where it came from; kept as the recipe's source.

    Returns:
        A draft to review and save.

    Raises:
        RecipeImportError: If the page has no readable recipe.
    """
    finder = _JsonLdFinder()
    finder.feed(page)
    for block in finder.blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        found = _find_recipe(data, _MAX_JSON_DEPTH)
        if found is not None:
            return _to_draft(found, url)
    msg = "That page doesn't have a recipe we can read."
    raise RecipeImportError(msg)


@dataclasses.dataclass(frozen=True)
class _Guard:
    """Which sites may be fetched, and how host names are resolved."""

    resolve: Callable[[str], list[str]]
    allowed_hosts: Collection[str]


def fetch_draft(
    url: str,
    client: httpx.Client,
    resolve: Callable[[str], list[str]] | None = None,
    allowed_hosts: Collection[str] = ALLOWED_HOSTS,
) -> recipes.RecipeDraft:
    """Downloads one recipe page and reads its recipe.

    Args:
        url: Web address of a page on one of ``allowed_hosts``.
        client: HTTP client to use; tests pass one with a mock transport.
        resolve: Turns a host name into IP addresses. Defaults to the
            system resolver.
        allowed_hosts: Host names that may be fetched (also for redirects
            and robots.txt). Defaults to the built-in ``ALLOWED_HOSTS``.

    Returns:
        A draft to review and save.

    Raises:
        RecipeImportError: If the site is not supported, the site's
            robots.txt forbids it, the page can't be fetched, or it holds
            no readable recipe.
    """
    guard = _Guard(resolve or _system_resolve, allowed_hosts)
    reply, final_url = _request(url.strip(), client, guard, robots=True)
    if reply.status_code != httpx.codes.OK:
        msg = f"The site answered with an error ({reply.status_code})."
        raise RecipeImportError(msg)
    return draft_from_html(reply.text, final_url)


def _request(
    url: str,
    client: httpx.Client,
    guard: _Guard,
    *,
    robots: bool,
) -> tuple[httpx.Response, str]:
    """GETs a URL, re-checking every redirect hop; returns reply and URL."""
    for _ in range(_MAX_REDIRECTS + 1):
        _check_address(url, guard)
        url = _canonical_url(url)
        if robots:
            _check_robots(url, client, guard)
        reply = _get_once(url, client)
        if reply.status_code not in _REDIRECT_STATUSES:
            return reply, url
        location = reply.headers.get("location")
        if not location:
            break
        url = urllib.parse.urljoin(url, location)
    msg = "That address redirects too many times."
    raise RecipeImportError(msg)


def _canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.fragment:
        msg = "Use a web address without a #fragment."
        raise RecipeImportError(msg)
    if parts.username or parts.password:
        msg = "Use a web address without login details."
        raise RecipeImportError(msg)
    host = parts.hostname
    if not host:
        msg = "Use a web address starting http:// or https://."
        raise RecipeImportError(msg)
    netloc = host
    if parts.port is not None:
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, parts.query, ""))


def _check_address(url: str, guard: _Guard) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        msg = "Use a web address starting http:// or https://."
        raise RecipeImportError(msg)
    host = parts.hostname
    if host not in guard.allowed_hosts or parts.username or parts.password:
        sites = ", ".join(sorted(guard.allowed_hosts))
        msg = f"That site isn't supported for import. Supported: {sites}."
        raise RecipeImportError(msg)
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = guard.resolve(host)
    if not addresses:
        msg = "That web address could not be found."
        raise RecipeImportError(msg)
    if not all(_is_public(address) for address in addresses):
        msg = "That address is on a private network, so it isn't allowed."
        raise RecipeImportError(msg)


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _system_resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def _check_robots(url: str, client: httpx.Client, guard: _Guard) -> None:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    reply, _ = _request(robots_url, client, guard, robots=False)
    if reply.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        msg = (
            "The site's robots.txt could not be read, so the page was skipped."
        )
        raise RecipeImportError(msg)
    if reply.status_code != httpx.codes.OK:
        return  # no robots.txt: nothing is disallowed
    rules = urllib.robotparser.RobotFileParser()
    rules.parse(reply.text.splitlines())
    if not rules.can_fetch(_ROBOTS_AGENT, url):
        msg = (
            "That site's robots.txt asks automated tools not to read this page."
        )
        raise RecipeImportError(msg)


def _get_once(url: str, client: httpx.Client) -> httpx.Response:
    """One GET with a timeout and a size cap; never follows redirects."""
    try:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > _MAX_BYTES:
                    msg = "That page is too large to import."
                    raise RecipeImportError(msg)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=body,
                request=response.request,
            )
    except httpx.TimeoutException as exc:
        msg = "The site took too long to answer."
        raise RecipeImportError(msg) from exc
    except httpx.HTTPError as exc:
        msg = "Couldn't reach that page."
        raise RecipeImportError(msg) from exc


def _find_recipe(node: Any, depth: int) -> dict[str, Any] | None:  # noqa: ANN401
    if depth < 0:
        return None
    if isinstance(node, list):
        children: Iterator[Any] = iter(node)
    elif isinstance(node, dict):
        kinds = node.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if "Recipe" in kinds:
            return node
        children = iter(node.values())
    else:
        return None
    for child in children:
        found = _find_recipe(child, depth - 1)
        if found is not None:
            return found
    return None


def _to_draft(node: dict[str, Any], url: str) -> recipes.RecipeDraft:
    name = _text(node.get("name"))[:_MAX_NAME].strip()
    if not name:
        msg = "That recipe has no name, so it can't be imported."
        raise RecipeImportError(msg)
    ingredients = [
        _text(line)
        for line in _as_list(
            node.get("recipeIngredient") or node.get("ingredients")
        )
        if isinstance(line, str)
    ]
    mins = _minutes(node)
    tags = []
    if mins is not None and mins <= _QUICK_MINS:
        tags.append("Quick")
    if any(fish in line.lower() for line in ingredients for fish in _OILY_FISH):
        tags.append("Oily fish")
    return recipes.RecipeDraft(
        name=name,
        style=_style(node.get("recipeCuisine")),
        mins=min(mins or _DEFAULT_MINS, 24 * 60),
        servings=_servings(node.get("recipeYield")),
        ingredients=tuple(ingredients),
        steps=tuple(_steps(node.get("recipeInstructions"))),
        tags=tuple(tags),
        source_url=url,
        source_name=_source_name(url),
    )


def _as_list(value: Any) -> list[Any]:  # noqa: ANN401
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:  # noqa: ANN401
    if not isinstance(value, str):
        return ""
    return html.unescape(_TAGS_RE.sub("", value)).strip()


def _steps(node: Any) -> list[str]:  # noqa: ANN401
    steps: list[str] = []
    for item in _as_list(node):
        if isinstance(item, str):
            steps.extend(line for line in map(_text, item.splitlines()) if line)
        elif isinstance(item, dict):
            if "itemListElement" in item:
                steps.extend(_steps(item["itemListElement"]))
            elif text := _text(item.get("text") or item.get("name")):
                steps.append(text)
    return steps


def _minutes(node: dict[str, Any]) -> int | None:
    total = _duration(node.get("totalTime"))
    if total:
        return total
    parts = _duration(node.get("prepTime")) + _duration(node.get("cookTime"))
    return parts or None


def _duration(value: Any) -> int:  # noqa: ANN401
    match = _DURATION.match(value.strip()) if isinstance(value, str) else None
    if not match:
        return 0
    days, hours, minutes, _seconds = (int(g or 0) for g in match.groups())
    return days * 24 * 60 + hours * 60 + minutes


def _servings(value: Any) -> int:  # noqa: ANN401
    for item in _as_list(value):
        found = re.search(r"\d+", str(item))
        if found and int(found.group()) > 0:
            return int(found.group())
    return _DEFAULT_SERVINGS


def _style(cuisine: Any) -> str:  # noqa: ANN401
    for item in _as_list(cuisine):
        lowered = str(item).lower()
        for style, words in _CUISINES.items():
            if any(word in lowered for word in words):
                return style
    return "Other"


def _source_name(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.")
    for site, name in _KNOWN_SITES.items():
        if host == site or host.endswith("." + site):
            return name
    return host
