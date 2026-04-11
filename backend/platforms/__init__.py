"""
Supported platforms registry.

Phase 1: Amazon only.
Phase 2: Add more platforms by instantiating their class here and appending
         to SUPPORTED_PLATFORMS — the rest of the tool picks them up automatically.
"""

from .base import BasePlatform
from .amazon import AmazonPlatform

SUPPORTED_PLATFORMS: list[BasePlatform] = [
    AmazonPlatform(),
    # Phase 2: add more platforms here, e.g.:
    # WalmartPlatform(),
    # BestBuyPlatform(),
]


def get_platform_for_url(url: str) -> BasePlatform | None:
    for platform in SUPPORTED_PLATFORMS:
        if platform.can_handle(url):
            return platform
    return None


def list_platform_names() -> list[str]:
    return [p.name for p in SUPPORTED_PLATFORMS]
