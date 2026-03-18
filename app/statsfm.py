"""stats.fm API client – public endpoints, no token required."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stats.fm/api/v1"
_TIMEOUT = 10.0
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; spoti-daily-drive/1.0)",
    "Accept": "application/json",
}


def resolve_username(username: str) -> Optional[dict]:
    """Resolve a stats.fm profile name to a customId.

    Tries direct lookup first, then falls back to the v1 search API.
    Returns {"customId": "...", "displayName": "..."} or None.
    """
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            # Step 1: direct lookup (works when username IS the customId)
            r = client.get(f"{BASE_URL}/users/{username}")
            logger.info("stats.fm direct lookup %s → %s", username, r.status_code)
            if r.status_code == 200:
                body = r.json()
                data = body.get("item") or body
                custom_id = data.get("customId") or username
                display_name = data.get("displayName") or username
                return {"customId": custom_id, "displayName": display_name}
            else:
                logger.warning("stats.fm direct lookup failed: %s %s", r.status_code, r.text[:200])

            # Step 2: search API fallback (v1 endpoint)
            r = client.get(
                f"{BASE_URL}/search",
                params={"query": username, "type": "user"},
            )
            logger.info("stats.fm search %s → %s", username, r.status_code)
            if r.status_code == 200:
                body = r.json()
                # Response can be {"items": {"users": [...]}} or {"items": [...]}
                items = body.get("items", {})
                users = items.get("users", []) if isinstance(items, dict) else items
                logger.info("stats.fm search returned %d users", len(users))
                if users:
                    u = users[0]
                    return {
                        "customId": u.get("customId") or u.get("id") or username,
                        "displayName": u.get("displayName") or username,
                    }
            else:
                logger.warning("stats.fm search failed: %s %s", r.status_code, r.text[:200])
        return None
    except Exception as exc:
        logger.warning("stats.fm resolve_username error: %s", exc)
        return None


def validate_user_id(user_id: str) -> Optional[dict]:
    """Return a minimal user dict if the user_id is valid, else None."""
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
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
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
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
