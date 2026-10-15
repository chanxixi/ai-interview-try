#!/usr/bin/env bash
#
# smoke-stream.sh —— 流式分析链路的端到端断言（tasks.md M8.1）。
#
# 与 smoke.sh 的分工：
#   smoke.sh        「四层骨架还活着吗」—— 三个 /healthz + /api/ping 全链贯通
#   smoke-stream.sh 「流式这条最脆的路还通吗」—— 真发一次请求，按 SSE 契约逐条验
#
# 前置：四个服务已启动（bash scripts/start-all.sh），且 job-service 的种子数据已导入
#       （否则 recommendations 会是空数组，脚本会明确告诉你差在哪一步）。
#
# 用法：
#   bash scripts/smoke-stream.sh
#   SAMPLE_PDF=脱敏资料/resume_01.pdf bash scripts/smoke-stream.sh   # 走 PDF 入口
#   RESUME_TEXT='熟悉 Java 与 MySQL' bash scripts/smoke-stream.sh     # 换一段文本
#
# 断言（spec §2.4 冻结面）：
#   1. SSE 三响应头齐全（content-type / cache-control / x-accel-buffering）
#   2. 首个事件是 meta（心跳注释帧不算事件）
#   3. 末个事件是 done
#   4. stage 事件覆盖**全部 7 个** stage，且顺序 == STAGE_ORDER
#   5. 有 result 事件，且 result.recommendations 非空
#   6. error 与 result 互斥（有 result 就不该有 error）
#
# 为什么不用 EventSource 风格的解析库：SSE 的线上格式只有「按 \n\n 分帧 + 取
# event:/data: 两行」两条规则（见 apps/analyzer/app/util/sse.py），
# 用 grep/awk 直读反而更能证明「服务端发出来的字节确实长这样」。
#
set -uo pipefail

BFF_URL="${BFF_URL:-http://localhost:3000}"
TRACE_ID="smoke-stream-$(date +%s)"
RESUME_TEXT="${RESUME_TEXT:-熟悉 Java、Spring Boot、MySQL、Redis、Docker、Git，有微服务与高并发经验}"
SAMPLE_PDF="${SAMPLE_PDF:-}"

# 临时目录放在 **workspace/.logs/**（已在 .gitignore 里）而不是 /tmp：
# ① 某些受限环境不允许写 /tmp；② 失败时留下的原始流就在仓库里，好找。
#
# ⚠️ 路径必须是**相对**的：Git Bash 会把 `$(pwd)` 给成 MSYS 形式（/e/代码/…），
# 而 curl 是原生 Windows 程序 —— 收到含中文的 MSYS 路径时无法创建输出文件，
# 报 `curl: (23) Failed writing received data to disk/application`。
# 所以先 cd 到 workspace，再用相对路径 `.logs/...`（不经过 MSYS 转换）。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_DIR}" || exit 1

TMP_ROOT=".logs"
mkdir -p "${TMP_ROOT}"

# 冻结顺序（spec §2.4）。这里手写一遍是有意的：**脚本要独立于被测代码**，
# 从 STAGE_ORDER 里读出来就变成「代码自己证明自己对」了。
STAGE_ORDER=(accepted parsed cleaned normalized matched recommended llm)

failures=0
pass() { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; failures=$((failures + 1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }

tmpdir="$(mktemp -d "${TMP_ROOT}/smoke-stream.XXXXXX" 2>/dev/null || mktemp -d)"
body="${tmpdir}/body.sse"
headers="${tmpdir}/headers.txt"

# 失败时把原始流留下来 —— 排查「为什么 stage 少了一个」必须看原始字节。
keep_on_failure() {
  local rc=$?
  if [ "${rc}" -ne 0 ] && [ -f "${body}" ]; then
    printf '\n原始流已保留：%s\n' "${body}" >&2
    rm -rf "${tmpdir}/curl.err" 2>/dev/null
    return
  fi
  rm -rf "${tmpdir}" 2>/dev/null
}
trap keep_on_failure EXIT

printf '\n== 0. 发起流式请求 ==\n'

# 组装请求：有 SAMPLE_PDF 走文件入口，否则走文本入口（两条入口都覆盖同一个契约）
curl_args=(-sS -N --max-time 90 -D "${headers}" -o "${body}"
  -H "Accept: text/event-stream"
  -H "X-Trace-Id: ${TRACE_ID}")

if [ -n "${SAMPLE_PDF}" ]; then
  if [ ! -f "${SAMPLE_PDF}" ]; then
    printf '\033[31m[smoke-stream] SAMPLE_PDF 不存在：%s\033[0m\n\n' "${SAMPLE_PDF}" >&2
    exit 1
  fi
  printf '  入口：PDF（%s）\n' "${SAMPLE_PDF}"
  curl_args+=(-F "file=@${SAMPLE_PDF};type=application/pdf")
else
  printf '  入口：resumeText\n'
  curl_args+=(-F "resumeText=${RESUME_TEXT}")
fi

if ! curl "${curl_args[@]}" "${BFF_URL}/api/analysis/stream" 2>"${tmpdir}/curl.err"; then
  printf '\033[31m[smoke-stream] 请求失败，BFF 是否在 %s？\033[0m\n' "${BFF_URL}" >&2
  sed 's/^/    /' "${tmpdir}/curl.err" >&2
  exit 1
fi

frame_count="$(grep -c '^event: ' "${body}" 2>/dev/null || printf '0')"
printf '  收到 %s 个事件帧（%s 字节）\n' "${frame_count}" "$(wc -c < "${body}" | tr -d ' ')"

if [ "${frame_count}" -eq 0 ]; then
  printf '\n\033[31m流里没有任何事件帧 —— 原始响应体前 400 字节：\033[0m\n' >&2
  head -c 400 "${body}" >&2
  printf '\n\n'
  exit 1
fi

# ---------------------------------------------------------------- 1. SSE 响应头
printf '\n== 1. SSE 三响应头（spec §2.4）==\n'

check_header() {
  local name="$1" needle="$2"
  local value
  value="$(grep -i "^${name}:" "${headers}" | tail -1 | tr -d '\r' | sed "s/^[^:]*: *//")"
  if printf '%s' "${value}" | grep -qi "${needle}"; then
    pass "${name}: ${value}"
  else
    fail "${name} 期望含 '${needle}'，实际 '${value}'"
  fi
}

check_header "content-type" "text/event-stream"
check_header "cache-control" "no-cache"
check_header "x-accel-buffering" "no"

# ---------------------------------------------------------------- 事件序列
# 事件类型按出现顺序（注释帧 `: ping` 不以 event: 开头，天然被排除）
mapfile -t events < <(grep '^event: ' "${body}" | sed 's/^event: //' | tr -d '\r')

printf '\n== 2. meta 首 / done 尾（spec §2.4 硬性规则 1）==\n'
if [ "${events[0]}" = "meta" ]; then
  pass "首帧是 meta"
else
  fail "首帧是 '${events[0]}'，期望 meta"
fi

last_idx=$(( ${#events[@]} - 1 ))
if [ "${events[last_idx]}" = "done" ]; then
  pass "末帧是 done"
else
  fail "末帧是 '${events[last_idx]}'，期望 done"
fi

# ---------------------------------------------------------------- 3. stage 齐全
printf '\n== 3. stage 齐全且顺序正确（spec §2.4）==\n'

# 只取 stage 事件的 data 行（awk 状态机：记住当前 event，遇到 data 就按需输出）
mapfile -t seen_stages < <(
  awk '/^event: /{ ev = substr($0, 8) } /^data: /{ if (ev == "stage") print substr($0, 7) }' "${body}" \
    | grep -o '"stage":"[a-z]*"' | sed 's/.*:"//; s/"$//'
)

# 去重但保持出现顺序（同一 stage 会发 start + ok 两帧，这是有意的）
mapfile -t uniq_stages < <(printf '%s\n' "${seen_stages[@]}" | awk '!seen[$0]++')

expected="$(printf '%s ' "${STAGE_ORDER[@]}" | sed 's/ $//')"
actual="$(printf '%s ' "${uniq_stages[@]}" | sed 's/ $//')"

if [ "${actual}" = "${expected}" ]; then
  pass "stage 序列 == STAGE_ORDER（${actual}）"
else
  fail "stage 序列不符"
  printf '       期望：%s\n' "${expected}"
  printf '       实际：%s\n' "${actual}"
fi

# 每个 stage 都应该有 start + ok 一对（fail 只在真失败时出现）
for stage in "${STAGE_ORDER[@]}"; do
  n="$(printf '%s\n' "${seen_stages[@]}" | grep -c "^${stage}$" || true)"
  if [ "${n}" -ge 2 ]; then
    pass "stage ${stage} 发了 ${n} 帧（start+ok）"
  elif [ "${n}" -eq 1 ]; then
    warn "stage ${stage} 只发了 1 帧 —— 正常流里每个 stage 应有 start+ok 一对"
  else
    fail "stage ${stage} 一帧都没有"
  fi
done

# ---------------------------------------------------------------- 4. result / error
printf '\n== 4. result 与 error 互斥，且推荐非空（AC11 / AC17）==\n'

has_result=0
has_error=0
printf '%s\n' "${events[@]}" | grep -qx 'result' && has_result=1
printf '%s\n' "${events[@]}" | grep -qx 'error' && has_error=1

if [ "${has_result}" -eq 1 ] && [ "${has_error}" -eq 1 ]; then
  fail "同时出现 result 与 error —— 两者必须互斥（spec §2.4）"
  printf '       error 内容：%s\n' \
    "$(awk '/^event: /{ ev = substr($0, 8) } /^data: /{ if (ev == "error") print substr($0, 7) }' "${body}" | head -1)"
elif [ "${has_error}" -eq 1 ]; then
  fail "流以 error 结束（没有 result）"
  printf '       error 内容：%s\n' \
    "$(awk '/^event: /{ ev = substr($0, 8) } /^data: /{ if (ev == "error") print substr($0, 7) }' "${body}" | head -1)"
elif [ "${has_result}" -eq 0 ]; then
  fail "没有 result 事件"
else
  pass "有 result 且无 error"

  result_data="$(awk '/^event: /{ ev = substr($0, 8) } /^data: /{ if (ev == "result") print substr($0, 7) }' "${body}" | tail -1)"

  # recommendations 非空：紧凑 JSON 下空数组就是字面量 "recommendations":[]
  if printf '%s' "${result_data}" | grep -q '"recommendations":\[\]'; then
    fail "recommendations 是空数组 —— 检查 job-service 种子数据是否已导入（gen-seed.sh → 启动幂等导入）"
  elif printf '%s' "${result_data}" | grep -q '"recommendations":\['; then
    # 数推荐条数：每个推荐项必有 jobId（AC16 的排序键），用它近似即可
    n_rec="$(printf '%s' "${result_data}" | grep -o '"jobId"' | wc -l | tr -d ' ')"
    pass "recommendations 非空（含 ${n_rec} 个 jobId 字段）"
  else
    fail "result 里找不到 recommendations 字段（契约要求字段必须有，可为空数组）"
  fi

  # match 可空是 part2 的有意变更（未给 jobId/jdText 时为 null）
  if printf '%s' "${result_data}" | grep -q '"match":null'; then
    pass "match 为 null（文本入口未指定 jobId，符合 part2 §2.3）"
  elif printf '%s' "${result_data}" | grep -q '"match":{'; then
    pass "match 非空（指定了 jobId）"
  else
    warn "result 里 match 字段形态未知"
  fi

  # meta 的 source 应该与入口一致
  meta_data="$(awk '/^event: /{ ev = substr($0, 8) } /^data: /{ if (ev == "meta") print substr($0, 7) }' "${body}" | head -1)"
  if [ -n "${SAMPLE_PDF}" ]; then
    want_source="pdf"
  else
    want_source="text"
  fi
  if printf '%s' "${meta_data}" | grep -q "\"source\":\"${want_source}\""; then
    pass "meta.source == ${want_source}"
  else
    fail "meta.source 期望 ${want_source}，实际 ${meta_data}"
  fi

  # LLM 降级位必须在（AC15 的观察点）
  if printf '%s' "${result_data}" | grep -q '"degraded"'; then
    degraded="$(printf '%s' "${result_data}" | grep -o '"degraded":[a-z]*' | head -1 | sed 's/.*://')"
    pass "meta.degraded == ${degraded}（LLM 降级看这里，AC15）"
  else
    fail "result.meta 缺 degraded 字段"
  fi
fi

# ---------------------------------------------------------------- 收尾
printf '\n----------------------------------------\n'
if [ "${failures}" -eq 0 ]; then
  printf '\033[32m流式冒烟通过：SSE 契约（顺序 / stage / 推荐 / 降级位）全部符合 spec §2.4\033[0m\n\n'
  exit 0
fi

printf '\033[31m流式冒烟失败：%d 项不通过\033[0m\n\n' "${failures}"
exit 1
