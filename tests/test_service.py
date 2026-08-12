from smallrag.config import Settings
from smallrag.models import QueryRequest, SearchResult, TokenUsage
from smallrag.service import RAGService


class FakeKB:
    async def search(self, query: str, top_k: int, alpha: float):
        return [SearchResult(
            id="42", title="RAG Design", space="AI", excerpt="Short summary", score=0.9,
            source="confluence", last_updated="2026-01-01", url="https://confluence/pages/42",
        )], 1

    async def fetch_page(self, page_id: str):
        return {"id": page_id, "content": "The system uses hybrid retrieval."}

    async def close(self):
        pass


class FakeModel:
    configured = True
    prompt = ""

    async def generate(self, **kwargs):
        self.prompt = kwargs["prompt"]
        return "It uses hybrid retrieval [1].", TokenUsage(input_tokens=30, output_tokens=7)

    async def close(self):
        pass


async def test_query_returns_evaluation_metadata() -> None:
    model = FakeModel()
    service = RAGService(Settings(anthropic_model="test-model"), FakeKB(), model)

    response = await service.query(QueryRequest(query="How does it retrieve?"), "request-1")

    assert response.answer.endswith("[1].")
    assert response.citations[0].page_id == "42"
    assert response.retrieval is not None
    assert response.retrieval.results[0].score == 0.9
    assert response.usage.input_tokens == 30
    assert "The system uses hybrid retrieval." in model.prompt


async def test_query_can_omit_raw_retrieval() -> None:
    service = RAGService(Settings(anthropic_model="test-model"), FakeKB(), FakeModel())

    response = await service.query(
        QueryRequest(query="How?", include_retrieval=False), "request-2"
    )

    assert response.retrieval is None
    assert len(response.citations) == 1

