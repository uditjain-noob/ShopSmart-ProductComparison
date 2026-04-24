"""
Amazon search results scraper.

Scrapes the Amazon search results page for a query and returns a lightweight
list of candidate products — title, URL, price, and rating only.

Used exclusively by the discovery agent; does NOT touch the product comparison
pipeline (AmazonPlatform.scrape_product is used for that).
"""

import logging
import os
import random
import re
import time
import urllib.parse  # noqa: F401 – kept for potential future use by callers

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_AMAZON_BASE = "https://www.amazon.in"


def _headers() -> dict:
    ua = random.choice(_USER_AGENTS)
    return {**_BASE_HEADERS, "User-Agent": ua}


def _proxy() -> dict | None:
    api_key = os.getenv("SCRAPER_API_KEY")
    if api_key:
        proxy_url = f"http://scraperapi:{api_key}@proxy-server.scraperapi.com:8001"
        return {"http": proxy_url, "https": proxy_url}
    manual = os.getenv("SCRAPER_PROXY")
    if manual:
        return {"http": manual, "https": manual}
    return None


def _asin_url(asin: str) -> str:
    """Build a clean product URL from an ASIN."""
    return f"{_AMAZON_BASE}/dp/{asin}"


def search_amazon(query: str, max_results: int = 20) -> list[dict]:
    """
    Scrape Amazon search results for *query* and return up to *max_results*
    lightweight product dicts.

    Each dict contains: title, url, description, price, rating.
    Missing fields are None rather than raising.
    """
    encoded = urllib.parse.quote_plus(query)
    search_url = f"{_AMAZON_BASE}/s?k={encoded}"

    proxies = _proxy()
    verify_ssl = proxies is None or "scraperapi" not in str(proxies)

    log.info("[AmazonSearch] GET %s", search_url)

    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(
            search_url,
            headers=_headers(),
            timeout=30,
            proxies=proxies or {"http": None, "https": None},
            verify=verify_ssl,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.error("[AmazonSearch] Request failed: %s", exc)
        raise RuntimeError(f"Amazon search request failed: {exc}") from exc

    soup = BeautifulSoup(resp.content, "lxml")

    # Brief bot-check guard
    page_text = soup.get_text(" ", strip=True).lower()
    if "enter the characters you see" in page_text or "not a robot" in page_text:
        raise RuntimeError("Amazon returned a CAPTCHA page for search request.")

    results: list[dict] = []

    for card in soup.select("[data-component-type='s-search-result']"):
        if len(results) >= max_results:
            break

        # ASIN is always on the card element itself — use it to build a clean URL
        asin = card.get("data-asin", "").strip()
        if not asin:
            continue

        # Short display title — truncated version shown in h2
        title_el = card.select_one("h2 span")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # Full spec title — .a-text-normal contains the untruncated product name
        # with all specs (battery, drivers, features, colour) baked in.
        # This is the richest "description" available on the search results page.
        full_title_el = card.select_one(".a-text-normal")
        description = full_title_el.get_text(strip=True) if full_title_el else None

        url = _asin_url(asin)

        # Price
        price_el = card.select_one(".a-price .a-offscreen")
        price = price_el.get_text(strip=True) if price_el else None

        # Rating (e.g. "4.3 out of 5 stars")
        rating: float | None = None
        rating_el = card.select_one(".a-icon-alt")
        if rating_el:
            m = re.search(r"([\d.]+)", rating_el.get_text())
            if m:
                rating = float(m.group(1))

        results.append({
            "title": title,
            "url": url,
            "description": description,
            "price": price,
            "rating": rating,
        })

    log.info("[AmazonSearch] Found %d results for '%s'", len(results), query)
    return results
