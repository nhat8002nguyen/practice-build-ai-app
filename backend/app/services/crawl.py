import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
_SKIPPED_TAGS = {"script", "style", "noscript", "svg", "head"}
_HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}
_BLOCK_TAGS = {"p", "div", "li", "br", "tr", "section", "article"}


class CrawlError(ValueError):
    pass


class _TextExtractor(HTMLParser):
    """Converts HTML to text, mapping h1-h6 to markdown headings for heading chunkers."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _SKIPPED_TAGS and tag != "head":
            self._skip_depth += 1
        elif tag in _HEADING_LEVELS:
            self._parts.append("\n\n" + "#" * _HEADING_LEVELS[tag] + " ")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIPPED_TAGS and tag != "head":
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _HEADING_LEVELS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip() or None
        elif self._skip_depth == 0 and not self._in_title:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> tuple[str | None, str]:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.title, extractor.text()


async def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise CrawlError("Only http and https URLs are supported")
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, parsed.port or 443
        )
    except socket.gaierror:
        raise CrawlError("Host could not be resolved") from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise CrawlError("URL resolves to a non-public address")


async def _read_limited(response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise CrawlError("Page is too large")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise CrawlError("Page is too large")
    return bytes(body)


async def fetch_page_text(
    url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, str]:
    """Return (title, text). Every redirect hop is re-validated against private ranges.

    Residual risk: DNS is resolved separately from the connection, so a rebinding
    host could still answer differently at connect time.
    """
    async with httpx.AsyncClient(
        timeout=10, follow_redirects=False, transport=transport
    ) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            await validate_public_url(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect and "location" in response.headers:
                        current = urljoin(current, response.headers["location"])
                        continue
                    if response.status_code >= 400:
                        raise CrawlError(f"URL returned HTTP {response.status_code}")
                    body = await _read_limited(response)
                    encoding = response.encoding or "utf-8"
            except httpx.HTTPError:
                raise CrawlError("Could not fetch URL") from None
            title, text = html_to_text(body.decode(encoding, errors="replace"))
            return title or urlparse(url).netloc, text
    raise CrawlError("Too many redirects")
