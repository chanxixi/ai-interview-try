"""种子数据一致性（M3.5）—— D3 的前置校验。

**为什么这道校验必须是测试而不是脚本**：
`scripts/gen-seed.sh` 已经在构建期校验「技能未登录词典」，
但它只在**跑脚本的时候**校验。将来有人直接改 `db/seed.sql`、或者往
`db/seed/jobs/*.json` 里加一个没复跑脚本的技能，构建期那道关就绕过去了。
放在 pytest 里，`mvn test` / CI 一跑就能发现。

三条断言，对应三条会静默出错的路：

1. 每个 `job_requirement.skill` 都是 `skills.yaml` 的 canonical
   → 否则库里出现 `skill_id IS NULL` 的行（D3 明令禁止）；
2. `extract_requirements()` 能从该岗位的 `jdRaw` 里抽回**全部**人工标注的技能
   → 否则「离线标注一套、运行期抽取另一套」，自定义 JD 路径的匹配度会莫名其妙偏低；
3. 岗位 `category` 都在 `categories.json` 的分类树里
   → 否则前端按分类筛岗位时这个岗位直接消失（D1）。
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from app.service.match.matcher import extract_requirements
from app.service.skill.normalizer import get_dictionary


def _load_jobs(seed_jobs_dir: Path) -> list[dict]:
    jobs = []
    for path in sorted(seed_jobs_dir.glob("*.json")):
        jobs.append(json.loads(path.read_text(encoding="utf-8")))
    assert jobs, f"{seed_jobs_dir} 下没有任何岗位 JSON"
    return jobs


def test_every_requirement_skill_is_a_known_canonical(seed_jobs_dir: Path) -> None:
    """D3：`job_requirement.skill` 一律是 canonical，库里不允许 `skill_id IS NULL`。"""
    dictionary = get_dictionary()
    jobs = _load_jobs(seed_jobs_dir)

    unknown: list[str] = []
    for job in jobs:
        for requirement in job["requirements"]:
            if requirement["skill"] not in dictionary:
                unknown.append(f"{job['code']} → {requirement['skill']}")

    assert not unknown, "以下技能未登录 skills.yaml，请先补词典再复跑 gen-seed.sh：" + "；".join(unknown)


def test_extractor_recovers_every_curated_skill_from_real_jd(seed_jobs_dir: Path) -> None:
    """运行期抽取器必须能从真实 JD 里抽回**全部**人工标注的技能。

    这是两条路径的口径对齐：预置岗位走「离线标注 + 落库」，
    自定义 JD 走「运行期抽取」。若抽取器漏掉某个技能，
    同一个人粘贴 JD 得到的匹配度会低于选预置岗位 —— 而用户没有任何线索知道为什么。
    """
    dictionary = get_dictionary()
    jobs = _load_jobs(seed_jobs_dir)

    missing: list[str] = []
    for job in jobs:
        extracted = {r.skill for r in extract_requirements(dictionary, job["jdRaw"])}
        for requirement in job["requirements"]:
            if requirement["skill"] not in extracted:
                missing.append(f"{job['code']} → {requirement['skill']}")

    assert not missing, "以下人工标注的技能无法从 jdRaw 抽回：" + "；".join(missing)


def test_job_categories_exist_in_taxonomy(seed_jobs_dir: Path) -> None:
    """D1：分类是数据。岗位的 `category` 必须能在分类树里找到，
    否则前端按分类筛选时该岗位会静默消失。
    """
    categories_file = seed_jobs_dir.parent / "categories.json"
    assert categories_file.is_file(), "缺少 db/seed/categories.json"

    tree = json.loads(categories_file.read_text(encoding="utf-8"))["categories"]
    known = {node["code"] for node in tree}

    jobs = _load_jobs(seed_jobs_dir)
    orphan = [f"{job['code']} → {job['category']}" for job in jobs if job["category"] not in known]

    assert not orphan, "以下岗位的分类不在分类树里：" + "；".join(orphan)


def test_every_job_has_requirements_or_declares_the_exception(seed_jobs_dir: Path) -> None:
    """每个岗位要么有技能要求，要么**显式声明**自己是 0 技能样本。

    `job-operation-01`（运营岗）有意 `requirements: []` —— 它是 M3.3「岗位 0 技能」
    边界的真实样本，测试的就是「除零不崩」。所以这里不能一律要求非空，
    但也不能允许「忘了写」和「有意为空」长得一样：后者必须带 `_zeroRequirements: true`。
    少了这个标记，将来某个岗位漏配要求会静默变成 0 分推荐，没人会发现。
    """
    jobs = _load_jobs(seed_jobs_dir)

    for job in jobs:
        if job["requirements"]:
            continue
        assert job.get("_zeroRequirements") is True, (
            f"{job['code']} 的 requirements 是空数组但没标 `_zeroRequirements`；"
            "若这是有意的（如非技术岗），请补上标记并写清理由"
        )


def test_every_requirement_has_evidence_verbatim_in_jd(seed_jobs_dir: Path) -> None:
    """`evidence` 是给人看的「为什么要求这个技能」，必须能在 jdRaw 里逐字找到。

    逐字找不到就是编的 —— `gen-seed.sh` 构建期也查这条，这里作为回归护栏。
    """
    jobs = _load_jobs(seed_jobs_dir)

    for job in jobs:
        for requirement in job["requirements"]:
            evidence = requirement.get("evidence") or ""
            assert evidence, f"{job['code']}/{requirement['skill']} 缺少 evidence"
            assert evidence in job["jdRaw"], (
                f"{job['code']}/{requirement['skill']} 的 evidence 不是 jdRaw 的逐字片段"
            )
