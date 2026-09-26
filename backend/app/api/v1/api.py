"""API v1 Router registry."""

from fastapi import APIRouter
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.workspaces import router as workspaces_router
from backend.app.api.v1.tasks import router as tasks_router
from backend.app.api.v1.providers import router as providers_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(workspaces_router)
api_v1_router.include_router(tasks_router)
api_v1_router.include_router(providers_router)
