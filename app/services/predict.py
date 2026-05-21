import logging

from app.domain.predict import PredictRequest, PredictResponse
from app.infra.database.database import get_session
from app.ml.classifier import IssueClassifier
from app.repositories.prediction_log import insert_prediction_log

logger = logging.getLogger(__name__)


def predict_issue(
    classifier: IssueClassifier,
    request: PredictRequest,
    *,
    request_id: str | None = None,
) -> PredictResponse:
    label, confidence = classifier.predict(request.text.strip())
    response = PredictResponse(label=label, confidence=confidence)

    logger.info(
        "prediction_completed",
        extra={
            "request_id": request_id or "unknown",
            "label": label,
            "confidence": confidence,
        },
    )

    session = get_session()
    if session is not None and request_id:
        try:
            insert_prediction_log(
                session,
                request_id=request_id,
                predicted_label=label,
                confidence=confidence,
                text_preview=request.text.strip()[:500],
            )
        except Exception as exc:
            logger.warning(
                "prediction_log_persist_failed",
                extra={"request_id": request_id, "error": str(exc)},
            )
        finally:
            session.close()

    return response
