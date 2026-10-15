"""简历文本清洗（M2.4 / M2.5）。

清洗是**唯一**该动文本的地方（`normalizer` / `matcher` 都不许再改），
所以这里的断言要钉得死一点 —— 尤其是「哪些字符会被改、哪些不会被改」，
因为下游的 `evidence` 摘录必须能在原文里逐字找到。

覆盖 tasks.md M2.5 点名的：**隐形字符 / 超长**，外加合并断行、章节切块、阅读顺序自检。

> 写这批测试时发现并修掉了三个真 bug（详见 `workspace/DELIVERY.md` 的修复登记）：
> ① 带空格的英文别名（`TECHNICAL SKILLS`）永远匹配不上；
> ② 项目符号行的**续行**会掉成独立一行；
> ③ `is_printable_ratio` 对整篇替换字符的烂文本报 100% 可打印。
> 下面每一条都有对应的回归断言。
"""

from __future__ import annotations

import pytest

from app.core.constants import RESUME_MAX_LENGTH
from app.service.cleaner import (
    SECTION_ALIASES,
    _ALIAS_TO_SECTION,
    check_reading_order,
    clean,
    is_printable_ratio,
    merge_broken_lines,
    normalize_newlines,
    split_sections,
    strip_invisibles,
    unify_width,
)

# ------------------------------------------------------------------ 字符级规整


def test_strip_invisibles_removes_zero_width_characters() -> None:
    """零宽字符不占宽度、肉眼看不见，但会让逐字比对静默失败 —— 最阴的一类脏数据。"""
    assert strip_invisibles("Java\u200bScript") == "JavaScript"
    assert strip_invisibles("Vue\u200d3") == "Vue3"
    assert strip_invisibles("\ufeff张三") == "张三"


def test_strip_invisibles_turns_nbsp_into_a_plain_space() -> None:
    """`\\xa0` 看起来是空格，但 `" " != "\\xa0"` —— 技能名里混一个就永远匹配不上。"""
    cleaned = strip_invisibles("Spring\xa0Boot")

    assert cleaned == "Spring Boot"
    assert "\xa0" not in cleaned


def test_strip_invisibles_removes_soft_hyphen() -> None:
    assert strip_invisibles("Ja\u00adva") == "Java"


def test_strip_invisibles_maps_line_and_paragraph_separators_to_newline() -> None:
    assert strip_invisibles("A\u2028B\u2029C") == "A\nB\nC"


def test_strip_invisibles_converts_the_ideographic_space() -> None:
    """全角空格 U+3000 归 `strip_invisibles` 管（它是「像空格的字符」之一），
    不归 `unify_width` 管 —— 后者只管 FF01–FF5E 那段全角 ASCII。"""
    assert strip_invisibles("Spring\u3000Boot") == "Spring Boot"
    assert unify_width("Spring\u3000Boot") == "Spring\u3000Boot"   # 明确边界，避免两处重复实现


# ------------------------------------------------------- 图标字体的字形（真实样本驱动）

#: 真实样本（`脱敏资料/*.pdf`）里出现过的图标字形。FontAwesome 在 U+F0xx，
#: 另一套模板图标字体在 U+E6xx —— 都落在私用区，抽成文字就是没有含义的码位。
_FA_BULLET = "\uf06c"      # resume_13 / resume_15：列表符号
_ICON_FONT_ICON = "\ue6b1"  # resume_12：标题旁的装饰图标
_FA_INFO = "\uf129"        # resume_10：标题前的图标


def test_strip_invisibles_replaces_a_leading_icon_glyph_with_a_bullet() -> None:
    """★ 真实数据驱动的一条：行首的图标字形是**列表符号**。

    直接删掉它，「项目符号行另起一段」这条规则就失效了 ——
    列表项会被并进上一段，段落结构全丢。所以换成真正的 `•`。
    """
    assert strip_invisibles(f"{_FA_BULLET} 熟练 Vue2/3") == "• 熟练 Vue2/3"
    assert strip_invisibles(f"   {_FA_BULLET}  熟悉 MySQL") == "• 熟悉 MySQL"


def test_strip_invisibles_deletes_inline_icon_glyphs() -> None:
    """行内的图标是纯装饰（「📅 年龄：24 岁」里的日历图标），没有文字含义，删。"""
    cleaned = strip_invisibles(f"姓\u3000\u3000名：张三{_ICON_FONT_ICON}")

    assert _ICON_FONT_ICON not in cleaned
    assert cleaned == "姓  名：张三"


def test_strip_invisibles_treats_del_as_a_leading_bullet() -> None:
    """U+007F(DEL) 在真实样本里也是列表符号（resume_09 的「技术专长」块）。"""
    assert strip_invisibles("\x7f 精通 Python 异步编程") == "• 精通 Python 异步编程"


def test_clean_recovers_list_items_from_icon_font_bullets() -> None:
    """端到端：图标字体的列表符号 → 真正识别成列表项，不再并进上一段。"""
    result = clean(f"个人技能\n{_FA_BULLET} 熟练 Vue2/3\n{_FA_BULLET} 熟悉 MySQL")

    assert result.text == "个人技能\n• 熟练 Vue2/3\n• 熟悉 MySQL"
    assert result.sections["skills"] == "• 熟练 Vue2/3\n• 熟悉 MySQL"


def test_clean_leaves_no_private_use_glyphs_in_the_text() -> None:
    """私用区码位对下游（LLM / 关键词匹配）只有负价值，清洗后不该残留。"""
    result = clean(f"个人简历 {_ICON_FONT_ICON} {_FA_INFO}\n基本信息\n姓名：张三")

    assert not any("\ue000" <= ch <= "\uf8ff" for ch in result.text)
    assert "\x7f" not in result.text


def test_unify_width_converts_fullwidth_ascii_to_halfwidth() -> None:
    assert unify_width("（）") == "()"
    assert unify_width("ＡＢＣ１２３") == "ABC123"


def test_unify_width_keeps_cjk_punctuation_outside_the_fullwidth_ascii_block() -> None:
    """`。`(U+3002) / `、`(U+3001) 不在 FF01–FF5E 里 → **不动**。
    锁死这条边界，避免以后有人图省事换成 NFKC。"""
    assert unify_width("你好。") == "你好。"
    assert unify_width("Java、Vue") == "Java、Vue"


def test_unify_width_does_not_apply_nfkc_folding() -> None:
    """故意不做 NFKC：`①`→`1`、`㎏`→`kg` 这类替换对中文简历破坏性大于收益，
    而且行为随 Unicode 版本变化 —— 清洗结果不该依赖 Python 版本。"""
    assert unify_width("①") == "①"
    assert unify_width("㎏") == "㎏"


def test_normalize_newlines_handles_crlf_and_lone_cr() -> None:
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"


# ------------------------------------------------------------------ 合并断行


def test_merge_joins_chinese_lines_without_a_space() -> None:
    """中文本来就不分词间空格。"""
    assert merge_broken_lines(["负责直播后台", "的开发与维护"]) == "负责直播后台的开发与维护"


def test_merge_joins_latin_lines_with_a_space() -> None:
    assert merge_broken_lines(["Spring", "Boot"]) == "Spring Boot"


def test_merge_rejoins_a_hyphenated_lowercase_word() -> None:
    """行尾连字符是排版断词提示，不是内容：`Soft-\\nware` → `Software`。"""
    assert merge_broken_lines(["Soft-", "ware"]) == "Software"


def test_merge_keeps_a_hyphen_before_a_capitalised_word() -> None:
    """`Spring-\\nBoot` 里的连字符是**内容**（专有名词自带的连字符），不能吞掉。
    只对「小写续行」做断词还原，就是这条边界的取舍。"""
    assert merge_broken_lines(["Spring-", "Boot"]) == "Spring- Boot"


def test_merge_starts_a_new_block_at_a_bullet_but_keeps_its_continuation() -> None:
    """★ 回归：项目符号行另起一段，但**续行要并进它** —— 这里曾经掉成独立一行。"""
    lines = ["项目经历", "• 负责直播后台开发", "与维护工作", "• 负责推荐系统"]

    assert merge_broken_lines(lines) == (
        "项目经历\n• 负责直播后台开发与维护工作\n• 负责推荐系统"
    )


def test_merge_keeps_a_section_header_on_its_own_line() -> None:
    """标题与项目符号**故意不同**：标题的后续行不属于标题。"""
    lines = ["教育背景", "2019-2023 XX 大学 计算机科学与技术"]

    assert merge_broken_lines(lines) == "教育背景\n2019-2023 XX 大学 计算机科学与技术"


def test_merge_starts_a_new_block_after_sentence_end_punctuation() -> None:
    assert merge_broken_lines(["完成了改造。", "下一段内容"]) == "完成了改造。\n下一段内容"


def test_merge_breaks_on_blank_line_and_collapses_consecutive_blanks() -> None:
    """PDF 抽取经常产生 3~5 个连续空行 —— 折叠成 1 个，否则切块与 Prompt 都很脏。"""
    assert merge_broken_lines(["第一段", "", "", "", "第二段"]) == "第一段\n\n第二段"


# ------------------------------------------------------------------ 阅读顺序自检


def test_reading_order_is_not_judged_on_too_few_lines() -> None:
    """3 行里 2 行短 = 0.67，比例没有统计意义 → 直接放过。"""
    assert check_reading_order(["Java", "2023", "本科"]) == (False, 0.0)


def test_reading_order_flags_mostly_short_lines() -> None:
    """双栏 / 表格被按列拼串时，行会大量退化成几个字的碎片 —— 这是有效信号。"""
    lines = ["Java", "2023", "本科", "Vue", "MySQL", "北京", "男", "20", "本科", "硕士", "博士", "学士"]

    suspect, ratio = check_reading_order(lines)

    assert suspect is True
    assert ratio == 1.0


def test_reading_order_accepts_normal_resume_lines() -> None:
    lines = ["负责直播后台系统的开发与维护工作，日均请求量三百万"] * 12

    assert check_reading_order(lines) == (False, 0.0)


def test_reading_order_ignores_blank_lines_in_the_denominator() -> None:
    lines = [""] * 20 + ["这是一行足够长的正常简历正文内容"] * 12

    assert check_reading_order(lines)[0] is False


# ------------------------------------------------------------------ 章节切块


def test_split_sections_puts_the_preamble_under_header() -> None:
    """第一个标题之前是姓名 / 电话 / 邮箱 —— 不属于任何具名章节，但绝不能丢。"""
    text = "张三\n13800000000\nzhang@example.com\n\n教育背景\nXX 大学 本科"

    sections = split_sections(text)

    assert sections["header"].startswith("张三")
    assert "XX 大学" in sections["education"]


def test_split_sections_recognises_a_multi_word_english_alias() -> None:
    """★ 回归：`TECHNICAL SKILLS` 曾经永远匹配不上 ——
    别名表带空格、候选 key 去空格，两边没归一化。"""
    sections = split_sections("TECHNICAL SKILLS\nJava / Vue3 / MySQL")

    assert "Java" in sections["skills"]


def test_split_sections_recognises_headers_mined_from_the_real_corpus() -> None:
    """这几个别名是从 `脱敏资料/*.pdf` 里挖出来的 —— 原本一个都匹配不上，
    整块内容被并进上一段。别名表要跟着真实数据长，而不是靠想。"""
    sections = split_sections(
        "个人技能\nJava\n\n技术专长\nPython\n\n个人优势\n沟通能力强\n\n求职岗位\nJava 开发工程师"
    )

    assert "Java" in sections["skills"]
    assert "Python" in sections["skills"]          # 两个别名指向同一章节 → 合并
    assert "沟通能力强" in sections["summary"]
    assert "Java 开发工程师" in sections["job_intent"]


def test_split_sections_recognises_numbered_and_decorated_headers() -> None:
    sections = split_sections("一、教育背景：\nXX 大学\n【项目经历】\n直播后台")

    assert "XX 大学" in sections["education"]
    assert "直播后台" in sections["projects"]


def test_split_sections_merges_repeated_headers() -> None:
    """同一章节名出现两次时合并，不覆盖。"""
    sections = split_sections("技能\nJava\n\n技能\nVue")

    assert sections["skills"].split("\n") == ["Java", "", "Vue"]


def test_split_sections_does_not_mistake_a_sentence_for_a_header() -> None:
    """保守判定的意义：正文里以「技能」开头的句子不能被当成标题 ——
    误切会把正文片段塞进 `sections`，让下游以为那是独立章节。"""
    sections = split_sections("技能要求：熟悉 Java 与 Vue3 的开发经验，具备良好的沟通能力")

    assert set(sections) == {"header"}


def test_split_sections_returns_empty_dict_for_empty_text() -> None:
    """切不出来不是错误。"""
    assert split_sections("") == {}


def test_alias_table_has_no_collisions_after_normalisation() -> None:
    """归一化后若两条别名撞车，字典推导会**静默丢掉一条** —— 用计数把它钉住。"""
    total = sum(len(aliases) for aliases in SECTION_ALIASES.values())

    assert len(_ALIAS_TO_SECTION) == total


# ------------------------------------------------------------------ clean 主入口


def test_clean_normalises_invisible_characters_end_to_end() -> None:
    result = clean("Java\u200bScript\n\nSpring\xa0Boot")

    assert result.text == "JavaScript\n\nSpring Boot"
    assert "\u200b" not in result.text
    assert "\xa0" not in result.text


def test_clean_marks_truncation_and_keeps_the_text_within_the_limit() -> None:
    """ADR-109：>20000 → 截断并标记（`meta.truncated`），不是报错。"""
    long_text = "正文内容。" * 500

    result = clean(long_text, max_length=100)

    assert result.truncated is True
    assert len(result.text) == 100
    assert result.original_length > 100
    assert any("截断" in warning for warning in result.warnings)


def test_clean_does_not_mark_truncation_when_within_the_limit() -> None:
    result = clean("短文本")

    assert result.truncated is False
    assert result.original_length == len(result.text)


def test_clean_default_limit_is_the_contract_value() -> None:
    result = clean("x" * (RESUME_MAX_LENGTH + 1))

    assert result.truncated is True
    assert len(result.text) == RESUME_MAX_LENGTH


def test_clean_splits_sections_and_keeps_names_in_the_closed_set() -> None:
    result = clean("教育背景\nXX 大学\n\n项目经历\n直播后台\n\n专业技能\nJava")

    assert {"education", "projects", "skills"} <= set(result.sections)
    assert set(result.sections) <= set(SECTION_ALIASES) | {"header"}


def test_clean_warns_when_reading_order_looks_broken() -> None:
    """只 WARN，不阻断（spec §3 明确不承诺所有排版都能正确解析）。"""
    text = "\n".join(
        ["Java", "Vue", "2023", "本科", "北京", "男", "硕士", "MySQL", "Redis", "Koa", "Vue3", "Vite"]
    )

    result = clean(text)

    assert result.reading_order_suspect is True
    assert any("阅读顺序" in warning for warning in result.warnings)


def test_clean_is_pure_and_deterministic() -> None:
    """纯函数：同样输入必得同样输出。后面所有阶段的可复现性都建立在它上面。"""
    sample = "教育背景\nXX 大学\n\n技能\nJava、Vue3"

    assert clean(sample) == clean(sample)


def test_clean_handles_empty_text_without_raising() -> None:
    result = clean("")

    assert result.text == ""
    assert result.sections == {}
    assert result.truncated is False


# ------------------------------------------------------------------ 排障指标


def test_is_printable_ratio_of_empty_text_is_zero() -> None:
    assert is_printable_ratio("") == 0.0


def test_is_printable_ratio_of_clean_text_is_one() -> None:
    assert is_printable_ratio("正常文本\nwith latin") == 1.0


def test_is_printable_ratio_counts_replacement_characters_as_bad() -> None:
    """★ 回归：`\\ufffd` 属于 Unicode 的 `So` 类，`str.isprintable()` 认为它可打印 ——
    但对我们的用途它恰恰是最该被发现的坏信号。"""
    assert is_printable_ratio("\ufffd\ufffd") == 0.0


def test_is_printable_ratio_counts_control_characters_as_bad() -> None:
    assert is_printable_ratio("a\x00b") == pytest.approx(2 / 3)
