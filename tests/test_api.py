from httpx import ASGITransport, AsyncClient

from smallrag.main import create_app
from smallrag.models import (
    Citation,
    LatencyBreakdown,
    QueryResponse,
    RetrievalData,
    RetrieveResponse,
    TokenUsage,
)


class FakeService:
    async def retrieve(self, payload, request_id):
        return RetrieveResponse(
            request_id=request_id,
            retrieval=RetrievalData(
                query=payload.query, top_k=payload.top_k or 5, alpha=0.5, total=0, results=[]
            ),
            latency_ms=1,
        )

    async def query(self, payload, request_id):
        return QueryResponse(
            request_id=request_id,
            answer="No evidence.",
            model="test-model",
            citations=[],
            retrieval=None,
            usage=TokenUsage(input_tokens=5, output_tokens=3),
            latency_ms=LatencyBreakdown(retrieval=1, page_fetch=0, generation=1, total=2),
        )

    async def readiness(self):
        return {"knowledge_base": {"ok": True}, "model_configuration": {"ok": True}}


async def test_health_and_request_id() -> None:
    app = create_app(service=FakeService())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health", headers={"X-Request-ID": "evaluation-run-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "evaluation-run-1"
    assert response.json()["status"] == "ok"


async def test_retrieve_endpoint() -> None:
    app = create_app(service=FakeService())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/retrieve", json={"query": "RAG", "top_k": 3})

    assert response.status_code == 200
    assert response.json()["retrieval"]["top_k"] == 3


async def test_validation_errors_do_not_echo_input() -> None:
    app = create_app(service=FakeService())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/query", json={"query": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

