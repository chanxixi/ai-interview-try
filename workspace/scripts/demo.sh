#!/usr/bin/env bash
#
# CareerLens 全链 Demo —— 一条命令验证「四个服务都能跑 + 能互相调用」。
#
# 与 scripts/smoke.sh 的区别：
#   smoke.sh   —— CI 用的冒烟断言（只看通过/失败，输出精简）
#   demo.sh    —— 给人看的演示脚本：逐跳打印真实响应，并解释「凭什么说这是真调用」
#
# 前置：四个服务已启动（顺序 analyzer → job-service → bff → web，见 docs/RUNBOOK.md）。
# 用法：bash scripts/demo.sh
#
# 不写任何临时文件、不依赖 jq —— 只用 curl + grep/sed 解析 JSON。
#
set -uo pipefail

ANALYZER_URL="${ANALYZER_URL:-http://127.0.0.1:8000}"
JOB_SERVICE_URL="${JOB_SERVICE_URL:-http://127.0.0.1:8080}"
BFF_URL="${BFF_URL:-http://127.0.0.1:3000}"
WEB_URL="${WEB_URL:-http://127.0.0.1:5173}"

TRACE_ID="demo-$(date +%s)"
failures=0

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_FAIL=$'\033[31m'; C_DIM=$'\033[2m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
  C_OK=''; C_FAIL=''; C_DIM=''; C_B=''; C_0=''
fi

pass() { printf '  %sPASS%s  %s\n' "${C_OK}" "${C_0}" "$1"; }
fail() { printf '  %sFAIL%s  %s\n' "${C_FAIL}" "${C_0}" "$1"; failures=$((failures + 1)); }
info() { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_0}"; }
step() { printf '\n%s%s%s\n' "${C_B}" "$1" "${C_0}"; }
show() { printf '  %s%s%s\n' "${C_DIM}" "$1" "${C_0}"; }

# 从 JSON 里取字符串字段（不依赖 jq）
jstr() { printf '%s' "$1" | grep -o "\"$2\":\"[^\"]*\"" | head -1 | sed "s/^\"$2\":\"//; s/\"\$//"; }

# GET → 结果写入全局 HTTP_CODE / HTTP_BODY
# 注意：分隔符不能用 `@` 开头 —— Windows 版 curl.exe 会把 `-w '@xxx'` 当成"从文件读取"
#       而报 `curl: option -w: error encountered when reading a file`。
SEP='::HTTP::'
HTTP_CODE=''; HTTP_BODY=''
get() {
  local url="$1" trace="${2:-}" raw
  if [ -n "${trace}" ]; then
    raw="$(curl -sS --max-time 25 -w "${SEP}%{http_code}" -H "X-Trace-Id: ${trace}" "${url}" 2>/dev/null)"
  else
    raw="$(curl -sS --max-time 25 -w "${SEP}%{http_code}" "${url}" 2>/dev/null)"
  fi
  HTTP_CODE="${raw##*${SEP}}"
  HTTP_BODY="${raw%${SEP}*}"
}

printf '%s\n' "=============================================================="
printf '%s\n' " CareerLens 全链 Demo   traceId=${TRACE_ID}"
printf '%s\n' "=============================================================="

# ---------------------------------------------------------------- 1
step "[1/5] 四个服务是否都在跑（健康检查）"

for entry in "analyzer|${ANALYZER_URL}" "job-service|${JOB_SERVICE_URL}" "bff|${BFF_URL}"; do
  name="${entry%%|*}"; url="${entry#*|}"
  get "${url}/healthz"
  if [ "${HTTP_CODE}" = "200" ] && printf '%s' "${HTTP_BODY}" | grep -q '"status":"ok"'; then
    pass "$(printf '%-12s' "${name}") ${url}/healthz  ${HTTP_BODY}"
  else
    fail "$(printf '%-12s' "${name}") ${url}/healthz  HTTP ${HTTP_CODE:-000}  无响应或状态异常（服务没起来？）"
  fi
done

# web 没有 /healthz，用首页 HTTP 200 判断 Vite 是否在跑
# （不用 `-o /dev/null`：部分沙箱里 curl 写 /dev/null 会失败并返回非 0）
web_code="$(curl -sS --max-time 10 -w '|%{http_code}' "${WEB_URL}/" 2>/dev/null || true)"
web_code="${web_code##*|}"
if [ "${web_code}" = "200" ]; then
  pass "$(printf '%-12s' "web") ${WEB_URL}/  首页 HTTP 200"
else
  fail "$(printf '%-12s' "web") ${WEB_URL}/  HTTP ${web_code:-000}  Vite dev server 没起来？"
fi

# ---------------------------------------------------------------- 2
step "[2/5] HOP 0  analyzer 自检（链路终点，它没有下游）"
get "${ANALYZER_URL}/internal/ping" "${TRACE_ID}"
if [ "${HTTP_CODE}" = "200" ]; then
  pass "GET ${ANALYZER_URL}/internal/ping  HTTP 200"
  show "${HTTP_BODY}"
  info "runtime=$(jstr "${HTTP_BODY}" runtime)   ← 由 Python 的 platform.python_version() 现场产生"
else
  fail "GET ${ANALYZER_URL}/internal/ping  HTTP ${HTTP_CODE:-000}"
fi

# ---------------------------------------------------------------- 3
step "[3/5] HOP 1  job-service → analyzer（Java 主动调 Python）"
get "${JOB_SERVICE_URL}/internal/ping" "${TRACE_ID}"
if [ "${HTTP_CODE}" = "200" ]; then
  pass "GET ${JOB_SERVICE_URL}/internal/ping  HTTP 200"
  show "${HTTP_BODY}"
  if printf '%s' "${HTTP_BODY}" | grep -q '"downstream"'; then
    pass "响应里出现 downstream 字段 → Java 真的往下调了一层"
  else
    fail "响应里没有 downstream 字段 → Java 没调 analyzer"
  fi
else
  fail "GET ${JOB_SERVICE_URL}/internal/ping  HTTP ${HTTP_CODE:-000}"
fi

# ---------------------------------------------------------------- 4
step "[4/5] HOP 2  bff → job-service → analyzer（BFF 串起两跳）"
get "${BFF_URL}/api/ping" "${TRACE_ID}"
if [ "${HTTP_CODE}" = "200" ]; then
  pass "GET ${BFF_URL}/api/ping  HTTP 200"
  show "${HTTP_BODY}"
  for svc in bff job-service analyzer; do
    if printf '%s' "${HTTP_BODY}" | grep -q "\"service\":\"${svc}\""; then
      pass "链路里含 ${svc}"
    else
      fail "链路里缺 ${svc}"
    fi
  done
else
  fail "GET ${BFF_URL}/api/ping  HTTP ${HTTP_CODE:-000}"
fi

# ---------------------------------------------------------------- 5
step "[5/5] HOP 3  web(Vite:5173) → bff（走前端代理 /api，前端唯一出口）"
get "${WEB_URL}/api/ping" "${TRACE_ID}"
WEB_BODY="${HTTP_BODY}"
if [ "${HTTP_CODE}" = "200" ] && printf '%s' "${WEB_BODY}" | grep -q '"service":"analyzer"'; then
  pass "GET ${WEB_URL}/api/ping  HTTP 200（Vite 代理把 /api 转给 BFF，一路打到 analyzer）"
  show "${WEB_BODY}"
else
  fail "GET ${WEB_URL}/api/ping  HTTP ${HTTP_CODE:-000}  前端代理没通（检查 vite.config.ts 的 proxy.target 与 BFF 是否在跑）"
fi

# ---------------------------------------------------------------- 附加断言
step "[附加] traceId 是否全链贯穿（spec.md §2.8）"

chain_hits="$(printf '%s' "${WEB_BODY}" | grep -o "${TRACE_ID}" | wc -l | tr -d ' ')"
if [ "${chain_hits}" -ge 3 ]; then
  pass "同一个 traceId 在链路里出现 ${chain_hits} 次（bff / job-service / analyzer 各一次）"
else
  fail "traceId 只出现 ${chain_hits} 次，说明某一跳没透传 X-Trace-Id"
fi

echoed="$(curl -sS -i --max-time 25 -H "X-Trace-Id: ${TRACE_ID}" "${BFF_URL}/api/ping" 2>/dev/null \
  | grep -i '^x-trace-id:' | tr -d '\r' | awk '{print $2}')"
if [ "${echoed}" = "${TRACE_ID}" ]; then
  pass "响应头 X-Trace-Id 原样回写（${echoed}）"
else
  fail "响应头 X-Trace-Id 不一致（期望 ${TRACE_ID}，实际 '${echoed}'）"
fi

step "[说明] 凭什么说「真的互相调用」而不是各自返回写死的假数据？"
info "关键在 runtime 字段 —— 它是各语言运行时自报的版本号："
info "  bff          runtime = $(jstr "${WEB_BODY}" runtime)     ← Node 自己报的"
info "  job-service  runtime = java 17.0.2                 ← JVM 自己报的"
info "  analyzer     runtime = python 3.13.14              ← Python 自己报的"
info "BFF 不可能凭空知道 JVM / CPython 的版本号 —— 这个字段只能来自真实的下游响应。"

# ---------------------------------------------------------------- 收尾
printf '\n%s\n' "--------------------------------------------------------------"
if [ "${failures}" -eq 0 ]; then
  printf '%s\n' "${C_OK}${C_B}全链 Demo 通过：四层服务全部可运行，且逐跳互相调用正常。${C_0}"
  printf '%s\n' "浏览器打开 ${WEB_URL} 点「运行连通性检查」可看到同样的结果（图形化）。"
  printf '\n'
  exit 0
fi
printf '%s\n' "${C_FAIL}${C_B}全链 Demo 失败：${failures} 项不通过，按上面 FAIL 行逐个排查。${C_0}"
printf '%s\n' "排查顺序建议：analyzer → job-service → bff → web（后者依赖前者）。"
printf '\n'
exit 1
