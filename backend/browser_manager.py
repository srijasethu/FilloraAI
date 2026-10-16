"""
browser_manager.py
------------------
Manages one Playwright browser profile per Google account.

Each account gets its own folder inside backend/browser_profiles/<account_name>/
This means login cookies, saved sessions, etc. are stored permanently per account.

Usage:
  - Call login_account("myaccount") once to open a browser for manual Google sign-in.
  - After you sign in, close the browser. The session is saved.
  - Future calls reuse the same profile so you stay logged in.
"""

import os
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext

# ── Where browser profiles are stored ────────────────────────────────────────
# Each account gets its own sub-folder: browser_profiles/<account_name>/
PROFILES_DIR = Path(__file__).parent / "browser_profiles"


def _get_profile_path(account_name: str) -> Path:
    """Return the directory path for a given account's browser profile."""
    # Sanitize the name so it's safe to use as a folder name
    safe_name = "".join(c for c in account_name if c.isalnum() or c in ("_", "-"))
    return PROFILES_DIR / safe_name


def list_accounts() -> list[str]:
    """
    Return a list of account names that have saved browser profiles.
    These are simply the folder names inside browser_profiles/.
    """
    if not PROFILES_DIR.exists():
        return []
    # Each sub-folder is one account
    return [folder.name for folder in PROFILES_DIR.iterdir() if folder.is_dir()]


def get_browser_context(account_name: str, playwright_instance) -> BrowserContext:
    """
    Open a persistent browser context for the given account.
    A persistent context saves cookies/login across sessions.

    Args:
        account_name: The name you gave to this Google account (e.g. "college_account")
        playwright_instance: A running Playwright instance (from sync_playwright())

    Returns:
        A Playwright BrowserContext with the account's session loaded.
    """
    profile_path = _get_profile_path(account_name)
    # Create the folder if it doesn't exist yet
    profile_path.mkdir(parents=True, exist_ok=True)

    print(f"[BrowserManager] Using profile at: {profile_path}")

    # Try to use real Chrome first (better compatibility with Google).
    # If Chrome isn't installed, fall back to Playwright's bundled Chromium.
    try:
        context = playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            channel="chrome",      # Use system Chrome
            headless=False,        # Always visible — you need to see and review the form
            args=["--start-maximized"],
            no_viewport=True,      # Let the window use its natural size
        )
        print("[BrowserManager] Launched with system Chrome.")
    except Exception:
        # Chrome not found — fall back to Playwright Chromium
        print("[BrowserManager] System Chrome not found. Using bundled Chromium.")
        context = playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )

    return context


def login_account(account_name: str):
    """
    Open a browser window and navigate to Google sign-in.
    Sign in manually — your session will be saved in the profile folder.
    Close the browser when done (or press Enter in the terminal).

    Args:
        account_name: A label for this Google account (e.g. "college_account").
    """
    print(f"\n[BrowserManager] Opening browser for account: '{account_name}'")
    print("[BrowserManager] Please sign in to Google in the browser window that opens.")
    print("[BrowserManager] Once you're signed in, come back here and press Enter to save and close.\n")

    with sync_playwright() as p:
        context = get_browser_context(account_name, p)
        page = context.new_page()

        # Navigate to Google's account page
        page.goto("https://accounts.google.com")

        # Wait for the user to finish signing in
        input("Press Enter here after you have signed in to Google... ")

        print(f"[BrowserManager] Session saved for account '{account_name}'. You won't need to sign in again.")
        context.close()
