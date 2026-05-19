from pydantic import BaseModel, Field, field_validator


class SummarizeRequest(BaseModel):
    text: str = Field(..., description="Issue thread text to summarize")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class SummarizeResponse(BaseModel):
    summary: str
