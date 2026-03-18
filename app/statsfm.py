"""stats.fm API client for enriched listening history data."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stats.fm/api/v1"
_TIMEOUT = 10.0


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def validate_token(token: str) -> Optional[dict]:
    """Return the stats.fm user object or None if the token is invalid."""
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(f"{BASE_URL}/me", headers=_headers(token))
        if r.status_code == 200:
            data = r.json()
            return data.get("item") or data
        return None
    except Exception as exc:
        logger.warning("stats.fm validate_token error: %s", exc)
        return None


def get_top_tracks(
    token: str,
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
                headers=_headers(token),
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
                # Normalise to URI form
                if not sid.startswith("spotify:track:"):
                    sid = f"spotify:track:{sid}"
                uris.append(sid)
        return uris
    except Exception as exc:
        logger.warning("stats.fm get_top_tracks error: %s", exc)
        return []
