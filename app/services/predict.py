from app.domain.predict import PredictRequest, PredictResponse
from app.infra.classifier import IssueClassifier


def predict_issue(classifier: IssueClassifier, request: PredictRequest) -> PredictResponse:
    label, confidence = classifier.predict(request.text.strip())
    return PredictResponse(label=label, confidence=confidence)
