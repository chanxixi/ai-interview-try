"""文档解析器「插件」框架 —— 协议 + 结果类型 + 注册表。

**为什么要这一层**（而不是直接 `from pypdf import PdfReader`）：

1. **格式可插拔**：加一种格式 = 加一个文件 + 在 `default_registry()` 里注册一行，
   调用方一行都不用改。这是「插件」的实际含义 —— 不是目录好看，而是**开闭原则的落点**。
2. **换库只改一处**：ADR-103 说 pypdf 抽乱序就换 pdfplumber。有这层之后，
   换库只动 `pdf_parser.py`，`cleaner` / 将来的 `analysis_stream_service` 完全不受影响。
3. **边界清晰**：解析器只回答「这份字节里有哪些文字」这一件事，
   不做清洗（`cleaner.py` 的事）、不做策略（要不要因为文本太少而报错，是上层的事）。

**职责边界（写死在这里，避免后面越界）**

| 谁 | 只做什么 | 绝不做什么 |
|---|---|---|
| `parser_plugin.py`（本文件） | 定协议、收结果、注册表 | 具体格式的解析逻辑 |
| `pdf_parser.py` / `docx_parser.py` | 字节 → `ParseResult` | 清洗、判断业务对错、日志打正文 |
| `cleaner.py` | 文本 → 干净文本 + 章节 | 读文件、抛业务错误码 |

**为什么不用 import 副作用做注册**：`import pdf_parser` 时自动注册看起来很省事，
但会带来两个坑 —— ① 导入顺序决定注册结果；② 单测里想只注册一个解析器做不到。
所以 `default_registry()` 是**显式**装配点，和 `core/dependencies.py` 是同一个思路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.constants import PDF_MIN_TEXT_LAYER_CHARS
from app.core.exceptions import AppException, ErrorCode


@dataclass(frozen=True)
class ParseResult:
    """解析器能给出的**全部事实**。不含判断，不含策略。

    :param text: 抽出的原始文本（未清洗，可能含 \\u200b / \\xa0 / 硬换行）
    :param page_count: 页数。PDF 是真实页数；DOCX 没有「页」的概念（分页由渲染决定），
                       固定填 1 —— 用 1 而不是 0 或 None，是为了让上层不必为空值分叉。
    :param encrypted: 文件是否带加密标记。注意 **True 不等于失败**：
                      只设了「所有者密码」的 PDF 可以用空密码打开，
                      这时 `encrypted=True` 且文本正常抽出来。
    :param has_text_layer: 是否抽到了足以当正文的文本（判定见 `judge_has_text_layer`）。
    :param document_format: `"pdf"` / `"docx"`，便于日志与上层分支。
    """

    text: str
    page_count: int
    encrypted: bool
    has_text_layer: bool
    document_format: str

    @property
    def non_whitespace_chars(self) -> int:
        return count_non_whitespace(self.text)


def count_non_whitespace(text: str) -> int:
    """非空白字符数。

    判「有没有文本层」时不能用 `len(text)`：扫描件经常能抽出页码 / 页眉的几个字符，
    再加上一堆换行与空格，`len` 会虚高。
    """
    return sum(1 for ch in text if not ch.isspace())


def judge_has_text_layer(text: str) -> bool:
    """M2.3 的判定：非空白字符 < 100 → 没有文本层。

    阈值来源与理由见 `core/constants.PDF_MIN_TEXT_LAYER_CHARS`。
    """
    return count_non_whitespace(text) >= PDF_MIN_TEXT_LAYER_CHARS


@runtime_checkable
class DocumentParser(Protocol):
    """一种文档格式的解析器。

    `runtime_checkable` 让测试可以直接 `isinstance(obj, DocumentParser)` 做结构校验，
    而不必让实现类去继承一个抽象基类 —— Protocol 的价值就在于「不强制继承」。
    """

    #: 与 `ParseResult.document_format` 同值的小写标识，例如 `"pdf"`
    document_format: str

    #: 该格式的 magic number 前缀（用于 `sniff`）。
    #: ⚠️ 这里只做**识别**，不做**准入**：准入（只允许 PDF）是 BFF 的职责（spec §2.8 / M6.2）。
    magic_prefixes: tuple[bytes, ...]

    def sniff(self, data: bytes) -> bool:
        """这份字节像不像本格式？只看头部，不解析。"""
        ...

    def parse(self, data: bytes) -> ParseResult:
        """解析。失败时抛 `AppException`（错误码见 spec §2.5）。"""
        ...


class UnsupportedFormatError(AppException):
    """没有任何已注册的解析器认领这份字节。"""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"不支持的文件格式：{detail}",
            http_status=415,
        )


class ParserRegistry:
    """格式 → 解析器。显式注册，不用导入副作用。"""

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        key = parser.document_format.lower()
        if key in self._parsers:
            # 静默覆盖会让「两个解析器抢同一个格式」变成很难查的 bug
            raise ValueError(f"格式 {key!r} 已注册过解析器")
        self._parsers[key] = parser

    def formats(self) -> tuple[str, ...]:
        """已注册的格式，按字典序（保证输出稳定，便于断言与日志）。"""
        return tuple(sorted(self._parsers))

    def get(self, document_format: str) -> DocumentParser:
        key = document_format.lower()
        parser = self._parsers.get(key)
        if parser is None:
            raise UnsupportedFormatError(
                f"{document_format!r}（已注册：{', '.join(self.formats()) or '无'}）"
            )
        return parser

    def detect(self, data: bytes) -> DocumentParser | None:
        """按 magic number 猜格式。猜不出返回 None —— 不抛错，
        因为「识别不出来」在调用方那里可能只是「该走别的分支」。"""
        for parser in self._parsers.values():
            if parser.sniff(data):
                return parser
        return None


def default_registry() -> ParserRegistry:
    """组合根：显式装配全部解析器。

    延迟 import 是为了避免「`parser_plugin` ↔ `pdf_parser`」的循环导入
    （两个解析器都要 import 本文件拿 `ParseResult`）。
    """
    from app.service import docx_parser, pdf_parser  # 延迟导入：打破循环

    registry = ParserRegistry()
    registry.register(pdf_parser.PARSER)
    registry.register(docx_parser.PARSER)
    return registry
