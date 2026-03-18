"""Assembles the Daily Drive playlist from tracks and podcast episodes."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from . import spotify as sp_api
from . import statsfm as sfm_api
from .auth import get_spotify
from .config import load_config, save_config


def interleave(tracks: list[str], episodes: list[str], episode_interval: int = 7) -> list[str]:
    """Interleave episodes into the track list at regular intervals."""
    if not episodes:
        return tracks
    result: list[str] = []
    ep_iter = iter(episodes)
    episode_due = False
    tracks_since_ep = 0
    ep_exhausted = False
    for track in tracks:
        result.append(track)
        tracks_since_ep += 1
        if not ep_exhausted and tracks_since_ep >= episode_interval:
            try:
                result.append(next(ep_iter))
                tracks_since_ep = 0
            except StopIteration:
                ep_exhausted = True
    return result


def build_playlist() -> dict:
    """Build and update the Daily Drive playlist. Returns a status dict."""
    sp = get_spotify()
    if sp is None:
        return {"ok": False, "error": "Not authenticated with Spotify"}

    config = load_config()
    total_tracks = config["total_tracks"]
    top_ratio = config["top_tracks_ratio"]
    rec_ratio = config["recommendations_ratio"]
    podcast_count = config["podcast_episodes"]
    selected_podcasts = config["selected_podcasts"]

    # How many tracks from each source
    top_count = max(1, int(total_tracks * top_ratio))
    rec_count = max(1, int(total_tracks * rec_ratio))

    sfm_user_id: str | None = config.get("statsfm_user_id")

    seen: set[str] = set()
    top_tracks: list[str] = []

    if sfm_user_id:
        # Primary source: stats.fm — sorted by actual stream count
        recent = sfm_api.get_top_tracks(sfm_user_id, range="months", limit=50)
        alltime = sfm_api.get_top_tracks(sfm_user_id, range="lifetime", limit=50)

        # Interleave recent + all-time for variety, dedup, cap at top_count
        for a, b in zip(recent, alltime):
            for uri in (a, b):
                if uri not in seen and len(top_tracks) < top_count:
                    seen.add(uri)
                    top_tracks.append(uri)
        for uri in recent + alltime:
            if uri not in seen and len(top_tracks) < top_count:
                seen.add(uri)
                top_tracks.append(uri)
    else:
        # Fallback: Spotify's own top tracks (no stream counts)
        short_term = sp_api.get_top_tracks(sp, "short_term", limit=min(top_count, 50))
        long_term = sp_api.get_top_tracks(sp, "long_term", limit=min(top_count, 50))
        for a, b in zip(short_term, long_term):
            for uri in (a, b):
                if uri not in seen and len(top_tracks) < top_count:
                    seen.add(uri)
                    top_tracks.append(uri)
        for uri in short_term + long_term:
            if uri not in seen and len(top_tracks) < top_count:
                seen.add(uri)
                top_tracks.append(uri)

    # Fill remaining slots with artist-based search (replaces removed /recommendations)
    rec_tracks = sp_api.get_recommendations(sp, top_tracks, limit=rec_count)
    # Deduplicate against top tracks
    rec_tracks = [u for u in rec_tracks if u not in seen]

    # Combine music tracks and shuffle slightly for freshness
    music_uris = top_tracks + rec_tracks
    random.shuffle(music_uris)
    music_uris = music_uris[:total_tracks]

    # Fetch podcast episodes
    episodes: list[str] = []
    eps_per_show = max(1, podcast_count // len(selected_podcasts)) if selected_podcasts else 0
    for show in selected_podcasts:
        eps = sp_api.get_latest_episodes(sp, show["id"], limit=eps_per_show)
        episodes.extend(eps)
        if len(episodes) >= podcast_count:
            break
    episodes = episodes[:podcast_count]

    # Interleave: one podcast episode every ~7 music tracks
    final_uris = interleave(music_uris, episodes, episode_interval=7)

    # Get or create playlist
    user = sp_api.get_current_user(sp)
    user_id = user["id"]
    playlist_id = sp_api.get_or_create_playlist(
        sp, user_id, config["playlist_name"], config.get("playlist_id")
    )

    sp_api.replace_playlist_tracks(sp, playlist_id, final_uris)

    # Persist playlist ID and last build time
    config["playlist_id"] = playlist_id
    config["last_build"] = datetime.now(timezone.utc).isoformat()
    save_config(config)

    return {
        "ok": True,
        "playlist_id": playlist_id,
        "tracks": len(music_uris),
        "episodes": len(episodes),
        "total": len(final_uris),
        "last_build": config["last_build"],
    }
