"""
form_filler.py
--------------
Uses Playwright to fill approved answers into an already-open Google Form.

IMPORTANT SAFETY RULES:
  - This file NEVER clicks Submit automatically.
  - The form stays open on the final page so you can review everything.
  - Only submit_form() submits, and only when you call it explicitly.

Expected flow:
  1. form_reader.py reads the form and keeps the browser page open.
  2. You review the AI-generated answers and approve/edit them.
  3. fill_form() fills the answers page by page and clicks Next between pages.
  4. The browser stays on the final page with all answers filled in.
  5. You visually inspect, then call submit_form() or click Submit yourself.
"""

import time
from playwright.sync_api import Page

# ══════════════════════════════════════════════════════════════════════════════
#  SELECTORS — same structure as form_reader.py; update here if Google changes HTML
# ══════════════════════════════════════════════════════════════════════════════

SEL_QUESTION_CONTAINER = 'div[role="listitem"]'
SEL_TITLE_SIMPLE       = '.M7eMe'
SEL_TITLE_FALLBACK     = '.HoXoMd'
SEL_SHORT_TEXT         = 'input[type="text"]'
SEL_PARAGRAPH          = 'textarea'
SEL_RADIO              = 'div[role="radio"]'
SEL_CHECKBOX           = 'div[role="checkbox"]'
SEL_LISTBOX            = 'div[role="listbox"]'
SEL_OPTION_ITEM        = 'div[role="option"]'
SEL_NEXT_BUTTON        = '[jsname="OCpkoe"], .Y5sE8d'
SEL_SUBMIT_BUTTON      = '[jsname="M2UYVd"]'
SEL_DATE_INPUT         = 'input[type="date"]'
SEL_TIME_INPUT         = 'input[type="time"]'

# ══════════════════════════════════════════════════════════════════════════════


def _get_question_text_from_card(card) -> str:
    """Read the question text from a form card element."""
    title_el = card.query_selector(SEL_TITLE_SIMPLE)
    if title_el:
        return title_el.inner_text().strip()
    title_el = card.query_selector(SEL_TITLE_FALLBACK)
    if title_el:
        return title_el.inner_text().strip()
    lines = [l.strip() for l in card.inner_text().splitlines() if l.strip()]
    return lines[0] if lines else ""


def _fill_short_text(card, answer: str):
    """Fill a single-line text input."""
    input_el = card.query_selector(SEL_SHORT_TEXT)
    if input_el:
        input_el.click()
        input_el.fill("")         # Clear first
        input_el.type(answer)     # Type the answer naturally (not paste)
        print(f"    ✓ Filled short text: {answer[:50]}")
    else:
        print("    ✗ Could not find text input field.")


def _fill_paragraph(card, answer: str):
    """Fill a multi-line textarea."""
    textarea = card.query_selector(SEL_PARAGRAPH)
    if textarea:
        textarea.click()
        textarea.fill("")
        textarea.type(answer)
        print(f"    ✓ Filled paragraph: {answer[:50]}...")
    else:
        print("    ✗ Could not find textarea.")


def _fill_multiple_choice(card, answer: str):
    """
    Click the radio button whose label matches the answer exactly.
    We iterate through all radio options and click the one that matches.
    """
    radios = card.query_selector_all(SEL_RADIO)
    for radio in radios:
        label = radio.get_attribute("aria-label") or radio.inner_text().strip()
        if label.strip() == answer.strip():
            radio.click()
            print(f"    ✓ Selected radio: {answer}")
            return
    print(f"    ✗ Could not find radio option '{answer}'. Available: "
          + str([r.get_attribute("aria-label") for r in radios]))


def _fill_checkbox(card, answers: list[str]):
    """
    Check the checkboxes whose labels match the answers list.
    Uncheck anything that shouldn't be checked.
    """
    checkboxes = card.query_selector_all(SEL_CHECKBOX)
    for cb in checkboxes:
        label = cb.get_attribute("aria-label") or cb.inner_text().strip()
        is_checked = cb.get_attribute("aria-checked") == "true"
        should_be_checked = label.strip() in [a.strip() for a in answers]

        if should_be_checked and not is_checked:
            cb.click()
            print(f"    ✓ Checked: {label}")
        elif not should_be_checked and is_checked:
            cb.click()  # Uncheck it
            print(f"    ○ Unchecked: {label}")


def _fill_dropdown(card, answer: str, page: Page):
    """
    Open a dropdown and select the matching option.
    Google Forms dropdowns use a listbox that opens as an overlay.
    """
    listbox = card.query_selector(SEL_LISTBOX)
    if not listbox:
        print("    ✗ Could not find dropdown.")
        return

    # Click to open the dropdown
    listbox.click()
    time.sleep(0.5)  # Wait for dropdown options to appear

    # Options appear as an overlay in the page
    options = page.query_selector_all(SEL_OPTION_ITEM)
    for option in options:
        if option.inner_text().strip() == answer.strip():
            option.click()
            print(f"    ✓ Selected dropdown: {answer}")
            return

    print(f"    ✗ Could not find dropdown option '{answer}'")


def _fill_linear_scale(card, answer: str):
    """
    Click the radio button in a linear scale that matches the numeric answer.
    Answer should be a string like "4" or "3".
    """
    radios = card.query_selector_all(SEL_RADIO)
    for radio in radios:
        label = radio.get_attribute("aria-label") or radio.inner_text().strip()
        # Match by number — the label might be "1", "2", etc. or "1 (Not at all)"
        if label.strip().startswith(answer.strip()):
            radio.click()
            print(f"    ✓ Selected scale value: {answer}")
            return
    print(f"    ✗ Could not find scale value '{answer}'")


def _fill_date(card, answer: str):
    """Fill a date input. Expected format: DD/MM/YYYY or YYYY-MM-DD."""
    date_input = card.query_selector(SEL_DATE_INPUT)
    if date_input:
        # Convert DD/MM/YYYY to YYYY-MM-DD if needed (HTML date input format)
        if "/" in answer:
            parts = answer.split("/")
            if len(parts) == 3:
                if len(parts[0]) == 4:  # Already YYYY/MM/DD
                    answer = f"{parts[0]}-{parts[1]}-{parts[2]}"
                else:  # DD/MM/YYYY
                    answer = f"{parts[2]}-{parts[1]}-{parts[0]}"
        date_input.fill(answer)
        print(f"    ✓ Filled date: {answer}")
    else:
        print("    ✗ Could not find date input.")


def _fill_time(card, answer: str):
    """Fill a time input. Expected format: HH:MM (24-hour)."""
    time_input = card.query_selector(SEL_TIME_INPUT)
    if time_input:
        time_input.fill(answer)
        print(f"    ✓ Filled time: {answer}")
    else:
        print("    ✗ Could not find time input.")


def fill_form(page: Page, questions: list[dict], answers: list[dict]) -> dict:
    """
    Fill all approved answers into the form, going page by page.
    Does NOT submit the form — leaves the browser open on the final page.

    Args:
        page: The Playwright Page with the form already open.
        questions: List of question dicts from form_reader.py
        answers: List of answer dicts from ai_brain.py (after user review)

    Returns:
        A summary dict: {filled: [...], skipped: [...], errors: [...]}
    """
    # Build a quick lookup: question id → answer
    answer_map = {ans["id"]: ans for ans in answers}

    # Build a lookup: question id → question metadata
    question_map = {q["id"]: q for q in questions}

    # Organize questions by page
    pages = {}
    for q in questions:
        p = q.get("page", 1)
        pages.setdefault(p, []).append(q)

    filled = []
    skipped = []
    errors = []

    print("\n[FormFiller] Starting to fill the form...")

    for page_num in sorted(pages.keys()):
        page_questions = pages[page_num]
        print(f"\n[FormFiller] Filling page {page_num} ({len(page_questions)} questions)...")

        # Get all question cards currently visible on the page
        time.sleep(1)
        cards = page.query_selector_all(SEL_QUESTION_CONTAINER)

        # Try to match cards to questions by text
        filled_on_page = 0
        for card in cards:
            card_text = _get_question_text_from_card(card)
            if not card_text:
                continue

            # Find the matching question by text similarity
            matched_question = None
            for q in page_questions:
                # Simple check: does the card text start with or contain the question text?
                if (q["question"].strip()[:50].lower() in card_text.lower() or
                        card_text.lower()[:50] in q["question"].lower()):
                    matched_question = q
                    break

            if not matched_question:
                # Could not match this card to a known question — skip it
                continue

            q_id = matched_question["id"]
            q_type = matched_question["type"]

            print(f"\n  Q{q_id}: [{q_type}] {matched_question['question'][:60]}")

            # Get the answer for this question
            answer_data = answer_map.get(q_id)

            if not answer_data:
                skipped.append({"id": q_id, "reason": "No answer provided"})
                print(f"    ⚠ Skipped: No answer found for Q{q_id}")
                continue

            answer_value = answer_data.get("answer", "")

            # Skip questions with empty answers (needs_input)
            if answer_value == "" or answer_value is None:
                skipped.append({"id": q_id, "reason": f"Empty answer (status: {answer_data.get('status')})"})
                print(f"    ⚠ Skipped: Empty answer ({answer_data.get('status')})")
                continue

            # Fill the answer based on question type
            try:
                if q_type == "short_text":
                    _fill_short_text(card, str(answer_value))
                elif q_type == "paragraph":
                    _fill_paragraph(card, str(answer_value))
                elif q_type == "multiple_choice":
                    _fill_multiple_choice(card, str(answer_value))
                elif q_type == "checkbox":
                    # Answer can be a list or a comma-separated string
                    if isinstance(answer_value, list):
                        _fill_checkbox(card, answer_value)
                    else:
                        _fill_checkbox(card, [answer_value])
                elif q_type == "dropdown":
                    _fill_dropdown(card, str(answer_value), page)
                elif q_type == "linear_scale":
                    _fill_linear_scale(card, str(answer_value))
                elif q_type == "date":
                    _fill_date(card, str(answer_value))
                elif q_type == "time":
                    _fill_time(card, str(answer_value))
                else:
                    skipped.append({"id": q_id, "reason": f"Unsupported type: {q_type}"})
                    print(f"    ⚠ Skipped: Unsupported type '{q_type}'")
                    continue

                filled.append({"id": q_id, "answer": answer_value})
                filled_on_page += 1
                time.sleep(0.3)  # Small delay between fills (feels more natural)

            except Exception as e:
                error_msg = f"Error filling Q{q_id}: {e}"
                errors.append({"id": q_id, "error": str(e)})
                print(f"    ✗ {error_msg}")

        print(f"[FormFiller] Filled {filled_on_page}/{len(page_questions)} questions on page {page_num}.")

        # Check if there's a Next button to go to the next page
        if page_num < max(pages.keys()):
            next_button = page.query_selector(SEL_NEXT_BUTTON)
            if next_button:
                print(f"[FormFiller] Clicking Next to go to page {page_num + 1}...")
                next_button.click()
                time.sleep(2)  # Wait for next page to load
            else:
                print(f"[FormFiller] Warning: Expected a Next button but didn't find one on page {page_num}.")

    # Print summary
    print("\n" + "═" * 60)
    print(f"[FormFiller] DONE! Summary:")
    print(f"  ✓ Filled:   {len(filled)} questions")
    print(f"  ⚠ Skipped:  {len(skipped)} questions")
    print(f"  ✗ Errors:   {len(errors)} questions")
    print("═" * 60)
    print("\n[FormFiller] ⚠️  The browser is open. REVIEW all answers before submitting!")
    print("[FormFiller] Call submit_form() only when you're ready.\n")

    return {"filled": filled, "skipped": skipped, "errors": errors}


def submit_form(page: Page) -> bool:
    """
    Submit the form — ONLY call this after you have reviewed everything.
    This clicks the Submit button once.

    Args:
        page: The Playwright Page with the filled form.

    Returns:
        True if submitted, False if the submit button was not found.
    """
    print("\n[FormFiller] 🚨 Submitting the form...")

    submit_button = page.query_selector(SEL_SUBMIT_BUTTON)
    if not submit_button:
        print("[FormFiller] ✗ Submit button not found. Are you on the last page?")
        return False

    submit_button.click()
    time.sleep(2)  # Wait for the confirmation page

    print("[FormFiller] ✓ Form submitted! Check the browser for a confirmation message.")
    return True
