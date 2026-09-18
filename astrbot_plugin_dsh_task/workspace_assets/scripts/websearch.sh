#!/usr/bin/env bash
# Tavily 检索入口（方案 §5.2/§5.3）：经插件 sidecar 走，密钥不进本环境、不落本目录。
# 用法: websearch.sh "<关键词>" [条数=5]
set -euo pipefail
Q="$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "${1:?用法: websearch.sh <query> [max]}")"
MAX="${2:-5}"
PORT="${DSH_SIDECAR_PORT:-18234}"
if ! curl -sf --max-time 40 "http://127.0.0.1:${PORT}/search?q=${Q}&max=${MAX}"; then
  echo '{"error":"sidecar 不可达：确认 dsh_task 插件已启用且配置了 tavily_api_key"}'
fi
echo
