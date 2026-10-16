"""
test_ai.py
----------
Tests the AI brain (ai_brain.py) with 6 sample questions -- no browser needed.

This is a pure Python test you can run anytime to verify:
  1. The Gemini API key is working.
  2. The AI correctly identifies confident vs needs_review vs needs_input answers.
  3. The answer format looks right.

Run with:
  python test_ai.py
"""

import sys
import json
from pathlib import Path

# Force UTF-8 output so emoji print correctly on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ai_brain import answer_questions


def load_profile() -> dict:
    """
    Load the real profile.json from the backend folder.
    This ensures test_ai.py always uses the same data as the live server.
    """
    profile_path = Path(__file__).parent / "profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(
            f"profile.json not found at {profile_path}. "
            "Please fill it in before running this test."
        )
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── The real profile is loaded inside run_test() via load_profile() ────────────
# No hardcoded profile data lives here. The source of truth is backend/profile.json.

# ── 6 sample questions covering all major types and statuses ──────────────────
SAMPLE_QUESTIONS = [
    {
        "id": 1,
        "page": 1,
        "question": "What is your full name?",
        "type": "short_text",
        "options": [],
        "required": True,
        "hint": ""
    },
    {
        "id": 2,
        "page": 1,
        "question": "What is your roll number?",
        "type": "short_text",
        "options": [],
        "required": True,
        "hint": ""
    },
    {
        "id": 3,
        "page": 1,
        "question": "Which department are you from?",
        "type": "multiple_choice",
        "options": [
            "Computer Science and Engineering",
            "Electronics and Communication Engineering",
            "Mechanical Engineering",
            "Civil Engineering",
            "Chemical Engineering"
        ],
        "required": True,
        "hint": ""
    },
    {
        "id": 4,
        "page": 1,
        "question": "Which of the following apply to you? (Select all that apply)",
        "type": "checkbox",
        "options": [
            "I have prior coding experience",
            "I have attended a hackathon before",
            "I am a vegetarian",
            "I need accommodation",
            "I have a laptop"
        ],
        "required": False,
        "hint": ""
    },
    {
        "id": 5,
        "page": 2,
        "question": "What is your opinion about polar bears? Write 2-3 sentences.",
        "type": "paragraph",
        "options": [],
        "required": False,
        "hint": "2-3 sentences"
    },
    {
        "id": 6,
        "page": 2,
        "question": "I hereby declare that all information provided is true and accurate. Do you agree?",
        "type": "multiple_choice",
        "options": ["Yes, I agree", "No, I do not agree"],
        "required": True,
        "hint": ""
    }
]


def run_test():
    # Load the real profile.json — same file the server uses
    try:
        profile = load_profile()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return

    print("=" * 70)
    print("  FilloraAI - AI Brain Test")
    print("=" * 70)
    print(f"  Profile loaded: {profile.get('full_name', '?')} | {profile.get('roll_number', '?')}")
    print(f"  Sending {len(SAMPLE_QUESTIONS)} questions to Gemini...\n")

    try:
        answers = answer_questions(SAMPLE_QUESTIONS, profile)
    except Exception as e:
        print(f"\nERROR: {e}")
        return

    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)

    # Print results in a readable way
    for q, a in zip(SAMPLE_QUESTIONS, answers):
        print(f"\n{'-' * 60}")
        print(f"Q{q['id']} [{q['type']}]: {q['question']}")
        if q['options']:
            print(f"   Options: {q['options']}")

        status_label = {"confident": "[OK] ", "needs_review": "[DRAFT]", "needs_input": "[NEED]"}.get(
            a.get("status", ""), "[?]"
        )
        print(f"\n   Status:  {status_label} {a.get('status', 'unknown')}")
        print(f"   Answer:  {a.get('answer', '')}")
        print(f"   Reason:  {a.get('reason', '')}")

    print(f"\n{'=' * 70}")
    print(f"  Test complete! Got {len(answers)} answers for {len(SAMPLE_QUESTIONS)} questions.")
    print(f"{'=' * 70}\n")

    # Count by status
    counts = {"confident": 0, "needs_review": 0, "needs_input": 0}
    for a in answers:
        s = a.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    print(f"  [OK]    confident:    {counts['confident']}")
    print(f"  [DRAFT] needs_review: {counts['needs_review']}")
    print(f"  [NEED]  needs_input:  {counts['needs_input']}")
    print()


if __name__ == "__main__":
    run_test()
