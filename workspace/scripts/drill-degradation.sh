#!/usr/bin/env bash
#
# drill-degradation.sh —— 六条降级演练的入口（tasks.md M8.3）。
#
# 为什么单独一个脚本、且必须**实测**：
#   降级路径的共同特征是「不跑也不会报错」。LLM 挂了不降级 → 用户拿不到推荐；
#   扫描件不报错 → 用户拿到一份 0 技能的「正常」结果；断连不处理 → 句柄慢慢漏光。
#   这些都不会让 /healthz 变红，只会让线上慢慢烂掉。所以每一条都必须
#   **主动制造故障、再断言行为**。
#
# 用法：
#   bash scripts/drill-degradation.sh            # 六条全跑
#   bash scripts/drill-degradation.sh 2 3        # 只跑第 2、3 条
#
# 前置：四层已启动（bash scripts/start-all.sh）；analyzer 的 LLM_* 环境变量**留空**
#       （第 1 条要的就是「LLM 不可用」这个状态，留空即不可用）。
#
# 与 gen-seed.sh 同构：入口用 shell（tasks 与 CI 按这个名字调），
# 判定逻辑写在 Python 里（要发原始 HTTP、解析 JSON、控制 socket 半关闭）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解释器优先级：显式指定 > analyzer 的 venv（项目自己的环境）> PATH 里的 python3 / python
# 本脚本只用标准库（http.client / socket / json），不依赖 analyzer 的第三方包。
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

if [ ! -f "${SCRIPT_DIR}/drill_degradation.py" ]; then
  printf '\033[31m[drill-degradation] 找不到 %s/drill_degradation.py\033[0m\n' "${SCRIPT_DIR}" >&2
  exit 1
fi

if ! PYTHON="$(find_python)"; then
  printf '\033[31m[drill-degradation] 找不到 python 解释器；用 PYTHON_BIN=/path/to/python 指定\033[0m\n' >&2
  exit 1
fi

# cd 到脚本目录再以相对路径调用：Git Bash 的 pwd 是 MSYS 形式（/e/代码/…），
# Windows 版 Python 不认，会被当成相对路径拼到当前盘上。脚本内部用 __file__ 自算绝对路径。
cd "${SCRIPT_DIR}" || exit 1
exec "${PYTHON}" drill_degradation.py "$@"
