#!/usr/bin/env bash
#
# 一键启动 CareerLens 四个服务（后台运行，日志写到 .logs/）。
#
# 用法：
#   bash scripts/start-all.sh            # 启动全部
#   bash scripts/start-all.sh analyzer   # 只启动某个（analyzer|job-service|bff|web）
#
# 启动顺序固定为 analyzer → job-service → bff → web（后者依赖前者），
# 每个服务启动后都会**等到健康检查通过**才继续下一个，避免"起了但还没就绪"的假成功。
#
# 停止：bash scripts/stop-all.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}" || exit 1

# ------------------------------------------------------------------
# 加载仓库根 .env（存在才加载；必须在下面的 PORT 默认值之前，好让 .env 能覆盖端口）
#
# 为什么必须在这里统一加载：`application.yml` 的 `JOB_DB_*` 全是 `${VAR:默认值}`
# 占位符，**只能由真实环境变量注入** —— Spring Boot 不读 .env。而 BFF
# （config/env.ts 用 dotenv）和 web（vite envDir）会各自读 workspace/.env。
# 不在入口统一加载的话，同一份 .env 对 Node 生效、对 Java 静默失效 ——
# 表现是「明明配了 MySQL，Java 还是连 H2」，排查时几乎不可能发现。
# `set -a` 让 source 进来的变量自动 export 给后续启动的子进程。
# 容器 / CI 里没有 .env，直接注入真实环境变量，本段自然跳过。
# ------------------------------------------------------------------
if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
fi

LOG_DIR="${ROOT}/.logs"
mkdir -p "${LOG_DIR}"

ANALYZER_PORT="${ANALYZER_PORT:-8000}"
JOB_SERVICE_PORT="${JOB_SERVICE_PORT:-8080}"
BFF_PORT="${BFF_PORT:-3000}"
WEB_PORT="${WEB_PORT:-5173}"

ONLY="${1:-all}"

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_FAIL=$'\033[31m'; C_DIM=$'\033[2m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
  C_OK=''; C_FAIL=''; C_DIM=''; C_B=''; C_0=''
fi

ok()   { printf '  %sOK%s    %s\n' "${C_OK}" "${C_0}" "$1"; }
bad()  { printf '  %sFAIL%s  %s\n' "${C_FAIL}" "${C_0}" "$1"; }
info() { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_0}"; }
step() { printf '\n%s%s%s\n' "${C_B}" "$1" "${C_0}"; }

port_busy() { netstat -ano 2>/dev/null | grep -q "LISTENING.*:${1}[[:space:]]"; }

# 等 URL 就绪。
#   - 不用 sleep：有些环境没有 sleep 命令
#   - 不用 `-o /dev/null`：部分沙箱里 curl 写 /dev/null 会失败并返回非 0，
#     导致「服务其实已经起来了」却被判为失败。改用 `-w` 取状态码。
wait_ok() {
  local url="$1" tries="${2:-30}" raw
  raw="$(curl -sS --max-time 3 --retry "${tries}" --retry-connrefused --retry-delay 1 \
          -w '|%{http_code}' "${url}" 2>/dev/null || true)"
  case "${raw}" in
    *'|200') return 0 ;;
    *) return 1 ;;
  esac
}

want() { [ "${ONLY}" = "all" ] || [ "${ONLY}" = "$1" ]; }

# ------------------------------------------------------------------
step "0) 前置检查"

ANALYZER_PY="${ROOT}/apps/analyzer/.venv/Scripts/python.exe"
[ -x "${ANALYZER_PY}" ] || ANALYZER_PY="${ROOT}/apps/analyzer/.venv/bin/python"
if [ ! -x "${ANALYZER_PY}" ]; then
  bad "analyzer 虚拟环境不存在：apps/analyzer/.venv"
  info "先执行： cd apps/analyzer && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt"
  exit 1
fi
ok "analyzer venv  ${ANALYZER_PY}"

JAR_NAME="job-service-0.1.0.jar"
if [ ! -f "${ROOT}/apps/job-service/target/${JAR_NAME}" ]; then
  bad "job-service 可执行 jar 不存在（还没打包）"
  info "先执行： cd apps/job-service && mvn.cmd -q clean package -DskipTests"
  exit 1
fi
ok "job-service jar  ${JAR_NAME}"

# java 可执行文件：优先 PATH，找不到则退回本机便携版 JDK
JAVA_BIN="$(command -v java 2>/dev/null || true)"
if [ -z "${JAVA_BIN}" ]; then
  JAVA_BIN="${HOME}/.workbuddy/binaries/tools/jdk/jdk-17.0.2/bin/java.exe"
fi
if [ -x "${JAVA_BIN}" ] || command -v "${JAVA_BIN}" >/dev/null 2>&1; then
  ok "java  ${JAVA_BIN}"
else
  bad "找不到 java，请把 JDK 17 加进 PATH 或设置 JAVA_HOME"
  exit 1
fi

for app in bff web; do
  if [ ! -d "${ROOT}/apps/${app}/node_modules" ]; then
    bad "${app} 依赖未安装（apps/${app}/node_modules 不存在）"
    info "先执行： cd apps/${app} && npm install"
    exit 1
  fi
  ok "${app} node_modules 已就绪"
done

# ------------------------------------------------------------------
if want analyzer; then
  step "1) analyzer  :${ANALYZER_PORT}"
  if port_busy "${ANALYZER_PORT}"; then
    ok "端口 ${ANALYZER_PORT} 已被占用，跳过启动（可能已在运行）"
  else
    ( cd "${ROOT}/apps/analyzer" && "${ANALYZER_PY}" -m uvicorn app.main:app \
        --host 127.0.0.1 --port "${ANALYZER_PORT}" > "${LOG_DIR}/analyzer.log" 2>&1 & )
    if wait_ok "http://127.0.0.1:${ANALYZER_PORT}/healthz"; then
      ok "已就绪  http://127.0.0.1:${ANALYZER_PORT}/healthz"
    else
      bad "启动超时，看日志： ${LOG_DIR}/analyzer.log"
      exit 1
    fi
  fi
fi

if want job-service; then
  step "2) job-service  :${JOB_SERVICE_PORT}"
  if port_busy "${JOB_SERVICE_PORT}"; then
    ok "端口 ${JOB_SERVICE_PORT} 已被占用，跳过启动"
  else
    # 显式指定端口/地址：环境里若有 SERVER__PORT=0 会把端口顶成随机值
    # jar 用**相对路径**：java.exe 是原生 Windows 程序，收到 MSYS 的 /e/... 路径
    # 会报 "Unable to access jarfile"，所以先 cd 进目录再传相对路径。
    ( cd "${ROOT}/apps/job-service" && "${JAVA_BIN}" -jar "target/${JAR_NAME}" \
        --server.port="${JOB_SERVICE_PORT}" --server.address=127.0.0.1 \
        > "${LOG_DIR}/job-service.log" 2>&1 & )
    if wait_ok "http://127.0.0.1:${JOB_SERVICE_PORT}/healthz" 40; then
      ok "已就绪  http://127.0.0.1:${JOB_SERVICE_PORT}/healthz"
    else
      bad "启动超时，看日志： ${LOG_DIR}/job-service.log"
      exit 1
    fi
  fi
fi

if want bff; then
  step "3) bff  :${BFF_PORT}"
  if port_busy "${BFF_PORT}"; then
    ok "端口 ${BFF_PORT} 已被占用，跳过启动"
  else
    ( cd "${ROOT}/apps/bff" && npm run dev > "${LOG_DIR}/bff.log" 2>&1 & )
    if wait_ok "http://127.0.0.1:${BFF_PORT}/healthz" 30; then
      ok "已就绪  http://127.0.0.1:${BFF_PORT}/healthz"
    else
      bad "启动超时，看日志： ${LOG_DIR}/bff.log"
      exit 1
    fi
  fi
fi

if want web; then
  step "4) web  :${WEB_PORT}"
  if port_busy "${WEB_PORT}"; then
    ok "端口 ${WEB_PORT} 已被占用，跳过启动"
  else
    ( cd "${ROOT}/apps/web" && npm run dev > "${LOG_DIR}/web.log" 2>&1 & )
    if wait_ok "http://127.0.0.1:${WEB_PORT}/" 30; then
      ok "已就绪  http://127.0.0.1:${WEB_PORT}/"
    else
      bad "启动超时，看日志： ${LOG_DIR}/web.log"
      exit 1
    fi
  fi
fi

# ------------------------------------------------------------------
printf '\n%s\n' "--------------------------------------------------------------"
printf '%s\n' "${C_OK}${C_B}启动完成。${C_0}"
printf '%s\n' "  验证全链：  bash scripts/demo.sh"
printf '%s\n' "  打开前端：  http://127.0.0.1:${WEB_PORT}  点「运行连通性检查」"
printf '%s\n' "  查看日志：  workspace/.logs/<服务名>.log"
printf '%s\n' "  停止全部：  bash scripts/stop-all.sh"
printf '\n'
