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
   best suits THEM personally. Rules for the questions:
   - Each question MUST target a real, specific trade-off visible in the specs, pros, or cons above
     (e.g. if one product has more RAM but worse battery, ask which matters more to the user).
   - Do NOT ask generic questions that apply to any product category. Every question must be
     grounded in the actual differences between THESE specific products: {titles}
   - Each question must have exactly 4 concise answer options (8 words or fewer per option).
   - Cover different dimensions: use case, priority trade-offs, budget sensitivity, workflow needs, etc.

Return ONLY a valid JSON object with exactly these keys — no markdown, no explanation:
{{
  "summary": "3-5 paragraph narrative...",
  "recommendation": "2-3 paragraph recommendation...",
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
    summary = data.get("summary", "")
    recommendation = data.get("recommendation", "")
    questions = data.get("questions", [])
    markdown = _build_markdown(profiles, summary, recommendation)

    return Comparison(
        products=profiles,
        summary=summary,
        recommendation=recommendation,
        markdown=markdown,
        questionnaire={"questions": questions},
    )
