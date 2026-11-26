import asyncio

import httpx
import pytest

from app.services import crawl
from app.services.crawl import CrawlError, html_to_text, validate_public_url


def test_html_to_text_maps_headings_and_skips_scripts():
    html = (
        "<html><head><title>Help</title></head><body><script>bad()</script>"
        "<h1>Refunds</h1><p>14 days.</p><h2>Shipping</h2><p>2 days.</p></body></html>"
    )

    title, text = html_to_text(html)

    assert title == "Help"
    assert "bad()" not in text
    assert "# Refunds" in text and "## Shipping" in text


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/a", "http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/"],
)
def test_validate_public_url_blocks_unsafe_targets(url):
    with pytest.raises(CrawlError):
        asyncio.run(validate_public_url(url))


def test_fetch_stops_reading_once_size_limit_is_exceeded(monkeypatch):
    chunk_size = 100_000
    sent = []

    async def body():
        for _ in range(100):
            sent.append(1)
            yield b"x" * chunk_size

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body()))
    monkeypatch.setattr(crawl, "validate_public_url", _allow_any_url)

    with pytest.raises(CrawlError, match="too large"):
        asyncio.run(crawl.fetch_page_text("http://example.com/", transport=transport))

    assert len(sent) * chunk_size < 2 * crawl.MAX_BYTES + chunk_size


def test_fetch_rejects_oversized_content_length_without_reading(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-length": str(crawl.MAX_BYTES + 1)}, content=b"x"
        )
    )
    monkeypatch.setattr(crawl, "validate_public_url", _allow_any_url)

    with pytest.raises(CrawlError, match="too large"):
        asyncio.run(crawl.fetch_page_text("http://example.com/", transport=transport))


def test_fetch_revalidates_redirect_targets(monkeypatch):
    validated = []

    async def record(url):
        validated.append(url)
        if "169.254" in url:
            raise CrawlError("URL resolves to a non-public address")

    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})

    monkeypatch.setattr(crawl, "validate_public_url", record)

    with pytest.raises(CrawlError, match="non-public"):
        asyncio.run(
            crawl.fetch_page_text(
                "http://example.com/", transport=httpx.MockTransport(handler)
            )
        )

    assert validated == ["http://example.com/", "http://169.254.169.254/meta"]


def test_validate_public_url_blocks_ipv4_mapped_loopback():
    with pytest.raises(CrawlError):
        asyncio.run(validate_public_url("http://[::ffff:127.0.0.1]/"))


async def _allow_any_url(url):
    return None
