"""解析器「插件」框架（M2.2 的骨架层）。

**为什么这层要单独测**：它是 M3/M4 会直接依赖的扩展点 ——
加一种格式、换一个 PDF 库都从这里过。测的是三条契约：

1. **注册表行为**：`register` 重复注册必须炸（静默覆盖 = 极难查的 bug）、
   `formats()` 顺序稳定、`get()` 不认识的格式给 `UNSUPPORTED_FORMAT`(415) 而不是掉进 500；
2. **`detect()` 只做识别不做准入**：认不出返回 `None` 而不是抛错 ——
   准入（只允许 PDF）是 BFF 的职责，混进来会让「谁负责拒绝」变模糊；
3. **`judge_has_text_layer` 的阈值边界**：99 → False / 100 → True，且按**非空白**字符计。
"""

from __future__ import annotations
import dataclasses
import pytest
from app.core.constants import PDF_MIN_TEXT_LAYER_CHARS
from app.core.errors.exceptions import ErrorCode
from app.service.document.parser_plugin import (
    DocumentParser,
    ParseResult,
    ParserRegistry,
    UnsupportedFormatError,
    count_non_whitespace,
    default_registry,
    judge_has_text_layer,
)


class _FakeParser:
    """最小实现：结构匹配 `DocumentParser` 即可，**不继承任何基类**（Protocol 的意义）。"""

    def __init__(self, document_format: str, prefix: bytes) -> None:
        self.document_format = document_format
        self.magic_prefixes = (prefix,)

    def sniff(self, data: bytes) -> bool:
        return data.startswith(self.magic_prefixes)

    def parse(self, data: bytes) -> ParseResult:
        return ParseResult(
            text=data.decode("latin-1"),
            page_count=1,
            encrypted=False,
            has_text_layer=False,
            document_format=self.document_format,
        )


# ------------------------------------------------------------------ 注册表


def test_registry_reports_formats_in_stable_sorted_order() -> None:
    registry = ParserRegistry()
    registry.register(_FakeParser("zzz", b"Z"))
    registry.register(_FakeParser("aaa", b"A"))

    # 顺序稳定是给日志与断言用的：注册顺序不该影响输出
    assert registry.formats() == ("aaa", "zzz")


def test_registering_the_same_format_twice_raises() -> None:
    registry = ParserRegistry()
    registry.register(_FakeParser("pdf", b"%PDF-"))

    with pytest.raises(ValueError):
        registry.register(_FakeParser("pdf", b"%PDF-"))


def test_get_unknown_format_raises_unsupported_format_with_415() -> None:
    registry = ParserRegistry()
    registry.register(_FakeParser("pdf", b"%PDF-"))

    with pytest.raises(UnsupportedFormatError) as exc:
        registry.get("xlsx")

    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT
    assert exc.value.http_status == 415
    assert "pdf" in exc.value.message          # 报错里要说清「已注册了哪些」，方便照做


def test_get_is_case_insensitive() -> None:
    registry = ParserRegistry()
    registry.register(_FakeParser("pdf", b"%PDF-"))

    assert registry.get("PDF").document_format == "pdf"


def test_detect_matches_by_magic_number() -> None:
    registry = ParserRegistry()
    registry.register(_FakeParser("pdf", b"%PDF-"))
    registry.register(_FakeParser("docx", b"PK\x03\x04"))

    assert registry.detect(b"%PDF-1.7\n...").document_format == "pdf"
    assert registry.detect(b"PK\x03\x04...").document_format == "docx"


def test_detect_returns_none_for_unknown_bytes_instead_of_raising() -> None:
    """识别不出来不是错误 —— 只说明「该走别的分支」。"""
    registry = ParserRegistry()
    registry.register(_FakeParser("pdf", b"%PDF-"))

    assert registry.detect(b"GIF89a") is None


def test_default_registry_exposes_pdf_and_docx() -> None:
    assert default_registry().formats() == ("docx", "pdf")


# ------------------------------------------------------------------ 结果与判定


def test_count_non_whitespace_ignores_whitespace_and_newlines() -> None:
    assert count_non_whitespace("a b\n\tc\u3000d") == 4


def test_judge_has_text_layer_boundary_is_exactly_the_constant() -> None:
    """99 → False，100 → True。阈值来自 `core/constants`，测试不重复写数字。"""
    assert judge_has_text_layer("x" * (PDF_MIN_TEXT_LAYER_CHARS - 1)) is False
    assert judge_has_text_layer("x" * PDF_MIN_TEXT_LAYER_CHARS) is True


def test_judge_has_text_layer_counts_only_non_whitespace_characters() -> None:
    """扫描件常能抽出页码 + 一堆换行；按 `len()` 判会把扫描件当有效简历放行。"""
    padded = "x" * (PDF_MIN_TEXT_LAYER_CHARS - 1) + "\n" * 5_000

    assert len(padded) > PDF_MIN_TEXT_LAYER_CHARS
    assert judge_has_text_layer(padded) is False


def test_parse_result_exposes_non_whitespace_chars() -> None:
    result = ParseResult(
        text="a b\nc",
        page_count=1,
        encrypted=False,
        has_text_layer=False,
        document_format="pdf",
    )

    assert result.non_whitespace_chars == 3


def test_parse_result_is_frozen() -> None:
    """事实对象必须不可变 —— 解析结果在层间传递，被就地改写会让排查变成猜谜。"""
    result = ParseResult(
        text="x",
        page_count=1,
        encrypted=False,
        has_text_layer=False,
        document_format="pdf",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.text = "y"  # type: ignore[misc]


def test_builtin_pdf_parser_satisfies_the_document_parser_protocol() -> None:
    """结构匹配（不靠继承）—— 这是 Protocol 而不是 ABC 的全部意义。"""
    from app.service.document.pdf_parser import PARSER

    assert isinstance(PARSER, DocumentParser)
