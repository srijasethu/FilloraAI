"""
test_form.py
------------
CLI script: end-to-end test on a real Google Form.

Usage:
  python test_form.py <form_url> <account_name>

Example:
  python test_form.py "https://docs.google.com/forms/d/e/your_form_id/viewform" "college_account"

What it does:
  1. Opens the form in a browser (uses the saved login for <account_name>).
  2. Reads all questions.
  3. Sends them to Gemini and gets answers.
  4. Prints a summary of questions and answers.
  5. Asks you: "Fill the form? (y/n)"
  6. If yes: fills all answers page by page (does NOT submit).
  7. Leaves the browser open for you to review, then asks: "Submit? (y/n)"
  8. Submits only if you type 'y'.
"""

import sys
import json
from playwright.sync_api import sync_playwright

import browser_manager
import form_reader
import form_filler
import ai_brain


def load_profile():
    """Load profile.json from the backend folder."""
    from pathlib import Path
    profile_path = Path(__file__).parent / "profile.json"
    if not profile_path.exists():
        print("❌ Error: profile.json not found. Please fill it in first.")
        sys.exit(1)
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_summary(questions: list, answers: list):
    """Print a formatted summary of questions and their AI answers."""
    print("\n" + "═" * 70)
    print("  FORM SUMMARY")
    print("═" * 70)

    answer_map = {a["id"]: a for a in answers}

    for q in questions:
        a = answer_map.get(q["id"], {})
        status = a.get("status", "unknown")
        status_emoji = {"confident": "✅", "needs_review": "📝", "needs_input": "❓"}.get(status, "❔")

        print(f"\nPage {q['page']} | Q{q['id']} [{q['type']}]")
        print(f"  Question: {q['question']}")
        if q.get('hint'):
            print(f"  Hint:     {q['hint']}")
        if q.get('options'):
            print(f"  Options:  {q['options']}")
        print(f"  {status_emoji} [{status}] Answer: {a.get('answer', '(empty)')}")
        print(f"  Reason: {a.get('reason', '')}")

    print("\n" + "═" * 70)
    print(f"  Total: {len(questions)} questions | "
          + f"{sum(1 for a in answers if a.get('status') == 'confident')} confident, "
          + f"{sum(1 for a in answers if a.get('status') == 'needs_review')} needs review, "
          + f"{sum(1 for a in answers if a.get('status') == 'needs_input')} needs input")
    print("═" * 70 + "\n")


def main():
    # ── Parse CLI arguments ────────────────────────────────────────────────────
    if len(sys.argv) < 3:
        print("Usage: python test_form.py <form_url> <account_name>")
        print("Example: python test_form.py https://forms.gle/xxx college_account")
        sys.exit(1)

    form_url     = sys.argv[1]
    account_name = sys.argv[2]

    print(f"\n{'═' * 70}")
    print("  FilloraAI — End-to-End Form Test")
    print(f"{'═' * 70}")
    print(f"  Form:    {form_url}")
    print(f"  Account: {account_name}")
    print(f"{'═' * 70}\n")

    # ── Load profile ───────────────────────────────────────────────────────────
    profile = load_profile()
    print(f"✓ Loaded profile for: {profile.get('full_name', 'Unknown')}")

    # ── Open browser and read form ─────────────────────────────────────────────
    with sync_playwright() as p:
        print(f"\n[Step 1] Opening browser for account '{account_name}'...")
        context = browser_manager.get_browser_context(account_name, p)

        print("\n[Step 2] Reading the form...")
        questions = form_reader.read_form(context, form_url)

        if not questions:
            print("❌ No questions found in the form. Exiting.")
            context.close()
            return

        print(f"\n✓ Found {len(questions)} questions.")

        # ── Get AI answers ─────────────────────────────────────────────────────
        print("\n[Step 3] Getting AI answers...")
        answers = ai_brain.answer_questions(questions, profile)

        # ── Print summary ──────────────────────────────────────────────────────
        print_summary(questions, answers)

        # ── Check for needs_input questions ───────────────────────────────────
        needs_input = [a for a in answers if a.get("status") == "needs_input"]
        if needs_input:
            print(f"⚠️  WARNING: {len(needs_input)} question(s) need your input (no answer will be filled):")
            for a in needs_input:
                q = next((q for q in questions if q["id"] == a["id"]), {})
                print(f"   - Q{a['id']}: {q.get('question', '?')}")
            print()

        # ── Ask user whether to fill ───────────────────────────────────────────
        fill = input("Fill the form with these answers? (y/n): ").strip().lower()
        if fill != 'y':
            print("Skipped filling. Closing browser.")
            context.close()
            return

        # Get the page that was kept open by form_reader
        page = getattr(context, '_fillora_page', None)
        if not page:
            print("❌ Error: form page not found. Please restart.")
            context.close()
            return

        # ── Fill the form ──────────────────────────────────────────────────────
        print("\n[Step 4] Filling the form...")
        summary = form_filler.fill_form(page, questions, answers)

        print(f"\n✓ Filled: {len(summary['filled'])} | Skipped: {len(summary['skipped'])} | Errors: {len(summary['errors'])}")

        if summary['skipped']:
            print("\nSkipped questions:")
            for s in summary['skipped']:
                q = next((q for q in questions if q["id"] == s["id"]), {})
                print(f"  - Q{s['id']}: {q.get('question', '?')} ({s['reason']})")

        # ── Ask user whether to submit ─────────────────────────────────────────
        print("\n⚠️  REVIEW the browser window carefully before submitting!")
        submit = input("Submit the form? Type 'yes' to confirm: ").strip().lower()

        if submit == 'yes':
            print("\n[Step 5] Submitting...")
            success = form_filler.submit_form(page)
            if success:
                print("✓ Form submitted successfully! Check the browser for confirmation.")
            else:
                print("❌ Submission failed. Please submit manually in the browser.")
        else:
            print("Submission skipped. The browser is still open — you can submit manually.")

        # Keep the browser open briefly so the user can see the result
        input("\nPress Enter to close the browser...")
        context.close()


if __name__ == "__main__":
    main()
