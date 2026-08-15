"""One-time Yahoo OAuth authorization.

Three ways to run it, so it works whether or not you have an interactive terminal:

    python -m scripts.authorize              interactive prompt
    python -m scripts.authorize --url        print the authorize URL and exit
    python -m scripts.authorize --code XYZ   exchange a code you already have

The two-step (--url then --code) form exists because a remote/automated session
can't type into an input() prompt.

The browser will land on https://localhost:8000/callback and show an error page —
nothing is serving that yet, which is expected and fine. The authorization code is
in the address bar as ?code=...
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings  # noqa: E402
from src.yahoo_auth import build_authorize_url, exchange_code_for_token  # noqa: E402


def _clean_code(raw: str) -> str:
    """Accept either a bare code or the whole redirected URL."""
    code = raw.strip()
    if "code=" in code:
        code = code.split("code=", 1)[1].split("&", 1)[0]
    return code


def _finish(settings: Settings, code: str) -> int:
    try:
        exchange_code_for_token(settings, _clean_code(code))
    except Exception as exc:  # noqa: BLE001
        print(f"\nToken exchange failed: {exc}")
        print("Common causes: the code expired (they are short-lived — get a fresh")
        print("one), or YAHOO_REDIRECT_URI does not exactly match the value registered")
        print("with Yahoo, character for character.")
        return 1
    print("\nAuthorized. Token saved to yahoo_token.json (gitignored, owner-read only).")
    print("It refreshes automatically from here on.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Yahoo OAuth authorization")
    parser.add_argument("--url", action="store_true", help="print the authorize URL and exit")
    parser.add_argument("--code", help="authorization code (or the full redirected URL)")
    args = parser.parse_args()

    settings = Settings.load()

    missing = [
        name
        for name, value in (
            ("YAHOO_CLIENT_ID", settings.yahoo_client_id),
            ("YAHOO_CLIENT_SECRET", settings.yahoo_client_secret),
        )
        if not value
    ]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in the Yahoo app credentials first.")
        return 1

    # Step 2 of the two-step flow: we already have a code.
    if args.code:
        return _finish(settings, args.code)

    url = build_authorize_url(settings)

    # Step 1 of the two-step flow: just emit the URL.
    if args.url:
        print(url)
        return 0

    print("\nOpening Yahoo authorization page:\n")
    print(f"  {url}\n")
    print("If the browser does not open, paste that URL in yourself.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("After approving, your browser will fail to load the callback page.")
    print("That is expected — copy the 'code' value out of the address bar.\n")

    code = input("Paste the code here: ").strip()
    if not code:
        print("No code entered. Aborted.")
        return 1

    return _finish(settings, code)


if __name__ == "__main__":
    raise SystemExit(main())
