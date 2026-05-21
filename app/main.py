import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import RequestLoggingMiddleware
from app.api.router import api_router
from app.infra.auth.auth import ensure_jwt_secret
from app.infra.cache.chat_memory import ChatMemory
from app.infra.database.database import get_session
from app.infra.observability.logging_config import configure_logging
from app.infra.observability.tracing import configure_tracing, instrument_fastapi
from app.infra.secrets.vault import apply_secrets, load_secrets
from app.infra.startup_validation import validate_startup
from app.infra.storage.minio_storage import upload_reports
from app.ml.classifier import IssueClassifier
from app.ml.embeddings import EmbeddingModel
from app.ml.summarizer import IssueSummarizer
from app.rag.retrieval import load_retriever
from app.services.chatbot import ChatbotService
from app.services.rag import RagService

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "models/bert_tiny_classifier"
REPORTS_DIR = ROOT / "reports"

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8501,http://localhost:5173,http://localhost:8080,http://127.0.0.1:8501,http://127.0.0.1:5173,http://127.0.0.1:8080",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    logger.info("api_boot_starting", extra={"step": "lifespan_begin"})

    secrets = load_secrets()
    apply_secrets(secrets)
    logger.info(
        "secrets_applied",
        extra={"step": "vault", "applied_count": len(secrets)},
    )

    tracing_active = configure_tracing()
    instrument_fastapi(application)
    logger.info(
        "tracing_status",
        extra={"step": "tracing", "active": tracing_active},
    )

    ensure_jwt_secret()
    validate_startup()
    logger.info("startup_validation_ok", extra={"step": "validation"})

    application.state.classifier = IssueClassifier.load(MODEL_DIR)
    logger.info(
        "classifier_loaded", extra={"step": "classifier", "model_dir": str(MODEL_DIR)}
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    application.state.summarizer = IssueSummarizer(api_key=api_key) if api_key else None
    logger.info(
        "summarizer_status",
        extra={"step": "summarizer", "enabled": api_key is not None},
    )

    application.state.chat_memory = ChatMemory.from_env()

    # Preload the sentence-transformer eagerly. If a RAG index exists,
    # ``load_retriever`` already constructs an EmbeddingModel; otherwise we
    # still want a hot embedder so the first /chat tool call (write_memory,
    # search_docs, etc.) doesn't pay the cold-start cost.
    application.state.retriever = load_retriever()
    if application.state.retriever is not None:
        # Reuse the retriever's embedder and force it warm.
        application.state.embedder = application.state.retriever.embedder
        application.state.embedder._load()
        logger.info(
            "rag_retriever_loaded",
            extra={"step": "rag_retriever", "embedder_warmed": True},
        )
    else:
        logger.warning(
            "rag_retriever_unavailable",
            extra={
                "step": "rag_retriever",
                "hint": "python scripts/build_rag_corpus.py && python scripts/build_rag_index.py",
            },
        )
        application.state.embedder = EmbeddingModel(preload=True)
        logger.info(
            "embedder_preloaded_standalone",
            extra={"step": "embedder", "model": application.state.embedder.model_name},
        )

    application.state.rag_service = None
    if api_key and application.state.retriever:
        application.state.rag_service = RagService(
            retriever=application.state.retriever,
            api_key=api_key,
            memory=application.state.chat_memory,
        )
        logger.info("rag_service_ready")

    application.state.chatbot_service = None
    if api_key:
        try:
            application.state.chatbot_service = ChatbotService.from_env(
                classifier=application.state.classifier,
                summarizer=application.state.summarizer,
                retriever=application.state.retriever,
                memory=application.state.chat_memory,
                # Reuse the preloaded embedder — never re-instantiate lazily.
                embedder=application.state.embedder,
                db_session_factory=get_session,
            )
            logger.info("chatbot_service_ready", extra={"step": "chatbot"})
        except Exception as exc:
            logger.warning("chatbot_service_unavailable", extra={"error": str(exc)})

    uploaded = upload_reports(REPORTS_DIR)
    if uploaded:
        logger.info(
            "reports_uploaded_to_minio",
            extra={"step": "minio", "count": len(uploaded), "keys": uploaded},
        )

    logger.info("api_boot_complete", extra={"step": "lifespan_ready"})
    yield
    logger.info("api_shutdown", extra={"step": "lifespan_end"})


def create_app() -> FastAPI:
    application = FastAPI(
        title="Maintainer's Copilot API",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
