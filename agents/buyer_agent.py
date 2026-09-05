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

MAX_RETRIES = 2


SYSTEM_PROMPT_TEMPLATE = """You are a buyer agent shopping on behalf of a human user. Your goal:

{goal}

You are talking to a seller agent, not a human. Rules:
1. Ask clarifying questions if the seller needs more information from you (size, quantity, etc.)
   before you can confirm a purchase.
2. When you're satisfied with what's on offer and want to proceed, clearly confirm the purchase
   in plain language (e.g. "Yes, I'll take it" / "Please go ahead with that order").
3. If you're told a purchase was rejected (e.g. out of stock, over budget, price mismatch), react
   sensibly — ask for an alternative, adjust your request, or explain you'll skip it. Never pretend
   a rejection didn't happen.
4. If you're told a payment failed after being approved, stay calm, acknowledge it plainly, and
   either ask to retry or ask about an alternative — don't panic, don't repeat the same failing
   action blindly, and don't claim success.
5. Once your goal is satisfied (a payment has actually succeeded) OR you've decided to give up
   (e.g. nothing suitable is available after a reasonable attempt), say so clearly and include
   "task_complete": true in your response. Otherwise "task_complete" must be false.

   CRITICAL: stating your intent to buy something, or confirming you want to proceed, is NOT
   the same as the task being complete. Do not set "task_complete" to true just because you said
   "I'll take it" or "please proceed with the order" — the purchase isn't done until you are
   explicitly told the payment succeeded. Keep "task_complete" false while you are waiting to
   hear back about a proposal, a validation result, or a payment outcome.

You must respond with ONLY a single valid JSON object, no other text before or after it, in exactly
this shape:
{{
  "message": "<what you say to the seller, or a closing summary if task_complete is true>",
  "task_complete": true or false
}}
"""


def _build_system_prompt(goal: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(goal=goal)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def get_buyer_response(
    goal: str,
    conversation_history: list[dict],
    incoming_message: str,
) -> dict:
    """
    Sends the latest message (from the seller, or a system event like a
    rejection/payment outcome) to the buyer agent and returns a parsed dict:
    {"message": str, "task_complete": bool}.

    conversation_history is a list of {"role": "user"|"assistant", "content": str}
    NOT including the system prompt (rebuilt fresh each call with the goal).
    From the buyer agent's point of view, "user" role = whatever it's reacting
    to (seller messages, rejection reasons, payment outcomes); "assistant" =
    its own past replies.

    Raises RuntimeError if valid JSON can't be produced after retries — same
    fail-loud philosophy as the seller agent.
    """
    system_prompt = _build_system_prompt(goal)
    messages = [{"role": "system", "content": system_prompt}] + conversation_history + [
        {"role": "user", "content": incoming_message}
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content
        parsed = _extract_json(raw_text)

        if parsed is not None and "message" in parsed and "task_complete" in parsed:
            return parsed

        last_error = raw_text
        messages.append({"role": "assistant", "content": raw_text})
        messages.append({
            "role": "user",
            "content": "That was not valid JSON in the required shape. Respond with ONLY the JSON object, nothing else.",
        })

    raise RuntimeError(
        f"Buyer agent failed to produce valid structured output after {MAX_RETRIES} attempts. "
        f"Last raw response: {last_error!r}"
    )