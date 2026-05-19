import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.router import api_router
from app.infra.classifier import IssueClassifier
from app.infra.summarizer import IssueSummarizer

MODEL_DIR = Path(__file__).resolve().parent.parent / "models/bert_tiny_classifier"


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.classifier = IssueClassifier.load(MODEL_DIR)
    if os.environ.get("OPENAI_API_KEY"):
        application.state.summarizer = IssueSummarizer.from_env()
    else:
        application.state.summarizer = None
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Maintainer's Copilot",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_app()
