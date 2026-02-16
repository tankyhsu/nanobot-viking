# nanobot-viking

[OpenViking](https://github.com/pinkponk/openviking) knowledge base integration for [nanobot](https://github.com/pinkponk/nanobot). Adds semantic search, RAG context augmentation, and knowledge management APIs to your nanobot deployment.

## What it does

- **RAG Augmentation** — Automatically retrieves relevant knowledge base context and injects it into user messages before they reach the LLM, improving answer quality
- **Semantic Search API** — Search and deep-search across documents and memories via HTTP endpoints
- **Resource Management** — Add files (Markdown, PDF, images) to the knowledge base via API; content is chunked, embedded, and indexed automatically
- **File Browser API** — Browse the `viking://` virtual filesystem
- **CLI Tool** — Command-line interface for knowledge base operations (search, add, ls, etc.)
- **Web UI Compatible** — Works with [nanobot-web-console](https://github.com/tankyhsu/nanobot-web-console) for visual knowledge browsing and search

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  FastAPI Server                    │
│                                                    │
│  /api/chat ──→ augment_with_context() ──→ Agent   │
│                      ↕                             │
│  /api/viking/* ──→ VikingService                  │
│                      │ (async wrapper)             │
│                      ↓                             │
│              ┌──────────────┐                      │
│              │ Worker Thread │  ← single thread    │
│              │              │     (queue-based)    │
│              │ SyncOpenViking│                      │
│              └──────┬───────┘                      │
│                     ↓                              │
│              AGFS (Go binary)  ← port 1833        │
│              Embedding API     ← SiliconFlow/etc  │
└──────────────────────────────────────────────────┘
```

### Why a single worker thread?

OpenViking's `SyncOpenViking` is **not thread-safe** — concurrent access from multiple threads causes hangs. All operations are serialized through a single dedicated worker thread with a queue. The async wrapper (`run_async`) bridges this to FastAPI's event loop with configurable timeouts.

Read operations (search, ls, etc.) timeout at 15s. Write operations (add_resource) timeout at 120s.

## Setup

### 1. Install OpenViking

```bash
pip install openviking
```

### 2. Configure embedding provider

Create `~/.openviking/ov.conf` (see [examples/ov.conf.example](examples/ov.conf.example)):

```json
{
  "embedding": {
    "dense": {
      "api_base": "https://api.siliconflow.cn/v1",
      "api_key": "YOUR_API_KEY",
      "provider": "openai",
      "dimension": 1024,
      "model": "BAAI/bge-m3"
    }
  },
  "vlm": {
    "api_base": "https://api.siliconflow.cn/v1",
    "api_key": "YOUR_API_KEY",
    "provider": "openai",
    "model": "deepseek-ai/DeepSeek-OCR"
  }
}
```

**Embedding model** (`BAAI/bge-m3`): Generates vector embeddings for semantic search. 1024 dimensions, 8192 token context.

**VLM model** (`DeepSeek-OCR`): Extracts text from images and PDFs when adding visual resources to the knowledge base.

Both are available on [SiliconFlow](https://siliconflow.cn). You can also use OpenAI, Azure, or any OpenAI-compatible API.

### 3. Copy files to your nanobot-api directory

```bash
cp viking_service.py viking_routes.py /path/to/your/nanobot-api/
cp viking_cli.py /usr/local/bin/viking && chmod +x /usr/local/bin/viking
```

### 4. Integrate into your server

```python
from viking_service import VikingService
from viking_routes import create_viking_router, augment_with_context

# In your lifespan:
viking = VikingService()
viking.start_worker()

# Mount routes:
app.include_router(create_viking_router(viking))

# In your chat endpoint — RAG augmentation:
augmented = await augment_with_context(viking, user_message)
response = await agent.process(content=augmented, ...)
```

See [examples/server_integration.py](examples/server_integration.py) for the full pattern.

### 5. Update health check

Report `viking_ready` so the web console knows whether to show the Knowledge Base UI:

```python
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_ready": agent is not None,
        "viking_ready": viking is not None and viking.ready,
    }
```

## API Endpoints

All endpoints are mounted under `/api/viking/` via the router.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/viking/status` | GET | Check if Viking is ready |
| `/api/viking/search` | POST | Semantic search `{"query": "...", "limit": 5}` |
| `/api/viking/find` | POST | Deep search (broader scope) `{"query": "...", "limit": 10}` |
| `/api/viking/add` | POST | Add file to knowledge base `{"path": "/tmp/doc.md"}` |
| `/api/viking/ls` | GET | Browse directory `?uri=viking://resources/` |
| `/api/viking/sessions` | GET | List Viking sessions |

### Search example

```bash
curl -X POST http://localhost:18790/api/viking/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how to configure network", "limit": 5}'
```

```json
{
  "result": "搜索 'how to configure network' 找到 2 条结果:\n\n[资源:setup_guide] Network configuration guide..."
}
```

### Add resource example

```bash
# Add a markdown document
curl -X POST http://localhost:18790/api/viking/add \
  -H "Content-Type: application/json" \
  -d '{"path": "/tmp/my_document.md"}'

# Supported: .md, .txt, .pdf, images (via DeepSeek-OCR)
```

## CLI Tool

`viking_cli.py` provides command-line access through the HTTP API (no direct OpenViking dependency needed):

```bash
viking search "raspberry pi services"
viking find "network configuration"
viking add /path/to/document.md
viking ls
viking ls viking://resources/my_project/
viking sessions
viking help
```

The CLI calls the nanobot-api HTTP endpoints, so the server must be running.

## Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENVIKING_CONFIG_FILE` | `~/.openviking/ov.conf` | Path to OpenViking config |

### VikingService constructor

```python
viking = VikingService(
    data_dir="/custom/path/to/data",  # default: ~/.openviking/data
)
```

### Timeouts

| Operation | Timeout | Configurable via |
|-----------|---------|-----------------|
| search, ls, read, abstract | 15s | `run_async(..., timeout=)` |
| find | 30s | `run_async(..., timeout=)` |
| add_resource | 120s | `run_async(..., timeout=)` |
| retrieve_context (RAG) | 10s | `run_async(..., timeout=)` |

## Design Decisions

### No auto-store of conversations

Viking's `commit_session` calls the embedding API which takes 10-30 seconds per conversation turn. This would block the single worker thread, freezing all queries. Since nanobot already persists conversations in JSONL files, auto-storing to Viking provides little value at a high cost. Use `viking add` to manually curate important knowledge.

### Graceful degradation

If OpenViking fails to initialize (missing config, AGFS timeout, etc.), the server continues to work normally — Viking is simply disabled. The health endpoint reports `viking_ready: false`, and the web console hides the Knowledge Base UI.

### AGFS restart after power loss

After an unclean shutdown, stale AGFS processes may prevent Viking from initializing. Fix:

```bash
killall agfs-server
systemctl restart nanobot-api
```

## File Structure

```
viking_service.py       # Core service: single-threaded async wrapper for OpenViking
viking_routes.py        # FastAPI router + RAG augmentation helper
viking_cli.py           # CLI tool (uses HTTP API)
examples/
  server_integration.py # How to integrate into your FastAPI server
  ov.conf.example       # OpenViking config template
```

## License

MIT
