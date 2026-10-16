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

# Force UTF-8 output so emoji print correctly on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ai_brain import answer_questions

# ── Sample profile (edit to match your profile.json for realistic output) ─────
SAMPLE_PROFILE = {
    "full_name": "Arjun Sharma",
    "roll_number": "2022-CS-047",
    "department": "Computer Science and Engineering",
    "year": "3rd Year",
    "college": "National Institute of Technology, Warangal",
    "email": "arjun.sharma@nitw.ac.in",
    "phone": "+91-9876543210",
    "gender": "Male",
    "dob": "15/08/2003",
    "city": "Warangal",
    "writing_samples": [
        "I chose Computer Science because I've always been fascinated by how software shapes the world around us. From building small scripts in high school to working on real projects in college, I genuinely enjoy the problem-solving aspect of coding — that moment when something finally clicks and works is what keeps me going.",
        "I work best in team environments where everyone pitches in honestly. During our semester project, I took on the backend integration because no one else was comfortable with APIs. It was challenging, but breaking it into smaller tasks made it manageable. I'd say my biggest strength is staying calm when things break — and they always do.",
        "The workshop on cloud computing really changed how I think about scalability. Before attending, I assumed servers were just 'big computers somewhere'. Learning about load balancing and containerization gave me a completely new perspective on how modern applications actually run in production."
    ],
    "custom_facts": {
        "hobbies": ["competitive programming", "reading tech blogs", "badminton"],
        "technical_skills": ["Python", "JavaScript", "React", "SQL", "Git"],
        "career_goal": "To work as a software engineer at a product-based company and eventually build my own startup.",
        "why_this_event": "I want to learn from industry professionals and network with peers who share the same passion for technology.",
        "dietary_preference": "Vegetarian",
        "tshirt_size": "M",
    }
}

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
    print("=" * 70)
    print("  FilloraAI - AI Brain Test")
    print("=" * 70)
    print(f"\nSending {len(SAMPLE_QUESTIONS)} questions to Gemini...\n")

    try:
        answers = answer_questions(SAMPLE_QUESTIONS, SAMPLE_PROFILE)
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
