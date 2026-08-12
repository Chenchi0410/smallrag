from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

from smallrag.clients import AnthropicClient, KnowledgeBaseClient
from smallrag.config import Settings
from smallrag.errors import ConfigurationError
from smallrag.models import (
    Citation,
    LatencyBreakdown,
    QueryRequest,
    QueryResponse,
    RetrievalData,
    RetrieveRequest,
    RetrieveResponse,
)


SYSTEM_PROMPT = """You answer questions only from the supplied Confluence context.
If the context does not contain enough information, say that clearly instead of guessing.
Answer in the same language as the user's question. Cite supporting pages inline as [1], [2], etc."""


@dataclass
class FetchedPage:
    result_index: int
    content: str


class RAGService:
    def __init__(self, settings: Settings, kb: KnowledgeBaseClient, model: AnthropicClient) -> None:
        self.settings = settings
        self.kb = kb
        self.model = model

    async def close(self) -> None:
        await asyncio.gather(self.kb.close(), self.model.close())

    async def retrieve(self, request: RetrieveRequest, request_id: str) -> RetrieveResponse:
        started = perf_counter()
        retrieval = await self._retrieve_data(request)
        return RetrieveResponse(
            request_id=request_id,
            retrieval=retrieval,
            latency_ms=_elapsed_ms(started),
        )

    async def query(self, request: QueryRequest, request_id: str) -> QueryResponse:
        total_started = perf_counter()

        retrieval_started = perf_counter()
        retrieval = await self._retrieve_data(request)
        retrieval_ms = _elapsed_ms(retrieval_started)

        fetch_started = perf_counter()
        pages = await self._fetch_pages(retrieval)
        context, citations = self._build_context(
            retrieval,
            pages,
            request.max_context_chars or self.settings.rag_default_max_context_chars,
        )
        page_fetch_ms = _elapsed_ms(fetch_started)

        model_name = request.model or self.settings.anthropic_model
        if not model_name:
            raise ConfigurationError("ANTHROPIC_MODEL must be configured or supplied in the request")

        prompt = f"Confluence context:\n\n{context or '[No relevant context was retrieved.]'}\n\nQuestion:\n{request.query}"
        generation_started = perf_counter()
        answer, usage = await self.model.generate(
            model=model_name,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        generation_ms = _elapsed_ms(generation_started)

        return QueryResponse(
            request_id=request_id,
            answer=answer,
            model=model_name,
            citations=citations,
            retrieval=retrieval if request.include_retrieval else None,
            usage=usage,
            latency_ms=LatencyBreakdown(
                retrieval=retrieval_ms,
                page_fetch=page_fetch_ms,
                generation=generation_ms,
                total=_elapsed_ms(total_started),
            ),
        )

    async def readiness(self) -> dict[str, object]:
        checks: dict[str, object] = {
            "model_configuration": {
                "ok": self.model.configured and bool(self.settings.anthropic_model),
                "detail": "configured" if self.model.configured and self.settings.anthropic_model else "missing required model settings",
            }
        }
        try:
            await self.kb.search("readiness probe", 1, 0.5)
            checks["knowledge_base"] = {"ok": True}
        except Exception as exc:
            checks["knowledge_base"] = {"ok": False, "detail": str(exc)}
        return checks

    async def _retrieve_data(self, request: RetrieveRequest) -> RetrievalData:
        top_k = request.top_k or self.settings.rag_default_top_k
        alpha = request.alpha if request.alpha is not None else self.settings.rag_default_alpha
        results, total = await self.kb.search(request.query, top_k, alpha)
        return RetrievalData(
            query=request.query,
            top_k=top_k,
            alpha=alpha,
            total=total,
            results=results,
        )

    async def _fetch_pages(self, retrieval: RetrievalData) -> list[FetchedPage]:
        async def fetch(index: int) -> FetchedPage:
            page = await self.kb.fetch_page(retrieval.results[index].id)
            return FetchedPage(result_index=index, content=page["content"].strip())

        fetched = await asyncio.gather(*(fetch(i) for i in range(len(retrieval.results))))
        return sorted(fetched, key=lambda page: page.result_index)

    @staticmethod
    def _build_context(
        retrieval: RetrievalData,
        pages: list[FetchedPage],
        max_chars: int,
    ) -> tuple[str, list[Citation]]:
        chunks: list[str] = []
        citations: list[Citation] = []
        remaining = max_chars

        for page in pages:
            result = retrieval.results[page.result_index]
            citation_number = len(citations) + 1
            prefix = f"[{citation_number}] {result.title}\nURL: {result.url}\n"
            if remaining <= len(prefix):
                break
            body = page.content or result.excerpt
            chunk = prefix + body[: remaining - len(prefix)]
            chunks.append(chunk)
            citations.append(
                Citation(
                    page_id=result.id,
                    title=result.title,
                    url=result.url,
                    score=result.score,
                    excerpt=result.excerpt,
                )
            )
            remaining -= len(chunk) + 2
            if remaining <= 0:
                break

        return "\n\n".join(chunks), citations


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1_000)

