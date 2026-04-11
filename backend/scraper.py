"""
Scraping orchestrator.

Scrapes a product from its original platform, then enriches the review pool
by searching every other supported platform for the same product.

Phase 1: Only Amazon is supported, so enrichment is a no-op.
Phase 2: When more platforms are added to SUPPORTED_PLATFORMS, this module
         will automatically search them and merge their reviews in.
"""

from .models import ProductData, Review
from .platforms import SUPPORTED_PLATFORMS, get_platform_for_url


def _merge_reviews(base: ProductData, extra_reviews: list[Review]) -> ProductData:
    base.reviews = base.reviews + extra_reviews
    return base


def scrape_product_with_enrichment(url: str) -> ProductData:
    platform = get_platform_for_url(url)
    if not platform:
        supported = ", ".join(p.name for p in SUPPORTED_PLATFORMS)
        raise ValueError(
            f"URL is not from a supported platform.\n"
            f"Supported platforms: {supported}\n"
            f"URL: {url}"
        )

    product_data = platform.scrape_product(url)

    # Enrich with reviews from every other supported platform.
    # Each additional platform searches by product title + first spec value
    # (usually a model number) to find the same product.
    other_platforms = [p for p in SUPPORTED_PLATFORMS if p.name != platform.name]
    extra_reviews: list[Review] = []

    for other in other_platforms:
        try:
            if hasattr(other, "search_and_scrape_reviews"):
                reviews = other.search_and_scrape_reviews(  # type: ignore[attr-defined]
                    title=product_data.title,
                    specs=product_data.specs,
                )
                extra_reviews.extend(reviews)
        except Exception:
            # Enrichment from additional platforms is best-effort; never block the main flow.
            pass

    return _merge_reviews(product_data, extra_reviews)
