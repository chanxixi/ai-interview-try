"""简历文本清洗 —— 解析出来的「原始文本」到「能拿去分析的正经文本」。

**为什么清洗必须独立成一层**：PDF 抽出来的文本是**按视觉排版**的碎片 ——
一行是「排版行」而不是「语义行」，还夹着零宽字符、不换行空格、全角标点。
后面每一步（技能归一化、证据摘录、LLM Prompt）都建立在这份文本上，
所以这里是**唯一**该做文本规整的地方：`normalizer` / `matcher` 都不许再改文本，
否则「同一个技能在两处匹配不上」这种问题会极难定位。

**七步，顺序有讲究**（顺序错了结果就不对）：

| # | 步骤 | 为什么在这个位置 |
|---|---|---|
| 1 | 统一换行 | 后面所有按行处理都假设只有 `\\n` |
| 2 | 去隐形字符 + 图标字形 | 零宽字符会让「逐字匹配」静默失败；图标字体的私用区字形不是文字，但**行首的那个是列表符号**（见 `strip_invisibles`） |
| 3 | 全半角统一 | 让「（）」与「()」在匹配时等价；**在合并断行之前**，否则行尾判断要处理两套标点 |
| 4 | **阅读顺序自检** | ★ 必须在合并断行**之前**：合并会毁掉行结构，之后再算「短行占比」就没意义了 |
| 5 | 合并断行 | 把「排版行」还原成「语义行」 |
| 6 | 截断 | 按最终要用的文本长度截断（>20000 → 截断并标记，ADR-109） |
| 7 | 按章节切块 | 切块描述的是**真正会往下走的那份文本**，所以放在截断之后 |

**本文件不做什么**：不读文件（那是 `*_parser.py`）、不抛业务错误码（清洗失败就是编程错误）、
不认技能（那是 `normalizer.py`）。
"""

from __future__ import annotations
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from app.core.constants import (
    READING_ORDER_MIN_LINES,
    READING_ORDER_SHORT_LINE_RATIO,
    RESUME_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 字符级规整

#: 零宽 / 双向控制字符：直接删。它们不占宽度，肉眼看不出来，
#: 但会让 `evidence` 与原文的逐字比对失败 —— 属于最阴的一类脏数据。
_ZERO_WIDTH_CHARS = (
    "\u200b"  # ZERO WIDTH SPACE —— 从网页复制简历时最常见
    "\u200c"  # ZERO WIDTH NON-JOINER
    "\u200d"  # ZERO WIDTH JOINER
    "\u200e"  # LEFT-TO-RIGHT MARK
    "\u200f"  # RIGHT-TO-LEFT MARK
    "\u2060"  # WORD JOINER
    "\ufeff"  # ZERO WIDTH NO-BREAK SPACE（BOM 混进正文）
)

#: 软连字符：排版换行提示，不是内容，删。
_SOFT_HYPHEN = "\u00ad"

#: 「像空格的」字符 → 普通空格。`\xa0`（NO-BREAK SPACE）是最常见的：
#: 它看起来是空格，但 `" " != "\xa0"`，技能名里混一个就永远匹配不上。
_SPACE_LIKE_CHARS = (
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u202f\u205f\u3000"
)

#: 行分隔符 / 段分隔符 → 换行
_LINE_SEPARATORS = "\u2028\u2029"

#: 图标字体的字形：落在**私用区**（U+E000–U+F8FF）或 DEL(0x7F)。
#:
#: 真实样本（`脱敏资料/*.pdf`）里它们是 FontAwesome / IcoMoon 这类图标字体的字形 ——
#: 在 PDF 上画出来是「小圆点」「电话图标」，抽成文字就成了没有文字含义的私用区码位。
#: 20 份样本里出现的：`\uf06c \uf06e \uf0d8 \uf0b2 \uf129 \uf095 \ue609 \ue656 \ue6b1` …
#:
#: ⚠️ **已知风险**：极老的中文字体可能把生僻字映射到私用区，那种情况下这里会误删。
#: 样本里 100% 是图标字形，所以先按这个规则走；真遇到丢字就收窄范围（见 DELIVERY.md 已知缺口）。
_SYMBOL_GLYPH_RE = re.compile("[\u007f\ue000-\uf8ff]")

#: 行首（允许前导空白）的图标字形 → 换成**真正的项目符号**。
#: 不换成空串的理由：项目符号是 `merge_broken_lines` 判断「另起一段」的依据，
#: 抹掉它会让「• 熟练 Vue2/3」这类列表项被并进上一段，段落结构就丢了。
#: 真实数据里 `\uf06c 熟练 Vue2/3`、`\x7f 精通 Python` 都属于这种。
_LEADING_SYMBOL_GLYPH_RE = re.compile(r"(?m)^[^\S\n]*[\u007f\ue000-\uf8ff]+[^\S\n]*")

_INVISIBLE_TABLE = {ord(ch): None for ch in _ZERO_WIDTH_CHARS + _SOFT_HYPHEN}
_SPACE_TABLE = {ord(ch): " " for ch in _SPACE_LIKE_CHARS}
_LINE_SEP_TABLE = {ord(ch): "\n" for ch in _LINE_SEPARATORS}

# ---------------------------------------------------------------- 行级判断

#: 项目符号 / 编号：这些行**一定是新的一条**，不能跟上一行合并。
_BULLET_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"[•·▪▫◦●○◆◇■□▶►※★☆\-–—*+>]"
    r"|\d{1,2}\s*[.、)）]"
    r"|[（(]\s*\d{1,2}\s*[)）]"
    r"|[一二三四五六七八九十]{1,3}\s*[、.)）]"
    r")\s*"
)

#: 句末标点：上一行以它结尾 → 说明那是一句的结束，不该与下一行粘连。
_SENTENCE_END = "。！？；!?;：:"

#: 章节标题别名表。**用 dict 只是为了分组可读** —— 查表走的是「归一化后精确相等」，
#: 与别名顺序无关（所以 `"项目经历"` 不必排在 `"项目"` 前面：两者都精确匹配，不会互相截胡；
#: 反过来说，`"项目"` 这个别名本身也不存在，不会被误当成 `"项目经历"`）。
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "job_intent": (
        "求职意向", "求职目标", "求职岗位", "期望职位", "期望岗位", "job intent", "objective",
    ),
    "education": ("教育背景", "教育经历", "教育情况", "学历背景", "教育", "education"),
    "experience": (
        "工作经历", "实习经历", "工作经验", "工作履历", "职业经历", "相关经历",
        "work experience", "experience",
    ),
    "projects": ("项目经历", "项目经验", "项目实践", "projects", "project experience"),
    "campus": ("校园经历", "在校经历", "社团经历", "学生工作", "校园实践", "campus"),
    "skills": (
        "专业技能", "技能清单", "掌握技能", "技能特长", "技术栈", "技能",
        # ↓ 这两个是从真实样本（脱敏资料/*.pdf）里挖出来的：它们在自己的简历里是独立标题，
        #   但原表没有，于是整块被并进上一段。别名表要跟着真实数据长，而不是靠想。
        "个人技能", "技术专长",
        "skills", "technical skills",
    ),
    "awards": ("获奖情况", "荣誉奖项", "获奖经历", "奖项", "荣誉", "awards", "honors"),
    "certificates": ("技能证书", "资格证书", "证书", "certificates", "certifications"),
    "summary": (
        "自我评价", "个人评价", "个人总结", "个人优势", "自我介绍", "个人简介",
        "summary", "about me",
    ),
    "basic": ("个人信息", "基本信息", "个人资料", "联系方式", "contact", "profile"),
}


def _alias_key(alias: str) -> str:
    """别名归一化 —— 候选行与别名表必须用**同一个**函数处理，否则两边对不上。

    为什么要去空白：别名里有 `"technical skills"` / `"project experience"` 这种带空格的，
    而候选行的 key 会被去掉所有空白。不一起处理的话，这些多词别名就是
    「表里有、实际永远匹配不上」的死条目 —— 写测试时才暴露出来。
    """
    return re.sub(r"\s+", "", alias.lower())


#: 归一化别名 → 规范章节名，用于 O(1) 查表
_ALIAS_TO_SECTION: dict[str, str] = {
    _alias_key(alias): name for name, aliases in SECTION_ALIASES.items() for alias in aliases
}

#: 标题行长度上限。**由别名表推导，不写死数字**：
#: 写死 12 会让 `"project experience"`(17) / `"technical skills"`(15) 这类长别名永远匹配不上。
#: 「不误判」本来就由「归一化后必须与某个别名**完全相等**」这条保证，
#: 这个上限只是把「标题不可能很长」的意图显式写出来，顺带挡住超长行白跑一次查表。
_MAX_HEADER_LEN = max(len(key) for key in _ALIAS_TO_SECTION)

#: 标题行里允许出现的装饰性标点（"一、教育背景：" 这种前缀/后缀要能剥掉）
_HEADER_TRIM = " \t:：、.。-_—[]【】()（）"

_CJK_RANGE = (
    (0x3400, 0x4DBF),    # 扩展 A
    (0x4E00, 0x9FFF),    # 基本区
    (0xF900, 0xFAFF),    # 兼容表意
)


# ---------------------------------------------------------------- 结果类型


@dataclass(frozen=True)
class CleanResult:
    """清洗结果。字段刻意全部是**事实**，判断交给上层。

    :param text: 清洗 + 截断后的文本 —— 这就是后面所有阶段要用的那一份
    :param sections: 章节名 → 该章节文本。切不出来就是空 dict，不报错
    :param truncated: 是否因为超过 `RESUME_MAX_LENGTH` 被截断（→ `meta.truncated`）
    :param original_length: 截断前的清洗文本长度（诊断用，让人知道丢了多少）
    :param reading_order_suspect: 阅读顺序自检是否可疑（只 WARN，不阻断）
    :param warnings: 人可读的告警，便于写进日志 / 调试
    """

    text: str
    sections: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    original_length: int = 0
    reading_order_suspect: bool = False
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------- 字符级步骤


def strip_invisibles(text: str) -> str:
    """删零宽字符、软连字符、图标字形；把「像空格的」统一成普通空格；行/段分隔符变换行。

    图标字形（私用区 / DEL）分两种处理，**顺序不能反**：

    1. **行首的**先换成 `•` —— 它是列表符号，抹掉就丢了段落结构；
    2. **其余的直接删** —— 行内的图标是纯装饰（「📅 年龄：24 岁」里的日历图标），没有文字含义。
    """
    text = _LEADING_SYMBOL_GLYPH_RE.sub("• ", text)
    text = _SYMBOL_GLYPH_RE.sub("", text)
    text = text.translate(_LINE_SEP_TABLE)
    text = text.translate(_INVISIBLE_TABLE)
    return text.translate(_SPACE_TABLE)


def unify_width(text: str) -> str:
    """全角 → 半角（只处理 ASCII 全角区 U+FF01–U+FF5E 与全角空格）。

    **为什么不用 `unicodedata.normalize("NFKC")`**：NFKC 会顺手做很多我们没打算做的替换
    （「①」→「1」、「㎏」→「kg」、「㈱」→「(株)」），对中文简历来说破坏性大于收益，
    而且行为随 Unicode 版本变化 —— 清洗结果不该依赖 Python 版本。
    只做「全角 ASCII → 半角 ASCII」这一件可预期的事。
    """
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:      # ！ 到 ～ 的整段全角 ASCII
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(ch)
    return "".join(chars)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------- 行级步骤


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGE)


def _is_bullet(line: str) -> bool:
    return bool(_BULLET_PREFIX_RE.match(line))


def _section_of(line: str) -> str | None:
    """这一行是不是章节标题？是就返回规范章节名。

    判定很保守：剥掉编号/装饰标点、去掉空白并小写后，**整行必须等于**某个别名。
    宁可漏切一个章节（正文照样往下走），也不要误切 —— 误切会把正文片段塞进 `sections`，
    让下游以为那是独立章节。精确相等这条本身就够严，长度上限只是显式化的意图。
    """
    stripped = line.strip()
    if not stripped:
        return None
    key = _alias_key(_BULLET_PREFIX_RE.sub("", stripped).strip(_HEADER_TRIM))
    if not key or len(key) > _MAX_HEADER_LEN:
        return None
    return _ALIAS_TO_SECTION.get(key)


def _ends_sentence(line: str) -> bool:
    return bool(line) and line[-1] in _SENTENCE_END


def _join_lines(previous: str, current: str) -> str:
    """把两行接起来 —— 这是「合并断行」的全部智能。

    三种接法，按优先级：
    1. **英文断词**：上一行以 `-` 结尾且前后都是字母（`Java-\\nScript`）→ 去掉连字符直接拼；
    2. **含中日韩字符**：直接拼，不加空格（中文本来就不分词间空格）；
    3. **纯拉丁**：加一个空格（`Spring\\nBoot` → `Spring Boot`）。
    """
    if (
        previous.endswith("-")
        and len(previous) >= 2
        and previous[-2].isascii()
        and previous[-2].isalpha()
        and current[:1].islower()
        and current[:1].isascii()
    ):
        return previous[:-1] + current

    if _is_cjk(previous[-1]) or _is_cjk(current[0]):
        return previous + current

    return previous + " " + current


def merge_broken_lines(lines: list[str]) -> str:
    """把「按视觉排版的碎片行」还原成「语义段落」。

    合并的中断条件（任一满足就另起一段）：

    - 遇到空行（原始段落分隔）
    - 当前行是**章节标题** → 标题自己独占一行，后面的正文另起
    - 当前行是**项目符号 / 编号行** → 另起一段，但**它后面的续行要并进它**
      （`• 负责 XX 系统` / `的开发与维护` 是一句话，被排版切成了两行）
    - 上一行以句末标点结尾 → 上一句已结束，不粘连

    ⚠️ 项目符号与章节标题的处理**故意不同**：符号行的续行属于这一条，
    标题行的续行不属于标题。都按「直接落块」处理的话，项目符号的续行会掉成独立一行。
    """
    blocks: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            blocks.append(buffer)
            buffer = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            blocks.append("")            # 保留段落分隔（后面会折叠连续空行）
            continue
        if _section_of(line) is not None:
            flush()
            blocks.append(line)          # 标题独占一行
            continue
        if _is_bullet(line):
            flush()
            buffer = line                # ★ 换 buffer 而不是落块：续行还要并进来
            continue
        if not buffer:
            buffer = line
            continue
        if _ends_sentence(buffer):
            flush()
            buffer = line
            continue
        buffer = _join_lines(buffer, line)

    flush()

    # 折叠连续空行：PDF 抽取经常产生 3~5 个连续空行
    collapsed: list[str] = []
    for block in blocks:
        if not block and collapsed and not collapsed[-1]:
            continue
        collapsed.append(block)
    return "\n".join(collapsed).strip()


def check_reading_order(lines: list[str]) -> tuple[bool, float]:
    """阅读顺序自检（M2.4）。返回 `(是否可疑, 短行占比)`。

    这是**启发式**，不是判定：双栏 / 表格排版被按列拼串时，抽出的行会大量退化成
    几个字的碎片（"Java"、"2023"、"本科" 各占一行），所以「短行占比」是个有效信号。
    它只用于 WARN —— spec §3 明确不承诺所有排版都能正确解析，把启发式当判据会造成误杀。
    """
    content = [line for line in lines if line.strip()]
    if len(content) < READING_ORDER_MIN_LINES:
        # 样本太少，比例没有统计意义
        return False, 0.0
    short = sum(1 for line in content if len(line.strip()) < 6)
    ratio = short / len(content)
    return ratio > READING_ORDER_SHORT_LINE_RATIO, ratio


def split_sections(text: str) -> dict[str, str]:
    """按章节标题切块。切不出来返回空 dict（不是错误）。

    第一个标题之前的内容归入 `"header"` —— 简历开头通常是姓名 / 电话 / 邮箱，
    它们不属于任何具名章节，但绝不能丢。
    """
    sections: dict[str, list[str]] = {}
    current = "header"
    for line in text.split("\n"):
        name = _section_of(line) if line.strip() else None
        if name is not None:
            current = name
            sections.setdefault(current, [])   # 同名章节出现两次时合并，不覆盖
            continue
        sections.setdefault(current, []).append(line)

    return {
        name: "\n".join(body).strip()
        for name, body in sections.items()
        if "\n".join(body).strip()
    }


# ---------------------------------------------------------------- 主入口


def clean(text: str, *, max_length: int = RESUME_MAX_LENGTH) -> CleanResult:
    """清洗入口。**纯函数**：同样输入必得同样输出，没有隐藏状态、不读配置、不写日志以外的副作用。

    :param text: 解析器给出的原始文本
    :param max_length: 上限（默认 `RESUME_MAX_LENGTH`；测试里可以调小来验截断）
    """
    warnings: list[str] = []

    text = normalize_newlines(text)
    text = strip_invisibles(text)
    text = unify_width(text)

    # 阅读顺序自检必须在合并断行之前 —— 合并之后就看不到行结构了
    raw_lines = text.split("\n")
    suspect, short_ratio = check_reading_order(raw_lines)
    if suspect:
        warnings.append(f"阅读顺序可疑：短行占比 {short_ratio:.0%}")
        logger.warning(
            "reading order may be broken (short_line_ratio=%.2f, lines=%d) —— "
            "多为双栏/表格排版，属已知缺口，不阻断",
            short_ratio, len([line for line in raw_lines if line.strip()]),
        )

    merged = merge_broken_lines(raw_lines)
    original_length = len(merged)

    truncated = original_length > max_length
    if truncated:
        merged = merged[:max_length]
        warnings.append(f"文本超长：{original_length} → {max_length} 字符已截断")
        logger.info("resume text truncated %d -> %d", original_length, max_length)

    sections = split_sections(merged)

    # 只打长度与结构，绝不打正文（spec §2.8）
    logger.info(
        "resume cleaned raw_chars=%d clean_chars=%d sections=%d truncated=%s suspect=%s",
        len(text), len(merged), len(sections), truncated, suspect,
    )

    return CleanResult(
        text=merged,
        sections=sections,
        truncated=truncated,
        original_length=original_length,
        reading_order_suspect=suspect,
        warnings=tuple(warnings),
    )


#: 抽取失败时最常见的「脏」字符。注意它属于 Unicode 的 `So` 类，
#: `str.isprintable()` **认为它是可打印的** —— 但对我们的用途，它恰恰是最该被发现的坏信号，
#: 所以单独排除。（写测试时才发现的坑：按 `isprintable()` 原样实现的话，这个函数
#: 对「整篇都是替换字符」的烂文本会报出 100% 可打印。）
_REPLACEMENT_CHAR = "\ufffd"


def is_printable_ratio(text: str) -> float:
    """可打印字符占比。给测试与排障用：PDF 抽错时常见大量 `\\ufffd`（替换字符）。

    不参与清洗决策 —— 它只是把「这份文本看起来有多烂」变成一个可断言的数。
    """
    if not text:
        return 0.0
    printable = sum(
        1
        for ch in text
        if (ch.isprintable() and ch != _REPLACEMENT_CHAR) or ch in "\n\t"
    )
    return printable / len(text)


__all__ = [
    "CleanResult",
    "SECTION_ALIASES",
    "check_reading_order",
    "clean",
    "is_printable_ratio",
    "merge_broken_lines",
    "normalize_newlines",
    "split_sections",
    "strip_invisibles",
    "unify_width",
]
