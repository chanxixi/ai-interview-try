"""PDF 解析（M2.2 / M2.3 / M2.5）。

覆盖 tasks.md M2.5 点名的六类：**正常 / 损坏 / 加密 / 无文本层 / 超长 / 隐形字符**
（超长与隐形字符是清洗层的活，在 `test_cleaner.py`；本文件管「解析出事实」这一半）。

**样本怎么来的**：`build_pdf()` 手搓最小合法 PDF（不依赖任何库），
只有**加密**样本借 `pypdf.PdfWriter` —— 应用侧「唯一 import pypdf」的约束针对 `app/`
（plan §7），而测试需要一个**加密器**，应用永远不做加密。手搓 RC4/AES 密文
只会让测试变得没法维护。

**被测的四条边界处理方式故意不同**（这是本文件最该记住的一点）：

| 情况 | 期望 | 为什么 |
|---|---|---|
| 空 / 损坏 / 截断 | 抛 `PDF_PARSE_FAILED`(422) | 连事实都拿不到 |
| 有密码且空密码解不开 | 抛 `PDF_ENCRYPTED`(422) | 同上 |
| 页数 > 10 | 抛 `PDF_TOO_MANY_PAGES`(422) | 不为 200 页文件白烧 CPU |
| 读完但文本太少 | **正常返回**，`has_text_layer=False` | ★ 必须带着「文本 + 页数」回来 |
"""

from __future__ import annotations
import io
from typing import Sequence
import pytest
from pypdf import PdfWriter
from app.core.constants import PDF_MAX_PAGES, PDF_MIN_TEXT_LAYER_CHARS
from app.core.errors.exceptions import AppException, ErrorCode
from app.service.document.parser_plugin import DocumentParser, count_non_whitespace
from app.service.document.pdf_parser import PARSER, PdfParseResult, parse_pdf

# ------------------------------------------------------------------ 样本构造


def _pdf_escape(text: str) -> str:
    """PDF 字面量字符串里的 `\\` `(` `)` 必须转义，否则内容流直接语法错误。"""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(page_texts: Sequence[str]) -> bytes:
    """手搓一个 pypdf 能正确解析的最小 PDF（ASCII 正文 + 标准 Helvetica）。

    自己拼 xref 而不是用库写：**样本要能被完全掌控** —— 页数、每页文本、
    以及故意损坏的程度（`build_pdf(...)[:200]` 这种），用生成器做更直接。
    """
    page_ids: list[int] = []
    content_ids: list[int] = []
    next_id = 3
    for _ in page_texts:
        page_ids.append(next_id)
        next_id += 1
        content_ids.append(next_id)
        next_id += 1
    font_id = next_id

    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode())
    for pid, cid, text in zip(page_ids, content_ids, page_texts):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {cid} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({_pdf_escape(text)}) Tj ET".encode()
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_pos = len(out)
    size = len(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


def _encrypt(pdf_bytes: bytes, *, user_password: str, owner_password: str) -> bytes:
    """用 pypdf 的 PdfWriter 造加密样本（测试里唯一 import pypdf 的用途）。"""
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    writer.encrypt(user_password=user_password, owner_password=owner_password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


#: 一份「正常简历」样本：正文必须**超过 `PDF_MIN_TEXT_LAYER_CHARS` 个非空白字符**，
#: 否则它本身就会落到「无文本层」那一类里去（这条一开始就踩了）。
_VALID_PDF = build_pdf(
    [
        "Alice Chen  Java Spring Boot Vue3 MySQL Redis Koa2 TypeScript Docker "
        "Bachelor of Computer Science  13800000000  alice@example.com  "
        "Full-stack engineer with three years of experience building live streaming "
        "and video platforms, familiar with distributed systems and CI/CD pipelines"
    ]
)
_CORRUPT_SAMPLES = {
    "truncated": _VALID_PDF[:200],                     # 头还在、xref/EOF 没了
    "garbage_after_header": b"%PDF-1.4\nnot really a pdf at all",
    "no_eof_marker": _VALID_PDF[:-40],
}


# ------------------------------------------------------------------ 正常路径


def test_normal_pdf_yields_all_facts() -> None:
    result = parse_pdf(_VALID_PDF)

    assert isinstance(result, PdfParseResult)
    assert "Alice Chen" in result.text
    assert "Java" in result.text
    assert result.page_count == 1
    assert result.encrypted is False
    assert result.has_text_layer is True
    assert result.document_format == "pdf"


def test_multi_page_text_is_concatenated_in_page_order() -> None:
    data = build_pdf(["FIRST PAGE MARKER", "SECOND PAGE MARKER", "THIRD PAGE MARKER"])

    result = parse_pdf(data)

    assert result.page_count == 3
    assert result.text.index("FIRST") < result.text.index("SECOND") < result.text.index("THIRD")


def test_parsing_is_deterministic() -> None:
    """同一份字节必得同一份事实 —— 后面所有阶段的可复现性都建立在它上面。"""
    assert parse_pdf(_VALID_PDF) == parse_pdf(_VALID_PDF)


# ------------------------------------------------------------------ 边界一：损坏


@pytest.mark.parametrize("sample_name", sorted(_CORRUPT_SAMPLES))
def test_corrupt_pdf_raises_parse_failed(sample_name: str) -> None:
    with pytest.raises(AppException) as exc:
        parse_pdf(_CORRUPT_SAMPLES[sample_name])

    assert exc.value.code is ErrorCode.PDF_PARSE_FAILED
    assert exc.value.http_status == 422


def test_empty_bytes_raises_parse_failed() -> None:
    with pytest.raises(AppException) as exc:
        parse_pdf(b"")

    assert exc.value.code is ErrorCode.PDF_PARSE_FAILED


def test_error_message_does_not_leak_internal_details() -> None:
    """spec §3.3：对外文案不得带库名 / 异常类名。"""
    with pytest.raises(AppException) as exc:
        parse_pdf(_CORRUPT_SAMPLES["truncated"])

    assert "pypdf" not in exc.value.message
    assert "Error" not in exc.value.message


# ------------------------------------------------------------------ 边界二：加密


def test_password_protected_pdf_raises_encrypted() -> None:
    data = _encrypt(_VALID_PDF, user_password="hunter2", owner_password="hunter2")

    with pytest.raises(AppException) as exc:
        parse_pdf(data)

    assert exc.value.code is ErrorCode.PDF_ENCRYPTED
    assert exc.value.http_status == 422


def test_owner_only_password_pdf_is_still_readable() -> None:
    """★ 最容易写错的一条边界：**只有所有者密码**的 PDF 能用空密码打开，
    此时 `encrypted=True` 但文本照常抽出 —— 把 `encrypted` 直接当失败会误杀这类文件。"""
    data = _encrypt(_VALID_PDF, user_password="", owner_password="owner-secret")

    result = parse_pdf(data)

    assert result.encrypted is True
    assert "Alice Chen" in result.text
    assert result.has_text_layer is True


# ------------------------------------------------------------------ 边界三：页数


def test_too_many_pages_raises() -> None:
    data = build_pdf(["Some resume body text"] * (PDF_MAX_PAGES + 1))

    with pytest.raises(AppException) as exc:
        parse_pdf(data)

    assert exc.value.code is ErrorCode.PDF_TOO_MANY_PAGES
    assert str(PDF_MAX_PAGES) in exc.value.message      # 报错要能照着改


def test_page_count_at_the_limit_is_accepted() -> None:
    data = build_pdf(["Some resume body text"] * PDF_MAX_PAGES)

    assert parse_pdf(data).page_count == PDF_MAX_PAGES


# ------------------------------------------------------------------ 边界四：无文本层


def test_scanned_pdf_returns_has_text_layer_false_instead_of_raising() -> None:
    """★ 本文件最关键的断言。

    扫描件（纯图片 PDF）能抽出页码那几个字符。这时**必须正常返回**：
    抛异常会把「文本长度」和「页数」两样事实一起丢掉，上层就没法区分
    「完全没文本」与「有文本层但极短」。要不要因此报 `PDF_NO_TEXT_LAYER` 是上层策略（M4）。
    """
    data = build_pdf(["1"])

    result = parse_pdf(data)

    assert result.has_text_layer is False
    assert result.page_count == 1                      # ← 事实没丢
    assert result.text == "1"                          # ← 抽到的内容也没丢
    assert count_non_whitespace(result.text) < PDF_MIN_TEXT_LAYER_CHARS


def test_text_layer_threshold_is_measured_in_non_whitespace_characters() -> None:
    below = build_pdf(["x" * (PDF_MIN_TEXT_LAYER_CHARS - 1)])
    at_threshold = build_pdf(["x" * PDF_MIN_TEXT_LAYER_CHARS])

    assert parse_pdf(below).has_text_layer is False
    assert parse_pdf(at_threshold).has_text_layer is True


def test_an_empty_page_does_not_lose_the_others() -> None:
    """抽不出文本的页按空页处理，不整体失败 —— 真实简历里偶尔有一页是纯图片，
    为它丢掉另外九页不划算。这里用「第一页没文本 + 第二页有正文」近似该场景。"""
    data = build_pdf(["", "REAL RESUME CONTENT ON PAGE TWO"])

    result = parse_pdf(data)

    assert result.page_count == 2
    assert "REAL RESUME CONTENT" in result.text


# ------------------------------------------------------------------ 插件协议


def test_pdf_parser_sniffs_the_pdf_magic_number() -> None:
    assert PARSER.sniff(b"%PDF-1.7\n...") is True
    assert PARSER.sniff(b"PK\x03\x04") is False
    assert PARSER.sniff(b"") is False


def test_pdf_parser_matches_the_document_parser_protocol() -> None:
    assert isinstance(PARSER, DocumentParser)
    assert PARSER.document_format == "pdf"


def test_pdf_parser_parse_delegates_to_parse_pdf() -> None:
    assert PARSER.parse(_VALID_PDF) == parse_pdf(_VALID_PDF)
