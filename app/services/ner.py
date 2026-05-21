from app.domain.ner import NerRequest, NerResponse
from app.ml import ner as ner_extractor


def extract_entities(request: NerRequest) -> NerResponse:
    entities = ner_extractor.extract_entities(request.text.strip())
    return NerResponse(**entities)
