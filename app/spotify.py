"""Thin wrappers around the Spotify Web API via spotipy."""
from __future__ import annotations

import random
from typing import Any

import spotipy


def get_top_tracks(sp: spotipy.Spotify, time_range: str, limit: int) -> list[str]:
    """Return a list of track URIs from the user's top tracks."""
    results = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    return [item["uri"] for item in results["items"] if item]


def get_recommendations(sp: spotipy.Spotify, seed_uris: list[str], limit: int) -> list[str]:
    """Return recommended track URIs based on seed tracks."""
    if not seed_uris:
        return []
    seeds = random.sample(seed_uris, min(5, len(seed_uris)))
    seed_ids = [uri.split(":")[-1] for uri in seeds]
    results = sp.recommendations(seed_tracks=seed_ids, limit=limit)
    return [track["uri"] for track in results["tracks"]]


def search_shows(sp: spotipy.Spotify, query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search for podcast shows and return [{id, name, publisher, image_url}]."""
    results = sp.search(q=query, type="show", limit=limit, market="from_token")
    shows = []
    for item in results["shows"]["items"]:
        image_url = item["images"][0]["url"] if item.get("images") else ""
        shows.append({
            "id": item["id"],
            "name": item["name"],
            "publisher": item["publisher"],
            "image_url": image_url,
        })
    return shows


def get_latest_episodes(sp: spotipy.Spotify, show_id: str, limit: int = 2) -> list[str]:
    """Return episode URIs for the latest episodes of a show."""
    results = sp.show_episodes(show_id, limit=limit, market="from_token")
    return [ep["uri"] for ep in results["items"] if ep and not ep.get("is_playable") is False]


def get_current_user(sp: spotipy.Spotify) -> dict[str, Any]:
    return sp.current_user()


def get_or_create_playlist(sp: spotipy.Spotify, user_id: str, name: str, existing_id: str | None) -> str:
    """Return the playlist ID, creating it if it doesn't exist."""
    if existing_id:
        try:
            sp.playlist(existing_id, fields="id")
            return existing_id
        except Exception:
            pass  # Playlist deleted or inaccessible, create a new one

    # Search existing playlists
    offset = 0
    while True:
        playlists = sp.current_user_playlists(limit=50, offset=offset)
        for pl in playlists["items"]:
            if pl["name"] == name and pl["owner"]["id"] == user_id:
                return pl["id"]
        if playlists["next"] is None:
            break
        offset += 50

    # Create new playlist
    pl = sp.user_playlist_create(user_id, name, public=False, description="Your personalized Daily Drive — auto-generated.")
    return pl["id"]


def replace_playlist_tracks(sp: spotipy.Spotify, playlist_id: str, uris: list[str]) -> None:
    """Replace all tracks in the playlist. Handles Spotify's 100-item limit."""
    # Replace first 100
    sp.playlist_replace_items(playlist_id, uris[:100])
    # Add remaining in chunks
    for i in range(100, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i:i + 100])
