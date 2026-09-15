from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from smallrag import __version__
from smallrag.clients import KnowledgeBaseClient, OpenAICompatibleClient
from smallrag.config import Settings, get_settings
from smallrag.errors import SmallRAGError
from smallrag.models import (
    ErrorDetail,
    ErrorResponse,
    QueryRequest,
    QueryResponse,
    ReadinessResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from smallrag.service import RAGService


_WEB_DIR = Path(__file__).with_name("web")


def build_service(settings: Settings) -> RAGService:
    kb_key = settings.confluence_kb_api_key.get_secret_value() if settings.confluence_kb_api_key else None
    llm_api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    kb = KnowledgeBaseClient(
        settings.confluence_kb_url,
        kb_key,
        verify_ssl=settings.confluence_kb_verify_ssl,
        timeout=settings.rag_request_timeout_seconds,
    )
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        llm_api_key,
        verify_ssl=settings.llm_verify_ssl,
        timeout=settings.rag_request_timeout_seconds,
    )
    return RAGService(settings, kb, model)


def create_app(settings: Settings | None = None, service: RAGService | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.rag = service or build_service(resolved_settings)
        yield
        if service is None:
            await app.state.rag.close()

    app = FastAPI(
        title="SmallRAG API",
        description="Evaluation-friendly RAG over the Confluence knowledge base.",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied[:128] if supplied else str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(SmallRAGError)
    async def smallrag_error_handler(request: Request, exc: SmallRAGError) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorDetail(code=exc.code, message=exc.message, request_id=request.state.request_id)
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="Request validation failed",
                request_id=request.state.request_id,
            )
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    async def web_app() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
        tags=["health"],
    )
    async def ready(request: Request):
        checks = await request.app.state.rag.readiness()
        ready_state = all(bool(check.get("ok")) for check in checks.values())
        body = ReadinessResponse(status="ready" if ready_state else "not_ready", checks=checks)
        if not ready_state:
            return JSONResponse(status_code=503, content=body.model_dump())
        return body

    @app.post(
        "/v1/retrieve",
        response_model=RetrieveResponse,
        responses={502: {"model": ErrorResponse}},
        tags=["rag"],
    )
    async def retrieve(payload: RetrieveRequest, request: Request) -> RetrieveResponse:
        return await request.app.state.rag.retrieve(payload, request.state.request_id)

    @app.post(
        "/v1/query",
        response_model=QueryResponse,
        responses={502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
        tags=["rag"],
    )
    async def query(payload: QueryRequest, request: Request) -> QueryResponse:
        return await request.app.state.rag.query(payload, request.state.request_id)

    return app


app = create_app()
