from fastapi import APIRouter, Request

from app.domain.predict import PredictRequest, PredictResponse
from app.services import predict as predict_service

router = APIRouter(tags=["predict"])


@router.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, request: Request) -> PredictResponse:
    classifier = request.app.state.classifier
    return predict_service.predict_issue(classifier, body)
