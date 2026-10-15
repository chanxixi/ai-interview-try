#!/usr/bin/env bash
#
# 停止 CareerLens 四个服务（按端口找进程并结束）。
#
# 用法：
#   bash scripts/stop-all.sh              # 停全部
#   bash scripts/stop-all.sh job-service  # 只停一个
#
set -uo pipefail

ANALYZER_PORT="${ANALYZER_PORT:-8000}"
JOB_SERVICE_PORT="${JOB_SERVICE_PORT:-8080}"
BFF_PORT="${BFF_PORT:-3000}"
WEB_PORT="${WEB_PORT:-5173}"

ONLY="${1:-all}"

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
else
  C_OK=''; C_DIM=''; C_0=''
fi

kill_port() {
  local port="$1" name="$2" pids
  pids="$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":${port}[[:space:]]" | awk '{print $5}' | sort -u)"
  if [ -z "${pids}" ]; then
    printf '  %s- %s :%s 未在运行%s\n' "${C_DIM}" "${name}" "${port}" "${C_0}"
    return 0
  fi
  for pid in ${pids}; do
    # 注意：Git Bash 里必须写成 taskkill "/PID" <pid> "/F"
    #   - `//PID` 这种 MSYS 双斜杠写法在这里**不生效**，会报「无效参数/选项 - '//PID'」
    #   - 不带引号的 `/PID` 会被 MSYS 当成路径转换掉，同样失败
    if taskkill "/PID" "${pid}" "/F" >/dev/null 2>&1; then
      printf '  %sOK%s  %s :%s 已停止 (pid %s)\n' "${C_OK}" "${C_0}" "${name}" "${port}" "${pid}"
    else
      kill -9 "${pid}" 2>/dev/null || true
      printf '  %s??%s  %s :%s 结束失败，请手动确认 (pid %s)\n' "${C_OK}" "${C_0}" "${name}" "${port}" "${pid}"
    fi
  done
}

printf '\n停止服务\n'
for entry in "analyzer|${ANALYZER_PORT}" "job-service|${JOB_SERVICE_PORT}" "bff|${BFF_PORT}" "web|${WEB_PORT}"; do
  name="${entry%%|*}"; port="${entry#*|}"
  if [ "${ONLY}" = "all" ] || [ "${ONLY}" = "${name}" ]; then
    kill_port "${port}" "${name}"
  fi
done
printf '\n'
