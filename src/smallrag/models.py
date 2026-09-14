from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4_000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    alpha: float | None = Field(default=None, ge=0, le=1)


class QueryRequest(RetrieveRequest):
    max_context_chars: int | None = Field(default=None, ge=1_000, le=200_000)
    include_retrieval: bool = True
    model: str | None = Field(default=None, min_length=1, max_length=200)
    max_tokens: int = Field(default=1_024, ge=1, le=8_192)
    temperature: float = Field(default=0, ge=0, le=1)


class SearchResult(BaseModel):
    id: str
    title: str
    space: str | None = None
    excerpt: str = ""
    score: float
    source: str | None = None
    last_updated: str | None = None
    url: str


class RetrievalData(BaseModel):
    query: str
    top_k: int
    alpha: float
    total: int
    results: list[SearchResult]


class RetrieveResponse(BaseModel):
    request_id: str
    retrieval: RetrievalData
    latency_ms: int


class Citation(BaseModel):
    page_id: str
    title: str
    url: str
    score: float
    excerpt: str


class ContextChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    source: str
    rank: int
    retrieval_score: float
    truncated: bool = False


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class LatencyBreakdown(BaseModel):
    retrieval: int
    page_fetch: int
    generation: int
    total: int


class QueryResponse(BaseModel):
    request_id: str
    answer: str
    model: str
    citations: list[Citation]
    contexts: list[ContextChunk]
    retrieval: RetrievalData | None = None
    usage: TokenUsage
    latency_ms: LatencyBreakdown


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, Any]
