# SmallRAG

SmallRAG is a deliberately small, evaluation-friendly RAG baseline. It reuses the existing
Confluence hybrid-search service as its retriever, fetches the selected pages, builds a bounded
context, and calls an Anthropic-compatible Messages API to generate a cited answer.

## API

- `POST /v1/retrieve` — retrieval only, for retriever evaluation
- `POST /v1/query` — end-to-end retrieval and answer generation
- `GET /health` — process liveness
- `GET /ready` — knowledge-base availability and model-configuration readiness
- `GET /docs` — interactive OpenAPI documentation

The query response includes the answer, citations, raw retrieval results (optional), token usage,
per-stage latency, model name, and request ID. This metadata is intended for later evaluation.

## Local setup

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` and set the real values. The model gateway's model alias is required:

```dotenv
CONFLUENCE_KB_API_KEY=...
ANTHROPIC_BASE_URL=http://model-gateway.example:4000
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_MODEL=your-model-alias
```

Start the API:

```powershell
.venv\Scripts\python -m uvicorn smallrag.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open <http://127.0.0.1:8000/docs>.

## Example requests

Retrieve documents without calling the model:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/retrieve `
  -ContentType application/json `
  -Body '{"query":"How does the firmware update process work?","top_k":5,"alpha":0.5}'
```

Run the full RAG pipeline:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/query `
  -ContentType application/json `
  -Body '{"query":"How does the firmware update process work?","top_k":5}'
```

Request fields such as `top_k`, `alpha`, `max_context_chars`, `model`, `max_tokens`, and
`temperature` can be overridden per evaluation case. Set `include_retrieval` to `false` if the
caller does not need raw retrieval results.

## Tests

Tests use in-memory upstream mocks and require no credentials or network access:

```powershell
.venv\Scripts\python -m pytest
```

## Docker

```powershell
docker build -t smallrag .
docker run --rm -p 8000:8000 --env-file .env smallrag
```

Secrets are read only from runtime environment variables. `.env` is ignored by both Git and
Docker build context; do not put credentials in source files.
