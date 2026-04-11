"""
Generates a structured ProductProfile from raw ProductData using an LLM.
"""

from .models import ProductData, ProductProfile
from .llm import call_llm, parse_llm_json


def _build_prompt(product: ProductData) -> str:
    specs_text = "\n".join(f"  - {k}: {v}" for k, v in list(product.specs.items())[:30])
    reviews_text = "\n".join(
        f"  [{r.rating}★ via {r.source}] {r.title}: {r.body[:300]}"
        for r in product.reviews[:12]
    )

    return f"""You are a product research assistant. Analyze the following product data and return a structured JSON profile.

Product: {product.title}
Price: {product.price or "Not listed"}
Platform: {product.platform}
Overall Rating: {product.rating} out of 5 ({product.rating_count or "no count"})

Description / Key Features:
{product.description[:1500] or "Not provided"}

Specifications:
{specs_text or "  Not available"}

Customer Reviews:
{reviews_text or "  No reviews available"}

Return ONLY a valid JSON object with exactly these keys — no markdown, no explanation:
{{
  "description_summary": "2-3 sentences summarising what this product is and who it is for",
  "pros": ["pro 1", "pro 2", "pro 3", "pro 4", "pro 5"],
  "cons": ["con 1", "con 2", "con 3"],
  "sentiment_score": "one of: Very Positive | Positive | Mixed | Negative | Very Negative",
  "notable_quotes": ["verbatim or lightly edited review quote 1", "quote 2", "quote 3"]
}}"""


def generate_profile(product: ProductData) -> ProductProfile:
    prompt = _build_prompt(product)
    response_text = call_llm(prompt)

    try:
        data = parse_llm_json(response_text)
    except (ValueError, Exception) as exc:
        raise ValueError(f"LLM returned invalid JSON for product '{product.title}': {exc}") from exc

    return ProductProfile(
        title=product.title,
        price=product.price,
        platform=product.platform,
        specs=product.specs,
        description_summary=data.get("description_summary", ""),
        pros=data.get("pros", []),
        cons=data.get("cons", []),
        sentiment_score=data.get("sentiment_score", "Unknown"),
        notable_quotes=data.get("notable_quotes", []),
    )
