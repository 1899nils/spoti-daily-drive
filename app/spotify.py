"""Thin wrappers around the Spotify Web API via spotipy."""
from __future__ import annotations

import base64
import io
import random
import urllib.request
from datetime import date
from typing import Any

import spotipy
from PIL import Image


def get_top_tracks(sp: spotipy.Spotify, time_range: str, limit: int) -> list[str]:
    """Return a list of track URIs from the user's top tracks."""
    results = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    return [item["uri"] for item in results["items"] if item]


def get_similar_tracks(
    sp: spotipy.Spotify,
    seed_uris: list[str],
    limit: int,
    rng: random.Random | None = None,
) -> list[str]:
    """Return track URIs from artists similar to the user's top artists.

    Uses Spotify's related-artists endpoint to find genuinely similar music
    rather than just more tracks from the same artists.

    Pass a date-seeded ``rng`` to get consistent daily variety (same result
    within a day, different every day).
    """
    if rng is None:
        rng = random.Random()
    if limit <= 0:
        return []

    # Get the user's top artists (IDs + names)
    try:
        top_result = sp.current_user_top_artists(limit=5, time_range="medium_term")
        top_artists = top_result["items"]
    except Exception:
        top_artists = []

    if not top_artists:
        return []

    top_artist_ids = {a["id"] for a in top_artists}
    seen_artist_ids = set(top_artist_ids)

    # For each top artist, fetch related artists (take more for a bigger pool)
    related_artists: list[dict] = []
    for artist in top_artists[:5]:
        try:
            rel = sp.artist_related_artists(artist["id"])["artists"]
            for ra in rel[:6]:
                if ra["id"] not in seen_artist_ids:
                    seen_artist_ids.add(ra["id"])
                    related_artists.append(ra)
        except Exception:
            continue

    # Daily-seeded shuffle → different artists each day, stable within a day
    rng.shuffle(related_artists)

    # Collect tracks from related artists via search.
    # Fetch more than needed per artist and daily-sample so it's not always
    # the same popular hits.
    collected: list[str] = []
    seen_track_ids = {uri.split(":")[-1] for uri in seed_uris}

    for artist in related_artists:
        if len(collected) >= limit:
            break
        try:
            results = sp.search(
                q=f'artist:"{artist["name"]}"', type="track", limit=10, market="from_token"
            )
            candidates = [
                t["uri"]
                for t in results["tracks"]["items"]
                if t["id"] not in seen_track_ids
            ]
            # Daily-sample up to 3 tracks per artist for variety
            picks = rng.sample(candidates, min(3, len(candidates)))
            for uri in picks:
                seen_track_ids.add(uri.split(":")[-1])
                collected.append(uri)
        except Exception:
            continue

    rng.shuffle(collected)
    return collected[:limit]


def get_recently_played(sp: spotipy.Spotify, limit: int = 50) -> list[str]:
    """Return URIs of recently played tracks, deduplicated (max 50)."""
    try:
        results = sp.current_user_recently_played(limit=min(limit, 50))
    except Exception:
        return []
    seen: set[str] = set()
    tracks: list[str] = []
    for item in results.get("items", []):
        uri = item["track"]["uri"]
        if uri not in seen:
            seen.add(uri)
            tracks.append(uri)
    return tracks


def get_top_artist_tracks(
    sp: spotipy.Spotify, limit: int = 50, rng: random.Random | None = None
) -> list[str]:
    """Return track URIs from the user's own top artists (their popular songs)."""
    try:
        result = sp.current_user_top_artists(limit=10, time_range="medium_term")
        artists = result["items"]
    except Exception:
        return []
    if rng:
        rng.shuffle(artists)
    seen: set[str] = set()
    tracks: list[str] = []
    for artist in artists:
        try:
            top = sp.artist_top_tracks(artist["id"])
            for t in top["tracks"]:
                if t["uri"] not in seen:
                    seen.add(t["uri"])
                    tracks.append(t["uri"])
        except Exception:
            continue
    if rng:
        rng.shuffle(tracks)
    return tracks[:limit]


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


def get_latest_episodes(
    sp: spotipy.Spotify, show_id: str, limit: int = 2, today_only: bool = False
) -> list[str]:
    """Return episode URIs for the latest episodes of a show.

    If today_only is True, only episodes released today are returned.
    """
    results = sp.show_episodes(show_id, limit=limit, market="from_token")
    today = date.today().isoformat()
    uris = []
    for ep in results["items"]:
        if not ep or ep.get("is_playable") is False:
            continue
        if today_only and ep.get("release_date", "") != today:
            continue
        # Skip episodes the user has already fully listened to
        if ep.get("resume_point", {}).get("fully_played", False):
            continue
        uris.append(ep["uri"])
    return uris


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


def search_tracks(sp: spotipy.Spotify, query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search for tracks and return [{id, name, artist, image_url}]."""
    results = sp.search(q=query, type="track", limit=limit, market="from_token")
    tracks = []
    for item in results["tracks"]["items"]:
        image_url = item["album"]["images"][0]["url"] if item["album"].get("images") else ""
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        tracks.append({
            "id": item["id"],
            "name": item["name"],
            "artist": artists,
            "image_url": image_url,
        })
    return tracks


def search_playlists(sp: spotipy.Spotify, query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search for playlists and return [{id, name, owner, image_url, track_count}]."""
    results = sp.search(q=query, type="playlist", limit=limit, market="from_token")
    playlists = []
    for item in results["playlists"]["items"]:
        if not item:
            continue
        image_url = item["images"][0]["url"] if item.get("images") else ""
        playlists.append({
            "id": item["id"],
            "name": item["name"],
            "owner": item["owner"]["display_name"],
            "image_url": image_url,
            "track_count": item["tracks"]["total"],
        })
    return playlists


def search_artists(sp: spotipy.Spotify, query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search for artists and return [{id, name, image_url, genres}]."""
    results = sp.search(q=query, type="artist", limit=limit, market="from_token")
    artists = []
    for item in results["artists"]["items"]:
        image_url = item["images"][0]["url"] if item.get("images") else ""
        artists.append({
            "id": item["id"],
            "name": item["name"],
            "image_url": image_url,
            "genres": ", ".join(item.get("genres", [])[:3]),
        })
    return artists


def get_playlist_track_ids(sp: spotipy.Spotify, playlist_ids: list[str]) -> set[str]:
    """Return the set of track IDs contained in any of the given playlists."""
    track_ids: set[str] = set()
    for pl_id in playlist_ids:
        offset = 0
        while True:
            try:
                results = sp.playlist_tracks(
                    pl_id, fields="items(track(id)),next", limit=100, offset=offset
                )
            except Exception:
                break
            for item in results.get("items", []):
                track = item.get("track")
                if track and track.get("id"):
                    track_ids.add(track["id"])
            if results.get("next") is None:
                break
            offset += 100
    return track_ids


def get_audio_features(sp: spotipy.Spotify, track_uris: list[str]) -> dict[str, dict]:
    """Fetch audio features for tracks (only spotify:track URIs). Returns {uri: features}."""
    uris = [u for u in track_uris if u.startswith("spotify:track:")]
    features: dict[str, dict] = {}
    try:
        for i in range(0, len(uris), 100):
            batch = [u.split(":")[-1] for u in uris[i:i + 100]]
            results = sp.audio_features(batch)
            if not results:
                continue
            for feat in results:
                if feat:
                    features[f"spotify:track:{feat['id']}"] = feat
    except Exception:
        pass
    return features


def sort_by_energy_arc(track_uris: list[str], features: dict, rng: random.Random) -> list[str]:
    """Sort tracks into a natural energy arc: mid → high → mid → low."""
    def energy(uri: str) -> float:
        return features.get(uri, {}).get("energy", 0.5)

    low  = [u for u in track_uris if energy(u) < 0.4]
    mid  = [u for u in track_uris if 0.4 <= energy(u) < 0.7]
    high = [u for u in track_uris if energy(u) >= 0.7]
    unknown = [u for u in track_uris if u not in features]

    rng.shuffle(low)
    rng.shuffle(mid)
    rng.shuffle(high)

    half_mid = len(mid) // 2
    return mid[:half_mid] + high + mid[half_mid:] + low + unknown


def update_playlist_details(sp: spotipy.Spotify, playlist_id: str, name: str, description: str) -> None:
    """Update playlist name and description."""
    try:
        sp.playlist_change_details(playlist_id, name=name, description=description)
    except Exception:
        pass


def generate_cover_collage(sp: spotipy.Spotify, track_uris: list[str]) -> str | None:
    """Create a 2x2 collage from the first 4 track album covers. Returns base64 JPEG or None."""
    track_only = [u for u in track_uris if u.startswith("spotify:track:")][:4]
    if len(track_only) < 4:
        return None
    ids = [u.split(":")[-1] for u in track_only]
    try:
        tracks = sp.tracks(ids)["tracks"]
    except Exception:
        return None

    images: list[Image.Image] = []
    for t in tracks:
        imgs = t.get("album", {}).get("images", []) if t else []
        if not imgs:
            return None
        url = imgs[0]["url"]
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                images.append(Image.open(io.BytesIO(resp.read())).convert("RGB"))
        except Exception:
            return None

    size = 300
    collage = Image.new("RGB", (size * 2, size * 2))
    for idx, img in enumerate(images):
        img = img.resize((size, size), Image.LANCZOS)
        x, y = (idx % 2) * size, (idx // 2) * size
        collage.paste(img, (x, y))

    buf = io.BytesIO()
    collage.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def upload_cover(sp: spotipy.Spotify, playlist_id: str, b64_image: str) -> None:
    """Upload a base64-encoded JPEG as the playlist cover."""
    try:
        sp.playlist_upload_cover_image(playlist_id, b64_image)
    except Exception:
        pass


def filter_excluded_artists(
    sp: spotipy.Spotify, track_uris: list[str], excluded_ids: set[str]
) -> list[str]:
    """Remove tracks by excluded artists. Fetches track details in batches of 50."""
    if not excluded_ids or not track_uris:
        return track_uris

    filtered: list[str] = []
    for i in range(0, len(track_uris), 50):
        batch_uris = track_uris[i : i + 50]
        batch_ids = [u.split(":")[-1] for u in batch_uris]
        try:
            tracks = sp.tracks(batch_ids)["tracks"]
        except Exception:
            filtered.extend(batch_uris)
            continue
        for uri, track in zip(batch_uris, tracks):
            if track and not any(a["id"] in excluded_ids for a in track.get("artists", [])):
                filtered.append(uri)
    return filtered
