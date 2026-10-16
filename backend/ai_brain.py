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

**"confident"** — Use this ONLY when the answer is a fact explicitly stated in the profile (name, roll number, email, phone, branch, year, cgpa, dob, city, college, tshirt_size, etc.). Rules:
- The value must appear directly in profile.json. Do NOT infer or guess from indirect clues.
- Example of FORBIDDEN inference: the profile has a github link → do NOT assume "I have a laptop" or "I have coding experience". Only mark confident if the profile has an explicit field for that fact.
- For multiple_choice / dropdown: one option must match a profile field verbatim or near-verbatim.
- For checkbox: only tick options that directly correspond to an explicit profile field.
- The answer field must be the exact answer string (or a list for checkboxes).

**"needs_review"** — Use this when:
- The answer requires a descriptive / opinion response (paragraph, short_text asking for reasons, experience, motivation, introduction, etc.).
- The answer is a reasonable guess from profile data but not a verbatim fact (e.g. inferring "I have coding experience" from technical_skills list).
- Write a natural, genuine-sounding draft in a real college student's voice.
- DO NOT sound like a robot or use corporate language.
- Study the "writing_samples" in the profile and imitate that tone and style.
- Match the length hinted by the form (if hint says "2-3 sentences", write 2-3 sentences; if it says "100 words", stay under 100 words).
- If no length hint is given, write 3-5 sentences — enough to be useful but not overwhelming.
- In the "reason" field, explicitly note that the answer is a guess/draft and what assumption you made.
- This is just a draft; the student will review and may edit it before submitting.

**"needs_input"** — MANDATORY for the following; no exceptions:
- ANY question that is a declaration, consent, agreement, undertaking, terms and conditions, or signature. This includes questions containing phrases like "I hereby declare", "I hereby confirm", "I agree", "I consent", "I undertake", "terms and conditions", "declaration", "signature". Set answer to "" always.
- The profile does not contain the required information and a guess is not appropriate.
- NEVER invent facts that aren't in the profile. Leave the answer as an empty string "".

## DECLARATION / CONSENT — ABSOLUTE RULE
If a question asks the student to agree, declare, confirm, sign, or consent to ANYTHING — even if the statement seems harmless or true — you MUST return status "needs_input" and answer "". The student must make this choice themselves. This rule overrides all other rules.

## ANSWER FORMAT RULES

- For **multiple_choice / dropdown**: answer must be EXACTLY one string from the options list, copied verbatim. Do not add punctuation or change capitalization.
- For **checkbox**: answer must be a JSON array of strings, each copied verbatim from the options list.
- For **linear_scale**: answer must be the number (as a string, e.g., "4") that best fits the student's profile.
- For **short_text / paragraph**: answer is a plain string.
- For **date**: answer in DD/MM/YYYY format unless the question specifies otherwise.
- For **time**: answer in HH:MM format (24-hour).
- If you're using **needs_input**, set answer to "".

## STRICT FACTS RULE — THIS IS THE MOST IMPORTANT RULE
You are ONLY allowed to use facts that appear word-for-word in the profile above.
Specifically:
- Skills: only those listed in custom_facts.technical_skills. Do NOT add any other skill.
- Languages: only those listed in custom_facts.languages_known. Do NOT add any other language.
- Hobbies: only those listed in custom_facts.hobbies. Do NOT add any other hobby.
- Achievements: only those listed in custom_facts.achievements. Do NOT invent awards, ranks, or certifications.
- Clubs: only those listed in custom_facts.clubs. Do NOT invent memberships.
- Dietary preference: use exactly what is in custom_facts.dietary_preference or the top-level field. Do NOT guess.
- For ANY fact not found in the profile: set status to "needs_input" and answer to "".
- NEVER fill gaps with plausible-sounding invented information. An empty answer is always better than a wrong one.
- For opinion/descriptive drafts (needs_review): you may write naturally, but only mention specific facts that are in the profile.

## OUTPUT FORMAT
- Return ONLY a valid JSON array. No markdown, no explanation text, no code fences.
- The array length must match the number of questions exactly.
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
- STRICT FACTS: only mention skills, languages, hobbies, and achievements that appear explicitly in the profile. Never invent facts.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
""".strip()

    return prompt


# ══════════════════════════════════════════════════════════════════════════════
#  POST-PROCESSING SAFETY NET
# ══════════════════════════════════════════════════════════════════════════════

# Keywords that identify declaration / consent / agreement questions.
# If ANY of these appear in the question text the answer is ALWAYS needs_input.
_DECLARATION_KEYWORDS = {
    "declare", "declaration", "consent", "agree", "agreement",
    "undertaking", "undertake", "terms", "signature", "hereby",
    "confirm", "i accept", "i acknowledge",
}


def _apply_safety_net(questions: list[dict], answers: list[dict]) -> list[dict]:
    """
    Post-processing guard that runs AFTER Gemini returns.

    Rules enforced here (regardless of what Gemini said):
    1. If the question text contains any declaration/consent keyword,
       force status="needs_input" and answer="".

    This is a hard code-level guarantee — Gemini cannot override it.
    """
    # Build a quick lookup: question id → question text (lowercased)
    q_text_map = {
        q["id"]: q.get("question", "").lower()
        for q in questions
    }

    patched = []
    for ans in answers:
        q_text = q_text_map.get(ans.get("id"), "")
        is_declaration = any(kw in q_text for kw in _DECLARATION_KEYWORDS)

        if is_declaration and ans.get("status") != "needs_input":
            print(
                f"[AiBrain][SafetyNet] Q{ans.get('id')} overridden to needs_input "
                f"(declaration keyword detected in: '{q_text[:80]}...')"
            )
            patched.append({
                "id": ans["id"],
                "answer": "",
                "status": "needs_input",
                "reason": (
                    "Safety net: this question contains a declaration/consent/agreement. "
                    "The student must answer this themselves."
                ),
            })
        else:
            patched.append(ans)

    return patched


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

    # Apply code-level safety net (declaration/consent override)
    answers = _apply_safety_net(questions, answers)

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
