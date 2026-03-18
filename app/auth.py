import os
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
CACHE_PATH = DATA_DIR / "spotify_token.json"

SCOPES = " ".join([
    "user-top-read",
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
    "user-read-private",
    "user-read-email",
])


def get_oauth() -> SpotifyOAuth:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
        scope=SCOPES,
        cache_path=str(CACHE_PATH),
        open_browser=False,
    )


def get_spotify() -> spotipy.Spotify | None:
    """Return an authenticated Spotify client, or None if not logged in."""
    oauth = get_oauth()
    token_info = oauth.get_cached_token()
    if not token_info:
        return None
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"])


def get_auth_url() -> str:
    return get_oauth().get_authorize_url()


def exchange_code(code: str) -> dict:
    oauth = get_oauth()
    return oauth.get_access_token(code, as_dict=True)


def is_authenticated() -> bool:
    oauth = get_oauth()
    token_info = oauth.get_cached_token()
    if not token_info:
        return False
    if oauth.is_token_expired(token_info):
        try:
            oauth.refresh_access_token(token_info["refresh_token"])
            return True
        except Exception:
            return False
    return True
