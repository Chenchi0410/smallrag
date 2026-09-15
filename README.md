# SmallRAG

SmallRAG is a deliberately small, evaluation-friendly RAG baseline. It reuses the existing
Confluence hybrid-search service as its retriever, fetches the selected pages, selects a bounded
query-relevant passage from each page, and calls an OpenAI-compatible Qwen chat API to generate a
cited answer.

## API

- `POST /v1/retrieve` — retrieval only, for retriever evaluation
- `POST /v1/query` — end-to-end retrieval and answer generation
- `GET /` — browser UI showing the answer and exact retrieved contexts
- `GET /health` — process liveness
- `GET /ready` — knowledge-base availability and model-configuration readiness
- `GET /docs` — interactive OpenAPI documentation

The query response includes the answer, citations, the exact `contexts` sent to the model,
raw retrieval results (optional), token usage, per-stage latency, model name, and request ID.
This metadata is intended for later evaluation.

## Model services

SmallRAG uses the locally deployed `qwen3-8b` service through the OpenAI-compatible Chat
Completions API:

```text
LLM_BASE_URL=http://10.245.65.19:11082
LLM_MODEL=qwen3-8b
```

Connectivity can be checked with:

```bash
curl --connect-timeout 5 http://10.245.65.19:11082/v1/models
```

The available `qwen3-embedding-0.6b` service at `http://10.245.65.19:11081` is not called by
SmallRAG. Retrieval and ranking are already provided by the Confluence hybrid-search service, so
adding a second embedding step here would duplicate that responsibility. The evaluation platform
may use the embedding service independently for semantic metrics.

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
LLM_BASE_URL=http://10.245.65.19:11082
LLM_API_KEY=
LLM_MODEL=qwen3-8b
LLM_ENABLE_THINKING=false
```

Create a local self-signed certificate (or use a certificate issued by your CA):

```powershell
New-Item -ItemType Directory -Force certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 `
  -keyout certs/server.key -out certs/server.crt `
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

For local development, change the certificate paths in `.env` to
`certs/server.crt` and `certs/server.key`, then start the HTTPS API:

```powershell
.venv\Scripts\python -m smallrag.run
```

Then open <https://127.0.0.1:18082/> for the UI or
<https://127.0.0.1:18082/docs> for OpenAPI. A browser warning is expected for a self-signed
certificate.

## Example requests

Retrieve documents without calling the model:

```powershell
Invoke-RestMethod -SkipCertificateCheck -Method Post -Uri https://127.0.0.1:18082/v1/retrieve `
  -ContentType application/json `
  -Body '{"query":"How does the firmware update process work?","top_k":5,"alpha":0.5}'
```

Run the full RAG pipeline:

```powershell
Invoke-RestMethod -SkipCertificateCheck -Method Post -Uri https://127.0.0.1:18082/v1/query `
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

The default HTTPS service port is `18082`.
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

LLM_BASE_URL=http://10.245.65.19:11082
LLM_API_KEY=
LLM_MODEL=qwen3-8b
LLM_VERIFY_SSL=true
LLM_ENABLE_THINKING=false

SERVER_PORT=18082
HTTPS_CERTFILE=/certs/server.crt
HTTPS_KEYFILE=/certs/server.key
```

The two upstream URLs must be reachable from inside the container. Do not use `127.0.0.1`
for a service running on the Ubuntu host; use its LAN address or `host.docker.internal`.

Build and start SmallRAG:

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/server.key -out certs/server.crt \
  -subj "/CN=$(hostname)" -addext "subjectAltName=DNS:$(hostname)"
sudo chown 10001:10001 certs/server.crt certs/server.key
sudo chmod 600 certs/server.key
docker build -t smallrag:latest .
docker run -d \
  --name smallrag \
  --restart unless-stopped \
  --env-file .env \
  --add-host host.docker.internal:host-gateway \
  -v "$(pwd)/certs:/certs:ro" \
  -p 18082:18082 \
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
curl -k https://127.0.0.1:18082/health
curl -k https://127.0.0.1:18082/ready
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
  -v "$(pwd)/certs:/certs:ro" \
  -p 18082:18082 \
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
sudo mkdir -p /opt/smallrag/certs
sudo openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout /opt/smallrag/certs/server.key -out /opt/smallrag/certs/server.crt \
  -subj "/CN=$(hostname)" -addext "subjectAltName=DNS:$(hostname)"
sudo chown -R smallrag:smallrag /opt/smallrag/certs
```

For this non-container deployment, set these paths in `/opt/smallrag/.env`:

```dotenv
HTTPS_CERTFILE=/opt/smallrag/certs/server.crt
HTTPS_KEYFILE=/opt/smallrag/certs/server.key
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
ExecStart=/opt/smallrag/.venv/bin/python -m smallrag.run
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
curl -k https://127.0.0.1:18082/ready
```

If UFW is enabled, restrict access to the evaluation server:

```bash
sudo ufw allow from <EVALUATION_SERVER_IP> to any port 18082 proto tcp
```

## Connect the evaluation platform

From the evaluation server, first confirm network access:

```bash
curl --cacert <CA_CERTIFICATE> https://<SMALLRAG_SERVER_IP>:18082/ready
```

In the generic RAG auto-detection page, enter this base URL:

```text
https://<SMALLRAG_SERVER_IP>:18082
```

The evaluator will probe `/v1/query`, send the question in the `query` field, and discover the
top-level `answer` plus the `contexts` retrieval array. You may also enter the full endpoint
`https://<SMALLRAG_SERVER_IP>:18082/v1/query`.

The image runs as a non-root user and exposes a Docker health check. Secrets are read only from
runtime environment variables. `.env` is ignored by both Git and Docker build context; do not put
credentials in source files or commit them to Git.
