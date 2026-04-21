from fastapi import FastAPI

from app.api.config import router as config_router
from app.api.health import router as health_router
from app.api.templates import router as templates_router

app = FastAPI(title="wps-ai-adapter", version="0.1.0")
app.include_router(health_router)
app.include_router(config_router)
app.include_router(templates_router)
