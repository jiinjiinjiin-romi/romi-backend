from fastapi import APIRouter

from app.api.v1.endpoints import bootstrap, health, profiles, saved_places, search_histories

router = APIRouter()

router.include_router(bootstrap.router)
router.include_router(health.router)
router.include_router(profiles.router)
router.include_router(saved_places.router)
router.include_router(search_histories.router)
