#!/usr/bin/env bash
#
# 骨架阶段的全链冒烟测试。
#
# 前置：四个服务已按 README §4 启动（analyzer → job-service → bff → web）。
# 用法：bash scripts/smoke.sh
#
# 检查内容：
#   1. 三个后端服务的 GET /healthz（spec.md §2.8）
#   2. BFF 的 GET /api/ping 能贯通 Vue → BFF → job-service → analyzer
#   3. 前端生成的 traceId 能在全链原样回来
#
set -uo pipefail

ANALYZER_URL="${ANALYZER_URL:-http://localhost:8000}"
JOB_SERVICE_URL="${JOB_SERVICE_URL:-http://localhost:8080}"
BFF_URL="${BFF_URL:-http://localhost:3000}"

TRACE_ID="smoke-$(date +%s)"
failures=0

pass() { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; failures=$((failures + 1)); }

printf '\n== 1. 健康检查（spec.md §2.8）==\n'
for entry in "analyzer:${ANALYZER_URL}" "job-service:${JOB_SERVICE_URL}" "bff:${BFF_URL}"; do
  name="${entry%%:*}"
  url="${entry#*:}"
  body="$(curl -sS --max-time 5 "${url}/healthz" 2>/dev/null || true)"

  if printf '%s' "${body}" | grep -q '"status":"ok"'; then
    pass "${name}  ${url}/healthz  ${body}"
  else
    fail "${name}  ${url}/healthz  无响应或状态异常（服务未启动？）"
  fi
done

printf '\n== 2. 全链连通性（Vue → BFF → job-service → analyzer）==\n'
chain="$(curl -sS --max-time 20 -H "X-Trace-Id: ${TRACE_ID}" "${BFF_URL}/api/ping" 2>/dev/null || true)"

if [ -z "${chain}" ]; then
  fail "BFF ${BFF_URL}/api/ping 无响应"
else
  for svc in bff job-service analyzer; do
    if printf '%s' "${chain}" | grep -q "\"service\":\"${svc}\""; then
      pass "链路包含 ${svc}"
    else
      fail "链路缺少 ${svc}"
    fi
  done

  hits="$(printf '%s' "${chain}" | grep -o "${TRACE_ID}" | wc -l | tr -d ' ')"
  if [ "${hits}" -ge 3 ]; then
    pass "traceId 全链贯穿（${TRACE_ID} 出现 ${hits} 次）"
  else
    fail "traceId 未全链贯穿（仅出现 ${hits} 次）"
  fi
fi

printf '\n== 3. traceId 回写响应头（便于调用方核对全链日志）==\n'
echoed="$(curl -sS -D - -o /dev/null --max-time 20 -H "X-Trace-Id: ${TRACE_ID}" \
  "${BFF_URL}/api/ping" 2>/dev/null \
  | grep -i '^x-trace-id:' | tr -d '\r' | awk '{print $2}')"

if [ "${echoed}" = "${TRACE_ID}" ]; then
  pass "响应头 X-Trace-Id 与请求一致（${echoed}）"
else
  fail "响应头 X-Trace-Id 不一致（期望 ${TRACE_ID}，实际 '${echoed}'）"
fi

printf '\n----------------------------------------\n'
if [ "${failures}" -eq 0 ]; then
  printf '\033[32m冒烟通过：四层骨架可运行且全链互调正常\033[0m\n\n'
  exit 0
fi

printf '\033[31m冒烟失败：%d 项不通过\033[0m\n\n' "${failures}"
exit 1
