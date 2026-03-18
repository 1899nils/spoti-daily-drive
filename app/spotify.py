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
    """Return recommended track URIs.

    The /recommendations endpoint was deprecated for new apps in November 2024.
    Workaround: fetch top artists, then search for tracks by those artists.
    """
    if not seed_uris or limit <= 0:
        return []

    # Get top artists for better seed diversity
    try:
        top_artists_result = sp.current_user_top_artists(limit=5, time_range="medium_term")
        artist_names = [a["name"] for a in top_artists_result["items"]]
        genres = list({g for a in top_artists_result["items"] for g in a.get("genres", [])})[:3]
    except Exception:
        artist_names = []
        genres = []

    collected: list[str] = []
    seen_ids = {uri.split(":")[-1] for uri in seed_uris}

    # Search by top artists
    for artist in artist_names[:3]:
        if len(collected) >= limit:
            break
        try:
            results = sp.search(q=f'artist:"{artist}"', type="track", limit=10, market="from_token")
            for track in results["tracks"]["items"]:
                if track["id"] not in seen_ids and len(collected) < limit:
                    seen_ids.add(track["id"])
                    collected.append(track["uri"])
        except Exception:
            continue

    # Fill remaining via genre search
    for genre in genres:
        if len(collected) >= limit:
            break
        try:
            results = sp.search(q=f"genre:{genre}", type="track", limit=10, market="from_token")
            for track in results["tracks"]["items"]:
                if track["id"] not in seen_ids and len(collected) < limit:
                    seen_ids.add(track["id"])
                    collected.append(track["uri"])
        except Exception:
            continue

    random.shuffle(collected)
    return collected[:limit]


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

    # Create new playlist via /me/playlists (user-specific endpoint removed Feb 2026)
    pl = sp.user_playlist_create(sp.me()["id"], name, public=False, description="Deine personalisierte Daily Drive Playlist — automatisch aktualisiert.")
    return pl["id"]


def replace_playlist_tracks(sp: spotipy.Spotify, playlist_id: str, uris: list[str]) -> None:
    """Replace all tracks in the playlist. Handles Spotify's 100-item limit."""
    # Replace first 100
    sp.playlist_replace_items(playlist_id, uris[:100])
    # Add remaining in chunks
    for i in range(100, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i:i + 100])
