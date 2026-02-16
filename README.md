# nanobot-viking

[English](#english) | [中文](#中文)

---

<a name="english"></a>

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

Both are available on [SiliconFlow](https://siliconflow.cn) — see [Free Models](#siliconflow-free-models) section below.

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

### Add resource example

```bash
curl -X POST http://localhost:18790/api/viking/add \
  -H "Content-Type: application/json" \
  -d '{"path": "/tmp/my_document.md"}'

# Supported: .md, .txt, .pdf, images (via DeepSeek-OCR)
```

## CLI Tool

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

### Timeouts

| Operation | Timeout |
|-----------|---------|
| search, ls, read, abstract | 15s |
| find | 30s |
| add_resource | 120s |
| retrieve_context (RAG) | 10s |

## Design Decisions

### No auto-store of conversations

Viking's `commit_session` calls the embedding API which takes 10-30 seconds per conversation turn. This would block the single worker thread, freezing all queries. Since nanobot already persists conversations in JSONL files, auto-storing to Viking provides little value at a high cost. Use `viking add` to manually curate important knowledge.

### Graceful degradation

If OpenViking fails to initialize (missing config, AGFS timeout, etc.), the server continues to work normally — Viking is simply disabled. The health endpoint reports `viking_ready: false`, and the web console hides the Knowledge Base UI.

### AGFS restart after power loss

After an unclean shutdown, stale AGFS processes may prevent Viking from initializing:

```bash
killall agfs-server
systemctl restart nanobot-api
```

## SiliconFlow Free Models

The embedding model (`BAAI/bge-m3`) and VLM model (`DeepSeek-OCR`) required by this project are both **available on the free tier** of [SiliconFlow](https://siliconflow.cn). No cost to get started with semantic search and document indexing.

Register via referral link for bonus credits: **https://cloud.siliconflow.cn/i/UzI0F3Xv**

<img src="siliconflow-qr.png" alt="SiliconFlow QR Code" width="200">

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

---

<a name="中文"></a>

# nanobot-viking（中文）

为 [nanobot](https://github.com/pinkponk/nanobot) 集成 [OpenViking](https://github.com/pinkponk/openviking) 知识库。为你的 nanobot 部署添加语义搜索、RAG 上下文增强和知识管理 API。

## 功能

- **RAG 上下文增强** — 自动检索知识库中的相关内容，注入到用户消息中再发给 LLM，提升回答质量
- **语义搜索 API** — 通过 HTTP 接口搜索文档和记忆
- **资源管理** — 通过 API 添加文件（Markdown、PDF、图片）到知识库，自动分块、向量化、索引
- **文件浏览 API** — 浏览 `viking://` 虚拟文件系统
- **CLI 命令行工具** — 搜索、添加、浏览等知识库操作
- **Web UI 兼容** — 配合 [nanobot-web-console](https://github.com/tankyhsu/nanobot-web-console) 实现可视化知识浏览和搜索

## 架构

```
┌──────────────────────────────────────────────────┐
│                  FastAPI 服务                      │
│                                                    │
│  /api/chat ──→ augment_with_context() ──→ Agent   │
│                      ↕                             │
│  /api/viking/* ──→ VikingService                  │
│                      │ (异步封装)                   │
│                      ↓                             │
│              ┌──────────────┐                      │
│              │  工作线程     │  ← 单线程            │
│              │              │     (队列串行化)      │
│              │ SyncOpenViking│                      │
│              └──────┬───────┘                      │
│                     ↓                              │
│              AGFS (Go 二进制)  ← 端口 1833         │
│              向量 API          ← SiliconFlow 等    │
└──────────────────────────────────────────────────┘
```

### 为什么用单工作线程？

OpenViking 的 `SyncOpenViking` **非线程安全**，多线程并发访问会导致死锁。所有操作通过单一工作线程和队列串行执行。异步封装（`run_async`）将同步操作桥接到 FastAPI 的事件循环。

## 快速开始

### 1. 安装 OpenViking

```bash
pip install openviking
```

### 2. 配置向量服务

创建 `~/.openviking/ov.conf`（参考 [examples/ov.conf.example](examples/ov.conf.example)）：

```json
{
  "embedding": {
    "dense": {
      "api_base": "https://api.siliconflow.cn/v1",
      "api_key": "你的API密钥",
      "provider": "openai",
      "dimension": 1024,
      "model": "BAAI/bge-m3"
    }
  },
  "vlm": {
    "api_base": "https://api.siliconflow.cn/v1",
    "api_key": "你的API密钥",
    "provider": "openai",
    "model": "deepseek-ai/DeepSeek-OCR"
  }
}
```

**向量模型**（`BAAI/bge-m3`）：生成语义搜索用的向量嵌入，1024 维，8192 token 上下文。

**视觉模型**（`DeepSeek-OCR`）：从图片和 PDF 中提取文字，用于知识库资源索引。

两个模型在 [SiliconFlow（硅基流动）](https://siliconflow.cn) 上均可**免费使用**。也支持 OpenAI、Azure 或任何 OpenAI 兼容 API。

### 3. 部署

```bash
cp viking_service.py viking_routes.py /path/to/your/nanobot-api/
cp viking_cli.py /usr/local/bin/viking && chmod +x /usr/local/bin/viking
```

### 4. 集成到服务

```python
from viking_service import VikingService
from viking_routes import create_viking_router, augment_with_context

# 启动时:
viking = VikingService()
viking.start_worker()

# 挂载路由:
app.include_router(create_viking_router(viking))

# 在对话接口中 — RAG 增强:
augmented = await augment_with_context(viking, user_message)
response = await agent.process(content=augmented, ...)
```

完整示例见 [examples/server_integration.py](examples/server_integration.py)。

## CLI 命令行工具

```bash
viking search "树莓派服务"
viking find "网络配置"
viking add /path/to/document.md
viking ls
viking sessions
```

## 异常恢复

断电后 AGFS 进程可能残留，导致 Viking 初始化失败：

```bash
killall agfs-server
systemctl restart nanobot-api
```

## SiliconFlow 免费模型

本项目使用的向量模型（`BAAI/bge-m3`）和视觉模型（`DeepSeek-OCR`）在 [SiliconFlow（硅基流动）](https://siliconflow.cn) 上均可**免费体验**，零成本即可开始使用语义搜索和文档索引。

通过推荐链接注册可获得额外赠送额度：**https://cloud.siliconflow.cn/i/UzI0F3Xv**

<img src="siliconflow-qr.png" alt="SiliconFlow 二维码" width="200">

## 许可证

MIT
