"""One-time Yahoo OAuth authorization.

Run:  python -m scripts.authorize

The browser will land on https://localhost:8000/callback and show an error page —
nothing is serving that yet, which is expected and fine. The authorization code is
in the address bar as ?code=... Copy it and paste it here.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings  # noqa: E402
from src.yahoo_auth import build_authorize_url, exchange_code_for_token  # noqa: E402


def main() -> int:
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

    url = build_authorize_url(settings)
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

    # Tolerate a pasted full URL rather than just the code.
    if "code=" in code:
        code = code.split("code=", 1)[1].split("&", 1)[0]

    try:
        exchange_code_for_token(settings, code)
    except Exception as exc:  # noqa: BLE001
        print(f"\nToken exchange failed: {exc}")
        print("Common causes: the code expired (they are short-lived — retry), or the")
        print("redirect URI in .env does not exactly match the one registered with Yahoo.")
        return 1

    print("\nAuthorized. Token saved to yahoo_token.json (gitignored, owner-read only).")
    print("It refreshes automatically from here on.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
