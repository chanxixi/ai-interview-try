#!/usr/bin/env python3
"""gen_seed.py —— 把「人工可编辑的源」编译成 `db/seed.sql`（唯一生成器）。

**为什么要有这个脚本**（plan §4.6）：
JD 原文是多行中文，直接手写进 SQL 要处理转义，人工维护成本高、极易写坏。
所以源用 JSON/YAML 写（人能读能改），脚本负责转义、算哈希、算下标、拼幂等语句。
结论：**`db/seed.sql` 是构建产物，禁止手改** —— 要改数据就改源再跑本脚本。

**输入**（全部是人可编辑的源）
    workspace/apps/analyzer/app/data/skills.yaml  技能词典真源（C4）
    workspace/db/seed/categories.json             岗位分类树（D1：数据不是代码）
    workspace/db/seed/jobs/*.json                 岗位源，一岗一文件

**输出**
    workspace/db/seed.sql                         分节 + 幂等，MySQL / H2 共用同一份

**两种幂等写法，各有理由**（都实测可在 MySQL 8.0 与 H2 MODE=MySQL 下执行）
    ① 字典与关联表 → `INSERT ... VALUES ... ON DUPLICATE KEY UPDATE <字面量>`
       紧凑，且用字面量而不是 MySQL 的 `VALUES(col)` 函数 —— 后者在 8.0.20 起已废弃，
       H2 也不支持。这样一份文件两边都能跑（spec §2.9 要求「同一份 seed.sql」）。
    ② `job` 表 → `INSERT ... SELECT ... FROM DUAL WHERE NOT EXISTS` + 带守卫的 `UPDATE`
       因为 spec §2.9 要求「重新导入只更新 source='seed' 的行，不覆盖人工录入」。
       用 `ON DUPLICATE KEY UPDATE` 表达这个守卫，得给每一列套一层
       `CASE WHEN source='seed' THEN ... ELSE <列名> END`，jd_raw 这类长文本要重复两遍，
       文件立刻臃肿到没法评审；拆成「缺则插 + 变了才更」反而更短也更清楚。
       顺带把 `version` 变成有意义的字段：**只在 content_hash 真变了才 +1**，
       而不是每次重启都涨一格（那种「版本号自己会跑」的现象最容易被当成 bug）。

**确定性**：输出不含时间戳，只含输入的 sha256 指纹。同一份源 → 逐字节相同的
`seed.sql`。这样「seed.sql 有没有被手改」可以用「复跑脚本 + git diff」直接判定
（附录 C 的审核项之一）。

**用法**
    python3 scripts/gen_seed.py            # 生成
    python3 scripts/gen_seed.py --check    # 只校验不落盘（CI 用，等价 M3.5 的种子校验）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- 路径

#: 本文件在 workspace/scripts/ 下 → parents[1] = workspace/
WORKSPACE = Path(__file__).resolve().parents[1]

SKILLS_YAML = WORKSPACE / "apps" / "analyzer" / "app" / "data" / "skills.yaml"
CATEGORIES_JSON = WORKSPACE / "db" / "seed" / "categories.json"
JOBS_DIR = WORKSPACE / "db" / "seed" / "jobs"
SEED_SQL = WORKSPACE / "db" / "seed.sql"

# --------------------------------------------------------------------------- 约束

#: 与 db/{mysql,h2}/schema.sql 的列宽逐字对齐。**超长必须在这里拦掉**：
#: 否则 MySQL 默认非严格模式下会静默截断（数据坏了但没人知道），
#: H2 则直接报错 —— 同一份源在两个库上行为不一致是最难查的一类问题。
MAX_LEN = {
    "category.code": 48,
    "category.name": 64,
    "skill.canonical": 64,
    "skill.category": 32,
    "skill_alias.alias": 64,
    "job.code": 48,
    "job.title": 128,
    "job.company": 128,
    "job.level": 32,
    "job_tag.tag": 32,
    "job_requirement.skill_raw": 64,
    "job_requirement.evidence": 512,
}

IMPORTANCE_WEIGHT_HINT = {"required": 1.0, "preferred": 0.5}
VALID_LEVELS = {"校招", "社招", "实习"}

#: 与 skills.yaml 的 categories 段一致；真正校验用的是 YAML 里那份（单一真源）。
CATEGORY_FALLBACK = [
    "language", "framework", "db", "middleware", "frontend", "devops", "tool", "ai",
]


class SeedError(Exception):
    """源数据不合法。**必须让生成失败**，不允许「尽力生成一份可能错的 seed」。"""


# --------------------------------------------------------------------------- 工具


def sql_str(value: str) -> str:
    """转义成 SQL 字符串字面量。

    反斜杠先转义（MySQL 默认把 `\\` 当转义符；不先处理会出现「源里一个反斜杠、
    库里两个」这类静默偏差）。单引号按 SQL 标准双写。
    真实换行符直接留在字面量里 —— MySQL 与 H2 都接受跨行字符串，比转成 `\\n`
    更安全：`\\n` 在 H2（非 MySQL 转义语义）里会原样存成两个字符。
    """
    if value is None:
        return "NULL"
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return "'" + escaped + "'"


def sql_value(value: Any) -> str:
    """None → NULL，其余按字符串处理（本脚本生成的列全是 VARCHAR/TEXT/INT）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        raise SeedError("布尔值不直接落库，请显式写 1/0")
    if isinstance(value, int):
        return str(value)
    return sql_str(str(value))


def sql_differs(column: str, value: str | None) -> str:
    """生成「该列与源不一致」的判定表达式，NULL 安全。

    为什么不用 `<>` 硬比：`company <> NULL` 在 SQL 里是 NULL（不是 TRUE），
    于是「源把 company 从某值改成空」这种漂移会被静默漏掉。
    写成 `IS NOT NULL` 之后，NULL 两侧的语义才是准的。
    """
    if value is None:
        return f"{column} IS NOT NULL"
    return f"{column} <> {sql_str(value)}"


def norm_text(text: str) -> str:
    """统一换行，避免 CRLF/LF 混用导致 content_hash 不稳定。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_len(where: str, value: str | None) -> None:
    if value is None:
        return
    limit = MAX_LEN.get(where)
    if limit is not None and len(value) > limit:
        raise SeedError(
            f"{where} 超长：{len(value)} > {limit} 字符（对照 db/*/schema.sql 的列宽）→ {value[:40]}…"
        )


def require(data: dict, key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise SeedError(f"{where} 缺少必填字段 {key!r}")
    return data[key]


# --------------------------------------------------------------------------- 读源


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # 延迟导入：--help 与路径报错不该依赖第三方包
    except ImportError:  # pragma: no cover
        raise SeedError("需要 PyYAML：pip install pyyaml（或走 apps/analyzer 的 venv）") from None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_categories() -> list[dict]:
    raw = load_json(CATEGORIES_JSON)
    items = raw.get("categories")
    if not items:
        raise SeedError(f"{CATEGORIES_JSON} 的 categories 为空")

    seen: dict[str, dict] = {}
    for i, item in enumerate(items):
        where = f"categories[{i}]"
        code = require(item, "code", where)
        name = require(item, "name", where)
        check_len("category.code", code)
        check_len("category.name", name)
        if code in seen:
            raise SeedError(f"{where} 分类 code 重复：{code}")
        seen[code] = item

    # parent 必须存在；level 由 parent 链推导（不手写，避免父子层级不一致）
    out: list[dict] = []
    for item in items:
        parent = item.get("parent")
        if parent is not None and parent not in seen:
            raise SeedError(f"分类 {item['code']} 的 parent={parent} 不存在")
        level, cur, hops = 1, parent, 0
        while cur is not None:
            hops += 1
            if hops > 8:
                raise SeedError(f"分类 {item['code']} 的 parent 链出现环或过深")
            cur = seen[cur].get("parent")
            level = hops + 1
        out.append(
            {
                "code": item["code"],
                "name": item["name"],
                "parent": parent,
                "level": level,
                "sort": int(item.get("sort", 0)),
            }
        )
    return out


def load_skills() -> tuple[list[str], list[dict]]:
    doc = load_yaml(SKILLS_YAML)
    allowed_cats = doc.get("categories") or CATEGORY_FALLBACK
    skills = doc.get("skills") or []
    if not skills:
        raise SeedError(f"{SKILLS_YAML} 的 skills 为空")

    canon_ci: dict[str, str] = {}
    alias_ci: dict[str, str] = {}
    out: list[dict] = []

    for i, item in enumerate(skills):
        where = f"skills[{i}]"
        canonical = require(item, "canonical", where)
        category = require(item, "category", where)
        check_len("skill.canonical", canonical)
        check_len("skill.category", category)

        if category not in allowed_cats:
            raise SeedError(f"{where} category={category!r} 不在闭集 {allowed_cats} 内")
        if canonical.lower() in canon_ci:
            raise SeedError(f"{where} canonical 重复（不分大小写）：{canonical}")
        canon_ci[canonical.lower()] = canonical

        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            raise SeedError(f"{where} aliases 必须是列表")
        for alias in aliases:
            check_len("skill_alias.alias", alias)
            key = str(alias).lower()
            if key == canonical.lower():
                # 规则②：别名不重复 canonical 自身，canonical 由「规范化后再查」命中
                raise SeedError(f"{where} 别名 {alias!r} 与自身 canonical 重复，删掉即可")
            if key in alias_ci:
                raise SeedError(
                    f"{where} 别名 {alias!r} 已被 {alias_ci[key]!r} 占用 —— "
                    f"歧义别名必须在源头消掉，不能靠运行期猜"
                )
            alias_ci[key] = canonical

        out.append({"canonical": canonical, "category": category, "aliases": list(aliases)})

    # 别名撞别的技能的 canonical：同一个词既当标准名又当别名，归一化结果取决于查表顺序
    cross = sorted(a for a in alias_ci if a in canon_ci and canon_ci[a] != alias_ci[a])
    if cross:
        raise SeedError(f"别名与其它技能的 canonical 冲突：{cross}")

    return list(allowed_cats), out


def load_jobs(category_codes: set[str], canon: set[str]) -> list[dict]:
    files = sorted(JOBS_DIR.glob("*.json"))
    if not files:
        raise SeedError(f"{JOBS_DIR} 下没有 *.json 岗位源")

    seen: dict[str, str] = {}
    out: list[dict] = []

    for path in files:
        job = load_json(path)
        where = path.name
        code = require(job, "code", where)
        title = require(job, "title", where)
        jd_raw = norm_text(require(job, "jdRaw", where))
        category = require(job, "category", where)

        check_len("job.code", code)
        check_len("job.title", title)
        check_len("job.company", job.get("company"))
        check_len("job.level", job.get("level"))

        if code in seen:
            raise SeedError(f"{where} 岗位 code 与 {seen[code]} 重复：{code}")
        seen[code] = where
        if not code.startswith("job-"):
            raise SeedError(f"{where} 岗位 code 应以 'job-' 开头（人工录入用 'manual-'）：{code}")
        if category not in category_codes:
            raise SeedError(f"{where} category={category!r} 不在分类树里（见 categories.json）")

        level = job.get("level")
        if level is not None and level not in VALID_LEVELS:
            raise SeedError(f"{where} level={level!r} 不在 {sorted(VALID_LEVELS)} 内")

        tags = job.get("tags") or []
        if not isinstance(tags, list):
            raise SeedError(f"{where} tags 必须是列表")
        for tag in tags:
            check_len("job_tag.tag", tag)

        reqs: list[dict] = []
        req_skills: dict[str, str] = {}
        for j, req in enumerate(job.get("requirements") or []):
            rwhere = f"{where}.requirements[{j}]"
            skill = require(req, "skill", rwhere)
            importance = require(req, "importance", rwhere)
            evidence = norm_text(require(req, "evidence", rwhere))

            check_len("job_requirement.skill_raw", skill)
            check_len("job_requirement.evidence", evidence)

            if skill not in canon:
                # D3：未登录词必须先补 skills.yaml，不能带着 NULL 的 skill_id 落库
                raise SeedError(
                    f"{rwhere} 技能 {skill!r} 未登录词典 —— 先补 skills.yaml 再落库（D3）"
                )
            if importance not in IMPORTANCE_WEIGHT_HINT:
                raise SeedError(
                    f"{rwhere} importance={importance!r} 只能是 {list(IMPORTANCE_WEIGHT_HINT)}"
                )
            if skill in req_skills:
                raise SeedError(f"{rwhere} 同岗位技能重复：{skill}（uk_job_skill 会拒绝）")
            req_skills[skill] = importance

            offset = jd_raw.find(evidence)
            if offset < 0:
                # 「evidence 逐字复制」这条规则靠这里机械保证，不靠人自觉
                raise SeedError(
                    f"{rwhere} evidence 不是 jdRaw 的逐字片段，找不到：{evidence[:40]!r}…"
                )
            reqs.append(
                {
                    "skill": skill,
                    "importance": importance,
                    "evidence": evidence,
                    "jd_offset": offset,
                }
            )

        company = job.get("company")
        out.append(
            {
                "code": code,
                "title": title,
                "company": company,
                "level": level,
                "category": category,
                "tags": list(tags),
                "jd_raw": jd_raw,
                # plan §4.2：sha256(company|title|jd_raw)，用来判断「JD 变了没」
                "content_hash": sha256_hex(f"{company or ''}|{title}|{jd_raw}"),
                "requirements": reqs,
            }
        )
    return out


def input_fingerprint() -> str:
    """输入指纹：同一份源 → 同一份 seed.sql（输出里不含时间戳）。"""
    digest = hashlib.sha256()
    for path in [SKILLS_YAML, CATEGORIES_JSON, *sorted(JOBS_DIR.glob("*.json"))]:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --------------------------------------------------------------------------- 生成


def render(categories: list[dict], skills: list[dict], jobs: list[dict]) -> str:
    out: list[str] = []
    w = out.append

    total_reqs = sum(len(j["requirements"]) for j in jobs)
    total_aliases = sum(len(s["aliases"]) for s in skills)

    w("-- " + "=" * 76)
    w("-- CareerLens · part2 种子数据（db/seed.sql）")
    w("-- " + "-" * 76)
    w("-- ⚠️ 本文件由 scripts/gen-seed.sh（内部 scripts/gen_seed.py）生成，**禁止手改**。")
    w("--    要改数据 → 改下面这些源 → 复跑脚本 → 重启（幂等导入）：")
    w("--      apps/analyzer/app/data/skills.yaml   技能词典真源（C4）")
    w("--      db/seed/categories.json              岗位分类树（D1：数据不是代码）")
    w("--      db/seed/jobs/*.json                  岗位源，一岗一文件")
    w("--")
    w("-- MySQL 8.0 与 H2（MODE=MySQL）**共用这一份**（spec §2.9）。")
    w("-- 幂等：字典/关联表走 ON DUPLICATE KEY UPDATE；job 表走「缺则插 + 变了才更」，")
    w("--       并带 source='seed' 守卫 —— 重复导入行数不变（AC23），且不覆盖人工录入。")
    w("-- 不删除任何行：岗位下架走 status='archived'（D2：只软删）。")
    w("--")
    w(f"-- 输入指纹 sha256: {input_fingerprint()}")
    w(f"-- 规模: 分类 {len(categories)} · 技能 {len(skills)} · 别名 {total_aliases} · "
      f"岗位 {len(jobs)} · 技能要求 {total_reqs}")
    w("-- " + "=" * 76)
    w("")

    # ---------------------------------------------------------------- 分类树
    w("-- " + "-" * 76)
    w("-- 1/5 job_category —— 岗位分类树（父行在前，子行先插再单独 UPDATE 回填 parent_id）")
    w("--     新增一类岗位 = 在 categories.json 加一行 + 复跑本脚本，不改 Java 代码（D1）")
    w("--     ⚠️ parent_id 拆成两条语句是为了绕开 MySQL 的 ERROR 1093：")
    w("--        ON DUPLICATE KEY UPDATE 子句里不能引用目标表（派生表也拦），")
    w("--        INSERT 的 VALUES 子查询则必须套派生表 —— 详见 gen_seed.py 里的实测注释。")
    w("--     ⚠️ 更新语句**不写 status**：运营把某分类归档后，重复导入不该把它复活")
    w("--        （与 AC23「岗位置 archived 后行仍在、但不再进候选」同一条规则）")
    w("-- " + "-" * 76)
    for c in sorted(categories, key=lambda x: (x["level"], x["sort"], x["code"])):
        # ⚠️ parent_id 的解析踩了 MySQL 8.0 的两个坑 —— 下面注释里的结论全是**实测**出来的，
        #   H2（MODE=MySQL）对这两种写法都不挑，所以只在真 MySQL 上暴露：
        #   ① `INSERT ... VALUES` 里引用**目标表本身**的裸子查询 → ERROR 1093
        #      （"You can't specify target table 'job_category' for update in FROM clause"）。
        #      套一层派生表 `(SELECT _p.id FROM (…) AS _p)` 让优化器先物化即可通过。
        #   ② `ON DUPLICATE KEY UPDATE` 子句里**无论怎么包都不能**引用目标表 ——
        #      连派生表包裹也会被拦（实测 T4 失败）。
        #      所以 parent_id 的「变了才更」只能拆成紧随其后的一条**独立 UPDATE**：
        #      独立 UPDATE 用派生表是合法的，② 的限制只作用于 ON DUPLICATE 子句。
        #   副作用为零：job_category 没有 updated_at 列，多一条 UPDATE 不产生额外漂移。
        parent_sql = (
            "NULL" if c["parent"] is None
            else f"(SELECT _p.id FROM (SELECT id FROM job_category "
                 f"WHERE code = {sql_str(c['parent'])}) AS _p)"
        )
        w("INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (")
        w(f"  {sql_str(c['code'])}, {sql_str(c['name'])}, {parent_sql}, {c['level']}, {c['sort']}, 'active'")
        w(") ON DUPLICATE KEY UPDATE")
        # ⚠️ 更新语句**不写 status**：运营把某分类归档后，重复导入不该把它复活（见分节注释）
        w(f"  name = {sql_str(c['name'])}, level = {c['level']}, sort_order = {c['sort']};")
        if c["parent"] is not None:
            w(f"UPDATE job_category SET parent_id = {parent_sql} "
              f"WHERE code = {sql_str(c['code'])};")
    w("")

    # ------------------------------------------------------------------ 技能
    w("-- " + "-" * 76)
    w("-- 2/5 skill —— 技能标准名（真源：app/data/skills.yaml，C4）")
    w("-- " + "-" * 76)
    for s in skills:
        w(f"INSERT INTO skill (canonical, category, status) VALUES ("
          f"{sql_str(s['canonical'])}, {sql_str(s['category'])}, 'active')")
        w(f"  ON DUPLICATE KEY UPDATE category = {sql_str(s['category'])};")
    w("")

    w("-- " + "-" * 76)
    w("-- 3/5 skill_alias —— 别名（归一化的第二跳；alias 全局唯一，大小写不敏感）")
    w("-- " + "-" * 76)
    for s in skills:
        for alias in s["aliases"]:
            owner = f"(SELECT id FROM skill WHERE canonical = {sql_str(s['canonical'])})"
            w(f"INSERT INTO skill_alias (skill_id, alias) VALUES ({owner}, {sql_str(alias)})")
            w(f"  ON DUPLICATE KEY UPDATE skill_id = {owner};")
    if total_aliases == 0:
        w("-- （本词典暂无别名）")
    w("")

    # ------------------------------------------------------------------ 岗位
    w("-- " + "-" * 76)
    w("-- 4/5 job —— 岗位主表（含 JD 原文）")
    w("--     ① 缺则插：WHERE NOT EXISTS 保证重复导入不新增行（AC23）")
    w("--     ② 变了才更：UPDATE 的 WHERE 逐列比对「这行与源是否不一致」。")
    w("--        为什么不只比 content_hash：hash 是**由源算出来的**，入库后就不再变；")
    w("--        若有人在库里改了 title 却没动 hash，只比 hash 会认为「已同步」而漏掉这次漂移。")
    w("--        逐列比对把 level / category_id 这两个不在 hash 里的字段也覆盖到了。")
    w("--        好处：内容没变就一个字节都不写 → version 不涨、updated_at 不动，")
    w("--        不会出现「每次重启版本号自己涨一格」这种像 bug 的现象。")
    w("--     ③ source='seed' 守卫：绝不覆盖人工录入的行（spec §2.9）")
    w("--     ④ 更新语句**不写 status**：已归档的岗位重复导入不会被复活（AC23）")
    w("-- " + "-" * 76)
    for j in jobs:
        cat = f"(SELECT id FROM job_category WHERE code = {sql_str(j['category'])})"
        drift = " OR ".join([
            f"content_hash <> {sql_str(j['content_hash'])}",
            f"title <> {sql_str(j['title'])}",
            sql_differs("company", j["company"]),
            sql_differs("level", j["level"]),
            f"category_id <> {cat}",
        ])
        w(f"-- {j['code']} · {j['title']} @ {j['company'] or '—'} [{j['category']}]")
        w("INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,")
        w("                 attributes, source, status, version)")
        w(f"SELECT {sql_str(j['code'])}, {sql_str(j['title'])}, {sql_value(j['company'])}, "
          f"{sql_value(j['level'])}, {cat},")
        w(f"       {sql_str(j['jd_raw'])},")
        w(f"       {sql_str(j['content_hash'])}, NULL, 'seed', 'active', 1")
        w(f"FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = {sql_str(j['code'])});")
        w("UPDATE job SET")
        w(f"  title = {sql_str(j['title'])}, company = {sql_value(j['company'])}, "
          f"level = {sql_value(j['level'])}, category_id = {cat},")
        w(f"  jd_raw = {sql_str(j['jd_raw'])}, content_hash = {sql_str(j['content_hash'])},")
        w("  version = version + 1, updated_at = CURRENT_TIMESTAMP")
        w(f"WHERE code = {sql_str(j['code'])} AND source = 'seed'")
        w(f"  AND ({drift});")
        w("")

    # -------------------------------------------------------------- 技能要求
    w("-- " + "-" * 76)
    w("-- 5/5 job_requirement + job_tag")
    w("--     skill_id 由 canonical 子查询解析 —— 脚本已保证每个 skill 都在词典里（D3），")
    w("--     所以这里永远不会插入 skill_id 为 NULL 的行。")
    w("--     jd_offset 是 evidence 在 jd_raw 中的字符下标，由脚本算，不手写。")
    w("-- " + "-" * 76)
    for j in jobs:
        w(f"-- {j['code']}")
        if not j["requirements"]:
            w("--   （无技术技能要求：非技术岗，M3.3「岗位 0 技能」边界的真实样本）")
        for r in j["requirements"]:
            jid = f"(SELECT id FROM job WHERE code = {sql_str(j['code'])})"
            sid = f"(SELECT id FROM skill WHERE canonical = {sql_str(r['skill'])})"
            w("INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)")
            w(f"  VALUES ({jid}, {sid}, {sql_str(r['skill'])}, "
              f"{sql_str(r['importance'])}, {sql_str(r['evidence'])}, {r['jd_offset']})")
            w(f"  ON DUPLICATE KEY UPDATE skill_raw = {sql_str(r['skill'])}, "
              f"importance = {sql_str(r['importance'])}, "
              f"evidence = {sql_str(r['evidence'])}, jd_offset = {r['jd_offset']};")
        for tag in j["tags"]:
            jid = f"(SELECT id FROM job WHERE code = {sql_str(j['code'])})"
            w(f"INSERT INTO job_tag (job_id, tag) VALUES ({jid}, {sql_str(tag)})")
            w(f"  ON DUPLICATE KEY UPDATE tag = {sql_str(tag)};")
        w("")

    w("-- " + "=" * 76)
    w("-- 导入完成。自检（AC23）：把本文件连续导入两次，各表行数必须一致：")
    w("--   SELECT COUNT(*) FROM job_category;  -- 14")
    w("--   SELECT COUNT(*) FROM skill;         -- 83")
    w("--   SELECT COUNT(*) FROM job;           -- 7")
    w("--   SELECT COUNT(*) FROM job_requirement WHERE skill_id IS NULL;  -- 必须 0（D3）")
    w("-- " + "=" * 76)
    return "\n".join(out) + "\n"

# --------------------------------------------------------------------------- 入口


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="skills.yaml + categories.json + jobs/*.json → db/seed.sql")
    parser.add_argument("--check", action="store_true", help="只校验源数据，不写文件（CI 用）")
    args = parser.parse_args(argv)

    try:
        categories = load_categories()
        allowed_cats, skills = load_skills()
        del allowed_cats  # 只用于校验
        jobs = load_jobs({c["code"] for c in categories}, {s["canonical"] for s in skills})
        sql = render(categories, skills, jobs)
    except SeedError as exc:
        print(f"[gen-seed] 校验失败：{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"[gen-seed] 源文件缺失：{exc}", file=sys.stderr)
        return 1

    reqs = sum(len(j["requirements"]) for j in jobs)
    aliases = sum(len(s["aliases"]) for s in skills)
    summary = (
        f"分类 {len(categories)} · 技能 {len(skills)} · 别名 {aliases} · "
        f"岗位 {len(jobs)} · 技能要求 {reqs}"
    )

    if args.check:
        print(f"[gen-seed] --check 通过：{summary}（未写文件）")
        return 0

    SEED_SQL.write_text(sql, encoding="utf-8", newline="\n")
    print(f"[gen-seed] 已生成 {SEED_SQL.relative_to(WORKSPACE.parent)}：{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
