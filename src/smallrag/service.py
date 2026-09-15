from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from time import perf_counter

from smallrag.clients import KnowledgeBaseClient, OpenAICompatibleClient
from smallrag.config import Settings
from smallrag.errors import ConfigurationError
from smallrag.models import (
    Citation,
    ContextChunk,
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

_CONTEXT_CHUNK_CHARS = 1_200
_CONTEXT_CHUNK_OVERLAP = 160
_BREAK_MARKERS = ("\n\n", "\n", "。", "！", "？", ". ", "; ", "；")


@dataclass
class FetchedPage:
    result_index: int
    content: str


class RAGService:
    def __init__(self, settings: Settings, kb: KnowledgeBaseClient, model: OpenAICompatibleClient) -> None:
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
        context, citations, contexts = self._build_context(
            retrieval,
            pages,
            request.query,
            request.max_context_chars or self.settings.rag_default_max_context_chars,
        )
        page_fetch_ms = _elapsed_ms(fetch_started)

        model_name = request.model or self.settings.llm_model
        if not model_name:
            raise ConfigurationError("LLM_MODEL must be configured or supplied in the request")

        prompt = f"Confluence context:\n\n{context or '[No relevant context was retrieved.]'}\n\nQuestion:\n{request.query}"
        generation_started = perf_counter()
        answer, usage = await self.model.generate(
            model=model_name,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            enable_thinking=self.settings.llm_enable_thinking,
        )
        generation_ms = _elapsed_ms(generation_started)

        return QueryResponse(
            request_id=request_id,
            answer=answer,
            model=model_name,
            citations=citations,
            contexts=contexts,
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
                "ok": self.model.configured and bool(self.settings.llm_model),
                "detail": "configured" if self.model.configured and self.settings.llm_model else "missing required model settings",
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
        query: str,
        max_chars: int,
    ) -> tuple[str, list[Citation], list[ContextChunk]]:
        chunks: list[str] = []
        citations: list[Citation] = []
        contexts: list[ContextChunk] = []
        remaining = max_chars

        for page in pages:
            result = retrieval.results[page.result_index]
            citation_number = len(citations) + 1
            prefix = f"[{citation_number}] {result.title}\nURL: {result.url}\n"
            if remaining <= len(prefix):
                break
            full_body = page.content or result.excerpt
            body, reduced = _select_relevant_passage(full_body, query, result.excerpt)
            available_body_chars = remaining - len(prefix)
            chunk = prefix + body[:available_body_chars]
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
            contexts.append(
                ContextChunk(
                    chunk_id=f"context:{result.id}",
                    document_id=result.id,
                    document_name=result.title,
                    content=chunk,
                    source=result.url,
                    rank=citation_number,
                    retrieval_score=result.score,
                    truncated=reduced or len(body) > available_body_chars,
                )
            )
            remaining -= len(chunk) + 2
            if remaining <= 0:
                break

        return "\n\n".join(chunks), citations, contexts


def _select_relevant_passage(content: str, query: str, excerpt: str) -> tuple[str, bool]:
    passages = _split_content(content)
    if len(passages) <= 1:
        return (passages[0] if passages else content.strip()), False

    query_features = _text_features(query)
    excerpt_features = _text_features(excerpt)

    def score(passage: str) -> float:
        passage_features = _text_features(passage)
        query_coverage = _feature_coverage(query_features, passage_features)
        excerpt_coverage = _feature_coverage(excerpt_features, passage_features)
        return query_coverage + (2 * excerpt_coverage)

    return max(passages, key=score), True


def _split_content(content: str) -> list[str]:
    text = content.strip()
    if not text:
        return []
    if len(text) <= _CONTEXT_CHUNK_CHARS:
        return [text]

    passages: list[str] = []
    blocks = [block.strip() for block in re.split(r"\n+", text) if block.strip()]
    for block in blocks:
        if len(block) <= _CONTEXT_CHUNK_CHARS:
            passages.append(block)
            continue

        start = 0
        while start < len(block):
            proposed_end = min(start + _CONTEXT_CHUNK_CHARS, len(block))
            end = proposed_end
            if proposed_end < len(block):
                minimum_break = start + (_CONTEXT_CHUNK_CHARS // 2)
                boundary = max(
                    (
                        block.rfind(marker, minimum_break, proposed_end) + len(marker)
                        for marker in _BREAK_MARKERS
                    ),
                    default=0,
                )
                if boundary > minimum_break:
                    end = boundary

            passage = block[start:end].strip()
            if passage:
                passages.append(passage)
            if end >= len(block):
                break
            start = max(end - _CONTEXT_CHUNK_OVERLAP, start + 1)

    return passages


def _text_features(text: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", "", text.lower())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def _feature_coverage(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 0.0


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1_000)
