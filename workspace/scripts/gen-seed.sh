#!/usr/bin/env bash
#
# gen-seed.sh —— 把「人工可编辑的源」编译成 db/seed.sql（入口脚本）。
#
# 源 → 产物：
#   apps/analyzer/app/data/skills.yaml   技能词典真源（C4）
#   db/seed/categories.json              岗位分类树（D1：数据不是代码）
#   db/seed/jobs/*.json                  岗位源，一岗一文件
#        │  bash scripts/gen-seed.sh
#        ▼
#   db/seed.sql                          分节 + 幂等，MySQL / H2 共用一份（禁止手改）
#
# 用法：
#   bash scripts/gen-seed.sh            生成 db/seed.sql
#   bash scripts/gen-seed.sh --check    只校验源数据，不落盘（CI / 提交前用）
#
# 为什么拆成 .sh + .py：入口必须叫 gen-seed.sh（tasks.md M1.5.3 与 CI 都按这个名字调），
# 但转义 / 算 content_hash / 算 jd_offset / 逐条校验这些活写在 Python 里才可读可测。
# 本脚本只负责「找解释器 + 透传参数」，不含任何业务逻辑。
#
# 校验会在这些情况**直接失败**（不允许「尽力生成一份可能错的 seed」）：
#   技能未登录词典（D3 的前置）· evidence 不是 jdRaw 的逐字片段 · 分类不在树里
#   别名重复（歧义别名）· 字段超出建表列宽 · 岗位 code / 分类 code 重复
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解释器优先级：显式指定 > analyzer 的 venv（项目自己的环境）> PATH 里的 python3 / python
# venv 优先是因为它是**本项目**的依赖环境；容器与 CI 里没有 venv，自然落到 PATH。
# 依赖：PyYAML（读 skills.yaml）—— 已在 apps/analyzer/requirements.txt 里显式声明。
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

if [ ! -f "${SCRIPT_DIR}/gen_seed.py" ]; then
  printf '\033[31m[gen-seed] 找不到生成器 %s/gen_seed.py\033[0m\n' "${SCRIPT_DIR}" >&2
  exit 1
fi

if ! PYTHON="$(find_python)"; then
  printf '\033[31m[gen-seed] 找不到 python 解释器；用 PYTHON_BIN=/path/to/python 指定\033[0m\n' >&2
  exit 1
fi

printf '\n== gen-seed ==\n'

# 先 cd 到脚本目录，再以**相对路径**调用生成器。
# 原因：Git Bash 下 `pwd` 给的是 MSYS 形式（/e/代码/…），Windows 版 Python 不认，
# 会把它当相对路径拼到当前盘上，变成 E:\e\代码\… 而报「找不到文件」。
# 传相对路径就不经过这层转换；gen_seed.py 内部用 __file__ 自己算绝对路径，
# 因此从任何目录调用本脚本都能正确找到源与产物。
cd "${SCRIPT_DIR}" || exit 1
exec "${PYTHON}" gen_seed.py "$@"
