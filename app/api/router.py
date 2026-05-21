from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    chat,
    health,
    ner,
    predict,
    rag,
    summarize,
    widgets,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(predict.router)
api_router.include_router(ner.router)
api_router.include_router(summarize.router)
api_router.include_router(rag.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
api_router.include_router(widgets.admin_router)
api_router.include_router(widgets.public_router)
