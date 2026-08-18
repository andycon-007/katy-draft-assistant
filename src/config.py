"""Configuration and shared paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
TOKEN_PATH = ROOT / "yahoo_token.json"  # gitignored

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    yahoo_client_id: str
    yahoo_client_secret: str
    yahoo_redirect_uri: str
    anthropic_api_key: str
    port: int
    league_id: str
    poll_interval_seconds: float
    model: str
    effort: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            yahoo_client_id=os.getenv("YAHOO_CLIENT_ID", ""),
            yahoo_client_secret=os.getenv("YAHOO_CLIENT_SECRET", ""),
            yahoo_redirect_uri=os.getenv(
                "YAHOO_REDIRECT_URI", "https://localhost:8000/callback"
            ),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            port=int(os.getenv("PORT", "8000")),
            league_id=os.getenv("YAHOO_LEAGUE_ID", "878541"),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "8")),
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5"),
            # medium, not high: measured at ~25s vs ~39s per call for materially the
            # same recommendations, and a Yahoo draft clock is only 60-90 seconds.
            effort=os.getenv("ANTHROPIC_EFFORT", "medium"),
        )

    def missing(self) -> list[str]:
        """Return names of required settings that are not populated."""
        gaps = []
        if not self.yahoo_client_id:
            gaps.append("YAHOO_CLIENT_ID")
        if not self.yahoo_client_secret:
            gaps.append("YAHOO_CLIENT_SECRET")
        if not self.anthropic_api_key:
            gaps.append("ANTHROPIC_API_KEY")
        return gaps


def load_json(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def load_rankings() -> dict:
    return load_json("rankings.json")


def load_league_settings() -> dict:
    return load_json("league_settings.json")
