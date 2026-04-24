"""
Generates a side-by-side comparison from a list of ProductProfiles.

Produces:
  - A written comparison summary
  - A recommendation
  - A PDF-ready HTML page and a Markdown document
"""

from .models import ProductProfile, Comparison
from .llm import call_llm, parse_llm_json


def _profile_to_text(p: ProductProfile) -> str:
    specs = "\n".join(f"  - {k}: {v}" for k, v in list(p.specs.items())[:20])
    pros = "\n".join(f"  + {pro}" for pro in p.pros)
    cons = "\n".join(f"  - {con}" for con in p.cons)
    quotes = "\n".join(f'  "{q}"' for q in p.notable_quotes)

    return (
        f"### {p.title}\n"
        f"- Price: {p.price or 'N/A'}\n"
        f"- Platform: {p.platform}\n"
        f"- Sentiment: {p.sentiment_score}\n"
        f"- Summary: {p.description_summary}\n\n"
        f"Specs:\n{specs or '  N/A'}\n\n"
        f"Pros:\n{pros or '  None listed'}\n\n"
        f"Cons:\n{cons or '  None listed'}\n\n"
        f"Notable Quotes:\n{quotes or '  None'}\n"
    )


def _build_comparison_prompt(profiles: list[ProductProfile]) -> str:
    products_text = "\n\n".join(_profile_to_text(p) for p in profiles)
    titles = ", ".join(f'"{p.title}"' for p in profiles)
    return f"""You are a product comparison expert. Analyse the following {len(profiles)} products and return a JSON object.

{products_text}

You must produce three things:

1. A comparison summary — 3-5 paragraph narrative covering key differences, trade-offs, and positioning.
2. A recommendation — 2-3 paragraph recommendation with a clear winner or use-case guidance backed by the data.
3. A personalisation questionnaire — exactly 5 multiple-choice questions to help a user decide which product
   best suits THEM personally.

   STRUCTURE — write the questions in this order:
   Q1–Q3: UNIVERSAL decision questions. These are about the user's lifestyle, habits, and priorities —
          NOT about the specs of these specific products. Think about what genuinely drives purchase
          decisions for this product category. Good examples by category:
            - Earphones/headphones: primary use (commute, gym, office, home), most important trait (sound quality, comfort, call clarity, noise cancellation), usage duration per day
            - Laptops: main activity (coding, creative work, browsing, gaming), where used most (desk, travel, both), how long before upgrade
            - Phones: what they value most (camera, battery, performance, display), how tech-savvy they are, ecosystem (Android/Apple)
          Do NOT ask about budget — the user has already chosen products in their price range.
          Do NOT ask about brand preference — keep it about real usage patterns.

   Q4–Q5: SPECIFIC differentiator questions. These must be grounded in an actual, meaningful difference
          visible in the specs, pros, or cons of THESE products: {titles}
          (e.g. if one has significantly better battery and another has better ANC, ask which matters more)

   RULES for all 5 questions:
   - Each question must have exactly 4 concise answer options (8 words or fewer per option).
   - Options must be mutually exclusive and meaningfully different.
   - Do NOT ask about price or budget.

CRITICAL — Return ONLY a valid JSON object. No markdown, no explanation outside the JSON.
Write "summary" and "recommendation" as ARRAYS of paragraph strings, NOT as one big string.
This prevents JSON parsing failures. Do NOT use double-quote characters (") inside any paragraph text — use single quotes instead if you need to quote a product name or phrase.

{{
  "summary": [
    "First paragraph of the comparison summary.",
    "Second paragraph.",
    "Third paragraph."
  ],
  "recommendation": [
    "First paragraph of the recommendation.",
    "Second paragraph."
  ],
  "questions": [
    {{"id": "q1", "text": "Question one?", "options": ["A", "B", "C", "D"]}},
    {{"id": "q2", "text": "Question two?", "options": ["A", "B", "C", "D"]}},
    {{"id": "q3", "text": "Question three?", "options": ["A", "B", "C", "D"]}},
    {{"id": "q4", "text": "Question four?", "options": ["A", "B", "C", "D"]}},
    {{"id": "q5", "text": "Question five?", "options": ["A", "B", "C", "D"]}}
  ]
}}"""


def _build_markdown(
    profiles: list[ProductProfile],
    summary: str,
    recommendation: str,
) -> str:
    lines: list[str] = ["# Product Comparison\n"]

    all_keys: list[str] = []
    seen: set[str] = set()
    for p in profiles:
        for k in p.specs:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    if all_keys:
        lines.append("## Specifications\n")
        headers = ["Specification"] + [p.title[:45] for p in profiles]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        rows_written = 0
        for key in all_keys:
            values = [p.specs.get(key, "") for p in profiles]
            if sum(1 for v in values if v) < 2:
                continue
            row = [key] + [v if v else "—" for v in values]
            row = [cell.replace("|", "/") for cell in row]
            lines.append("| " + " | ".join(row) + " |")
            rows_written += 1
        if rows_written == 0:
            for key in all_keys[:30]:
                row = [key] + [p.specs.get(key, "—") for p in profiles]
                row = [cell.replace("|", "/") for cell in row]
                lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("## Comparison Summary\n")
    lines.append(summary)
    lines.append("\n## Recommendation\n")
    lines.append(recommendation)
    lines.append("\n## Product Profiles\n")

    for p in profiles:
        lines.append(f"### {p.title}\n")
        lines.append(f"**Price:** {p.price or 'N/A'}  ")
        lines.append(f"**Platform:** {p.platform}  ")
        lines.append(f"**Sentiment:** {p.sentiment_score}\n")
        lines.append(f"{p.description_summary}\n")
        lines.append("**Pros:**")
        for pro in p.pros:
            lines.append(f"- {pro}")
        lines.append("\n**Cons:**")
        for con in p.cons:
            lines.append(f"- {con}")
        if p.notable_quotes:
            lines.append("\n**Notable Reviews:**")
            for quote in p.notable_quotes:
                lines.append(f"> {quote}")
        lines.append("")

    return "\n".join(lines)


def generate_comparison(profiles: list[ProductProfile]) -> Comparison:
    prompt = _build_comparison_prompt(profiles)
    response_text = call_llm(prompt)

    try:
        data = parse_llm_json(response_text)
    except (ValueError, Exception) as exc:
        raise ValueError(f"LLM returned invalid JSON for comparison: {exc}") from exc

    def _join(field: object) -> str:
        """Accept either an array of paragraphs (new format) or a plain string (fallback)."""
        if isinstance(field, list):
            return "\n\n".join(str(p) for p in field if p)
        return str(field) if field else ""

    summary        = _join(data.get("summary", ""))
    recommendation = _join(data.get("recommendation", ""))
    questions      = data.get("questions", [])
    markdown = _build_markdown(profiles, summary, recommendation)

    return Comparison(
        products=profiles,
        summary=summary,
        recommendation=recommendation,
        markdown=markdown,
        questionnaire={"questions": questions},
    )
