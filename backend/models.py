from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Review:
    rating: float
    title: str
    body: str
    source: str  # platform name


@dataclass
class ProductData:
    url: str
    platform: str
    title: str
    price: Optional[str]
    description: str
    specs: dict[str, str]
    reviews: list[Review]
    rating: Optional[float]
    rating_count: Optional[str]


@dataclass
class ProductProfile:
    title: str
    price: Optional[str]
    platform: str
    specs: dict[str, str]
    description_summary: str
    pros: list[str]
    cons: list[str]
    sentiment_score: str
    notable_quotes: list[str]


@dataclass
class Comparison:
    products: list[ProductProfile]
    summary: str
    recommendation: str
    markdown: str
    questionnaire: dict = field(default_factory=dict)  # { "questions": [...] }
