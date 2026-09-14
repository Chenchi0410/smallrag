from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from smallrag.errors import ConfigurationError, UpstreamError
from smallrag.models import SearchResult, TokenUsage


class KnowledgeBaseClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        verify_ssl: bool,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            verify=verify_ssl,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, top_k: int, alpha: float) -> tuple[list[SearchResult], int]:
        data = await self._request("POST", "/search", json={"query": query, "top_k": top_k, "alpha": alpha})
        try:
            results = [SearchResult.model_validate(item) for item in data.get("results", [])]
            return results, int(data.get("total", len(results)))
        except (ValidationError, TypeError, ValueError) as exc:
            raise UpstreamError("knowledge_base", "Knowledge base returned an invalid search response") from exc

    async def fetch_page(self, page_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/pages/{page_id}")
        if not isinstance(data.get("content"), str):
            raise UpstreamError("knowledge_base", "Knowledge base returned an invalid page response")
        return data

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("JSON root is not an object")
            return data
        except httpx.TimeoutException as exc:
            raise UpstreamError("knowledge_base", "Knowledge base request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                "knowledge_base", f"Knowledge base returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError("knowledge_base", "Knowledge base request failed") from exc


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        *,
        verify_ssl: bool,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._configured = bool(base_url)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=(base_url or "http://unconfigured.invalid").rstrip("/"),
            headers=headers,
            verify=verify_ssl,
            timeout=timeout,
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return self._configured

    async def close(self) -> None:
        await self._client.aclose()

    async def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        enable_thinking: bool,
    ) -> tuple[str, TokenUsage]:
        if not self._configured:
            raise ConfigurationError("LLM_BASE_URL must be configured")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        try:
            response = await self._client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("JSON root is not an object")
            choices = data.get("choices") or []
            message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
            answer = message.get("content", "").strip() if isinstance(message, dict) else ""
            if not answer:
                raise ValueError("response does not contain choices[0].message.content")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError("usage is not an object")
            return answer, TokenUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError("model", "Model request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise UpstreamError("model", f"Model gateway returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise UpstreamError("model", "Model gateway returned an invalid response") from exc
