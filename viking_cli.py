#!/usr/bin/env python3
"""Viking CLI - nanobot通过exec工具调用此脚本操作知识库。

用法:
  viking search <query>        搜索知识库
  viking find <query>          深度搜索（递归目录检索）
  viking add <file_path>       添加文件到知识库
  viking ls [uri]              列出目录内容
  viking sessions              列出会话记录
  viking help                  显示帮助

注意: 此CLI通过nanobot-api的HTTP接口操作Viking，需要nanobot-api服务运行中。
"""

import json
import sys
import urllib.request
import urllib.error

API_BASE = "http://127.0.0.1:18790"


def api_get(path):
    try:
        req = urllib.request.Request(f"{API_BASE}{path}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"API unavailable: {e}"}
    except Exception as e:
        return {"error": str(e)}


def api_post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"API unavailable: {e}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    args = sys.argv[1:]
    if not args or args[0] == "help":
        print(__doc__)
        return

    cmd = args[0]
    rest = " ".join(args[1:]) if len(args) > 1 else ""

    if cmd == "search":
        if not rest:
            print("用法: viking search <query>")
            return
        r = api_post("/api/viking/search", {"query": rest, "limit": 10})
        print(r.get("result", r.get("error", "Unknown error")))

    elif cmd == "find":
        if not rest:
            print("用法: viking find <query>")
            return
        r = api_post("/api/viking/find", {"query": rest, "limit": 10})
        print(r.get("result", r.get("error", "Unknown error")))

    elif cmd == "add":
        if not rest:
            print("用法: viking add <file_path>")
            return
        r = api_post("/api/viking/add", {"path": rest})
        print(r.get("result", r.get("error", "Unknown error")))

    elif cmd == "ls":
        uri = rest if rest else "viking://resources/"
        r = api_get(f"/api/viking/ls?uri={urllib.request.quote(uri)}")
        print(r.get("result", r.get("error", "Unknown error")))

    elif cmd == "sessions":
        r = api_get("/api/viking/sessions")
        print(r.get("result", r.get("error", "Unknown error")))

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
