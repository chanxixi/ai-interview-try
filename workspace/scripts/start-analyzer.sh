#!/usr/bin/env bash
# ============================================================================
# 只启动 analyzer（Python / FastAPI）—— 不检查 node_modules，不要求 job-service 已打包
#
# 为什么单独有这个脚本：
#   `start-all.sh` 的前置检查是**全量**的：它默认要在同一次运行里把四个服务都拉起来，
#   所以只要 bff/web 的 node_modules 缺失或 job-service 的 jar 还没打包，就会 `exit 1`，
#   哪怕你只想跑 analyzer。做 M2/M3（解析 · 清洗 · 归一化）时反复被这个挡住，
#   于是把「只跑一层」的入口独立出来 —— 单体调试不该为别的服务的构建状态买单。
#
# 用法：
#   bash scripts/start-analyzer.sh              # 后台启动，等到 /healthz 通过才返回
#   bash scripts/start-analyzer.sh --fg         # 前台启动（Ctrl-C 停止），带 --reload
#   ANALYZER_PORT=8011 bash scripts/start-analyzer.sh    # 换端口
# 停止：
#   bash scripts/stop-all.sh analyzer           # 或 Ctrl-C（前台模式）
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}" || exit 1

PORT="${ANALYZER_PORT:-8000}"
HOST="${ANALYZER_HOST:-127.0.0.1}"
LOG_DIR="${ROOT}/.logs"
LOG="${LOG_DIR}/analyzer.log"
mkdir -p "${LOG_DIR}"

FG=0
[ "${1:-}" = "--fg" ] && FG=1

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_FAIL=$'\033[31m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
else
  C_OK=''; C_FAIL=''; C_DIM=''; C_0=''
fi
ok()   { printf '  %sOK%s    %s\n' "${C_OK}" "${C_0}" "$1"; }
bad()  { printf '  %sFAIL%s  %s\n' "${C_FAIL}" "${C_0}" "$1"; }
info() { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_0}"; }

# ---- 1. 找解释器：项目 venv 优先 -------------------------------------------
PY="${ROOT}/apps/analyzer/.venv/Scripts/python.exe"
[ -x "${PY}" ] || PY="${ROOT}/apps/analyzer/.venv/bin/python"
if [ ! -x "${PY}" ]; then
  bad "analyzer 虚拟环境不存在：apps/analyzer/.venv"
  info "先执行： cd apps/analyzer && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt"
  exit 1
fi
ok "venv      ${PY}"

# ---- 2. 端口占用：已在跑就不再起一个 ---------------------------------------
if netstat -ano 2>/dev/null | grep -q "LISTENING.*:${PORT}[[:space:]]"; then
  info "端口 ${PORT} 已被占用 —— 可能已经在运行，直接用即可"
  info "健康检查： curl http://${HOST}:${PORT}/healthz"
  info "想换端口： ANALYZER_PORT=8011 bash scripts/start-analyzer.sh"
  exit 0
fi
ok "端口      ${PORT} 空闲"

# ---- 3. 启动 ----------------------------------------------------------------
# cwd 必须是 apps/analyzer：config.py 的 env_file=".env" 按**进程 CWD** 解析。
if [ "${FG}" = "1" ]; then
  info "前台启动（Ctrl-C 停止）→ http://${HOST}:${PORT}/docs"
  cd "${ROOT}/apps/analyzer" && exec "${PY}" -m uvicorn app.main:app \
      --host "${HOST}" --port "${PORT}" --reload
fi

( cd "${ROOT}/apps/analyzer" && "${PY}" -m uvicorn app.main:app \
    --host "${HOST}" --port "${PORT}" > "${LOG}" 2>&1 & )

# ---- 4. 等就绪（不用 sleep：部分环境没有该命令）-----------------------------
raw="$(curl -sS --max-time 3 --retry 30 --retry-connrefused --retry-delay 1 \
        -w '|%{http_code}' "http://${HOST}:${PORT}/healthz" 2>/dev/null || true)"
if [ "${raw##*|}" = "200" ]; then
  ok "已就绪    http://${HOST}:${PORT}/healthz"
  info "接口文档： http://${HOST}:${PORT}/docs"
  info "日志：     .logs/analyzer.log"
  info "停止：     bash scripts/stop-all.sh analyzer"
else
  bad "启动超时或失败，看日志： ${LOG}"
  tail -20 "${LOG}" 2>/dev/null
  exit 1
fi
