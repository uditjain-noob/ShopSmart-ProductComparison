"""
Smarter Product Finder Agent.

Given the products a user already compared and their questionnaire answers,
this agent uses Gemini function calling to search Amazon and find 3 new
products that genuinely fit the user's criteria better.

The agent runs a real while-loop: if it evaluates candidates and none are
good enough, it refines its query and searches again — up to MAX_ITERATIONS
tool-call rounds.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable

from google import genai
from google.genai import types
from dotenv import load_dotenv

from .models import ProductProfile
from .platforms.amazon_search import search_amazon as _search_amazon

load_dotenv()

log = logging.getLogger(__name__)

MAX_ITERATIONS        = 15    # hard cap on tool-call rounds
MAX_PRODUCTS_EVAL     = 10    # stop fetching details once this many have been checked
DEFAULT_MODEL         = "gemini-2.5-flash"
FALLBACK_MODELS       = ["gemini-2.5-pro", "gemini-2.5-flash-lite"]
AGENT_MAX_ROUNDS      = 3     # rounds of model cycling before giving up
AGENT_ROUND_WAIT      = 4     # seconds to wait between full rounds


# ── Gemini call with retry/fallback ──────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(code in msg for code in ("503", "429", "unavailable", "resource_exhausted", "overloaded"))


def _call_with_fallback(
    client: genai.Client,
    contents: list,
    config: types.GenerateContentConfig,
    preferred_model: str,
) -> tuple:
    """
    Call generate_content with round-robin model fallback.

    On a retryable error (503/429) the next model in the list is tried immediately.
    If every model fails in a round, we sleep AGENT_ROUND_WAIT seconds and retry
    the whole cycle up to AGENT_MAX_ROUNDS times.

    Returns (response, model_that_succeeded).
    """
    models = [preferred_model] + [m for m in FALLBACK_MODELS if m != preferred_model]

    for round_num in range(1, AGENT_MAX_ROUNDS + 1):
        if round_num > 1:
            log.warning(
                "[Agent] All models failed in round %d — waiting %ds before round %d…",
                round_num - 1, AGENT_ROUND_WAIT, round_num,
            )
            time.sleep(AGENT_ROUND_WAIT)

        for model in models:
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config,
                )
                if model != preferred_model:
                    log.info("[Agent] Succeeded with fallback model: %s", model)
                return response, model
            except Exception as exc:
                if _is_retryable(exc):
                    log.warning("[Agent] Model %s retryable error: %s", model, exc)
                    continue
                raise  # non-retryable — propagate immediately

    raise RuntimeError(
        f"Agent: all models {models} failed after {AGENT_MAX_ROUNDS} round(s)."
    )


# ── Output model ─────────────────────────────────────────────────────────────

@dataclass
class BetterSuggestion:
    title: str
    url: str
    price: str | None
    rating: float | None
    reason: str   # personalised explanation referencing questionnaire answers


# ── Budget inference ─────────────────────────────────────────────────────────

_PRICE_RE = re.compile(r"[\$£€₹¥₩]?\s*([\d,]+(?:\.\d{1,2})?)")


def _parse_price(price_str: str | None) -> float | None:
    if not price_str:
        return None
    m = _PRICE_RE.search(price_str.replace(",", ""))
    return float(m.group(1)) if m else None


def infer_budget(profiles: list[ProductProfile]) -> tuple[float | None, float | None]:
    """
    Derive a comfortable budget band from the prices of already-compared products.
    Returns (lower_bound, upper_bound) as floats, or (None, None) if no prices
    could be parsed.
    """
    prices = [p for p in (_parse_price(prof.price) for prof in profiles) if p]
    if not prices:
        return None, None
    lo = min(prices) * 0.75
    hi = max(prices) * 1.25
    return lo, hi


# ── Lightweight product details ───────────────────────────────────────────────

def _get_product_details(url: str) -> dict:
    """
    Scrape a single Amazon product page and return only the fields the agent
    needs: name, price, and a short description (≤5 feature bullets).

    Intentionally minimal to keep the LLM context window manageable across
    many calls in the tool-calling loop.
    """
    from .platforms.amazon import AmazonPlatform
    platform = AmazonPlatform()
    try:
        soup = platform._get_soup(url)
        title_el = soup.find("span", id="productTitle")
        name = title_el.get_text(strip=True) if title_el else "Unknown"

        price_el = soup.select_one(".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
        price = price_el.get_text(strip=True) if price_el else None

        bullets = soup.select("#feature-bullets li span.a-list-item")
        short_desc = " | ".join(
            b.get_text(strip=True) for b in bullets[:5] if b.get_text(strip=True)
        )

        return {"name": name, "price": price, "short_description": short_desc}
    except Exception as exc:
        log.warning("[Agent] get_product_details failed for %s: %s", url[:70], exc)
        return {"name": url, "price": None, "short_description": "Could not fetch details."}


# ── Tool dispatch ─────────────────────────────────────────────────────────────

def _dispatch(tool_name: str, args: dict) -> dict:
    """Execute a tool call and return a dict suitable for FunctionResponse."""
    if tool_name == "search_amazon":
        query = args.get("query", "")
        max_results = int(args.get("max_results", 20))
        try:
            results = _search_amazon(query, max_results=max_results)
            return {"products": results, "count": len(results)}
        except Exception as exc:
            return {"error": str(exc)}

    if tool_name == "get_product_details":
        url = args.get("url", "")
        return _get_product_details(url)

    return {"error": f"Unknown tool: {tool_name}"}


# ── System prompt builder ─────────────────────────────────────────────────────

def _build_system_prompt(
    profiles: list[ProductProfile],
    questions: list[dict],
    answers: dict[str, str],
    budget_min: float | None,
    budget_max: float | None,
) -> str:
    seen_titles = "\n".join(f"  - {p.title} ({p.price or 'price unknown'})" for p in profiles)

    qa_lines = "\n".join(
        f"  Q: {q['text']}\n  A: {answers.get(q['id'], 'Not answered')}"
        for q in questions
    )

    budget_note = (
        f"${budget_min:.0f}–${budget_max:.0f} (inferred from products already compared)"
        if budget_min and budget_max
        else "unknown — use your judgment based on the products already seen"
    )

    return f"""You are a smart product research agent helping a user find better products on Amazon.

CONTEXT — Products the user has ALREADY compared (do NOT suggest these or near-identical variants):
{seen_titles}

CONTEXT — User's budget range: {budget_note}

CONTEXT — User's preferences from questionnaire:
{qa_lines}

YOUR GOAL:
Find exactly 3 products on Amazon that are genuinely BETTER fits for this user than what they have already seen.
"Better" means: fits their stated preferences more closely, within their budget range, and offers something the compared products do not.

PROCESS:
1. Call search_amazon with a targeted query based on the user's preferences.
2. Evaluate returned titles and prices. For each promising candidate (aim for ~5 per round), call get_product_details.
3. Decide: does this product fit the user's criteria? If yes, note it as a suggestion. If no, discard it.
4. If you have fewer than 3 good suggestions after evaluating a batch, refine your query and call search_amazon again.
5. You may call get_product_details at most 10 times in total. Once you have evaluated 10 products, STOP searching and output your best suggestions immediately, even if fewer than 3.

RULES:
- Never suggest a product already in the "already compared" list above.
- Never suggest obvious color/size variants of already-compared products.
- Stay within the inferred budget range unless a product clearly offers exceptional value slightly outside it.
- Each suggestion's reason must reference specific questionnaire answers.
- Hard limit: get_product_details may be called at most 10 times. After 10 evaluations, output JSON immediately.

FINAL RESPONSE (when you have 3 suggestions, or when forced to stop at 10 evaluations):
Return ONLY valid JSON — no markdown, no explanation outside the JSON:
{{
  "suggestions": [
    {{
      "title": "exact product name as it appears on Amazon",
      "url": "https://www.amazon.in/dp/ASIN",
      "price": "₹XX,XXX or null",
      "rating": 4.3,
      "reason": "2-3 sentences explaining why this fits the user's specific answers"
    }}
  ]
}}"""


# ── Gemini function declarations ──────────────────────────────────────────────

_SEARCH_TOOL = types.FunctionDeclaration(
    name="search_amazon",
    description=(
        "Search Amazon India for products matching the query. "
        "Returns up to max_results candidates with title, url, description, price, rating."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "query":       {"type": "string", "description": "Search query, e.g. 'wireless noise cancelling headphones under $150'"},
            "max_results": {"type": "integer", "description": "Maximum number of results to return (default 20)", "default": 20},
        },
        "required": ["query"],
    },
)

_DETAILS_TOOL = types.FunctionDeclaration(
    name="get_product_details",
    description=(
        "Get lightweight details for a specific Amazon product URL: "
        "name, short description (key features), and price. "
        "Call this for promising candidates to evaluate them against the user's criteria."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full Amazon product URL (https://www.amazon.com/dp/ASIN)"},
        },
        "required": ["url"],
    },
)


# ── Main agent entry point ────────────────────────────────────────────────────

def find_better_products(
    profiles: list[ProductProfile],
    questions: list[dict],
    answers: dict[str, str],
    progress_callback: Callable[[str], None] | None = None,
) -> list[BetterSuggestion]:
    """
    Run the discovery agent and return up to 3 BetterSuggestion objects.

    progress_callback, if provided, is called with a human-readable status
    string at key milestones so callers can surface progress to the UI.

    Raises ValueError if the agent cannot find any suitable products.
    """
    def _progress(msg: str) -> None:
        log.info("[Agent] %s", msg)
        if progress_callback:
            progress_callback(msg)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")
    client          = genai.Client(api_key=api_key)
    preferred_model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    budget_min, budget_max = infer_budget(profiles)
    if budget_min and budget_max:
        log.info("[Agent] Inferred budget range: $%.0f – $%.0f", budget_min, budget_max)
    else:
        log.info("[Agent] Could not infer budget from compared products (no prices found)")

    _progress("Building search context from your preferences…")
    system_prompt = _build_system_prompt(profiles, questions, answers, budget_min, budget_max)

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=[_SEARCH_TOOL, _DETAILS_TOOL])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    # Seed the conversation
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text="Start searching for better products for this user.")],
        )
    ]

    iteration       = 0
    final_text: str | None = None
    searches_done   = 0
    details_fetched = 0
    start_time      = time.monotonic()
    current_model   = preferred_model  # may be updated by fallback

    while iteration < MAX_ITERATIONS:
        log.info("[Agent] ── Iteration %d / %d ──────────────────────────", iteration + 1, MAX_ITERATIONS)
        log.info("[Agent] Calling Gemini (model=%s, turns_in_context=%d)…", current_model, len(contents))

        t0 = time.monotonic()
        response, current_model = _call_with_fallback(client, contents, config, current_model)
        elapsed_llm = time.monotonic() - t0
        log.info("[Agent] Gemini responded in %.1fs (model=%s)", elapsed_llm, current_model)

        # No more tool calls → model has finished
        if not response.function_calls:
            log.info("[Agent] Model returned final answer (no tool calls)")
            final_text = response.text
            break

        tool_names = [c.name for c in response.function_calls]
        log.info("[Agent] Model requested %d tool call(s): %s", len(tool_names), tool_names)

        # Append the model's turn (may include multiple tool_call parts)
        contents.append(response.candidates[0].content)

        # Execute every tool call in this round and collect results
        tool_result_parts: list[types.Part] = []
        for call in response.function_calls:
            if call.name == "search_amazon":
                query = call.args.get("query", "")
                max_r = call.args.get("max_results", 20)
                searches_done += 1
                _progress(f'Searching Amazon: "{query}"…')
                log.info("[Agent] search_amazon  query=%r  max_results=%s", query, max_r)

            elif call.name == "get_product_details":
                url = call.args.get("url", "")
                details_fetched += 1
                _progress(f"Checking product {details_fetched}: {url.split('/dp/')[-1].split('/')[0]}…")
                log.info("[Agent] get_product_details  url=%s", url)

            t_tool = time.monotonic()
            result_data = _dispatch(call.name, call.args)
            elapsed_tool = time.monotonic() - t_tool

            result_size = len(result_data.get("products", result_data)) if isinstance(result_data.get("products"), list) else len(str(result_data))
            log.info(
                "[Agent] %-22s → %s in %.2fs",
                f"{call.name}()",
                f"{result_data.get('count', '')} results" if "count" in result_data else f"{result_size} chars",
                elapsed_tool,
            )

            tool_result_parts.append(
                types.Part.from_function_response(
                    name=call.name,
                    response=result_data,
                )
            )

        # role must be 'tool' (not 'user') so Gemini recognises these as function results
        contents.append(types.Content(role="tool", parts=tool_result_parts))
        iteration += 1

        _progress(
            f"Evaluated {details_fetched} product(s) across {searches_done} search(es) so far…"
        )

        # Hard cap: once 10 products evaluated, force finalisation now
        if details_fetched >= MAX_PRODUCTS_EVAL:
            log.info(
                "[Agent] Reached %d-product evaluation cap — requesting final answer",
                MAX_PRODUCTS_EVAL,
            )
            _progress("Reached product limit — finalising best suggestions…")
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"You have now evaluated {details_fetched} products (the limit). "
                             "Output your best suggestions as JSON immediately. "
                             "Do not call any more tools."
                    )],
                )
            )
            final_response, current_model = _call_with_fallback(client, contents, config, current_model)
            final_text = final_response.text or ""
            break

    total_elapsed = time.monotonic() - start_time
    log.info(
        "[Agent] Loop finished — iterations=%d  searches=%d  details=%d  total=%.1fs",
        iteration, searches_done, details_fetched, total_elapsed,
    )

    # If we exhausted iterations without a final text, ask for whatever it has
    if final_text is None:
        log.warning("[Agent] Max iterations (%d) reached — requesting final answer", MAX_ITERATIONS)
        _progress("Finalising results…")
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text="You have reached the search limit. "
                    "Return the best suggestions you have found so far as JSON, "
                    "even if fewer than 3."
                )],
            )
        )
        final_response, current_model = _call_with_fallback(client, contents, config, current_model)
        final_text = final_response.text or ""

    suggestions = _parse_suggestions(final_text)
    _progress(f"Done — found {len(suggestions)} suggestion(s) in {total_elapsed:.0f}s")
    return suggestions


# ── Parse agent output ────────────────────────────────────────────────────────

def _parse_suggestions(text: str) -> list[BetterSuggestion]:
    """Parse the agent's final JSON response into BetterSuggestion objects."""
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)

    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Agent returned no JSON. Response was: {text[:200]}")

    data = json.loads(text[start:end])
    raw_suggestions = data.get("suggestions", [])

    if not raw_suggestions:
        raise ValueError("Agent returned empty suggestions list.")

    results = []
    for s in raw_suggestions[:3]:
        results.append(BetterSuggestion(
            title  = s.get("title", "Unknown Product"),
            url    = s.get("url", ""),
            price  = s.get("price"),
            rating = float(s["rating"]) if s.get("rating") is not None else None,
            reason = s.get("reason", ""),
        ))
    return results
