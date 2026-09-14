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

The query response includes the answer, citations, the exact `contexts` sent to the model,
raw retrieval results (optional), token usage, per-stage latency, model name, and request ID.
This metadata is intended for later evaluation.

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
.venv\Scripts\python -m uvicorn smallrag.main:app --host 0.0.0.0 --port 18081 --reload
```

Then open <http://127.0.0.1:18081/docs>.

## Example requests

Retrieve documents without calling the model:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:18081/v1/retrieve `
  -ContentType application/json `
  -Body '{"query":"How does the firmware update process work?","top_k":5,"alpha":0.5}'
```

Run the full RAG pipeline:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:18081/v1/query `
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

## Ubuntu deployment

The default service port is `18081`, avoiding commonly occupied ports such as 8000 and 8080.
Allow this port only from the RAG evaluation server or another trusted internal network.

### Option A: Docker (recommended)

Install Docker Engine, then clone and configure the service:

```bash
git clone https://github.com/Chenchi0410/smallrag.git
cd smallrag
cp .env.example .env
nano .env
```

Fill in at least these values in `.env`:

```dotenv
CONFLUENCE_KB_URL=https://your-confluence-kb-service
CONFLUENCE_KB_API_KEY=your-api-key
CONFLUENCE_KB_VERIFY_SSL=false

ANTHROPIC_BASE_URL=http://your-model-gateway
ANTHROPIC_AUTH_TOKEN=your-model-token
ANTHROPIC_MODEL=your-model-alias
ANTHROPIC_VERIFY_SSL=true
```

The two upstream URLs must be reachable from inside the container. Do not use `127.0.0.1`
for a service running on the Ubuntu host; use its LAN address or `host.docker.internal`.

Build and start SmallRAG:

```bash
docker build -t smallrag:latest .
docker run -d \
  --name smallrag \
  --restart unless-stopped \
  --env-file .env \
  --add-host host.docker.internal:host-gateway \
  -p 18081:18081 \
  smallrag:latest
```

If Docker Hub or PyPI is slow on the company network, the build sources can be overridden:

```bash
docker build \
  --build-arg PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim \
  --build-arg PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  -t smallrag:latest .
```

Check startup and readiness:

```bash
docker logs --tail=100 smallrag
curl http://127.0.0.1:18081/health
curl http://127.0.0.1:18081/ready
```

`/health` only confirms that the API process is running. `/ready` also checks the knowledge-base
connection and model configuration, and must return `status: ready` before evaluation.

To deploy a later version:

```bash
git pull --ff-only
docker build -t smallrag:latest .
docker rm -f smallrag
docker run -d \
  --name smallrag \
  --restart unless-stopped \
  --env-file .env \
  --add-host host.docker.internal:host-gateway \
  -p 18081:18081 \
  smallrag:latest
```

### Option B: Python virtual environment and systemd

Use this option when Docker is unavailable. Python 3.11 or newer is required.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
sudo git clone https://github.com/Chenchi0410/smallrag.git /opt/smallrag
sudo useradd --system --no-create-home --shell /usr/sbin/nologin smallrag
sudo chown -R smallrag:smallrag /opt/smallrag
sudo -u smallrag python3 -m venv /opt/smallrag/.venv
sudo -u smallrag /opt/smallrag/.venv/bin/python -m pip install /opt/smallrag
sudo -u smallrag cp /opt/smallrag/.env.example /opt/smallrag/.env
sudo nano /opt/smallrag/.env
```

Create `/etc/systemd/system/smallrag.service`:

```ini
[Unit]
Description=SmallRAG API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=smallrag
Group=smallrag
WorkingDirectory=/opt/smallrag
EnvironmentFile=/opt/smallrag/.env
ExecStart=/opt/smallrag/.venv/bin/python -m uvicorn smallrag.main:app --host 0.0.0.0 --port 18081
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Enable and verify the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now smallrag
sudo systemctl status smallrag --no-pager
sudo journalctl -u smallrag -n 100 --no-pager
curl http://127.0.0.1:18081/ready
```

If UFW is enabled, restrict access to the evaluation server:

```bash
sudo ufw allow from <EVALUATION_SERVER_IP> to any port 18081 proto tcp
```

## Connect the evaluation platform

From the evaluation server, first confirm network access:

```bash
curl http://<SMALLRAG_SERVER_IP>:18081/ready
```

In the generic RAG auto-detection page, enter this base URL:

```text
http://<SMALLRAG_SERVER_IP>:18081
```

The evaluator will probe `/v1/query`, send the question in the `query` field, and discover the
top-level `answer` plus the `contexts` retrieval array. You may also enter the full endpoint
`http://<SMALLRAG_SERVER_IP>:18081/v1/query`.

The image runs as a non-root user and exposes a Docker health check. Secrets are read only from
runtime environment variables. `.env` is ignored by both Git and Docker build context; do not put
credentials in source files or commit them to Git.
