"""M3 真实样本门禁 —— 用 `脱敏资料/` 里的真 PDF 跑通「解析 → 清洗 → 归一化 → 匹配 → 推荐」。

**为什么必须用真实样本**（tasks.md DoD #9）：
构造的假 PDF 只有「格式正确」一个属性，而真实简历带着全部脏数据 ——
图标字形、双栏、软连字符、中英混排、技能写成 `SpringBoot` / `VUE3` / `C/C++`。
归一化和匹配的bug 九成只在这些输入上现形。

**为什么缺失时 skip 而不是 fail**：
真实简历涉及隐私，克隆仓库时可能不带这批文件。此时应跳过，
而不是让整套测试红掉 —— 否则 CI 会因为「没有样本」这种环境原因失败。
"""

from __future__ import annotations
import json
import time
from pathlib import Path
import pytest
from app.service.document.cleaner import clean
from app.service.match.matcher import Requirement, ResumeSkills
from app.service.skill.normalizer import get_dictionary
from app.service.document.parser_plugin import default_registry
from app.service.match.recommender import JobCandidate, recommend


@pytest.fixture(scope="module")
def dictionary():
    return get_dictionary()


def _candidates_from_seed(seed_jobs_dir: Path) -> list[JobCandidate]:
    candidates: list[JobCandidate] = []
    for path in sorted(seed_jobs_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        candidates.append(
            JobCandidate(
                jobId=raw["code"],
                title=raw["title"],
                company=raw.get("company"),
                level=raw.get("level"),
                category=raw.get("category"),
                requirements=tuple(
                    Requirement(
                        skill=r["skill"],
                        importance=r["importance"],
                        evidence=r.get("evidence", ""),
                        jd_offset=r.get("jdOffset"),
                        skill_raw=r.get("skillRaw"),
                    )
                    for r in raw["requirements"]
                ),
            )
        )
    return candidates


@pytest.fixture(scope="module")
def seed_jobs_dir() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        found = candidate / "db" / "seed" / "jobs"
        if found.is_dir():
            return found
    pytest.fail("找不到 workspace/db/seed/jobs")


@pytest.mark.parametrize("index", range(3))
def test_real_resume_produces_recommendations(
    index: int, real_resume_dir: Path | None, seed_jobs_dir: Path, dictionary
) -> None:
    """抽 3 份真实简历（按文件名排序取前 3，保证可复现）跑完整推荐链。

    断言的是**不变量**而不是具体分数：技能数 > 0、推荐条数 = min(3, 岗位数)、
    降序、`reason` 非空。具体分数会随样本变化，写死它只会得到一堆脆弱的用例。
    """
    if real_resume_dir is None:
        pytest.skip("仓库里没有 脱敏资料/ 真实样本，跳过真实样本门禁")

    pdfs = sorted(real_resume_dir.glob("*.pdf"))
    assert len(pdfs) >= index + 1, f"真实样本不足 {index + 1} 份"

    data = pdfs[index].read_bytes()
    parser = default_registry().detect(data)
    assert parser is not None, f"{pdfs[index].name} 不是可识别的 PDF"

    parsed = parser.parse(data)
    cleaned = clean(parsed.text)
    resume = ResumeSkills(tuple(dictionary.extract_unique(cleaned.text)))

    # ① 清洗与归一化：真实简历必须能认出至少一个技能
    assert cleaned.text, "清洗后文本为空"
    assert len(resume) >= 1, f"{pdfs[index].name} 一个技能都没认出 —— 词典或抽取有问题"

    # ② 匹配与推荐
    candidates = _candidates_from_seed(seed_jobs_dir)
    recommendations = recommend(candidates, resume)

    assert len(recommendations) == min(3, len(candidates))
    assert [r.score for r in recommendations] == sorted(
        (r.score for r in recommendations), reverse=True
    )
    for recommendation in recommendations:
        assert recommendation.reason, "reason 不允许为空"
        assert recommendation.title
        # 集合自洽（AC17）
        matched = {m.skill for m in recommendation.matched}
        missing = {m.skill for m in recommendation.missing}
        assert matched & missing == set()
        assert matched | missing == {
            r.skill
            for c in candidates
            if c.jobId == recommendation.jobId
            for r in c.requirements
        }


def test_full_chain_on_all_real_samples_stays_within_time_budget(
    real_resume_dir: Path | None, seed_jobs_dir: Path, dictionary
) -> None:
    """20 份真实样本全跑一遍的耗时预算。

    这不是性能测试，是**回归护栏**：归一化是 O(别名数 × 文本长度)，
    一旦有人把它改成对每个候选岗位重扫一遍全文，耗时会是岗位数的倍数 ——
    这里会在它变慢一个数量级之前就红。
    """
    if real_resume_dir is None:
        pytest.skip("仓库里没有 脱敏资料/ 真实样本，跳过真实样本门禁")

    pdfs = sorted(real_resume_dir.glob("*.pdf"))
    candidates = _candidates_from_seed(seed_jobs_dir)
    registry = default_registry()

    started = time.perf_counter()
    recognised = 0
    for pdf in pdfs:
        data = pdf.read_bytes()
        parser = registry.detect(data)
        if parser is None:
            continue
        cleaned = clean(parser.parse(data).text)
        resume = ResumeSkills(tuple(dictionary.extract_unique(cleaned.text)))
        recommend(candidates, resume)
        recognised += 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert recognised >= len(pdfs) - 1, f"{len(pdfs) - recognised} 份样本解析失败"
    # 20 份 × (解析 + 清洗 + 归一化 + 7 岗位匹配)。阈值放宽到 30s：
    # PDF 解析本身就要几十毫秒，这里要防的是数量级退化，不是常数倍波动。
    assert elapsed_ms < 30_000, f"{len(pdfs)} 份样本耗时 {elapsed_ms:.0f}ms，疑似算法退化"
