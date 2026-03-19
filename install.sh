#!/usr/bin/env bash
# install.sh — nanobot-viking 一键安装脚本
# 用法：在 nanobot-web-console 目录执行：
#   curl -fsSL https://raw.githubusercontent.com/tankyhsu/nanobot-viking/main/install.sh | bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
DEST_DIR="${PWD}"
VIKING_SERVICE="viking_service.py"
GITHUB_RAW="https://raw.githubusercontent.com/tankyhsu/nanobot-viking/main"

echo "============================================"
echo "  nanobot-viking 一键安装脚本"
echo "  目标目录: ${DEST_DIR}"
echo "============================================"

# ---------- 1. 安装 openviking ----------
echo ""
echo "[1/2] 检测 / 安装 openviking..."

if python3 -c "import openviking" 2>/dev/null; then
    echo "  ✅ openviking 已安装，跳过"
else
    echo "  📦 正在安装 openviking..."
    if python3 -m pip install openviking; then
        echo "  ✅ openviking 安装成功"
    else
        echo "  ❌ pip install openviking 失败" >&2
        echo "     请尝试：pip3 install openviking 或 python3 -m pip install --user openviking" >&2
        exit 1
    fi
fi

# ---------- 2. 复制 viking_service.py ----------
echo ""
echo "[2/2] 安装 ${VIKING_SERVICE} 到 ${DEST_DIR}..."

# 判断是否在仓库目录内执行（本地开发场景）
if [ -f "${SCRIPT_DIR}/${VIKING_SERVICE}" ] && [ "${SCRIPT_DIR}" != "${DEST_DIR}" ]; then
    cp "${SCRIPT_DIR}/${VIKING_SERVICE}" "${DEST_DIR}/${VIKING_SERVICE}"
    echo "  ✅ 从本地仓库复制"
elif [ -f "${DEST_DIR}/${VIKING_SERVICE}" ]; then
    echo "  ✅ ${VIKING_SERVICE} 已存在，跳过下载"
else
    echo "  ⬇️  从 GitHub 下载 ${VIKING_SERVICE}..."
    if curl -fsSL "${GITHUB_RAW}/${VIKING_SERVICE}" -o "${DEST_DIR}/${VIKING_SERVICE}"; then
        echo "  ✅ 下载成功"
    else
        echo "  ❌ 下载失败，请检查网络或手动下载：" >&2
        echo "     ${GITHUB_RAW}/${VIKING_SERVICE}" >&2
        exit 1
    fi
fi

# ---------- 完成 ----------
echo ""
echo "============================================"
echo "  ✅ 安装完成！"
echo ""
echo "  下一步：重启 server.py 后刷新页面，"
echo "  状态栏应显示 \"Viking ON\"。"
echo "============================================"
