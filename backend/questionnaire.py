"""
Generates a personalised product recommendation based on user questionnaire answers.

The questionnaire questions themselves are produced inside comparator.py in the same
LLM call as the comparison summary, so no extra call is needed during the job pipeline.
This module handles only the on-demand recommendation that fires when the user submits
their answers.
"""

from .models import ProductProfile
from .llm import call_llm, parse_llm_json


def generate_personalized_recommendation(
    profiles: list[ProductProfile],
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """
    Given the compared products, the questionnaire questions, and the user's answers,
    pick the single best-fit product and explain why.

    Returns { "recommended_title": str, "reasoning": str }
    """
    products_text = "\n\n".join(
        f'• "{p.title}"\n'
        f'  Summary: {p.description_summary}\n'
        f'  Pros: {", ".join(p.pros[:4])}\n'
        f'  Cons: {", ".join(p.cons[:3])}\n'
        f'  Price: {p.price or "N/A"}'
        for p in profiles
    )

    qa_text = "\n".join(
        f'Q: {q["text"]}\nA: {answers.get(q["id"], "Not answered")}'
        for q in questions
    )

    titles_list = "\n".join(f'  "{p.title}"' for p in profiles)

    prompt = f"""A user is choosing between {len(profiles)} products. Based on their questionnaire answers, recommend the single best match.

Products:
{products_text}

User's questionnaire answers:
{qa_text}

You MUST pick exactly one product. Its title must be copied verbatim from:
{titles_list}

Focus on which specific answers most strongly indicate a preference for one product over the others.

Return ONLY valid JSON — no markdown, no explanation:
{{
  "recommended_title": "exact title copied from the list above",
  "reasoning": "2-3 sentences explaining which answers drove this choice and why this product fits those specific needs"
}}"""

    response = call_llm(prompt)
    try:
        return parse_llm_json(response)
    except (ValueError, Exception) as exc:
        raise ValueError(f"LLM returned invalid JSON for recommendation: {exc}") from exc
