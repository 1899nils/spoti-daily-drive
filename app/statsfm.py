"""stats.fm API client – public endpoints, no token required."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stats.fm/api/v1"
_SEARCH_URL = "https://api.stats.fm/api/search"
_TIMEOUT = 10.0


def resolve_username(username: str) -> Optional[dict]:
    """Resolve a stats.fm profile name to a customId.

    Tries direct lookup first, then falls back to the search API.
    Returns {"customId": "...", "displayName": "..."} or None.
    """
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            # Step 1: direct lookup (works when username IS the customId)
            r = client.get(f"{BASE_URL}/users/{username}")
            if r.status_code == 200:
                data = r.json().get("item", r.json())
                custom_id = data.get("customId") or username
                display_name = data.get("displayName") or username
                return {"customId": custom_id, "displayName": display_name}

            # Step 2: search API fallback
            r = client.get(_SEARCH_URL, params={"query": username, "type": "user"})
            if r.status_code == 200:
                users = r.json().get("items", {}).get("users", [])
                if users:
                    u = users[0]
                    return {
                        "customId": u.get("customId") or u.get("id") or username,
                        "displayName": u.get("displayName") or username,
                    }
        return None
    except Exception as exc:
        logger.warning("stats.fm resolve_username error: %s", exc)
        return None


def validate_user_id(user_id: str) -> Optional[dict]:
    """Return a minimal user dict if the user_id is valid, else None."""
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(
                f"{BASE_URL}/users/{user_id}/top/tracks",
                params={"range": "weeks", "limit": 1},
            )
        if r.status_code == 200:
            return {"id": user_id}
        return None
    except Exception as exc:
        logger.warning("stats.fm validate_user_id error: %s", exc)
        return None


def get_top_tracks(
    user_id: str,
    range: str = "months",
    limit: int = 50,
) -> list[str]:
    """Return a list of Spotify track URIs sorted by stream count.

    range: 'weeks' | 'months' | 'lifetime'
    """
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(
                f"{BASE_URL}/users/{user_id}/top/tracks",
                params={"range": range, "limit": limit},
            )
        if r.status_code != 200:
            logger.warning("stats.fm top/tracks returned %s", r.status_code)
            return []
        items = r.json().get("items", [])
        uris: list[str] = []
        for item in items:
            track = item.get("track", {})
            ext = track.get("externalIds", {})
            spotify_ids = ext.get("spotify", [])
            if spotify_ids:
                sid = spotify_ids[0]
                if not sid.startswith("spotify:track:"):
                    sid = f"spotify:track:{sid}"
                uris.append(sid)
        return uris
    except Exception as exc:
        logger.warning("stats.fm get_top_tracks error: %s", exc)
        return []
