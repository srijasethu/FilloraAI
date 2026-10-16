"""
ai_brain.py
-----------
ALL calls to the Gemini API live here — and ONLY here.

This design means if you ever want to switch from Gemini to another AI provider
(e.g., OpenAI, Claude), you only need to edit this one file.

Key functions:
  - answer_questions(questions, profile) → list of answer dicts
  - regenerate_answer(question, profile, instruction) → single answer dict

Each answer dict has:
  {
    "id": <question id>,
    "answer": <the answer text or list>,
    "status": "confident" | "needs_review" | "needs_input",
    "reason": <brief explanation of why this status was chosen>
  }
"""

import json
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── Gemini client setup ───────────────────────────────────────────────────────
from google import genai
from google.genai import types

# Read API key from environment — never hardcode it
_API_KEY = os.getenv("GEMINI_API_KEY")
if not _API_KEY:
    raise EnvironmentError(
        "[AiBrain] GEMINI_API_KEY not found in environment. "
        "Please add it to backend/.env"
    )

# Read model name from environment, default to gemini-3.5-flash-lite
_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Initialize the Gemini client
_client = genai.Client(api_key=_API_KEY)

# ── Retry settings for rate limit errors (important on free tier) ─────────────
MAX_RETRIES = 4          # How many times to retry on rate limit
INITIAL_WAIT = 5         # Seconds to wait before first retry
BACKOFF_FACTOR = 2       # Each retry waits twice as long

# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

def _build_main_prompt(questions: list[dict], profile: dict) -> str:
    """
    Build the prompt that sends all questions + profile to Gemini in one call.
    Clear rules are given so the AI knows exactly what to do for each question type.
    """

    profile_json = json.dumps(profile, indent=2)
    questions_json = json.dumps(questions, indent=2)

    prompt = f"""
You are FilloraAI — an assistant that fills Google Forms on behalf of a college student.

## YOUR PROFILE (the student's personal data)
{profile_json}

## QUESTIONS FROM THE FORM
{questions_json}

## YOUR TASK
Return a JSON array where each element corresponds to one question. 
The array must have exactly as many items as there are questions above.

Each item must follow this exact structure:
{{
  "id": <same id as the question>,
  "answer": <the answer — see rules below>,
  "status": "<confident | needs_review | needs_input>",
  "reason": "<one short sentence explaining your choice>"
}}

## STATUS RULES — READ CAREFULLY

**"confident"** — Use this when:
- The answer is a clear fact found in the profile (name, roll no, department, year, phone, etc.)
- For multiple_choice or dropdown: one option clearly matches the profile data
- For checkbox: one or more options clearly apply to the student
- The answer field should be the exact answer string (or a list for checkboxes).

**"needs_review"** — Use this for descriptive / opinion questions (paragraph or short text asking for reasons, experience, opinions, introductions, motivations, etc.). Rules:
- Write a natural, genuine-sounding draft in a real college student's voice.
- DO NOT sound like a robot or use corporate language.
- Study the "writing_samples" in the profile and imitate that tone and style.
- Match the length hinted by the form (if hint says "2-3 sentences", write 2-3 sentences; if it says "100 words", stay under 100 words).
- If no length hint is given, write 3-5 sentences — enough to be useful but not overwhelming.
- This is just a draft; the student will review and may edit it before submitting.

**"needs_input"** — Use this when:
- The profile does not contain the required information (e.g., consent, signature, declaration, specific personal info not provided).
- NEVER invent facts that aren't in the profile. Leave the answer as an empty string "".
- Examples: "I agree to the terms", signature fields, ID proof numbers not in profile.

## ANSWER FORMAT RULES

- For **multiple_choice / dropdown**: answer must be EXACTLY one string from the options list, copied verbatim. Do not add punctuation or change capitalization.
- For **checkbox**: answer must be a JSON array of strings, each copied verbatim from the options list.
- For **linear_scale**: answer must be the number (as a string, e.g., "4") that best fits the student's profile.
- For **short_text / paragraph**: answer is a plain string.
- For **date**: answer in DD/MM/YYYY format unless the question specifies otherwise.
- For **time**: answer in HH:MM format (24-hour).
- If you're using **needs_input**, set answer to "".

## IMPORTANT
- Return ONLY a valid JSON array. No markdown, no explanation text, no code fences.
- The array length must match the number of questions exactly.
- Do not make up personal facts that aren't in the profile.
""".strip()

    return prompt


def _build_regenerate_prompt(question: dict, profile: dict, instruction: str) -> str:
    """
    Build a prompt for regenerating a single answer with specific instructions
    (e.g., "make it shorter", "use a more formal tone", "mention internship experience").
    """
    profile_json = json.dumps(profile, indent=2)
    question_json = json.dumps(question, indent=2)

    prompt = f"""
You are FilloraAI. A student is reviewing a Google Form answer and wants you to rewrite it.

## STUDENT PROFILE
{profile_json}

## THE QUESTION
{question_json}

## INSTRUCTION FROM STUDENT
"{instruction}"

## YOUR TASK
Rewrite the answer for this question following the instruction above.
Return a single JSON object (not an array):
{{
  "id": {question.get("id", 0)},
  "answer": "<rewritten answer>",
  "status": "<confident | needs_review | needs_input>",
  "reason": "<one sentence explaining what you changed>"
}}

Rules:
- Match the student's voice from the profile's writing_samples.
- Follow the form's hint about length if present.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
""".strip()

    return prompt


# ══════════════════════════════════════════════════════════════════════════════
#  CORE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini_with_retry(prompt: str) -> str:
    """
    Call Gemini with automatic retry on rate limit errors (HTTP 429).
    Uses exponential backoff: waits 5s, then 10s, then 20s, then 40s.

    Args:
        prompt: The full prompt string to send.

    Returns:
        The raw text response from Gemini.

    Raises:
        RuntimeError if all retries are exhausted.
    """
    wait = INITIAL_WAIT

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,   # Some creativity for opinion answers
                    # Ask Gemini to return JSON
                    response_mime_type="application/json",
                ),
            )
            return response.text

        except Exception as e:
            error_str = str(e).lower()

            # Check if this is a rate limit error
            if "429" in error_str or "quota" in error_str or "rate" in error_str:
                if attempt < MAX_RETRIES:
                    print(f"[AiBrain] Rate limit hit. Waiting {wait}s before retry {attempt}/{MAX_RETRIES}...")
                    time.sleep(wait)
                    wait *= BACKOFF_FACTOR
                else:
                    raise RuntimeError(
                        f"[AiBrain] Gemini rate limit exceeded after {MAX_RETRIES} retries. "
                        "Please wait a minute and try again."
                    )
            else:
                # Not a rate limit error — don't retry
                raise RuntimeError(f"[AiBrain] Gemini API error: {e}")

    raise RuntimeError("[AiBrain] Unexpected: ran out of retries without raising.")


def answer_questions(questions: list[dict], profile: dict) -> list[dict]:
    """
    Send all questions + student profile to Gemini in ONE API call.
    Returns a list of answer dicts, one per question.

    Args:
        questions: List of question dicts from form_reader.py
        profile: The student's data from profile.json

    Returns:
        List of dicts: [{id, answer, status, reason}, ...]
    """
    if not questions:
        return []

    print(f"[AiBrain] Sending {len(questions)} questions to Gemini ({_MODEL})...")

    prompt = _build_main_prompt(questions, profile)
    raw_response = _call_gemini_with_retry(prompt)

    # Parse the JSON response
    try:
        answers = json.loads(raw_response)
    except json.JSONDecodeError as e:
        # Try to extract JSON from the response if it has extra text
        import re
        json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
        if json_match:
            try:
                answers = json.loads(json_match.group())
            except Exception:
                raise RuntimeError(
                    f"[AiBrain] Gemini returned invalid JSON. Raw response:\n{raw_response[:500]}"
                )
        else:
            raise RuntimeError(
                f"[AiBrain] Gemini returned invalid JSON: {e}\nRaw response:\n{raw_response[:500]}"
            )

    # Validate the response structure
    if not isinstance(answers, list):
        raise RuntimeError(f"[AiBrain] Expected a JSON array but got: {type(answers)}")

    print(f"[AiBrain] Got {len(answers)} answers from Gemini.")

    # Summarize what we got
    for ans in answers:
        status = ans.get("status", "unknown")
        q_id = ans.get("id", "?")
        print(f"[AiBrain]   Q{q_id}: {status} — {str(ans.get('answer', ''))[:60]}")

    return answers


def regenerate_answer(question: dict, profile: dict, instruction: str) -> dict:
    """
    Regenerate the answer for a single question with a specific instruction.
    Used when the user wants to tweak a draft (e.g., "make it shorter").

    Args:
        question: The question dict from form_reader.py
        profile: The student's data from profile.json
        instruction: What the user wants changed (e.g., "make it more formal")

    Returns:
        A single answer dict: {id, answer, status, reason}
    """
    print(f"[AiBrain] Regenerating answer for Q{question.get('id')} with instruction: '{instruction}'")

    prompt = _build_regenerate_prompt(question, profile, instruction)
    raw_response = _call_gemini_with_retry(prompt)

    try:
        answer = json.loads(raw_response)
    except json.JSONDecodeError:
        import re
        json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if json_match:
            answer = json.loads(json_match.group())
        else:
            raise RuntimeError(
                f"[AiBrain] Gemini returned invalid JSON for regeneration.\nRaw: {raw_response[:500]}"
            )

    print(f"[AiBrain] Regenerated: {answer.get('status')} — {str(answer.get('answer', ''))[:60]}")
    return answer
