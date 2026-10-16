#!/usr/bin/env bash
#
# drill-part3.sh —— part3 降级演练的入口（tasks.md N6.1 / AC29）。
#
# 与 drill-degradation.sh 的分工：
#   drill-degradation.sh  六条，**真实 HTTP**（要四层全开）—— 守「跨进程的协议行为」
#   本脚本                四条，**进程内打桩**（零依赖）—— 守「降级分支覆盖」
# 后者能进 CI，前者不能（CI 里没有四层服务）。
#
# 用法：
#   bash scripts/drill-part3.sh            # 四条全跑
#   bash scripts/drill-part3.sh 2 3        # 只跑第 2、3 条
#
# 前置：无。脚本自己起一个「会返回坏 JSON」的本地 HTTP 服务来制造内容失败，
#      并用一个空端口制造连接失败 —— 不需要真实 LLM，也不需要任何服务在跑。
#
# 与 gen-seed.sh / drill-degradation.sh 同构：入口用 shell（tasks 与 CI 按这个名字调），
# 判定逻辑写在 Python 里（要发 HTTP、解析 SSE、造故障）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解释器优先级：显式指定 > analyzer 的 venv（项目自己的环境）> PATH 里的 python3 / python。
# ⚠️ 本脚本与 drill-degradation.sh **不同**：它必须 import analyzer 的应用代码
# （`app.service.analysis_stream_service`），所以**需要 analyzer 的第三方依赖**，
# 用系统 Python 大概率会因为缺 fastapi 而失败。
find_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then printf '%s' "${PYTHON_BIN}"; return 0; fi
  for candidate in \
    "${SCRIPT_DIR}/../apps/analyzer/.venv/Scripts/python.exe" \
    "${SCRIPT_DIR}/../apps/analyzer/.venv/bin/python"; do
    if [ -x "${candidate}" ]; then printf '%s' "${candidate}"; return 0; fi
  done
  for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then printf '%s' "${candidate}"; return 0; fi
  done
  return 1
}

if [ ! -f "${SCRIPT_DIR}/drill_part3.py" ]; then
  printf '\033[31m[drill-part3] 找不到 %s/drill_part3.py\033[0m\n' "${SCRIPT_DIR}" >&2
  exit 1
fi

if ! PYTHON="$(find_python)"; then
  printf '\033[31m[drill-part3] 找不到 python 解释器；用 PYTHON_BIN=/path/to/python 指定\033[0m\n' >&2
  exit 1
fi

# cd 到脚本目录再以相对路径调用：Git Bash 的 pwd 是 MSYS 形式（/e/代码/…），
# Windows 版 Python 不认，会被当成相对路径拼到当前盘上。脚本内部用 __file__ 自算绝对路径。
cd "${SCRIPT_DIR}" || exit 1
exec "${PYTHON}" drill_part3.py "$@"
