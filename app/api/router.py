from fastapi import APIRouter

from app.api.routes import health, ner, predict, summarize

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(predict.router)
api_router.include_router(ner.router)
api_router.include_router(summarize.router)
