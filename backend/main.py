"""
main.py
-------
FastAPI application — the backend server for FilloraAI.

Endpoints:
  GET  /accounts               — list saved Google accounts
  POST /accounts/login         — open browser for manual sign-in
  GET  /profile                — get the student's profile data
  PUT  /profile                — update the student's profile data
  POST /read-form              — open a form, extract questions, get AI answers
  POST /regenerate             — rewrite a single answer with a new instruction
  POST /fill-form              — fill approved answers into the open form
  POST /submit-form            — submit the form (explicit user approval required)

The browser session is kept alive in memory between read → fill → submit.
This way the same browser window (with the same login) is reused.

Run with:
  uvicorn main:app --reload
"""

import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import browser_manager
import form_reader
import form_filler
import ai_brain

# ── File paths ────────────────────────────────────────────────────────────────
BACKEND_DIR  = Path(__file__).parent
PROFILE_FILE = BACKEND_DIR / "profile.json"


# ── In-memory session state ───────────────────────────────────────────────────
# We keep one browser session alive between read → fill → submit.
# This is simple and sufficient for single-user use.
class Session:
    def __init__(self):
        self.playwright    = None   # The running Playwright instance
        self.context       = None   # The browser context (logged-in profile)
        self.page          = None   # The currently open form page
        self.questions     = []     # Extracted questions from the form
        self.answers       = []     # AI-generated answers
        self.current_url   = None   # The form URL currently open
        self.account_name  = None   # Which Google account is being used

# Global session — one active form at a time
session = Session()


# ── FastAPI app setup ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing to initialize
    yield
    # Shutdown: close the browser if it's open
    if session.context:
        try:
            session.context.close()
        except Exception:
            pass
    if session.playwright:
        try:
            session.playwright.stop()
        except Exception:
            pass

app = FastAPI(
    title="FilloraAI Backend",
    description="An AI agent that reads and fills Google Forms for you.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow requests from the frontend (Vite dev server, Create React App, and direct HTML files)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite default
        "http://localhost:3000",   # CRA default
        "null",                    # file:// origin (when opening index.html directly)
        "*",                       # Allow all for development convenience
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
#  REQUEST/RESPONSE MODELS (Pydantic)
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    account_name: str   # e.g. "college_account"

class ReadFormRequest(BaseModel):
    url: str            # Full Google Form URL
    account: str        # Account name to use

class RegenerateRequest(BaseModel):
    question: dict      # The question dict
    instruction: str    # e.g. "make it shorter and more casual"

class FillFormRequest(BaseModel):
    url: str            # Form URL (for reference/validation)
    account: str        # Account name
    answers: list       # List of answer dicts [{id, answer, status, reason}]

class ProfileUpdate(BaseModel):
    data: dict          # The updated profile data


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _load_profile() -> dict:
    """Load the student's profile from profile.json."""
    if not PROFILE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="profile.json not found. Please create it in the backend/ folder."
        )
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_profile(data: dict):
    """Save updated profile data to profile.json."""
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _ensure_browser(account_name: str):
    """
    Make sure a browser context is open for the given account.
    If the account changed or no browser is open, start a new one.
    Runs Playwright in a thread because it's synchronous.
    """
    global session

    # If we already have a context for this account, reuse it
    if session.context and session.account_name == account_name:
        return

    # Close any existing browser
    if session.context:
        try:
            session.context.close()
        except Exception:
            pass
    if session.playwright:
        try:
            session.playwright.stop()
        except Exception:
            pass

    # Start a fresh Playwright instance
    from playwright.sync_api import sync_playwright
    session.playwright = sync_playwright().start()
    session.context = browser_manager.get_browser_context(account_name, session.playwright)
    session.account_name = account_name
    print(f"[Main] Browser context opened for account: {account_name}")


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
def root():
    """Health check — confirms the server is running."""
    return {"status": "ok", "message": "FilloraAI backend is running!"}


@app.get("/accounts", tags=["Accounts"])
def get_accounts():
    """
    List all saved Google accounts (profile folders).
    Returns a list of account names you can use.
    """
    accounts = browser_manager.list_accounts()
    return {"accounts": accounts}


@app.post("/accounts/login", tags=["Accounts"])
async def login_account(request: LoginRequest):
    """
    Open a browser window so you can sign in to Google manually.
    The session is saved and reused for future requests with this account name.

    This is a blocking call — it waits for you to press Enter in the terminal.
    Run it as a background task or from the CLI for best results.
    """
    try:
        # Run the blocking login in a thread so we don't block FastAPI's event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, browser_manager.login_account, request.account_name)
        return {"message": f"Login saved for account '{request.account_name}'."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {e}")


@app.get("/profile", tags=["Profile"])
def get_profile():
    """Get the student's profile data from profile.json."""
    profile = _load_profile()
    return {"profile": profile}


@app.put("/profile", tags=["Profile"])
def update_profile(request: ProfileUpdate):
    """Update the student's profile data in profile.json."""
    _save_profile(request.data)
    return {"message": "Profile updated successfully.", "profile": request.data}


@app.post("/read-form", tags=["Form"])
async def read_form_endpoint(request: ReadFormRequest):
    """
    Main endpoint: opens the form, extracts questions, and gets AI answers.

    Steps:
      1. Open the form URL with the specified Google account.
      2. Extract all questions (across all pages).
      3. Send questions + profile to Gemini for answers.
      4. Return questions and answers (with status: confident/needs_review/needs_input).

    The browser stays open so fill-form can reuse it.
    """
    global session

    try:
        # Step 1: Open the browser with the correct account
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _ensure_browser, request.account)

        # Step 2: Read the form (runs in thread because Playwright is sync)
        def read_and_answer():
            questions = form_reader.read_form(session.context, request.url)
            profile = _load_profile()
            answers = ai_brain.answer_questions(questions, profile)
            return questions, answers

        questions, answers = await loop.run_in_executor(None, read_and_answer)

        # Save to session for fill-form to use
        session.questions    = questions
        session.answers      = answers
        session.current_url  = request.url
        # The page is stored on the context by form_reader.read_form
        if hasattr(session.context, '_fillora_page'):
            session.page = session.context._fillora_page

        return {
            "success": True,
            "total_questions": len(questions),
            "questions": questions,
            "answers": answers,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/regenerate", tags=["Form"])
async def regenerate_answer(request: RegenerateRequest):
    """
    Regenerate the answer for one question with a custom instruction.
    Example: "Make it more formal" or "Mention my internship experience".
    """
    try:
        profile = _load_profile()
        loop = asyncio.get_event_loop()
        new_answer = await loop.run_in_executor(
            None,
            ai_brain.regenerate_answer,
            request.question,
            profile,
            request.instruction
        )
        return {"success": True, "answer": new_answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/fill-form", tags=["Form"])
async def fill_form_endpoint(request: FillFormRequest):
    """
    Fill the form with the approved answers.
    The browser must already be open from /read-form.
    Does NOT submit the form — leaves it open for review.
    """
    global session

    if not session.page:
        raise HTTPException(
            status_code=400,
            detail="No form is currently open. Call /read-form first."
        )

    try:
        loop = asyncio.get_event_loop()

        def do_fill():
            return form_filler.fill_form(session.page, session.questions, request.answers)

        summary = await loop.run_in_executor(None, do_fill)

        return {
            "success": True,
            "message": "Form filled! Review the browser window, then call /submit-form to submit.",
            "summary": summary,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/submit-form", tags=["Form"])
async def submit_form_endpoint():
    """
    Submit the form — ONLY call this after you've reviewed everything in the browser.
    This is a one-way action. Make sure the answers look correct first!
    """
    global session

    if not session.page:
        raise HTTPException(
            status_code=400,
            detail="No form is open. Fill the form first."
        )

    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, form_filler.submit_form, session.page)

        if success:
            # Clear the session after submission
            session.page = None
            session.questions = []
            session.answers = []
            return {"success": True, "message": "Form submitted successfully!"}
        else:
            return {"success": False, "message": "Submit button not found. Are you on the last page?"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
