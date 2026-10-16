"""
form_reader.py
--------------
Uses Playwright to open a Google Form and extract every question from every page.

Google Forms renders questions as div[role="listitem"] elements. Each contains:
  - The question text
  - Input elements that tell us the question type
  - Option labels (for MCQ, checkbox, dropdown)
  - A red asterisk (*) if the question is required
  - An optional description/hint below the question text

This file keeps all CSS selectors in one place at the top so they're easy to update
if Google ever changes their HTML structure.
"""

import time
from playwright.sync_api import Page, BrowserContext

# ══════════════════════════════════════════════════════════════════════════════
#  SELECTORS — update these if Google Forms changes its HTML structure
# ══════════════════════════════════════════════════════════════════════════════

# Each question is a "listitem" role div
SEL_QUESTION_CONTAINER = 'div[role="listitem"]'

# Question title text — the main heading inside a question card
SEL_QUESTION_TITLE = '[data-params], .M7eMe, .HoXoMd, [role="heading"]'

# Alternative simpler title selector (Google Forms uses these class names)
SEL_TITLE_SIMPLE = '.M7eMe'          # Primary question text
SEL_TITLE_FALLBACK = '.HoXoMd'       # Sometimes the title is here

# Hint/description text below the question
SEL_HINT = '.gubaDc, .cBGGJ'

# Required marker — Google shows a red asterisk for required questions
SEL_REQUIRED = '[aria-label*="required"], [aria-required="true"]'

# Input type selectors — used to detect what kind of question this is
SEL_SHORT_TEXT = 'input[type="text"]'
SEL_PARAGRAPH  = 'textarea'
SEL_RADIO      = 'div[role="radio"]'     # Multiple choice
SEL_CHECKBOX   = 'div[role="checkbox"]'  # Checkboxes
SEL_LISTBOX    = 'div[role="listbox"]'   # Dropdown
SEL_OPTION_ITEM = 'div[role="option"]'   # Options inside a dropdown

# "Next" button to go to the next page of a multi-page form
SEL_NEXT_BUTTON = '[jsname="OCpkoe"], .Y5sE8d'

# The submit button text (we detect this to know we're on the last page)
SEL_SUBMIT_BUTTON = '[jsname="M2UYVd"], .uArJ5e.Y5sE8d'

# Linear scale — has role="radio" but also has scale-specific labels
SEL_SCALE_ROW = 'div[role="radiogroup"]'
SEL_SCALE_LABEL = '.eLNT1d'   # Low/high labels like "1 = Not at all, 5 = Very much"

# ══════════════════════════════════════════════════════════════════════════════


def _get_question_text(card) -> str:
    """Extract the main question text from a question card element."""
    # Try the primary selector first
    title_el = card.query_selector(SEL_TITLE_SIMPLE)
    if title_el:
        return title_el.inner_text().strip()
    # Fall back to the other selector
    title_el = card.query_selector(SEL_TITLE_FALLBACK)
    if title_el:
        return title_el.inner_text().strip()
    # Last resort: grab all text and take the first meaningful line
    full_text = card.inner_text().strip()
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    return lines[0] if lines else "Unknown question"


def _get_hint(card) -> str:
    """Extract the hint/description text (e.g. 'Max 100 words') from a question card."""
    hint_el = card.query_selector(SEL_HINT)
    if hint_el:
        return hint_el.inner_text().strip()
    return ""


def _is_required(card) -> bool:
    """Check if a question is marked as required (has a red asterisk)."""
    # Google puts aria-required on the input, or has an asterisk in aria-label
    req_el = card.query_selector(SEL_REQUIRED)
    if req_el:
        return True
    # Some versions put a literal asterisk (*) in the question text
    text = card.inner_text()
    return "* " in text or text.endswith("*")


def _detect_type_and_options(card) -> tuple[str, list[str]]:
    """
    Detect the question type and extract options if applicable.

    Returns:
        A tuple of (question_type_string, list_of_options)
        - question_type is one of: short_text, paragraph, multiple_choice,
          checkbox, dropdown, linear_scale, date, time, file_upload
    """
    # ── File upload ────────────────────────────────────────────────────────
    # Google Forms shows a file upload button with specific text
    if card.query_selector('input[type="file"]') or "Upload" in card.inner_text():
        # We can't fill file upload questions programmatically
        return "file_upload", []

    # ── Date input ─────────────────────────────────────────────────────────
    if card.query_selector('input[type="date"]'):
        return "date", []

    # ── Time input ─────────────────────────────────────────────────────────
    if card.query_selector('input[type="time"]'):
        return "time", []

    # ── Dropdown (listbox) ─────────────────────────────────────────────────
    listbox = card.query_selector(SEL_LISTBOX)
    if listbox:
        # Click to open the dropdown and collect all options
        try:
            listbox.click()
            time.sleep(0.5)  # Wait for dropdown to open
            # Options appear in the page (not inside the card) after clicking
            page = card.owner_frame().page if hasattr(card, "owner_frame") else None
        except Exception:
            pass

        # Try to get options from the card itself (before clicking)
        option_els = card.query_selector_all(SEL_OPTION_ITEM)
        options = [opt.inner_text().strip() for opt in option_els if opt.inner_text().strip()]
        return "dropdown", options

    # ── Checkbox (multi-select) ────────────────────────────────────────────
    checkboxes = card.query_selector_all(SEL_CHECKBOX)
    if checkboxes:
        options = []
        for cb in checkboxes:
            # The label is usually a sibling or parent span
            label = cb.get_attribute("aria-label") or cb.inner_text().strip()
            if label and label not in ("__other_option_", "Other"):
                options.append(label)
        return "checkbox", options

    # ── Multiple choice (radio) ────────────────────────────────────────────
    radios = card.query_selector_all(SEL_RADIO)
    if radios:
        # Check if this is actually a linear scale (radio buttons in a row)
        scale_row = card.query_selector(SEL_SCALE_ROW)
        if scale_row:
            # Collect the scale range labels and numbers
            all_text = card.inner_text()
            return "linear_scale", [all_text.strip()]  # Return raw text for AI to interpret

        options = []
        for radio in radios:
            label = radio.get_attribute("aria-label") or radio.inner_text().strip()
            if label and label != "__other_option_":
                options.append(label)
        return "multiple_choice", options

    # ── Paragraph (multi-line text area) ──────────────────────────────────
    if card.query_selector(SEL_PARAGRAPH):
        return "paragraph", []

    # ── Short text (single-line input) ────────────────────────────────────
    if card.query_selector(SEL_SHORT_TEXT):
        return "short_text", []

    # ── Unknown ────────────────────────────────────────────────────────────
    return "unknown", []


def extract_questions_from_page(page: Page, page_number: int, question_id_start: int) -> list[dict]:
    """
    Extract all questions visible on the current page.

    Args:
        page: The Playwright Page object (already at the form URL).
        page_number: Which page of the form we're on (1-indexed).
        question_id_start: What number to start the question IDs from.

    Returns:
        A list of question dicts with keys: id, page, question, type, options, required, hint.
    """
    # Wait for questions to appear
    try:
        page.wait_for_selector(SEL_QUESTION_CONTAINER, timeout=10000)
    except Exception:
        print(f"[FormReader] No questions found on page {page_number}.")
        return []

    cards = page.query_selector_all(SEL_QUESTION_CONTAINER)
    questions = []

    for i, card in enumerate(cards):
        try:
            question_text = _get_question_text(card)
            hint = _get_hint(card)
            required = _is_required(card)
            q_type, options = _detect_type_and_options(card)

            # Skip file upload questions — we can't fill them
            if q_type == "file_upload":
                print(f"[FormReader] Skipping file upload question: '{question_text}'")
                continue

            question_dict = {
                "id": question_id_start + len(questions),
                "page": page_number,
                "question": question_text,
                "type": q_type,
                "options": options,
                "required": required,
                "hint": hint,
            }
            questions.append(question_dict)
            print(f"[FormReader]   Q{question_dict['id']}: [{q_type}] {question_text[:60]}...")

        except Exception as e:
            print(f"[FormReader] Warning: Could not parse question {i} on page {page_number}: {e}")
            continue

    return questions


def read_form(context: BrowserContext, form_url: str) -> list[dict]:
    """
    Open the Google Form and extract all questions across all pages.

    Args:
        context: A Playwright BrowserContext (with the user's Google session loaded).
        form_url: The full URL of the Google Form.

    Returns:
        A flat list of all questions from all pages.
    """
    print(f"\n[FormReader] Opening form: {form_url}")
    page = context.new_page()

    try:
        page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)  # Let the page fully render (Google Forms uses a lot of JS)
    except Exception as e:
        raise RuntimeError(f"[FormReader] Could not open form URL: {e}")

    all_questions = []
    page_number = 1

    while True:
        print(f"\n[FormReader] Reading page {page_number}...")

        # Extract questions from the current page
        page_questions = extract_questions_from_page(page, page_number, len(all_questions))
        all_questions.extend(page_questions)

        # Check if there's a "Next" button — if yes, go to the next page
        next_button = page.query_selector(SEL_NEXT_BUTTON)

        # Also check that it's not actually the Submit button
        submit_button = page.query_selector(SEL_SUBMIT_BUTTON)

        if next_button and not submit_button:
            print(f"[FormReader] Moving to page {page_number + 1}...")
            next_button.click()
            time.sleep(2)  # Wait for the next page to load
            page_number += 1
        else:
            # No more pages — we're done
            print(f"\n[FormReader] Finished reading form. Total pages: {page_number}, Total questions: {len(all_questions)}")
            break

    # Keep the page open — form_filler.py will reuse it to fill answers
    # Store the page reference on the context for later use
    context._fillora_page = page

    return all_questions
