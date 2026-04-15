"""Assembles the Daily Drive playlist from tracks and podcast episodes."""
from __future__ import annotations

from datetime import date, datetime, timezone
from random import Random

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

    # How many tracks from each source.
    # rec_count requests the full total so filters don't shrink the final playlist.
    top_count = max(1, int(total_tracks * top_ratio))
    rec_count = total_tracks

    # Date-seeded RNG: same result within one day, different every day
    day_rng = Random(date.today().isoformat())

    sfm_user_id: str | None = config.get("statsfm_user_id")

    # Track cooldown: exclude tracks used in recent builds to force daily variety
    recent_track_ids: set[str] = set(config.get("recent_track_ids", []))

    seen: set[str] = set()
    top_tracks: list[str] = []

    # Fetch a larger pool so we can randomly sample — guarantees variety day-to-day
    pool_size = min(top_count * 3, 50)

    if sfm_user_id:
        # Primary source: stats.fm — fetch 3 ranges for maximum pool diversity
        sfm_weeks = sfm_api.get_top_tracks(sfm_user_id, range="weeks", limit=pool_size)
        sfm_months = sfm_api.get_top_tracks(sfm_user_id, range="months", limit=pool_size)
        sfm_lifetime = sfm_api.get_top_tracks(sfm_user_id, range="lifetime", limit=pool_size)

        # Build interleaved pool (weeks/months/lifetime round-robin, then remainders)
        pool: list[str] = []
        for a, b, c in zip(sfm_weeks, sfm_months, sfm_lifetime):
            for uri in (a, b, c):
                if uri not in seen:
                    seen.add(uri)
                    pool.append(uri)
        for uri in sfm_weeks + sfm_months + sfm_lifetime:
            if uri not in seen:
                seen.add(uri)
                pool.append(uri)

        # Cooldown: prefer tracks not used recently; stale tracks fill remaining slots
        fresh = [u for u in pool if u.split(":")[-1] not in recent_track_ids]
        stale = [u for u in pool if u.split(":")[-1] in recent_track_ids]
        sample_size = min(top_count, len(pool))
        fresh_count = min(sample_size, len(fresh))
        stale_needed = max(0, sample_size - fresh_count)
        top_tracks = (
            day_rng.sample(fresh, fresh_count)
            + day_rng.sample(stale, min(stale_needed, len(stale)))
        )
        day_rng.shuffle(top_tracks)
    else:
        # Fallback: Spotify's own top tracks — fetch all 3 time ranges for more diversity
        short_term = sp_api.get_top_tracks(sp, "short_term", limit=pool_size)
        medium_term = sp_api.get_top_tracks(sp, "medium_term", limit=pool_size)
        long_term = sp_api.get_top_tracks(sp, "long_term", limit=pool_size)

        pool = []
        for a, b, c in zip(short_term, medium_term, long_term):
            for uri in (a, b, c):
                if uri not in seen:
                    seen.add(uri)
                    pool.append(uri)
        for uri in short_term + medium_term + long_term:
            if uri not in seen:
                seen.add(uri)
                pool.append(uri)

        # Cooldown: same logic as stats.fm path
        fresh = [u for u in pool if u.split(":")[-1] not in recent_track_ids]
        stale = [u for u in pool if u.split(":")[-1] in recent_track_ids]
        sample_size = min(top_count, len(pool))
        fresh_count = min(sample_size, len(fresh))
        stale_needed = max(0, sample_size - fresh_count)
        top_tracks = (
            day_rng.sample(fresh, fresh_count)
            + day_rng.sample(stale, min(stale_needed, len(stale)))
        )
        day_rng.shuffle(top_tracks)

    seen = set(top_tracks)  # update seen to only the selected tracks

    # Fill remaining slots with tracks from similar (related) artists
    rec_tracks = sp_api.get_similar_tracks(sp, top_tracks, limit=rec_count, rng=day_rng)
    # Deduplicate against top tracks
    rec_tracks = [u for u in rec_tracks if u not in seen]

    # Combine and shuffle (day-seeded for daily consistency)
    music_uris = top_tracks + rec_tracks
    day_rng.shuffle(music_uris)

    # Sort by energy arc for a natural Spotify-like flow
    features = sp_api.get_audio_features(sp, music_uris)
    if features:
        music_uris = sp_api.sort_by_energy_arc(music_uris, features, day_rng)

    # Fallback 1: popular tracks from the user's own top artists
    if len(music_uris) < total_tracks:
        pool_seen = set(music_uris)
        extra = sp_api.get_top_artist_tracks(
            sp, limit=(total_tracks - len(music_uris)) * 2, rng=day_rng
        )
        extra = [u for u in extra if u not in pool_seen]
        music_uris.extend(extra)

    # Fallback 2: recently played tracks
    if len(music_uris) < total_tracks:
        pool_seen = set(music_uris)
        recent = sp_api.get_recently_played(sp, limit=50)
        recent = [u for u in recent if u not in pool_seen]
        music_uris.extend(recent)

    # Apply filters BEFORE truncating so excluded tracks don't shrink the playlist
    excluded_artist_ids: set[str] = {a["id"] for a in config.get("excluded_artists", [])}
    if excluded_artist_ids:
        music_uris = sp_api.filter_excluded_artists(sp, music_uris, excluded_artist_ids)

    excluded_track_ids: set[str] = {t["id"] for t in config.get("excluded_tracks", [])}
    if excluded_track_ids:
        music_uris = [u for u in music_uris if u.split(":")[-1] not in excluded_track_ids]

    excluded_playlist_ids: list[str] = config.get("excluded_playlist_ids", [])
    if excluded_playlist_ids:
        blocked_track_ids: set[str] = sp_api.get_playlist_track_ids(sp, excluded_playlist_ids)
        music_uris = [u for u in music_uris if u.split(":")[-1] not in blocked_track_ids]

    # Truncate to target count after filtering
    music_uris = music_uris[:total_tracks]

    # Fetch today's podcast episodes; favorites play first, rest interleaved
    fav_episodes: list[str] = []
    reg_episodes: list[str] = []
    for show in selected_podcasts:
        eps = sp_api.get_latest_episodes(sp, show["id"], limit=1, today_only=True)
        if eps:
            if show.get("is_favorite"):
                fav_episodes.append(eps[0])
            else:
                reg_episodes.append(eps[0])

    # Respect podcast_count limit; favorites take priority
    fav_episodes = fav_episodes[:podcast_count]
    reg_episodes = reg_episodes[:max(0, podcast_count - len(fav_episodes))]

    # Favorites prepended at the very start; regular episodes interleaved
    final_uris = fav_episodes + interleave(music_uris, reg_episodes, episode_interval=7)
    episodes = fav_episodes + reg_episodes

    # Get or create playlist
    user = sp_api.get_current_user(sp)
    user_id = user["id"]
    playlist_id = sp_api.get_or_create_playlist(
        sp, user_id, config["playlist_name"], config.get("playlist_id")
    )

    sp_api.replace_playlist_tracks(sp, playlist_id, final_uris)

    # Update playlist description with today's date and track count
    today_str = date.today().strftime("%-d. %B %Y")
    description = f"Made for you · {today_str} · {len(music_uris)} Songs"
    sp_api.update_playlist_details(sp, playlist_id, config["playlist_name"], description)

    # Generate and upload 2x2 album art collage
    cover = sp_api.generate_cover_collage(sp, music_uris)
    if cover:
        sp_api.upload_cover(sp, playlist_id, cover)

    # Persist playlist ID and last build time
    config["playlist_id"] = playlist_id
    config["last_build"] = datetime.now(timezone.utc).isoformat()

    # Update track cooldown history: keep a rolling window of ~3 builds worth of IDs
    # so the next build prefers tracks not played recently
    used_ids = [u.split(":")[-1] for u in music_uris if u.startswith("spotify:track:")]
    used_set = set(used_ids)
    existing_history = [tid for tid in config.get("recent_track_ids", []) if tid not in used_set]
    config["recent_track_ids"] = (used_ids + existing_history)[: total_tracks * 3]

    save_config(config)

    return {
        "ok": True,
        "playlist_id": playlist_id,
        "tracks": len(music_uris),
        "episodes": len(episodes),
        "total": len(final_uris),
        "last_build": config["last_build"],
    }
