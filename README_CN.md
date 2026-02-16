# nanobot-viking

**[English](README.md) | [中文](README_CN.md)**

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

### 5. 更新健康检查

报告 `viking_ready` 让 Web 控制台决定是否显示知识库 UI：

```python
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_ready": agent is not None,
        "viking_ready": viking is not None and viking.ready,
    }
```

## API 接口

所有接口通过路由挂载在 `/api/viking/` 下。

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/viking/status` | GET | 检查 Viking 是否就绪 |
| `/api/viking/search` | POST | 语义搜索 `{"query": "...", "limit": 5}` |
| `/api/viking/find` | POST | 深度搜索（更大范围） `{"query": "...", "limit": 10}` |
| `/api/viking/add` | POST | 添加文件到知识库 `{"path": "/tmp/doc.md"}` |
| `/api/viking/ls` | GET | 浏览目录 `?uri=viking://resources/` |
| `/api/viking/sessions` | GET | 列出 Viking 会话 |

### 搜索示例

```bash
curl -X POST http://localhost:18790/api/viking/search \
  -H "Content-Type: application/json" \
  -d '{"query": "如何配置网络", "limit": 5}'
```

### 添加资源示例

```bash
curl -X POST http://localhost:18790/api/viking/add \
  -H "Content-Type: application/json" \
  -d '{"path": "/tmp/my_document.md"}'

# 支持格式：.md, .txt, .pdf, 图片（通过 DeepSeek-OCR）
```

## CLI 命令行工具

```bash
viking search "树莓派服务"
viking find "网络配置"
viking add /path/to/document.md
viking ls
viking sessions
```

CLI 通过 HTTP API 调用 nanobot-api，需确保服务已启动。

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENVIKING_CONFIG_FILE` | `~/.openviking/ov.conf` | OpenViking 配置文件路径 |

### 超时设置

| 操作 | 超时 |
|------|------|
| search, ls, read, abstract | 15 秒 |
| find | 30 秒 |
| add_resource | 120 秒 |
| retrieve_context (RAG) | 10 秒 |

## 设计决策

### 不自动存储对话

Viking 的 `commit_session` 调用向量 API 需要 10-30 秒，会阻塞单工作线程导致所有查询冻结。nanobot 已通过 JSONL 持久化对话，自动存储到 Viking 性价比很低。建议使用 `viking add` 手动管理重要知识。

### 优雅降级

OpenViking 初始化失败（配置缺失、AGFS 超时等）时，服务正常运行，Viking 功能自动禁用。健康接口报告 `viking_ready: false`，Web 控制台自动隐藏知识库 UI。

### 断电后恢复

非正常关机后 AGFS 进程可能残留，导致 Viking 初始化失败：

```bash
killall agfs-server
systemctl restart nanobot-api
```

## SiliconFlow 免费模型

本项目使用的向量模型（`BAAI/bge-m3`）和视觉模型（`DeepSeek-OCR`）在 [SiliconFlow（硅基流动）](https://siliconflow.cn) 上均可**免费体验**，零成本即可开始使用语义搜索和文档索引。

通过推荐链接注册可获得额外赠送额度：**https://cloud.siliconflow.cn/i/UzI0F3Xv**

<img src="siliconflow-qr.png" alt="SiliconFlow 二维码" width="200">

## 文件结构

```
viking_service.py       # 核心服务：OpenViking 的单线程异步封装
viking_routes.py        # FastAPI 路由 + RAG 增强辅助函数
viking_cli.py           # CLI 命令行工具（通过 HTTP API）
examples/
  server_integration.py # 集成到 FastAPI 服务的完整示例
  ov.conf.example       # OpenViking 配置模板
```

## 许可证

MIT
