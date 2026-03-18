"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()  # picks up .env in cwd when running locally

from .auth import exchange_code, get_auth_url, get_spotify, is_authenticated
from .builder import build_playlist
from .config import load_config, save_config
from .scheduler import schedule_all, start_scheduler
from . import spotify as sp_api
from . import statsfm as sfm_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield


app = FastAPI(title="Spotify Daily Drive", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Web UI ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    return RedirectResponse(get_auth_url())


@app.get("/auth/url")
async def auth_url():
    return {"url": get_auth_url()}


@app.get("/auth/callback")
async def auth_callback(code: str = Query(...)):
    try:
        exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/")


@app.get("/auth/status")
async def auth_status():
    if not is_authenticated():
        return {"authenticated": False, "user": None}
    sp = get_spotify()
    user = sp_api.get_current_user(sp)
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "name": user.get("display_name"),
            "image": user["images"][0]["url"] if user.get("images") else None,
        },
    }


# ── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return load_config()


@app.post("/api/settings")
async def update_settings(body: dict[str, Any]):
    config = load_config()
    allowed = {"total_tracks", "top_tracks_ratio", "recommendations_ratio",
               "podcast_episodes", "schedule_times", "playlist_name",
               "statsfm_user_id", "statsfm_display_name"}
    for key in allowed:
        if key in body:
            config[key] = body[key]
    save_config(config)
    # Reschedule if times changed
    if "schedule_times" in body:
        schedule_all(config["schedule_times"])
    return {"ok": True, "config": config}


# ── stats.fm ─────────────────────────────────────────────────────────────────

@app.get("/api/statsfm/resolve")
async def statsfm_resolve(username: str = Query(..., min_length=1)):
    result = await asyncio.to_thread(sfm_api.resolve_username, username)
    if result is None:
        return {"ok": False}
    return {"ok": True, "customId": result["customId"], "displayName": result["displayName"]}


@app.get("/api/statsfm/status")
async def statsfm_status():
    config = load_config()
    user_id = config.get("statsfm_user_id")
    if not user_id:
        return {"connected": False, "user": None}
    user = await asyncio.to_thread(sfm_api.validate_user_id, user_id)
    if user is None:
        return {"connected": False, "user": None}
    return {
        "connected": True,
        "user": {
            "id": user_id,
            "name": user_id,
            "image": None,
        },
    }


# ── Podcasts ──────────────────────────────────────────────────────────────────

@app.get("/api/podcasts/search")
async def search_podcasts(q: str = Query(..., min_length=1)):
    sp = get_spotify()
    if sp is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    results = sp_api.search_shows(sp, q)
    return {"shows": results}


@app.get("/api/podcasts/selected")
async def get_selected_podcasts():
    return {"podcasts": load_config()["selected_podcasts"]}


@app.post("/api/podcasts/selected")
async def set_selected_podcasts(body: dict[str, Any]):
    podcasts = body.get("podcasts", [])
    config = load_config()
    config["selected_podcasts"] = podcasts
    save_config(config)
    return {"ok": True, "podcasts": podcasts}


# ── Build ─────────────────────────────────────────────────────────────────────

@app.post("/api/build")
async def trigger_build():
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await asyncio.to_thread(build_playlist)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Build failed"))
    return result


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    from .scheduler import scheduler
    config = load_config()
    next_run = None
    job = scheduler.get_job("daily_build")
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()
    playlist_url = None
    if config.get("playlist_id"):
        playlist_url = f"https://open.spotify.com/playlist/{config['playlist_id']}"
    return {
        "last_build": config.get("last_build"),
        "next_run": next_run,
        "playlist_url": playlist_url,
        "authenticated": is_authenticated(),
    }
