"""
scripts/test_seller_agent.py

Day 6 sanity check: talk to the seller agent with a few hardcoded buyer
messages (no buyer agent involved yet) and print its structured responses,
so you can eyeball whether it's behaving sensibly before wiring up the full
conversation loop.

Run:
    python scripts/test_seller_agent.py
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.seller_agent import get_seller_response

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
catalog = json.loads((DATA_DIR / "catalog.json").read_text())

TEST_MESSAGES = [
    "Hi, do you have any running shoes?",
    "I'd like to buy the Runner Pro sneakers, size UK9.",
    "Do you have trail running shoes in stock?",
    "Can I get the high-top basketball shoes?",
    "I want 3 cotton t-shirts.",
    "Do you sell laptops?",
]


def main():
    for i, message in enumerate(TEST_MESSAGES, 1):
        print(f"\n{'='*70}")
        print(f"Buyer [{i}]: {message}")
        print("=" * 70)
        try:
            response = get_seller_response(message, conversation_history=[], catalog=catalog)
            print(f"Seller reply: {response['reply']}")
            print(f"Proposal: {json.dumps(response['proposal'])}")
        except RuntimeError as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    main()
