"""OpenViking service wrapper for nanobot integration.

All OpenViking read operations run in a single dedicated worker thread.
Write operations (add_resource) also use this thread but with longer timeouts.
Conversation auto-store is disabled to avoid blocking queries.
"""

import asyncio
import logging
import os
import queue
import threading
from typing import Any, Optional

logger = logging.getLogger("viking_service")

OV_CONFIG = os.environ.get("OPENVIKING_CONFIG_FILE", os.path.expanduser("~/.openviking/ov.conf"))
os.environ.setdefault("OPENVIKING_CONFIG_FILE", OV_CONFIG)


class _Request:
    __slots__ = ("fn", "args", "event", "result", "error")

    def __init__(self, fn, args):
        self.fn = fn
        self.args = args
        self.event = threading.Event()
        self.result = None
        self.error = None


class VikingService:
    """Single-threaded OpenViking service wrapper."""

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.expanduser("~/.openviking/data")
        self._ov = None
        self._ready = False
        self._queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None

    def _ensure_init(self):
        if self._ov is None:
            from openviking import SyncOpenViking
            self._ov = SyncOpenViking(data_dir=self.data_dir)
            self._ov.initialize()
            self._ready = True
            logger.info(f"OpenViking initialized, data_dir={self.data_dir}")

    def start_worker(self):
        """Start the single worker thread."""
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="viking-worker")
        self._worker.start()

    def _worker_loop(self):
        self._ensure_init()
        while True:
            try:
                req = self._queue.get(timeout=60)
                if req is None:
                    break
                try:
                    req.result = req.fn(*req.args)
                except Exception as e:
                    req.error = e
                    logger.error(f"Viking worker error in {req.fn.__name__}: {e}")
                finally:
                    req.event.set()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Viking worker loop error: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    async def run_async(self, fn, *args, timeout: float = 15.0):
        """Submit to worker thread and await result with timeout."""
        req = _Request(fn, args)
        self._queue.put(req)
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: req.event.wait(timeout) and req.result),
                timeout=timeout + 2
            )
            if req.error:
                raise req.error
            if not req.event.is_set():
                logger.error(f"Viking operation timed out: {fn.__name__}")
                return None
            return req.result
        except asyncio.TimeoutError:
            logger.error(f"Viking async timeout: {fn.__name__}")
            return None
        except Exception as e:
            logger.error(f"Viking async error: {fn.__name__}: {e}")
            return None

    # --- Sync operations (run in worker thread) ---

    def _search(self, query: str, limit: int = 5) -> str:
        results = self._ov.search(query, limit=limit)
        output = []
        total = results.total

        if results.memories:
            for mem in results.memories:
                content = getattr(mem, "content", str(mem))
                output.append(f"[记忆] {content[:300]}")

        if results.resources:
            for res in results.resources:
                uri = getattr(res, "uri", "")
                abstract = getattr(res, "abstract", "")
                content = getattr(res, "content", "") or abstract
                output.append(f"[资源:{uri}] {content[:300]}")

        if not output:
            return f"搜索 '{query}' 无结果 (total={total})"
        return f"搜索 '{query}' 找到 {total} 条结果:\n\n" + "\n\n".join(output)

    def _find(self, query: str, limit: int = 10) -> str:
        results = self._ov.find(query, limit=limit)

        if hasattr(results, "total") and results.total == 0:
            return f"深度搜索 '{query}' 无结果"

        output = []
        if hasattr(results, "memories"):
            for mem in (results.memories or []):
                content = getattr(mem, "content", str(mem))
                output.append(f"[记忆] {content[:300]}")
        if hasattr(results, "resources"):
            for res in (results.resources or []):
                uri = getattr(res, "uri", "")
                abstract = getattr(res, "abstract", "")
                content = getattr(res, "content", "") or abstract
                output.append(f"[资源:{uri}] {content[:300]}")

        total = getattr(results, "total", len(output))
        if not output:
            return f"深度搜索 '{query}' 无结果"
        return f"深度搜索 '{query}' 找到 {total} 条:\n\n" + "\n\n".join(output)

    def _add_resource(self, path: str) -> str:
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        result = self._ov.add_resource(path, wait=True, timeout=120)
        status = result.get("status", "unknown")
        errors = result.get("errors", [])
        uri = result.get("root_uri", "")
        if errors:
            return f"添加资源失败: {', '.join(errors)}"
        return f"资源已添加: {uri} (status={status})"

    def _ls(self, uri: str = "viking://resources/") -> str:
        items = self._ov.ls(uri)
        if not items:
            return f"目录 {uri} 为空"
        lines = []
        for item in items:
            name = item.get("name", "")
            is_dir = item.get("isDir", False)
            size = item.get("size", 0)
            marker = "D" if is_dir else "F"
            lines.append(f"  [{marker}] {name} ({size}b)")
        return f"目录 {uri}:\n" + "\n".join(lines)

    def _read(self, uri: str) -> str:
        try:
            content = self._ov.read(uri)
            return content[:2000] if len(content) > 2000 else content
        except Exception as e:
            return f"读取失败: {e}"

    def _abstract(self, uri: str) -> str:
        try:
            return self._ov.abstract(uri)
        except Exception as e:
            return f"获取摘要失败: {e}"

    def _list_sessions(self) -> str:
        sessions = self._ov.list_sessions()
        if not sessions:
            return "暂无会话记录"
        lines = []
        for s in sessions[:20]:
            sid = s.get("session_id", "") if isinstance(s, dict) else str(s)
            lines.append(f"  - {sid}")
        return f"会话列表:\n" + "\n".join(lines)

    def _retrieve_context(self, query: str, limit: int = 3) -> str:
        results = self._ov.search(query, limit=limit)
        context_parts = []

        if results.memories:
            for mem in results.memories[:3]:
                content = getattr(mem, "content", str(mem))
                if content:
                    context_parts.append(f"[记忆] {content}")

        if results.resources:
            for res in results.resources[:3]:
                uri = getattr(res, "uri", "")
                abstract = getattr(res, "abstract", "")
                content = getattr(res, "content", "") or abstract
                title = getattr(res, "title", uri)
                if content:
                    context_parts.append(f"[知识库:{title}] {content[:500]}")

        return "\n\n".join(context_parts) if context_parts else ""

    # --- Public async API ---

    async def search(self, query: str, limit: int = 5) -> str:
        result = await self.run_async(self._search, query, limit, timeout=15)
        return result or f"搜索 '{query}' 超时"

    async def find(self, query: str, limit: int = 10) -> str:
        result = await self.run_async(self._find, query, limit, timeout=30)
        return result or f"深度搜索 '{query}' 超时"

    async def add_resource(self, path: str) -> str:
        result = await self.run_async(self._add_resource, path, timeout=120)
        return result or "添加资源超时"

    async def ls(self, uri: str = "viking://resources/") -> str:
        result = await self.run_async(self._ls, uri, timeout=15)
        return result or f"列出目录 {uri} 超时"

    async def read(self, uri: str) -> str:
        result = await self.run_async(self._read, uri, timeout=15)
        return result or "读取超时"

    async def abstract(self, uri: str) -> str:
        result = await self.run_async(self._abstract, uri, timeout=15)
        return result or "获取摘要超时"

    async def list_sessions(self) -> str:
        result = await self.run_async(self._list_sessions, timeout=15)
        return result or "获取会话列表超时"

    async def retrieve_context(self, query: str, limit: int = 3) -> str:
        result = await self.run_async(self._retrieve_context, query, limit, timeout=10)
        return result or ""

    def close(self):
        self._queue.put(None)
        if self._ov:
            try:
                self._ov.close()
            except Exception:
                pass
