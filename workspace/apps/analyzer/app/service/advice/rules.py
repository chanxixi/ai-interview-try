"""规则兜底 —— LLM 不可用时的 `issues` 来源（M4.5）。

**为什么需要它**：`issues` 的唯一运行期职责属于 LLM（Prompt-2），但 LLM 会超时、
会返回非法 JSON、会整个不可用。spec §2.4 硬性规则 4 说「降级时 `thinking` 可为 0 次，
但 `result` 与 `done` 照常」—— 那 `issues` 从哪来？就从这里。

**设计约束（写死，防止它悄悄变成第二套 LLM）**：

1. **纯确定性**：同一份文本两次调用结果完全一致。不抽样、不调模型、不依赖字典序之外的任何东西。
2. **evidence 必须逐字来自原文**：所有规则都从原文切片段，不允许生成「看起来像」的文本。
3. **宁可漏不可编**：判不出来就返回空数组。空数组是诚实的，
   「为了有内容而编一条」会直接误导用户改简历。
4. **与 LLM 输出同构**：同样的 5 个 type、同样的 severity 枚举、同样的字段。
   降级前后前端渲染逻辑完全一致。

## 五条规则怎么定的

| type | 判据 | 为什么这么判 |
|---|---|---|
| `MISSING_CONTACT` | 全文找不到手机号/邮箱 | 唯一能 100% 确定的问题，正则就够 |
| `NO_QUANTIFY` | 含动作动词的句子里没有任何数字 | 「负责订单系统」 vs 「负责订单系统，QPS 从 800 提到 3000」—— 差的就是数字 |
| `SKILL_STUFFING` | 技能章节条目数 > 25 | 真实简历技能章普遍 10–20 条；抄词典才会超 |
| `TIMELINE_GAP` | 经历里的时间区间重叠或倒挂 | 时间区间是可解析的结构化事实，重叠=同时写了两段全职 |
| `NO_STAR` | 项目句子以「负责」开头且既无数字也无结果词 | STAR 的 R（Result）缺失的最弱信号，只作 low |

后四条都是**启发式**，准确性低于 LLM。所以它们只在降级时兜底，
并且 severity 普遍压得比 LLM 低——避免在「其实没这个问题」时误导用户。
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from app.core.constants import (
    MAX_ISSUES,
    MIN_ACTION_VERBS_FOR_NO_QUANTIFY,
    SKILL_STUFFING_THRESHOLD,
    SUGGESTION_MAX_CHARS,
)
from app.schema.response.analyze_response import Issue, IssueType, Severity

# ---------------------------------------------------------------- 正则（模块级编译：避免每条句子重编）


#: 中国大陆手机号。不要求更严的号段校验 —— 这是「有没有留联系方式」，不是「号码是否有效」。
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

#: 邮箱。宽松匹配：只要能识别出「留了邮箱」这个事实。
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: 动作动词。命中说明这句话在讲「做了什么」，才有可能被要求量化。
_ACTION_VERBS = (
    "负责", "完成", "优化", "提升", "设计", "实现", "搭建", "重构", "推动",
    "主导", "参与", "开发", "上线", "改造", "解决", "降低", "提高",
)

#: 结果词。有它说明这句话至少给了个结论，不足以判 NO_STAR。
_RESULT_WORDS = ("提升", "降低", "提高", "减少", "增长", "达成", "完成", "上线", "落地", "覆盖")

#: 时间区间：`2023.03-2024.06` / `2023/3-2024/6` / `2023.03 – 2024.06`。
_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{4})[./年](?P<sm>\d{1,2})月?\s*[-–—~至]\s*"
    r"(?P<end>\d{4})[./年](?P<em>\d{1,2})月?"
)

#: 句子切分。**不含 `；`/`，`** —— 中文简历的一条经历常是一整个分号句，
#: 切太碎会让「没有数字」的误判率飙升。
_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]")

#: 技能章节的列表项：`- Vue` / `• Vue` / `1. Vue` / `Vue、React` 里的 `、` 也算分隔。
_SKILL_ITEM_RE = re.compile(r"^\s*(?:[-•*]\s*|\d+[.、)]\s*)?(.+)$")

#: **规模**信号（量级 / 吞吐 / 人数）。与 `_check_no_quantify` 的「有没有数字」是**同源判据**，
#: 一并供 part3 的 `项目影响力` 兜底判档使用（spec §2.5.1：同一件事**禁止两套判据**）。
#:
#: 为什么不把 `%` / `ms` 算进来：它们是**量化的结果**（对应 L2），而规模是另一回事
#: （对应 L3「量化结果 + 规模」）。混在一起会让所有写了百分比的简历都拿 L3。
_SCALE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万|亿|千|[kKwW]|人|名|个|条|台|次|QPS|qps|TPS|tps|PV|UV|DAU|MAU)"
    r"|用户数|数据量"
)


@dataclass(frozen=True)
class _Candidate:
    """一条待确认的 issue。`evidence` 在构造时就必须是原文片段。"""

    type: IssueType
    severity: Severity
    evidence: str
    suggestion: str


def _clip(text: str, limit: int = 60) -> str:
    """把证据截到可读长度。**只截断，不改写** —— 逐字复制的承诺不能破。"""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _skill_items(skills_text: str) -> list[str]:
    """技能章节的条目。按行 + `、` / `，` / `/` 拆，去掉空项。"""
    items: list[str] = []
    for line in skills_text.split("\n"):
        matched = _SKILL_ITEM_RE.match(line)
        if not matched:
            continue
        for piece in re.split(r"[、，,/]", matched.group(1)):
            piece = piece.strip(" ：:;；")
            if piece:
                items.append(piece)
    return items


# ---------------------------------------------------------------- 可复用原语（part3 兜底判档同源消费）

#: 项目 / 工作经历之外的章节不参与「影响力」判档：个人信息里的手机号是**数字**，
#: 但它不说明任何「做事的结果」。把它们排除掉，才不会让一份写了手机号的简历直接拿 L2。
_IMPACT_SECTIONS = ("projects", "experience")


@dataclass(frozen=True)
class TimeSpan:
    """一个可解析的时间区间。`start` / `end` 是 `YYYYMM` 形式的整数，便于直接比大小。"""

    start: int
    end: int
    raw: str


@dataclass(frozen=True)
class QuantifyFacts:
    """「有没有量化」的事实集合。**影响判档的唯一输入**（spec §2.5.1）。

    `action` / `numbered` / `scaled` 是**递进的三层**（有动作 ⊂ 有数字 ⊂ 有规模），
    分开暴露是为了让调用方按自己的口径取用，而不是各自再扫一遍正则。
    """

    action: tuple[str, ...] = ()
    numbered: tuple[str, ...] = ()
    scaled: tuple[str, ...] = ()


def sentences(text: str) -> list[str]:
    """分句。公开出来是为了让 part3 的兜底判档与 `_check_no_quantify` **同一套切分**。"""
    return _sentences(text)


def has_action_verb(text: str) -> bool:
    return any(verb in text for verb in _ACTION_VERBS)


def has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def has_scale(text: str) -> bool:
    return _SCALE_RE.search(text) is not None


def time_spans(text: str) -> list[TimeSpan]:
    """抽出全部时间区间。与 `_check_timeline_gap` **共用同一个 `_TIME_RANGE_RE`** ——
    改正则两处同时生效，不会「时间线检查认得出、成长性判档认不出」。
    """
    return [
        TimeSpan(
            start=int(m.group("start")) * 100 + int(m.group("sm")),
            end=int(m.group("end")) * 100 + int(m.group("em")),
            raw=m.group(0),
        )
        for m in _TIME_RANGE_RE.finditer(text)
    ]


def quantify_facts(text: str, sections: dict[str, str] | None = None) -> QuantifyFacts:
    """扫「工作痕迹」范围内的量化事实（`项目影响力` 兜底判档的输入）。

    范围优先取 `projects` / `experience` 两章；两章都空时才退回全文 ——
    退回是必要的（纯文本入参或不规范排版可能切不出章节），
    但**优先章节**能挡掉「个人信息里的手机号被当成量化结果」这一类误判。
    """
    sections = sections or {}
    scope = "\n".join(sections.get(key) or "" for key in _IMPACT_SECTIONS).strip()
    if not scope:
        scope = text

    action: list[str] = []
    numbered: list[str] = []
    scaled: list[str] = []
    for sentence in _sentences(scope):
        if len(sentence) < 8 or not has_action_verb(sentence):
            continue
        action.append(sentence)
        if not has_digit(sentence):
            continue
        numbered.append(sentence)
        if has_scale(sentence):
            scaled.append(sentence)

    return QuantifyFacts(action=tuple(action), numbered=tuple(numbered), scaled=tuple(scaled))


# ---------------------------------------------------------------- 五条规则


def _check_missing_contact(text: str) -> list[_Candidate]:
    if _PHONE_RE.search(text) or _EMAIL_RE.search(text):
        return []
    return [
        _Candidate(
            type=IssueType.MISSING_CONTACT,
            severity=Severity.HIGH,
            evidence=_clip(text[:60]) or "（空文本）",
            suggestion="补充手机号或邮箱",
        )
    ]


def _check_no_quantify(text: str) -> list[_Candidate]:
    """含动作动词但整句没有任何数字 → 缺量化。"""
    hits: list[_Candidate] = []
    for sentence in _sentences(text):
        if len(sentence) < 8:
            continue                      # 太短的句子（「负责架构」）没有讨论价值
        if not any(verb in sentence for verb in _ACTION_VERBS):
            continue
        if any(ch.isdigit() for ch in sentence):
            continue
        hits.append(
            _Candidate(
                type=IssueType.NO_QUANTIFY,
                severity=Severity.HIGH,
                evidence=_clip(sentence),
                suggestion="补充 QPS / 耗时 / 提升幅度等数字",
            )
        )
        if len(hits) >= MIN_ACTION_VERBS_FOR_NO_QUANTIFY + 1:
            break
    return hits


def _check_skill_stuffing(sections: dict[str, str]) -> list[_Candidate]:
    skills_text = sections.get("skills") or ""
    items = _skill_items(skills_text)
    if len(items) <= SKILL_STUFFING_THRESHOLD:
        return []
    return [
        _Candidate(
            type=IssueType.SKILL_STUFFING,
            severity=Severity.MEDIUM,
            evidence=_clip(skills_text),
            suggestion=f"技能列了 {len(items)} 项，删掉与目标岗位无关的",
        )
    ]


def _check_timeline_gap(text: str, sections: dict[str, str]) -> list[_Candidate]:
    """时间区间倒挂或重叠。

    **倒挂**（起 > 止）在任何位置都是错，全文查；
    **重叠**只在**同一章节内**查 —— 这是被真实样本教出来的一条：

    最初版本全文排序后比对相邻区间，结果把「项目经历 2025.09-2026.06」和
    「工作经历 2023.07-2026.07」判成重叠。可项目本来就发生在任职期间，
    那是最正常的简历结构。真正算问题的只有「两段**工作经历**时间重叠」。

    所以重叠判定限定在 `experience` 章节内；其他章节的区间只参与倒挂检查。
    """
    # ---- 倒挂：全文 ----------------------------------------------------
    for matched in _TIME_RANGE_RE.finditer(text):
        start = int(matched.group("start")) * 100 + int(matched.group("sm"))
        end = int(matched.group("end")) * 100 + int(matched.group("em"))
        if end < start:
            return [
                _Candidate(
                    type=IssueType.TIMELINE_GAP,
                    severity=Severity.MEDIUM,
                    evidence=_clip(matched.group(0)),
                    suggestion="时间段起止写反了",
                )
            ]

    # ---- 重叠：只在 experience 章节内 ----------------------------------
    experience = sections.get("experience") or ""
    spans: list[tuple[int, int, str]] = []
    for matched in _TIME_RANGE_RE.finditer(experience):
        start = int(matched.group("start")) * 100 + int(matched.group("sm"))
        end = int(matched.group("end")) * 100 + int(matched.group("em"))
        spans.append((start, end, matched.group(0)))

    ordered = sorted(spans)
    for (_, prev_end, prev_raw), (start, _, raw) in zip(ordered, ordered[1:]):
        if start < prev_end:
            return [
                _Candidate(
                    type=IssueType.TIMELINE_GAP,
                    severity=Severity.MEDIUM,
                    evidence=_clip(f"{prev_raw} 与 {raw}"),
                    suggestion="两段工作经历时间重叠，核对是否为并行",
                )
            ]
    return []


def _check_no_star(text: str) -> list[_Candidate]:
    """以「负责」开头、既无数字也无结果词的句子 → 缺结果（最弱信号，只给 low）。"""
    hits: list[_Candidate] = []
    for sentence in _sentences(text):
        if not sentence.startswith("负责"):
            continue
        if any(ch.isdigit() for ch in sentence):
            continue
        if any(word in sentence for word in _RESULT_WORDS):
            continue
        hits.append(
            _Candidate(
                type=IssueType.NO_STAR,
                severity=Severity.LOW,
                evidence=_clip(sentence),
                suggestion="补一句做成了什么、结果如何",
            )
        )
        if len(hits) >= 2:
            break
    return hits


# ---------------------------------------------------------------- 入口


#: severity 降序 → 同 severity 按 type 名字典序。**固定顺序**，保证确定性（spec §2.4）。
_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


def detect_issues(text: str, sections: dict[str, str] | None = None) -> list[Issue]:
    """规则兜底：从清洗后的简历文本找出结构性问题。

    :param text: 清洗后的全文（`clean()` 的 `CleanResult.text`）
    :param sections: `clean()` 的 `CleanResult.sections`；缺省时按空 dict 处理
                    （技能章节判不出来只是少一条 SKILL_STUFFING，不影响其他规则）
    :return: 按 severity 降序排列的 issues，**可能为空数组**（宁可漏不可编）
    """
    sections = sections or {}
    if not text.strip():
        return []

    candidates: list[_Candidate] = []
    candidates += _check_missing_contact(text)
    candidates += _check_no_quantify(text)
    candidates += _check_skill_stuffing(sections)
    candidates += _check_timeline_gap(text, sections)
    candidates += _check_no_star(text)

    ordered = sorted(candidates, key=lambda c: (_SEVERITY_RANK[c.severity], c.type.value))

    issues: list[Issue] = []
    for candidate in ordered[:MAX_ISSUES]:
        suggestion = candidate.suggestion
        if len(suggestion) > SUGGESTION_MAX_CHARS:
            suggestion = suggestion[:SUGGESTION_MAX_CHARS]
        issues.append(
            Issue(
                type=candidate.type,
                severity=candidate.severity,
                evidence=candidate.evidence,
                suggestion=suggestion,
            )
        )
    return issues
