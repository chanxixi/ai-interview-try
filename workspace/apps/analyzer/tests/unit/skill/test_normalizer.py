"""技能归一化（M3.2 / M3.6）。

这一层是整条匹配链的**入口**：它认不出的技能，后面全都当不存在。
所以断言要钉死两件事 —— ① 该认的一个不漏；② **不该认的一个不认**。
②比①重要：漏认只是分数偏低，误认（把 `JavaScript` 当成 `Java`）会让
「明明没写过 Java」的人拿到命中项，属于**给出错误证据**，比漏认严重得多。

覆盖 tasks.md M3.2 的四步：查别名 → 规范化后再查 → 编辑距离兜底 → unknown。
"""

from __future__ import annotations
import time
import pytest
from app.core.constants import FUZZY_MATCH_THRESHOLD, FUZZY_MIN_LENGTH, MIN_SCAN_ALIAS_LENGTH
from app.service.skill.normalizer import (
    SkillDictionary,
    SkillEntry,
    SkillMention,
    edit_distance,
    fold,
    get_dictionary,
    similarity,
)


@pytest.fixture(scope="module")
def dictionary() -> SkillDictionary:
    return get_dictionary()


# ------------------------------------------------------------------ 词典加载


def test_dictionary_loads_from_repo_yaml(dictionary: SkillDictionary) -> None:
    """词典必须从仓库里的 YAML 加载（C4：真源在仓库，不在数据库）。

    `source` 指向真实文件这一条也要断言 —— 否则哪天路径算错、`load()` 回退到空词典，
    下面所有「认不出」的用例会集体通过（空词典对所有输入都返回 None），
    测试全绿而功能全废。
    """
    assert len(dictionary) >= 60, "spec §1 要求 skills.yaml ≥60 条"
    assert dictionary.source.endswith("skills.yaml")
    assert "language" in dictionary.categories


def test_dictionary_rejects_ambiguous_alias() -> None:
    """两个技能写同一个别名 → 构造期就炸。

    不拦的后果是「同一个字符串这次归 A、下次归 B」（取决于遍历顺序），
    而这种不确定性在打分里表现为无法复现的偶发 bug。
    """
    with pytest.raises(ValueError, match="别名歧义"):
        SkillDictionary.from_entries(
            [
                SkillEntry(canonical="Java", category="language", aliases=("JDK",)),
                SkillEntry(canonical="JavaScript", category="language", aliases=("jdk",)),
            ],
            categories=("language",),
        )


def test_dictionary_rejects_category_outside_closed_set(tmp_path) -> None:
    """category 是闭集（plan §4.4）。写错分类比不写分类更糟 —— 它会让
    「按分类统计技能分布」的下游拿到一个从不出现的值。
    """
    bad = tmp_path / "skills.yaml"
    bad.write_text(
        "categories: [language]\nskills:\n  - canonical: Java\n    category: framework\n    aliases: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="category"):
        SkillDictionary.load(bad)


def test_dictionary_fails_loudly_when_file_missing(tmp_path) -> None:
    """词典缺失必须**立刻炸**，不能静默返回空词典。

    空词典会让所有技能变 unknown → 匹配度全是 0 → 表现为「系统坏了但没报错」，
    这是最难查的一类故障。
    """
    with pytest.raises(FileNotFoundError):
        SkillDictionary.load(tmp_path / "nope.yaml")


# ------------------------------------------------------------------ 四步归一化


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # ① 查别名表（精确）
        ("SpringBoot", "Spring Boot"),
        ("Koa2", "Koa"),
        ("Golang", "Go"),
        ("大模型", "LLM"),
        # ② 规范化后再查：大小写 / 空格 / 连接符 / 全半角
        ("spring boot", "Spring Boot"),
        ("SPRINGBOOT", "Spring Boot"),
        ("spring-boot", "Spring Boot"),
        ("spring_boot", "Spring Boot"),
        ("ＳＰＲＩＮＧ　ＢＯＯＴ", "Spring Boot"),
        ("nodejs", "Node.js"),
        ("tcp ip", "TCP/IP"),
        ("c/c++", "C++"),
        ("vue3", "Vue"),
        ("es6", "JavaScript"),
        # ③ 编辑距离兜底
        ("Typescrpt", "TypeScript"),
        ("Sprng Boot", "Spring Boot"),
        # ④ unknown
        ("塞伯坦星语", None),
        ("Blockchainxxx", None),
    ],
)
def test_normalize_four_steps(dictionary: SkillDictionary, raw: str, expected: str | None) -> None:
    assert dictionary.normalize(raw) == expected


def test_normalize_java_is_not_javascript(dictionary: SkillDictionary) -> None:
    """**本文件最重要的一条**：`Java` 不许被归一成 `JavaScript`（tasks.md M3.2 点名）。

    三条防线各自单独验证，坏掉任何一条这个用例就会红：
    ① 编辑距离门槛 —— `java` vs `javascript` 相似度只有 0.40，进不了兜底；
    ② 抽取时的边界检查 —— `JavaScript` 里找 `java`，后一个字符是 `S`（ASCII 字母数字）；
    ③ 最长优先 —— `javascript` 比 `java` 先匹配。
    """
    assert dictionary.normalize("Java") == "Java"
    assert dictionary.normalize("java") == "Java"
    assert dictionary.normalize("JavaScript") == "JavaScript"
    assert dictionary.normalize("javascript") == "JavaScript"

    # 防线①：相似度离阈值很远，且 java 长度已过门槛（4），所以是「真的不相似」而非「被门槛挡住」
    assert similarity("java", "javascript") < FUZZY_MATCH_THRESHOLD
    assert len("java") >= FUZZY_MIN_LENGTH

    # 防线② + ③：文本里只应命中 JavaScript，不该额外产出 Java
    canonicals = [m.canonical for m in dictionary.extract("熟悉 JavaScript 与 TypeScript")]
    assert canonicals == ["JavaScript", "TypeScript"]


def test_normalize_is_deterministic(dictionary: SkillDictionary) -> None:
    """同一输入两次调用结果一致（spec §2.4 确定性）。

    兜底那一步遍历的是 `sorted(self._by_folded)` 且只在「严格更高」时替换，
    所以同分时取字典序更小的 canonical —— 这里连跑两遍验证没有隐藏的字典序依赖。
    """
    for raw in ("Typescrpt", "Sprng Boot", "kubernetess", "java", "JavaScript"):
        assert dictionary.normalize(raw) == dictionary.normalize(raw)


def test_normalize_rejects_empty_and_none(dictionary: SkillDictionary) -> None:
    assert dictionary.normalize("") is None
    assert dictionary.normalize("   ") is None
    assert dictionary.normalize(None) is None


# ------------------------------------------------------------------ 全文抽取


def test_extract_returns_offset_into_original_text(dictionary: SkillDictionary) -> None:
    """`offset` 必须是**原文**坐标，不是折叠后坐标。

    折叠会删空格，两者差好几个字符；拿折叠坐标去原文高亮会整体错位，
    而 `resumeEvidence` 是给用户看的证据，错位等于证据失效。
    """
    text = "后端：Spring Boot + MySQL"
    mentions = {m.canonical: m for m in dictionary.extract(text)}

    assert mentions["Spring Boot"].offset == 3
    assert text[mentions["Spring Boot"].offset :][:11] == "Spring Boot"
    assert text[mentions["MySQL"].offset :][:5] == "MySQL"


def test_extract_raw_is_verbatim_substring(dictionary: SkillDictionary) -> None:
    """`raw` 必须能在原文里逐字找到（`evidence` 的可用性依赖这条）。"""
    text = "熟悉C/C++/Java开发语言，具备良好的编程习惯"
    mentions = {m.canonical: m for m in dictionary.extract(text)}

    assert mentions["C++"].raw == "C/C++"      # 原文写法，不是标准名
    assert mentions["Java"].raw == "Java"
    assert text[mentions["C++"].offset :][:5] == "C/C++"


def test_extract_does_not_match_inside_longer_ascii_word(dictionary: SkillDictionary) -> None:
    """边界检查：`Go` 不许命中 `Google`，`Git` 不许命中 `GitHub`。"""
    canonicals = [m.canonical for m in dictionary.extract("用 Google 搜资料，代码放 GitHub")]
    assert "Go" not in canonicals
    assert "Git" not in canonicals
    assert canonicals == []


def test_extract_prefers_longest_alias(dictionary: SkillDictionary) -> None:
    """最长优先：`Vue3` 命中 Vue 一次，不该同时产出 `Vue` 和 `Vue3` 两条。"""
    mentions = dictionary.extract("熟练使用 Vue3 与 Vite")
    assert [m.canonical for m in mentions] == ["Vue", "Vite"]
    assert mentions[0].raw == "Vue3"


def test_extract_matches_cjk_without_word_boundary(dictionary: SkillDictionary) -> None:
    """中文没有词边界，「大语言模型」在长句里就是子串命中。

    这条与上一条不矛盾：边界规则只对 ASCII 别名生效（`term.isascii()`）。
    """
    mentions = dictionary.extract("具备大语言模型与检索增强生成相关实践经验")
    assert [m.canonical for m in mentions] == ["LLM", "RAG"]


def test_extract_keeps_repeats_and_extract_unique_dedupes(dictionary: SkillDictionary) -> None:
    """`extract` 保留重复（原始事实），`extract_unique` 按 canonical 去重。

    打分只关心「会不会」，但 `resume.skills` 要给人看 —— 列 5 条 Java 没有信息量。
    """
    text = "熟悉 Java；项目用 Java；还写过一点 java"

    every = dictionary.extract(text)
    assert len(every) == 3
    assert [m.raw for m in every] == ["Java", "Java", "java"]

    unique = dictionary.extract_unique(text)
    assert [m.canonical for m in unique] == ["Java"]
    assert unique[0].raw == "Java"          # 保留第一次出现
    assert unique[0].offset == every[0].offset


def test_extract_on_empty_text(dictionary: SkillDictionary) -> None:
    assert dictionary.extract("") == []
    assert dictionary.extract_unique("") == []


def test_single_letter_alias_is_not_scanned_but_is_normalizable(dictionary: SkillDictionary) -> None:
    """单字母别名（`C`）不参与全文扫描，但 `normalize()` 仍认它。

    为什么不扫描：`C++` 里的 `C` 后面跟的是 `+`（不是 ASCII 字母数字），
    边界检查救不了它 —— 会把 `C++` 同时判成 `C` 和 `C++`，同一段文本重复计分。
    """
    assert MIN_SCAN_ALIAS_LENGTH >= 2
    assert dictionary.normalize("C") == "C"

    canonicals = [m.canonical for m in dictionary.extract("熟悉 C++ 与 C#")]
    assert canonicals == ["C++", "C#"]


def test_extract_stays_within_time_budget(dictionary: SkillDictionary) -> None:
    """性能预算（模块 docstring 里写了「143 词 × 23200 字符 ≈ 10ms」）。

    阈值放 500ms 而不是 20ms：CI 机器比开发机慢是常态，卡得太紧会得到
    随机器波动的假失败。这里要防的是**算法退化**（比如不小心变成 O(n²)），
    不是一个常数倍的快慢。
    """
    text = "熟练掌握 Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes；" * 400
    assert len(text) > 20_000

    started = time.perf_counter()
    mentions = dictionary.extract(text)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert len(mentions) == 2800
    assert elapsed_ms < 500, f"抽取 23200 字符耗时 {elapsed_ms:.0f}ms，超出预算"


# ------------------------------------------------------------------ 相似度工具


def test_similarity_uses_longer_length_as_denominator() -> None:
    """分母取**较长**者长度，这样 `java` vs `javascript` 才会低到进不了兜底。

    若取较短者，相似度会是 1 - 6/4 = -0.5（更宽松的反面：`abc` vs `abcdefgh` 会算 0.5），
    短词之间会大面积互撞。
    """
    assert similarity("java", "javascript") == pytest.approx(1 - 6 / 10)
    assert similarity("abc", "abcdefgh") == pytest.approx(1 - 5 / 8)


def test_edit_distance_basics() -> None:
    assert edit_distance("", "") == 0
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("abc", "") == 3
    assert edit_distance("", "abc") == 3
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("java", "javascript") == 6


def test_fold_drops_separators_but_keeps_meaningful_symbols() -> None:
    """`+` / `#` 必须保留 —— `C++` 与 `C`、`C#` 与 `C` 是不同的技能。"""
    assert fold("C++") == "c++"
    assert fold("C#") == "c#"
    assert fold("TCP/IP") == "tcpip"
    assert fold("Spring Boot") == "springboot"
    assert fold("Node.js") == "nodejs"
    assert fold("  Spring\tBoot\n") == "springboot"


def test_mention_is_frozen() -> None:
    """结果类型是 frozen dataclass —— 命中事实不该被下游改。"""
    mention = SkillMention(raw="Java", canonical="Java", category="language", offset=0)
    with pytest.raises(Exception):
        mention.offset = 5  # type: ignore[misc]
