import os
import json
from typing import Optional
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

if not API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in environment. Check your .env file.")

client = Groq(api_key=API_KEY)

MAX_RETRIES = 2  # structured output from smaller/faster models isn't 100% reliable first try


SYSTEM_PROMPT_TEMPLATE = """You are the seller agent for a small apparel and footwear store on an \
agentic commerce platform. You are talking to a buyer agent, not a human directly.

Here is your REAL, CURRENT catalog. This is the ONLY source of truth for what you sell, at what \
price, and what's in stock. Never invent products, prices, or stock levels that aren't in this list:

{catalog_json}

Rules you must follow:
1. Only discuss and offer products that appear in the catalog above.
2. If a product is out of stock (stock = 0) or inactive (active = false), you must say it is \
unavailable — never offer to sell it.
3. Never state a price other than the exact price_inr value from the catalog.
4. When the buyer has clearly agreed to purchase a SPECIFIC product at a SPECIFIC quantity, include \
a "proposal" in your response. If the buyer is still browsing, asking questions, or hasn't confirmed \
a specific item yet, "proposal" must be null.
5. IMPORTANT: if the buyer asks you to retry, try again, or re-attempt a purchase (for example after \
being told a payment failed), you MUST include the "proposal" object again with the same sku, \
quantity, and price — every single time a purchase attempt should happen, not just the first time. \
Never respond to a retry request with only reassurance text and no proposal, since that leaves \
nothing for the payment system to act on. If in doubt about whether to include a proposal on a \
retry, include it.
6. You are not the one who approves payments — you only propose. A separate system checks and \
approves or rejects every proposal, so it is fine (expected, even) if a proposal later gets rejected.

You must respond with ONLY a single valid JSON object, no other text before or after it, in exactly \
this shape:
{{
  "reply": "<your natural-language message to the buyer>",
  "proposal": null OR {{"sku": "<catalog sku>", "quantity": <integer>, "proposed_price_inr": <number, must exactly match catalog price_inr>}}
}}
"""


def _build_system_prompt(catalog: list[dict]) -> str:
    # Only expose the fields the seller agent actually needs to reason about,
    # keeps the prompt shorter and avoids leaking irrelevant internal fields.
    slim_catalog = [
        {
            "sku": p["sku"],
            "name": p["name"],
            "category": p["category"],
            "price_inr": p["price_inr"],
            "stock": p["stock"],
            "variants": p["variants"],
            "active": p["active"],
        }
        for p in catalog
    ]
    return SYSTEM_PROMPT_TEMPLATE.format(catalog_json=json.dumps(slim_catalog, indent=2))


def _extract_json(text: str) -> Optional[dict]:
    """Models sometimes wrap JSON in markdown fences or add stray text
    despite instructions. This strips common wrapping before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: find the first '{' and last '}' and try that slice
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def get_seller_response(
    buyer_message: str,
    conversation_history: list[dict],
    catalog: list[dict],
) -> dict:
    """
    Sends the buyer's message (plus conversation history) to the seller agent
    and returns a parsed dict: {"reply": str, "proposal": dict|None}.

    conversation_history is a list of {"role": "user"|"assistant", "content": str}
    in the format the Groq/OpenAI-style chat API expects, NOT including the
    system prompt (that's added fresh here every call using the live catalog).

    Raises RuntimeError if the model fails to produce valid JSON after retries
    — this is deliberate: a broken/unparseable response should be a visible,
    logged failure, not silently swallowed into a fake default.
    """
    system_prompt = _build_system_prompt(catalog)
    messages = [{"role": "system", "content": system_prompt}] + conversation_history + [
        {"role": "user", "content": buyer_message}
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.3,  # low temperature: this is a commerce decision, not creative writing
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content
        parsed = _extract_json(raw_text)

        if parsed is not None and "reply" in parsed and "proposal" in parsed:
            return parsed

        last_error = raw_text
        # retry with a stricter nudge if the first attempt didn't come back clean
        messages.append({"role": "assistant", "content": raw_text})
        messages.append({
            "role": "user",
            "content": "That was not valid JSON in the required shape. Respond with ONLY the JSON object, nothing else.",
        })

    raise RuntimeError(
        f"Seller agent failed to produce valid structured output after {MAX_RETRIES} attempts. "
        f"Last raw response: {last_error!r}"
    )