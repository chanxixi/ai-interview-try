#!/usr/bin/env bash
#
# smoke-deep.sh —— part3 `deep` 模式的端到端冒烟（tasks.md 交付物：1 条 deep 端到端冒烟）。
#
# 与 smoke-stream.sh 的分工：
#   smoke-stream.sh  part2 的流式契约（standard）—— 7 阶段 / meta 首 / done 尾
#   本脚本           part3 的深分析—— reviewed 阶段 + 四个新块 + 出处完整性 + standard 回退
#
# 前置：四个服务已启动（bash scripts/start-all.sh），job-service 的种子已导入
#       （否则没有候选集 → 没有 match → verdicts 会是空的，脚本会说明差在哪一步）。
#
# 用法：
#   bash scripts/smoke-deep.sh
#   JOB_ID=job-backend-01 bash scripts/smoke-deep.sh
#   TOP_N=10 bash scripts/smoke-deep.sh
#
# 断言（AC24 / AC25 / AC27 / AC35 的可当堂验证版）：
#   1. deep：事件序列出现 stage(reviewed)，且**在 result 之前**
#   2. deep：result 含 verdicts / improvements / growthDirections / abilityProfile
#   3. deep：每条 verdict 的档位合法、reason 非空
#   4. deep：每个维度分都带 rubricRef；有分的维度必须有 evidence（AC27）
#   5. deep：overall 存在（缺维时允许为 null —— 那是「算不出」，不是 0）
#   6. standard：**不发** reviewed，且响应里一个 part3 的键都没有（AC25）
#   7. topN 生效：recommendations 条数 = min(topN, 候选数)
#
# 为什么脚本里手写一份阶段表与键名而不从代码里读：**脚本要独立于被测代码**，
# 从被测代码里读出来就变成「代码自己证明自己对」了。
#
# ⚠️ LLM 关着也能跑：四个块会退化成规则兜底（**非空**），断言 2-5 依然成立 ——
#    这正是 `deep` 降级路径的端到端证据。想验 LLM 参与，把 analyzer 的 LLM_* 配上再看 `meta.llmUsed`。
#
set -uo pipefail

BFF_URL="${BFF_URL:-http://localhost:3000}"
JOB_ID="${JOB_ID:-job-backend-01}"
TOP_N="${TOP_N:-3}"
RESUME_TEXT="${RESUME_TEXT:-熟悉 Java、Spring Boot、MySQL，做过订单系统的接口优化，把 P99 从 800ms 降到 120ms}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_DIR}" || exit 1

TMP_ROOT=".logs"
mkdir -p "${TMP_ROOT}"

failures=0
checks=0
pass() { checks=$((checks + 1)); printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { checks=$((checks + 1)); failures=$((failures + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }

# 需要一个 JSON 解析器。python 一定有（analyzer 的 venv 也有），比 jq 可靠。
find_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then printf '%s' "${PYTHON_BIN}"; return 0; fi
  for candidate in \
    "${SCRIPT_DIR}/../apps/analyzer/.venv/Scripts/python.exe" \
    "${SCRIPT_DIR}/../apps/analyzer/.venv/bin/python" \
    python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then printf '%s' "${candidate}"; return 0; fi
  done
  return 1
}
if ! PYTHON="$(find_python)"; then
  printf '\033[31m[smoke-deep] 找不到 python 解释器；用 PYTHON_BIN=/path/to/python 指定\033[0m\n' >&2
  exit 1
fi

tmpdir="$(mktemp -d "${TMP_ROOT}/smoke-deep.XXXXXX" 2>/dev/null || mktemp -d)"
deep_body="${tmpdir}/deep.sse"
std_body="${tmpdir}/standard.sse"

# 取 SSE 流里的 result 事件 data（单行 JSON）。
extract_result() {
  "${PYTHON}" - "$1" <<'PY'
import json, sys, pathlib

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
for block in raw.split("\n\n"):
    if not block.strip() or block.lstrip().startswith(":"):
        continue
    event, data = "", []
    for line in block.split("\n"):
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):])
    if event == "result" and data:
        print("\n".join(data))
        break
PY
}

echo "== part3 deep 端到端冒烟 =="
echo "BFF: ${BFF_URL} · jobId: ${JOB_ID} · topN: ${TOP_N}"

# ---------------------------------------------------------------- deep
echo
echo "-- 1) deep 请求 --"
curl -sS -N -X POST "${BFF_URL}/api/analysis/stream" \
  -H 'Accept: text/event-stream' \
  -H "X-Trace-Id: smoke-deep-$(date +%s)" \
  -F "resumeText=${RESUME_TEXT}" \
  -F "jobId=${JOB_ID}" \
  -F 'analysisDepth=deep' \
  -F "topN=${TOP_N}" \
  > "${deep_body}" 2>"${tmpdir}/deep.err" || warn "curl 退出码非 0（看 ${tmpdir}/deep.err）"

if ! grep -q '^event: result' "${deep_body}"; then
  fail "deep：没有收到 result 事件（先确认四层都起来了、种子已导入）"
  printf '  原始流：%s\n' "${deep_body}"
  exit 1
fi

# 断言 1：reviewed 出现且在 result 之前
reviewed_line="$(grep -n '"stage":"reviewed"' "${deep_body}" | head -1 | cut -d: -f1)"
result_line="$(grep -n '^event: result' "${deep_body}" | head -1 | cut -d: -f1)"
if [ -n "${reviewed_line}" ] && [ -n "${result_line}" ] && [ "${reviewed_line}" -lt "${result_line}" ]; then
  pass "deep：stage(reviewed) 出现，且在 result 之前（AC24）"
else
  fail "deep：stage(reviewed) 缺失或位置不对（reviewed=${reviewed_line:-无} result=${result_line:-无}）"
fi

# 断言 2/3/4/5/7：把 result 交给 python 逐条验
extract_result "${deep_body}" > "${tmpdir}/deep.result.json"
if [ ! -s "${tmpdir}/deep.result.json" ]; then
  fail "deep：result 的 data 无法提取"
else
  "${PYTHON}" - "${tmpdir}/deep.result.json" "${TOP_N}" <<'PY'
import json, pathlib, sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
top_n = int(sys.argv[2])
failures = []

def check(ok, label, detail=""):
    mark = "OK  " if ok else "FAIL"
    print(f"  {mark} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)

BLOCKS = ["verdicts", "improvements", "growthDirections", "abilityProfile"]
missing = [key for key in BLOCKS if key not in payload]
check(not missing, "deep：result 含四个新块（AC24）", f"缺 {missing}" if missing else "")

meta = payload.get("meta", {})
check(meta.get("analysisDepth") == "deep", "deep：meta.analysisDepth = deep")
check(set(["verdictCount", "directionCount"]) <= set(meta),
      "deep：meta 带 verdictCount / directionCount")

verdicts = payload.get("verdicts", [])
match = payload.get("match") or {}
expected = len(match.get("matched", [])) + len(match.get("missing", []))
check(len(verdicts) == expected,
      "deep：verdicts 条数 = match 条数（骨架未被增删）", f"{len(verdicts)} / {expected}")

bad_kind = [v["skill"] for v in verdicts if v.get("verdict") not in ("satisfied", "partial", "missing")]
check(not bad_kind, "deep：每条 verdict 的档位合法（AC26）", str(bad_kind) if bad_kind else "")
no_reason = [v["skill"] for v in verdicts if not (v.get("reason") or "").strip()]
check(not no_reason, "deep：每条 verdict 都有 reason（AC26）", str(no_reason) if no_reason else "")

profile = payload.get("abilityProfile")
if profile is None:
    check(False, "deep：abilityProfile 存在（除非 rubric 读不到）")
else:
    dims = profile.get("dimensions", [])
    check(len(dims) == 6, "deep：六维齐全", f"{len(dims)} 维")
    no_ref = [d["name"] for d in dims if not (d.get("rubricRef") or "").strip()]
    check(not no_ref, "deep：每个维度分都带 rubricRef（AC27）", str(no_ref) if no_ref else "")
    no_evidence = [d["name"] for d in dims if d.get("score") and not (d.get("evidence") or "").strip()]
    check(not no_evidence, "deep：有分的维度都带原文 evidence（AC27）",
          str(no_evidence) if no_evidence else "")
    check("overall" in profile, "deep：overall 字段存在（缺维时为 null = 算不出，不是 0）")
    check(any(d.get("score") for d in dims), "deep：至少有一维算出了分（不是六维全空）")

recs = payload.get("recommendations", [])
check(len(recs) == min(top_n, len(recs)) and len(recs) <= top_n,
      "deep：recommendations 条数 <= topN（AC35）", f"{len(recs)} 条 / topN={top_n}")

check(bool(payload.get("improvements")) or bool(payload.get("growthDirections")),
      "deep：优化点或方向至少有一块非空（断 LLM 走规则模板）")

sys.exit(1 if failures else 0)
PY
  if [ $? -ne 0 ]; then
    failures=$((failures + 1))
  fi
fi

# ---------------------------------------------------------------- standard 回退
echo
echo "-- 2) standard（缺省）回退 --"
curl -sS -N -X POST "${BFF_URL}/api/analysis/stream" \
  -H 'Accept: text/event-stream' \
  -H "X-Trace-Id: smoke-deep-std-$(date +%s)" \
  -F "resumeText=${RESUME_TEXT}" \
  -F "jobId=${JOB_ID}" \
  > "${std_body}" 2>"${tmpdir}/std.err" || warn "curl 退出码非 0（看 ${tmpdir}/std.err）"

if grep -q '"stage":"reviewed"' "${std_body}"; then
  fail "standard：不应出现 stage(reviewed)（AC25）"
else
  pass "standard：不发 reviewed 阶段（AC25）"
fi

extract_result "${std_body}" > "${tmpdir}/std.result.json"
if [ ! -s "${tmpdir}/std.result.json" ]; then
  fail "standard：result 的 data 无法提取"
else
  "${PYTHON}" - "${tmpdir}/std.result.json" <<'PY'
import json, pathlib, sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
failures = []

def check(ok, label, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)

PART2_KEYS = ["resume", "issues", "match", "recommendations", "meta"]
PART2_META = ["traceId", "llmUsed", "degraded", "elapsedMs", "source",
              "truncated", "recommendationCount"]
PART3 = ["verdicts", "improvements", "growthDirections", "abilityProfile",
         "analysisDepth", "verdictCount", "directionCount"]

check(list(payload.keys()) == PART2_KEYS, "standard：顶层键与 part2 逐字同序",
      str(list(payload.keys())))
check(list(payload["meta"].keys()) == PART2_META, "standard：meta 键与 part2 逐字同序",
      str(list(payload["meta"].keys())))
leaked = [k for k in PART3 if k in payload or k in payload["meta"]]
check(not leaked, "standard：一个 part3 的键都没有（AC25）", str(leaked) if leaked else "")

sys.exit(1 if failures else 0)
PY
  if [ $? -ne 0 ]; then
    failures=$((failures + 1))
  fi
fi

echo
if [ "${failures}" -eq 0 ]; then
  printf '\033[32m== deep 端到端冒烟通过 ==\033[0m\n'
else
  printf '\033[31m== deep 端到端冒烟失败：%d 组断言未过 ==\033[0m\n' "${failures}"
  printf '原始流保留在：%s\n' "${tmpdir}" >&2
fi
exit "${failures}"
