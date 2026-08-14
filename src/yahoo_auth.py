"""Yahoo OAuth2 — one-time authorization, then automatic refresh.

Yahoo's OAuth2 is standard authorization-code flow. The only awkward part is the
redirect: we register https://localhost:8000/callback but nothing serves it during
the initial handshake, so the browser shows an error page. The authorization code
is still in the address bar — you copy it out and paste it in. One time only.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
from pathlib import Path

import httpx

from .config import TOKEN_PATH, Settings

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Refresh this many seconds before actual expiry, so a poll never races the clock.
REFRESH_MARGIN_SECONDS = 120


def build_authorize_url(settings: Settings) -> str:
    params = {
        "client_id": settings.yahoo_client_id,
        "redirect_uri": settings.yahoo_redirect_uri,
        "response_type": "code",
        "language": "en-us",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _basic_auth_header(settings: Settings) -> str:
    raw = f"{settings.yahoo_client_id}:{settings.yahoo_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def exchange_code_for_token(settings: Settings, code: str) -> dict:
    """Trade the one-time authorization code for access + refresh tokens."""
    resp = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(settings),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "redirect_uri": settings.yahoo_redirect_uri,
            "code": code,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    token = resp.json()
    token["obtained_at"] = time.time()
    save_token(token)
    return token


def refresh_token(settings: Settings, token: dict) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(settings),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "redirect_uri": settings.yahoo_redirect_uri,
            "refresh_token": token["refresh_token"],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    new_token = resp.json()
    # Yahoo does not always echo the refresh token back; keep the old one if absent.
    new_token.setdefault("refresh_token", token["refresh_token"])
    new_token["obtained_at"] = time.time()
    save_token(new_token)
    return new_token


def save_token(token: dict) -> None:
    TOKEN_PATH.write_text(json.dumps(token, indent=2), encoding="utf-8")
    # Tokens are credentials — keep them owner-readable only.
    Path(TOKEN_PATH).chmod(0o600)


def load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def is_expired(token: dict) -> bool:
    obtained = token.get("obtained_at", 0)
    expires_in = token.get("expires_in", 3600)
    return time.time() >= (obtained + expires_in - REFRESH_MARGIN_SECONDS)


def get_valid_access_token(settings: Settings) -> str:
    """Return a usable access token, refreshing if needed.

    Raises RuntimeError if no token exists — run scripts/authorize.py first.
    """
    token = load_token()
    if token is None:
        raise RuntimeError(
            "No Yahoo token found. Run: python -m scripts.authorize"
        )
    if is_expired(token):
        token = refresh_token(settings, token)
    return token["access_token"]
