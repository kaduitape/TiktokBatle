import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import battles, characters, gifts, live, music, players, settings_routes, simulator, ws_routes
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.providers.simulation_provider import simulation_provider
from app.providers.tiktok_provider import tiktok_provider
from app.seed import run_seed
from app.services.event_queue import event_queue
from app.services.gift_cache import gift_cache

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    async with AsyncSessionLocal() as db:
        await run_seed(db)
        await gift_cache.refresh(db)

    # Every provider (simulator, real TikTok LIVE) feeds the same queue,
    # which drains into the one GamePipeline entry point (section 49/56).
    simulation_provider.on_event(event_queue.enqueue)
    tiktok_provider.on_event(event_queue.enqueue)

    os.makedirs(settings.upload_dir, exist_ok=True)

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(battles.router)
app.include_router(characters.router)
app.include_router(gifts.router)
app.include_router(gifts.combo_router)
app.include_router(players.router)
app.include_router(simulator.router)
app.include_router(live.router)
app.include_router(music.router)
app.include_router(settings_routes.router)
app.include_router(ws_routes.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
