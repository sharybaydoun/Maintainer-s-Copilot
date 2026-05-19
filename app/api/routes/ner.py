from fastapi import APIRouter

from app.domain.ner import NerRequest, NerResponse
from app.services import ner as ner_service

router = APIRouter(tags=["ner"])


@router.post("/ner", response_model=NerResponse)
def ner(body: NerRequest) -> NerResponse:
    return ner_service.extract_entities(body)
