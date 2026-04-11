import logging
import os
import random
import re
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ..models import ProductData, Review
from .base import BasePlatform

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

# ── Retry schedule ────────────────────────────────────────────────────────────
# Wait times in seconds before each retry (attempt 1 is immediate).
_RETRY_DELAYS = [3, 6, 12, 24, 48, 96]


class _CaptchaError(RuntimeError):
    """Raised when Amazon serves a CAPTCHA/bot-check page instead of a product page."""


# ── Rotating User-Agents ──────────────────────────────────────────────────────
# Rotating across real browser strings reduces the chance of consistent
# fingerprint-based blocking on successive retries.
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _headers_for_attempt(attempt: int) -> dict:
    ua = _USER_AGENTS[(attempt - 1) % len(_USER_AGENTS)]
    return {**_BASE_HEADERS, "User-Agent": ua}


_COUNTRY_FROM_DOMAIN = {
    "amazon.in":     "in",
    "amazon.co.uk":  "gb",
    "amazon.de":     "de",
    "amazon.fr":     "fr",
    "amazon.co.jp":  "jp",
    "amazon.ca":     "ca",
    "amazon.com.au": "au",
    "amazon.com":    "us",
}


def _scraper_api_proxy(url: str) -> dict | None:
    """
    Build a ScraperAPI proxy dict if SCRAPER_API_KEY is set.
    Automatically picks the country code matching the Amazon domain in the URL.
    ScraperAPI handles IP rotation, CAPTCHA solving, and retries internally.
    SSL verification must be disabled when using the proxy port method.
    """
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return None

    country = next(
        (code for domain, code in _COUNTRY_FROM_DOMAIN.items() if domain in url),
        "us",
    )
    username = f"scraperapi.country_code={country}"
    proxy_url = f"http://{username}:{api_key}@proxy-server.scraperapi.com:8001"
    log.info("[Amazon] ScraperAPI proxy active (country=%s)", country)
    return {"http": proxy_url, "https": proxy_url}


def _fallback_proxy() -> dict | None:
    """Manual proxy from SCRAPER_PROXY env var (used only when SCRAPER_API_KEY is absent)."""
    proxy = os.getenv("SCRAPER_PROXY")
    if proxy:
        return {"http": proxy, "https": proxy}
    return None


class AmazonPlatform(BasePlatform):
    @property
    def name(self) -> str:
        return "Amazon"

    @property
    def base_url(self) -> str:
        return "https://www.amazon.com"

    def can_handle(self, url: str) -> bool:
        return bool(re.search(r"amazon\.(com|co\.uk|co\.jp|de|fr|ca|in|com\.au)", url))

    def _fetch_once(self, url: str, attempt: int, proxies: dict | None, verify_ssl: bool) -> BeautifulSoup:
        """Single HTTP attempt."""
        session = requests.Session()
        session.trust_env = False

        log.info("[Amazon] Attempt %d — GET %s", attempt, url[:90])
        response = session.get(
            url,
            headers=_headers_for_attempt(attempt),
            timeout=60,   # ScraperAPI can take longer for JS-heavy pages
            proxies=proxies or {"http": None, "https": None},
            verify=verify_ssl,
        )
        log.info("[Amazon] Attempt %d — HTTP %d", attempt, response.status_code)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")
        page_text = soup.get_text(" ", strip=True).lower()
        if any(phrase in page_text for phrase in (
            "enter the characters you see below",
            "sorry, we just need to make sure you're not a robot",
            "type the characters you see in this image",
            "to discuss automated access to amazon data",
        )):
            raise _CaptchaError("Amazon returned a CAPTCHA / bot-check page.")
        return soup

    def _get_soup(self, url: str) -> BeautifulSoup:
        """
        Fetch page with automatic ScraperAPI routing when SCRAPER_API_KEY is set.

        With ScraperAPI:
            ScraperAPI handles IP rotation, CAPTCHA solving and retries internally.
            We still do up to 2 local retries for transient network hiccups.

        Without ScraperAPI:
            Falls back to direct requests with exponential back-off:
            immediate → 3 s → 6 s → 12 s → 24 s → 48 s → 96 s (7 attempts).
        """
        scraper_proxies = _scraper_api_proxy(url)
        using_scraper_api = scraper_proxies is not None

        if using_scraper_api:
            # ScraperAPI does the heavy lifting — 2 local attempts are enough
            delays     = [0, 5]
            proxies    = scraper_proxies
            verify_ssl = False   # required by ScraperAPI proxy port method
            log.info("[Amazon] Using ScraperAPI for %s", url[:90])
        else:
            delays     = [0] + _RETRY_DELAYS
            proxies    = _fallback_proxy()
            verify_ssl = True
            if proxies:
                log.info("[Amazon] Using manual SCRAPER_PROXY for %s", url[:90])
            else:
                log.warning(
                    "[Amazon] No proxy configured. Direct scraping may be rate-limited. "
                    "Set SCRAPER_API_KEY in .env to enable ScraperAPI."
                )

        last_error: Exception = RuntimeError("Unknown scraping error.")

        for attempt, wait in enumerate(delays, start=1):
            if wait:
                jitter       = random.uniform(0, wait * 0.25)
                actual_wait  = wait + jitter
                log.warning(
                    "[Amazon] Attempt %d failed — %s. Retrying in %.1f s…",
                    attempt - 1, last_error, actual_wait,
                )
                time.sleep(actual_wait)

            try:
                return self._fetch_once(url, attempt, proxies, verify_ssl)
            except _CaptchaError as exc:
                last_error = exc
            except requests.HTTPError as exc:
                log.error("[Amazon] Non-retryable HTTP %s on attempt %d", exc.response.status_code, attempt)
                raise
            except Exception as exc:
                last_error = exc
                log.error("[Amazon] Unexpected error on attempt %d: %s", attempt, exc)

        source = "ScraperAPI" if using_scraper_api else "direct connection"
        log.error("[Amazon] All %d attempts via %s failed for %s", len(delays), source, url[:90])
        raise RuntimeError(
            f"Could not scrape this Amazon URL after {len(delays)} attempts via {source}. "
            f"Last error: {last_error}."
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        el = soup.find("span", id="productTitle")
        return el.get_text(strip=True) if el else "Unknown Product"

    def _extract_price(self, soup: BeautifulSoup) -> str | None:
        for selector in [
            ".a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#sns-base-price",
        ]:
            el = soup.select_one(selector)
            if el:
                return el.get_text(strip=True)
        return None

    def _extract_specs_from_bullets(self, soup: BeautifulSoup) -> dict[str, str]:
        """
        Parse feature bullets for hardware spec patterns.
        Used as an enrichment source when the formal spec table is sparse.
        Each pattern captures a concise value — not full marketing sentences.
        """
        specs: dict[str, str] = {}
        patterns = [
            (r"\d+[\w‑\-]*[\s\-]?core\s+CPU", "CPU Cores"),
            (r"\d+[\w‑\-]*[\s\-]?core\s+GPU", "GPU Cores"),
            (r"M\d+(?:\s*(?:Pro|Max|Ultra))?\s*chip", "Chip"),
            (r"\d+\s*GB\s+Unified\s+Memory", "Unified Memory"),
            (r"\d+(?:GB|TB)\s+SSD\s+Storage", "SSD Storage"),
            (r"\d+(?:\.\d+)?\s*cm\s*\([\d.]+[″\"]?\)", "Display Size"),
            (r"Liquid Retina(?:\s+XDR)?", "Display Type"),
            (r"[\d,]+\s*nits", "Peak Brightness"),
            (r"(?:up to\s+)?\d+[\-–]?\d*\s*hours?\s+(?:battery\s*)?(?:life)?", "Battery Life"),
            (r"\d+MP\s+[\w\s]+?camera", "Camera"),
        ]
        for li in soup.select("#feature-bullets li span.a-list-item"):
            text = li.get_text(" ", strip=True)
            for pattern, label in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match and label not in specs:
                    specs[label] = match.group(0).strip()
        return specs

    def _extract_specs(self, soup: BeautifulSoup) -> dict[str, str]:
        specs: dict[str, str] = {}

        for table in soup.select(
            "#productDetails_techSpec_section_1, "
            "#productDetails_detailBullets_sections1, "
            "#productDetails_techSpec_section_2, "
            ".prodDetTable"
        ):
            for row in table.select("tr"):
                cells = row.select("th, td")
                if len(cells) == 2:
                    key = cells[0].get_text(strip=True)
                    val = re.sub(r"\s+", " ", cells[1].get_text(strip=True))
                    if key and val:
                        specs[key] = val

        for li in soup.select("#detailBullets_feature_div li span.a-list-item"):
            text = li.get_text(" ", strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                key = parts[0].strip().strip("\u200f\u200e")
                val = parts[1].strip()
                if key and val and key not in specs:
                    specs[key] = val

        for item in soup.select(".pdp-externalAd .a-list-item, #glance_icons_div li"):
            text = item.get_text(" ", strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key and val and key not in specs:
                    specs[key] = val

        bullet_specs = self._extract_specs_from_bullets(soup)
        for key, val in bullet_specs.items():
            if key not in specs:
                specs[key] = val

        title_el = soup.find("span", id="productTitle")
        if title_el:
            title_text = title_el.get_text(" ", strip=True)
            for key, val in self._extract_specs_from_bullets(
                BeautifulSoup(f"<ul><li><span class='a-list-item'>{title_text}</span></li></ul>", "lxml")
            ).items():
                if key not in specs:
                    specs[key] = val

        return specs

    def _extract_description(self, soup: BeautifulSoup) -> str:
        bullets = soup.select("#feature-bullets li span.a-list-item")
        if bullets:
            return "\n".join(b.get_text(strip=True) for b in bullets if b.get_text(strip=True))
        desc = soup.select_one("#productDescription")
        if desc:
            return desc.get_text(" ", strip=True)
        return ""

    def _extract_rating(self, soup: BeautifulSoup) -> tuple[float | None, str | None]:
        rating: float | None = None
        count: str | None = None
        rating_el = soup.select_one("#acrPopover")
        if rating_el:
            title_attr = rating_el.get("title", "")
            match = re.search(r"([\d.]+)", str(title_attr))
            if match:
                rating = float(match.group(1))
        count_el = soup.select_one("#acrCustomerReviewText")
        if count_el:
            count = count_el.get_text(strip=True)
        return rating, count

    def _extract_reviews(self, soup: BeautifulSoup) -> list[Review]:
        reviews: list[Review] = []
        for review_div in soup.select("[data-hook='review']")[:10]:
            rating_el = review_div.select_one(
                "[data-hook='review-star-rating'] .a-icon-alt, "
                "[data-hook='cmps-review-star-rating'] .a-icon-alt"
            )
            rating = 0.0
            if rating_el:
                match = re.search(r"([\d.]+)", rating_el.get_text())
                if match:
                    rating = float(match.group(1))
            title_el = review_div.select_one("[data-hook='review-title'] span:not(.a-icon-alt)")
            title = title_el.get_text(strip=True) if title_el else ""
            body_el = review_div.select_one("[data-hook='review-body'] span")
            body = body_el.get_text(strip=True) if body_el else ""
            if body:
                reviews.append(Review(rating=rating, title=title, body=body, source="Amazon"))
        return reviews

    def scrape_product(self, url: str) -> ProductData:
        soup = self._get_soup(url)
        return ProductData(
            url=url,
            platform=self.name,
            title=self._extract_title(soup),
            price=self._extract_price(soup),
            description=self._extract_description(soup),
            specs=self._extract_specs(soup),
            reviews=self._extract_reviews(soup),
            rating=self._extract_rating(soup)[0],
            rating_count=self._extract_rating(soup)[1],
        )
