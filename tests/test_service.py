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


class LongPageKB(FakeKB):
    async def search(self, query: str, top_k: int, alpha: float):
        return [SearchResult(
            id="42",
            title="BIOS Configuration",
            space="AI",
            excerpt="Update Settings PATCH /redfish/v1/Systems/Self/Bios/SD with If-None-Match.",
            score=0.9,
            source="confluence",
            last_updated="2026-01-01",
            url="https://confluence/pages/42",
        )], 1

    async def fetch_page(self, page_id: str):
        introduction = "Unrelated inventory introduction. " * 80
        relevant = (
            "Update Settings PATCH /redfish/v1/Systems/Self/Bios/SD with "
            "the If-None-Match request header."
        )
        appendix = "Unrelated appendix material. " * 80
        return {"id": page_id, "content": f"{introduction}\n\n{relevant}\n\n{appendix}"}


async def test_query_returns_evaluation_metadata() -> None:
    model = FakeModel()
    service = RAGService(Settings(llm_model="test-model"), FakeKB(), model)

    response = await service.query(QueryRequest(query="How does it retrieve?"), "request-1")

    assert response.answer.endswith("[1].")
    assert response.citations[0].page_id == "42"
    assert response.contexts[0].document_id == "42"
    assert response.contexts[0].content.startswith("[1] RAG Design")
    assert response.contexts[0].content in model.prompt
    assert response.contexts[0].truncated is False
    assert response.retrieval is not None
    assert response.retrieval.results[0].score == 0.9
    assert response.usage.input_tokens == 30
    assert "The system uses hybrid retrieval." in model.prompt


async def test_query_can_omit_raw_retrieval() -> None:
    service = RAGService(Settings(llm_model="test-model"), FakeKB(), FakeModel())

    response = await service.query(
        QueryRequest(query="How?", include_retrieval=False), "request-2"
    )

    assert response.retrieval is None
    assert len(response.citations) == 1
    assert len(response.contexts) == 1


async def test_query_selects_relevant_passage_from_long_page() -> None:
    model = FakeModel()
    service = RAGService(Settings(llm_model="test-model"), LongPageKB(), model)

    response = await service.query(
        QueryRequest(query="Which PATCH URL and request header update BIOS settings?"),
        "request-3",
    )

    context = response.contexts[0]
    assert context.chunk_id == "context:42"
    assert "/redfish/v1/Systems/Self/Bios/SD" in context.content
    assert "If-None-Match" in context.content
    assert not context.content.endswith("Unrelated appendix material.")
    assert context.content in model.prompt
    assert context.truncated is True
