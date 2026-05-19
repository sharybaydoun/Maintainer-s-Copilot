from pydantic import BaseModel, Field, field_validator


class NerRequest(BaseModel):
    text: str = Field(..., description="Issue or thread text to analyze")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


class NerResponse(BaseModel):
    filenames: list[str]
    functions: list[str]
    urls: list[str]
    stack_trace: list[str]
    code_tokens: list[str]
