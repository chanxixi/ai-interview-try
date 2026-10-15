"""技能归一化 —— 任意写法 → `skills.yaml` 里的 canonical（契约变更 C4）。

**这一层只回答一个问题：这段文字里提到了哪些「词典内的技能」。**
它不打分（`matcher.py` 的事）、不排序（`recommender.py` 的事）、不读数据库
（spec §2.7：Python 禁止直连库，词典真源在仓库里）。

## 两个入口，两种用途

| 入口 | 输入 | 输出 | 谁在用 |
|---|---|---|---|
| `normalize(raw)` | **一个**技能字符串 | canonical 或 `None` | 自定义 JD 的技能名归一化、测试 |
| `extract(text)` | **一段**文本 | 全文所有命中（带 offset） | 简历技能抽取、`matcher` 的输入 |

## 四步归一化（tasks.md M3.2，顺序不能换）

1. **查别名表**（精确匹配，大小写/空格敏感）—— 最快的一跳，覆盖 `SpringBoot` 这类规范写法；
2. **规范化后再查** —— 规范化 = 全半角统一 + 转小写 + 去掉空白与连接符。
   这一跳覆盖 `spring boot` / `SPRINGBOOT` / `ＳＰＲＩＮＧＢＯＯＴ` / `spring-boot`；
3. **编辑距离兜底** —— 相似度 ≥ 0.90 且长度 ≥ 4，救手滑（`TypeScript`→`Typescrpt`）；
4. **`unknown`** —— 返回 `None`，**不抛异常、不阻断**。认不出只是少认一个技能，
   为它抛错会让整份简历分析失败，代价远大于收益。

## 为什么 `Java` 不会被误判成 `JavaScript`

这是本文件最重要的一条不变量，三道防线叠加：

| 防线 | 挡住什么 |
|---|---|
| 第 3 步的**长度门槛**（≥4） | `java`(4) vs `javascript`(10) 相似度只有 0.40，根本进不了兜底 |
| 抽取时的**边界检查** | 文本 `JavaScript` 里找 `java`：后一个字符是 `S`（ASCII 字母数字）→ 拒绝 |
| 扫描的**最长优先** | `javascript`(10) 比 `java`(4) 先匹配，命中区间被占用后不再重复计 |

反过来 `java` 能正常命中 `熟悉 Java 开发` / `Java、Spring Boot`（后邻是中文或标点，不是字母数字）。

## 全文扫描为什么不用正则

直觉上会写 `re.compile("|".join(aliases))`，但那会同时丢掉三样东西：
① **边界控制**（要按 ASCII 词边界判断，正则得为每个别名单独加 `\\b`，而 `C++` 这种含 `+` 的
别名 `\\b` 语义是错的）；② **最长优先**（正则 alternation 是**最短**优先，`Spring Boot`
会被 `Spring` 抢先）；③ **offset 回填**（折叠后的坐标要映射回原文坐标才能给出可解释的证据）。
手写扫描能同时满足这三条，代价是 O(别名数 × 文本长度) —— 实测 143 个扫描词扫 23200 字符
约 10ms，而简历上限是 20000 字符，完全在预算内。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.core.constants import (
    FUZZY_MATCH_THRESHOLD,
    FUZZY_MIN_LENGTH,
    MIN_SCAN_ALIAS_LENGTH,
)
from app.core.resources import read_yaml, resource_path
from app.service.cleaner import unify_width

#: 词典文件名。**路径拼接与 YAML 读取统一在 `core/resources.py`**（指南 §4.1）——
#: 本文件只负责「把 dict 解释成 `SkillDictionary`」。
#: 真源在仓库（C4）：随代码分发的只读资源，按 `__file__` 定位而不是按 CWD。
DICTIONARY_NAME = "skills.yaml"

#: 折叠时要**删掉**的字符：各类空白 + 连接符。
#: 为什么删 `.` / `-` / `_` / `\\` / `/`：让 `Node.js`≡`NodeJS`、`nest.js`≡`NestJS`、
#: `rust-lang`≡`rustlang`、`github-actions`≡`GitHub Actions`、`TCP/IP`≡`tcpip`。
#: 为什么**不删** `+` 和 `#`：`C++` 与 `C`、`C#` 与 `C` 必须保持不同 —— 它们是不同的技能。
_FOLD_DROP = " \t\r\n\v\f\u00a0\u200b\u200c\u200d\u3000-_.\\/"

_FOLD_TABLE = str.maketrans("", "", _FOLD_DROP)

_ASCII_ALNUM = re.compile(r"[0-9A-Za-z]")


# ---------------------------------------------------------------- 结果类型


@dataclass(frozen=True)
class SkillEntry:
    """词典里的一条技能。`aliases` 保留**原始写法**（不折叠），便于人读与回显。"""

    canonical: str
    category: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SkillMention:
    """文本里的一次技能命中。字段全部是**事实**，判断交给上层。

    :param raw: 原文片段（逐字复制，可直接当证据展示）
    :param canonical: 标准名
    :param category: 分类（language / framework / ...）
    :param offset: `raw` 在**原文**中的起始下标（折叠前的坐标，人可定位）
    """

    raw: str
    canonical: str
    category: str
    offset: int


# ---------------------------------------------------------------- 折叠（查表的归一化形式）


def fold(text: str) -> str:
    """归一化形式：全半角统一 → 转小写 → 删空白与连接符。

    候选词与待查词**必须**都过这个函数，否则 `TECHNICAL SKILLS` 这类多词条目
    会变成「表里有、永远匹配不上」的死条目（`cleaner._alias_key` 踩过同一个坑）。
    """
    return unify_width(text).translate(_FOLD_TABLE).lower()


def _fold_with_index(text: str) -> tuple[str, list[int]]:
    """折叠文本，同时给出「折叠后第 i 个字符对应原文哪个位置」。

    删字符会让下标漂移，所以必须边删边记。没有这张表，`SkillMention.offset`
    就只能给折叠坐标，前端拿它去原文里高亮会整体错位。
    """
    chars: list[str] = []
    index: list[int] = []
    for position, char in enumerate(unify_width(text)):
        folded = char.lower()
        if folded in _FOLD_DROP:
            continue
        chars.append(folded)
        index.append(position)
    return "".join(chars), index


def _is_ascii_word_char(char: str) -> bool:
    return bool(_ASCII_ALNUM.match(char))


def edit_distance(left: str, right: str) -> int:
    """Levenshtein 距离（标准 DP，无第三方依赖）。

    两个调用点都限定了长度（≥4 的词典键 × ≤ 词典规模），O(n·m) 完全够用；
    真到了需要优化的量级，应该先问「为什么词典有几万条」。
    """
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,                       # 删除
                    current[j - 1] + 1,                    # 插入
                    previous[j - 1] + (char_left != char_right),  # 替换
                )
            )
        previous = current
    return previous[-1]


def similarity(left: str, right: str) -> float:
    """`1 - 距离 / 较长者长度`。用较长者而不是较短者做分母：
    否则 `java` vs `javascript` 会算成 0.0（更宽松），正是我们要防的误判。
    """
    if not left and not right:
        return 1.0
    longest = max(len(left), len(right))
    if longest == 0:
        return 1.0
    return 1.0 - edit_distance(left, right) / longest


# ---------------------------------------------------------------- 词典


class SkillDictionary:
    """`skills.yaml` 的内存形态。

    **构造时就把歧义拦掉**：两个技能写同一个别名（折叠后相同）直接抛 `ValueError`。
    这不是洁癖 —— 歧义别名会让「同一个字符串这次归 A、下次归 B」，
    而 `gen-seed.sh` 已经在构建期做了同一件事，两边口径必须一致。
    """

    def __init__(
        self,
        entries: Mapping[str, SkillEntry],
        *,
        source: str = "",
        categories: Sequence[str] = (),
    ) -> None:
        self._entries: dict[str, SkillEntry] = dict(entries)
        self._source = source
        self._categories = tuple(categories)

        # ① 精确别名表：原文 → canonical（不过滤大小写/空格）
        self._by_exact: dict[str, str] = {}
        # ② 折叠别名表：fold(term) → canonical
        self._by_folded: dict[str, str] = {}
        # ③ 扫描索引：fold(term) → canonical，按长度降序（最长优先）
        scan: dict[str, str] = {}

        for canonical, entry in self._entries.items():
            self._register(canonical, canonical)
            for alias in entry.aliases:
                self._register(alias, canonical)

        for key, canonical in self._by_folded.items():
            if len(key) >= MIN_SCAN_ALIAS_LENGTH:
                scan[key] = canonical

        self._scan_index: tuple[tuple[str, str], ...] = tuple(
            sorted(scan.items(), key=lambda item: (-len(item[0]), item[0]))
        )

    # ------------------------------------------------------------ 构造

    def _register(self, term: str, canonical: str) -> None:
        """把一个写法（canonical 自身或别名）登记进三张表。"""
        if not term or not term.strip():
            raise ValueError(f"词典条目为空：canonical={canonical!r}")
        owner = self._by_exact.get(term)
        if owner is not None and owner != canonical:
            raise ValueError(
                f"别名歧义：{term!r} 同时属于 {owner!r} 与 {canonical!r}；"
                "请在 skills.yaml 里改掉其中一个（gen-seed.sh 会报同样的错）"
            )
        self._by_exact[term] = canonical

        key = fold(term)
        owner = self._by_folded.get(key)
        if owner is not None and owner != canonical:
            raise ValueError(
                f"别名歧义（折叠后相同）：{term!r} → {key!r} 同时属于 {owner!r} 与 {canonical!r}"
            )
        self._by_folded[key] = canonical

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[SkillEntry],
        *,
        categories: Sequence[str] = (),
        source: str = "",
    ) -> SkillDictionary:
        by_canonical: dict[str, SkillEntry] = {}
        for entry in entries:
            if entry.canonical in by_canonical:
                raise ValueError(f"canonical 重复：{entry.canonical!r}")
            by_canonical[entry.canonical] = entry
        return cls(by_canonical, source=source, categories=categories)

    @classmethod
    def load(cls, path: Path | str | None = None) -> SkillDictionary:
        """从 `skills.yaml` 加载。文件缺失 / 结构不对都**立刻炸**，不静默返回空词典 ——
        空词典会让所有技能都变 `unknown`，表现为「匹配度全是 0」这种最难查的假故障。
        """
        target = Path(path) if path is not None else resource_path(DICTIONARY_NAME)
        # 先给**领域化**文案（比「资源不存在」更能指路），再交给统一读取点做
        # 「顶层必须是 mapping」这类通用校验。
        if not target.is_file():
            raise FileNotFoundError(f"技能词典不存在：{target}")

        raw = read_yaml(target)

        declared = raw.get("categories") or []
        if not isinstance(declared, list) or not declared:
            raise ValueError(f"技能词典缺少 categories 闭集：{target}")

        skills = raw.get("skills") or []
        if not isinstance(skills, list) or not skills:
            raise ValueError(f"技能词典缺少 skills 列表：{target}")

        entries: list[SkillEntry] = []
        for index, item in enumerate(skills):
            if not isinstance(item, dict):
                raise ValueError(f"skills[{index}] 必须是 mapping：{item!r}")
            canonical = item.get("canonical")
            category = item.get("category")
            aliases = item.get("aliases") or []
            if not isinstance(canonical, str) or not canonical.strip():
                raise ValueError(f"skills[{index}].canonical 非法：{canonical!r}")
            if category not in declared:
                raise ValueError(
                    f"skills[{index}]（{canonical}）的 category={category!r} 不在闭集 {list(declared)} 内"
                )
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise ValueError(f"skills[{index}]（{canonical}）的 aliases 必须是字符串列表")
            entries.append(
                SkillEntry(
                    canonical=canonical,
                    category=category,
                    aliases=tuple(aliases),
                )
            )

        return cls.from_entries(entries, categories=declared, source=str(target))

    # ------------------------------------------------------------ 查询

    @property
    def source(self) -> str:
        return self._source

    @property
    def categories(self) -> tuple[str, ...]:
        return self._categories

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, canonical: object) -> bool:
        return canonical in self._entries

    def entry(self, canonical: str) -> SkillEntry | None:
        return self._entries.get(canonical)

    def canonicals(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def category_of(self, canonical: str) -> str | None:
        entry = self._entries.get(canonical)
        return entry.category if entry else None

    # ------------------------------------------------------------ 四步归一化

    def normalize(self, raw: str) -> str | None:
        """任意写法 → canonical；认不出返回 `None`（不抛错，见模块 docstring 第 4 步）。"""
        if raw is None:
            return None
        text = raw.strip()
        if not text:
            return None

        # ① 查别名表（精确）
        hit = self._by_exact.get(text)
        if hit is not None:
            return hit

        # ② 规范化后再查
        key = fold(text)
        if not key:
            return None
        hit = self._by_folded.get(key)
        if hit is not None:
            return hit

        # ③ 编辑距离兜底（长度门槛见 FUZZY_MIN_LENGTH 的注释）
        if len(key) >= FUZZY_MIN_LENGTH:
            best: str | None = None
            best_score = -1.0
            # 升序遍历 + 只在「严格更高」时替换 → 同分取字典序更小的 canonical，
            # 保证**确定性**（spec §2.4：同一输入两次调用结果必须一致）。
            for candidate in sorted(self._by_folded):
                score = similarity(key, candidate)
                if score < FUZZY_MATCH_THRESHOLD:
                    continue
                if score > best_score:
                    best, best_score = self._by_folded[candidate], score
            if best is not None:
                return best

        # ④ unknown
        return None

    # ------------------------------------------------------------ 全文抽取

    def extract(self, text: str) -> list[SkillMention]:
        """扫出文本里**所有**技能命中，按原文 offset 升序。

        同一技能出现多次会返回多条（保留原始事实，去重是上层的事）。
        """
        if not text:
            return []

        folded, index = _fold_with_index(text)
        if not folded:
            return []

        consumed = [False] * len(folded)
        hits: list[SkillMention] = []

        for term, canonical in self._scan_index:      # 已按长度降序
            length = len(term)
            start = folded.find(term)
            while start != -1:
                end = start + length
                if not any(consumed[start:end]) and self._has_boundary(text, index, start, end, term):
                    for position in range(start, end):
                        consumed[position] = True
                    raw_start = index[start]
                    raw_end = index[end - 1] + 1
                    hits.append(
                        SkillMention(
                            raw=text[raw_start:raw_end],
                            canonical=canonical,
                            category=self.category_of(canonical) or "",
                            offset=raw_start,
                        )
                    )
                start = folded.find(term, start + 1)

        hits.sort(key=lambda mention: (mention.offset, mention.canonical))
        return hits

    def extract_unique(self, text: str) -> list[SkillMention]:
        """按 canonical 去重，每个技能保留**第一次**出现（offset 最小）。

        匹配打分只需要「会不会」，但 `resume.skills` 要给人看，重复列 5 条 Java 没有信息量。
        """
        seen: set[str] = set()
        unique: list[SkillMention] = []
        for mention in self.extract(text):
            if mention.canonical in seen:
                continue
            seen.add(mention.canonical)
            unique.append(mention)
        return unique

    @staticmethod
    def _has_boundary(
        text: str,
        index: Sequence[int],
        start: int,
        end: int,
        term: str,
    ) -> bool:
        """ASCII 别名要求左右都不是 ASCII 字母数字（词边界）；CJK 别名不要求。

        **为什么 CJK 不要求**：中文没有词边界，「数据结构」在「掌握数据结构与算法」里
        就是子串命中，加边界检查反而会漏。
        **为什么 ASCII 要**：否则 `Java` 会命中 `JavaScript`、`Go` 会命中 `Google`。
        """
        if not term.isascii():
            return True
        left = index[start] - 1
        if left >= 0 and _is_ascii_word_char(text[left]):
            return False
        right = index[end - 1] + 1
        if right < len(text) and _is_ascii_word_char(text[right]):
            return False
        return True


@lru_cache(maxsize=1)
def get_dictionary() -> SkillDictionary:
    """进程级单例（与 `core.config.get_settings()` 同一个思路）。

    词典在运行期不变，每次请求重读 YAML 是纯浪费；但它又是**可替换的依赖**，
    所以走函数而不是模块级变量 —— 测试里 `get_dictionary.cache_clear()` 或直接
    `SkillDictionary.load(临时文件)` 都能换掉它。
    """
    return SkillDictionary.load()
