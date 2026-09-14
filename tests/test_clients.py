import json

import httpx
import pytest

from smallrag.clients import KnowledgeBaseClient, OpenAICompatibleClient
from smallrag.errors import UpstreamError


@pytest.mark.asyncio
async def test_knowledge_base_search_and_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "kb-secret"
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "results": [{
                        "id": "42", "title": "RAG", "space": "AI", "excerpt": "An excerpt",
                        "score": 0.9, "source": "confluence", "last_updated": "2026-01-01",
                        "url": "https://confluence/pages/42",
                    }],
                },
            )
        return httpx.Response(200, json={"id": "42", "content": "Full page"})

    client = KnowledgeBaseClient(
        "https://kb.local", "kb-secret", verify_ssl=False, timeout=1,
        transport=httpx.MockTransport(handler),
    )
    results, total = await client.search("RAG", 5, 0.5)
    page = await client.fetch_page("42")
    await client.close()

    assert total == 1
    assert results[0].id == "42"
    assert page["content"] == "Full page"


@pytest.mark.asyncio
async def test_openai_compatible_chat_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer model-secret"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["messages"][0] == {"role": "system", "content": "system"}
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Answer [1]"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 4},
            },
        )

    client = OpenAICompatibleClient(
        "http://model.local", "model-secret", verify_ssl=True, timeout=1,
        transport=httpx.MockTransport(handler),
    )
    answer, usage = await client.generate(
        model="test-model", system="system", prompt="question", max_tokens=100, temperature=0,
        enable_thinking=False,
    )
    await client.close()

    assert answer == "Answer [1]"
    assert usage.input_tokens == 20
    assert usage.output_tokens == 4


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_invalid_json_shape() -> None:
    client = OpenAICompatibleClient(
        "http://model.local", None, verify_ssl=True, timeout=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )

    with pytest.raises(UpstreamError, match="invalid response"):
        await client.generate(
            model="test-model", system="system", prompt="question", max_tokens=100,
            temperature=0, enable_thinking=False,
        )

    await client.close()
