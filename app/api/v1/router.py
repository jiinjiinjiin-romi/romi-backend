from fastapi import APIRouter

from app.api.v1.endpoints import (
    agent,
    bootstrap,
    driving_sessions,
    health,
    profiles,
    reports,
    saved_places,
    search_histories,
    voice,
)

router = APIRouter()

router.include_router(agent.router)
router.include_router(bootstrap.router)
router.include_router(health.router)
router.include_router(driving_sessions.router)
router.include_router(profiles.router)
router.include_router(reports.router)
router.include_router(saved_places.router)
router.include_router(search_histories.router)
router.include_router(voice.router)
