from pydantic import BaseModel, Field, field_validator


class RagQueryRequest(BaseModel):
    query: str = Field(..., description="Natural-language question about the project")
    session_id: str | None = Field(
        default=None,
        description="Optional session ID for conversational memory (stateless if omitted)",
    )

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value

    @field_validator("session_id")
    @classmethod
    def session_id_valid(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("session_id must not be empty when provided")
        return value.strip() if value else None


class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str
    text: str
    section: str | None = None
    score: float


class RagQueryMetadata(BaseModel):
    latency_ms: float
    retrieval_confidence: float
    retrieval_mode: str = "hybrid"
    session_id: str | None = None
    rewritten_query: str | None = None
    refused: bool = False
    refusal_reason: str | None = None


class RagQueryResponse(BaseModel):
    answer: str
    sources: list[str]
    retrieved_chunks: list[RetrievedChunk]
    metadata: RagQueryMetadata | None = None
