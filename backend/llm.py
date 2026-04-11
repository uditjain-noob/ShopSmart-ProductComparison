"""
Thin wrapper around the Gemini API via the google-genai SDK.

Configure via .env:
    GEMINI_API_KEY=AIza...
    GEMINI_MODEL=gemini-2.5-flash   # optional override
"""

import json
import os
import re

from google import genai
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash"

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Add it to your .env file.")
        _client = genai.Client(api_key=api_key)
    return _client


def call_llm(prompt: str) -> str:
    """Send a single user prompt and return the model's reply as a string."""
    client = _get_client()
    model  = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


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
