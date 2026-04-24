"""
Thin wrapper around the Gemini API via the google-genai SDK.

Configure via .env:
    GEMINI_API_KEY=AIza...
    GEMINI_MODEL=gemini-2.5-flash   # optional primary model override

Retry / fallback strategy — round-robin across all models:

    Round 1:  gemini-2.5-flash → gemini-2.5-pro → gemini-2.5-flash-lite
    (wait 4 s if all failed)
    Round 2:  gemini-2.5-flash → gemini-2.5-pro → gemini-2.5-flash-lite
    (wait 4 s if all failed)
    … up to MAX_ROUNDS, then raise.

Each model gets ONE attempt per round. On a 503 / rate-limit we move to the
next model immediately — no waiting within a round.
Non-retryable errors (bad API key, invalid request) raise straight away.
"""

import json
import logging
import os
import re
import time

from google import genai
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

# Fallback order after the primary model. All three are on the Google AI
# Studio free tier (Tier 1). Edit here or set GEMINI_MODEL in .env to change.
#   gemini-2.5-pro        — more capable; free tier limited to 5 RPM
#   gemini-2.5-flash-lite — lightest/fastest; least likely to be overloaded
# NOTE: gemini-2.0-flash / gemini-2.0-flash-lite are deprecated (shutdown June 2026).
FALLBACK_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
]

INTER_ROUND_WAIT = 4   # seconds to rest between full rounds
MAX_ROUNDS       = 5   # give up after this many complete rounds

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Add it to your .env file.")
        _client = genai.Client(api_key=api_key)
    return _client


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient server-side errors worth cycling past."""
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "503", "unavailable", "high demand", "overloaded",
        "429", "resource_exhausted", "rate limit", "too many requests",
    ))


def call_llm(prompt: str) -> str:
    """
    Send a single user prompt and return the model's reply as a string.

    Round-robin fallback: each model gets one shot per round; on 503/rate-limit
    the next model is tried immediately. After all models fail in a round, waits
    INTER_ROUND_WAIT seconds then starts the next round.
    """
    primary = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    models: list[str] = [primary] + [m for m in FALLBACK_MODELS if m != primary]

    client    = _get_client()
    last_exc: Exception = RuntimeError("No models tried.")

    for round_num in range(1, MAX_ROUNDS + 1):
        if round_num > 1:
            log.warning(
                "[LLM] All %d models unavailable in round %d — waiting %ds before round %d…",
                len(models), round_num - 1, INTER_ROUND_WAIT, round_num,
            )
            time.sleep(INTER_ROUND_WAIT)

        for model in models:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                if model != primary or round_num > 1:
                    log.info("[LLM] Success — model: %s  round: %d", model, round_num)
                return response.text

            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc):
                    log.warning(
                        "[LLM] Round %d — %s returned 503/rate-limit, moving to next model…",
                        round_num, model,
                    )
                else:
                    raise   # auth failure, bad request — no point continuing

    raise RuntimeError(
        f"All Gemini models unavailable after {MAX_ROUNDS} rounds. "
        f"Last error: {last_exc}"
    ) from last_exc


def parse_llm_json(text: str) -> dict:
    """
    Robustly parse a JSON object from LLM output.

    Handles the most common model quirks:
    - Markdown code fences  (```json ... ```)
    - Literal newlines / tabs / carriage-returns inside string values
      (invalid in JSON but common when models write multi-paragraph text)
    - Stray text before the opening brace or after the closing brace

    Uses a character-level state machine so escaped quotes inside strings
    are never mis-treated as string delimiters.
    """
    # 1. Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)

    # 2. Extract the outermost { ... } block
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("LLM response contained no JSON object.")
    text = text[start:end]

    # 3. Try direct parse first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 4. Escape bare control characters inside string values via state machine
    result      = []
    in_string   = False
    escape_next = False

    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)

    return json.loads("".join(result))
