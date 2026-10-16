"""Word（.docx）解析 —— 自己用标准库实现的那个插件（M2.2 的扩展点）。

**⚠️ 本期它不在上传链路上**（spec §1：DOCX 属 Out of Scope；AC12 要求改名成 `.pdf` 的
docx 被 415 拒）。写测试的理由不是「它会跑」，而是：**它已经是仓库里可被调用的代码**，
没测试的代码就是负债 —— 要么测，要么删。这里是「预留能力」，所以测它。

测的是三件事：
1. **能正确抠出文字**：段落 / 手动换行 / 制表位 / 表格单元格 / 修订删除的内容；
2. **拒绝时给的错要能照做**：旧版 `.doc` 要提示「另存为 .docx」，而不是一句「格式不支持」；
3. **安全边界**：zip 炸弹在解压**前**被拦、坏 XML 不炸到 500。
"""

from __future__ import annotations
import io
import zipfile
import pytest
from app.core.errors.exceptions import AppException, ErrorCode
from app.service.document import docx_parser
from app.service.document.docx_parser import PARSER, parse_docx
from app.service.document.parser_plugin import (
    DocumentParser,
    UnsupportedFormatError,
    default_registry,
)

# ------------------------------------------------------------------ 样本构造

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_DOCUMENT_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{_NS_W}">'
    "<w:body>{body}</w:body>"
    "</w:document>"
)


def build_docx(
    body: str,
    *,
    main_part: str = "word/document.xml",
) -> bytes:
    """拼一个最小 .docx（本质就是个 zip）。

    **故意不带 `[Content_Types].xml` / `_rels` 等部件** —— 解析器只需要
    `word/document.xml`（`parse_docx` 也只检查这一件）。样本越少，
    「测试失败到底是解析器错了还是样本错了」越容易判断。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr(main_part, _DOCUMENT_TEMPLATE.format(body=body))
    return buffer.getvalue()


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


#: 足够长（> 100 非空白字符）的正常简历正文
_LONG_BODY = "".join(
    para(line)
    for line in (
        "教育背景",
        "XX 大学 计算机科学与技术 本科 2019-2023",
        "专业技能",
        "Java / Spring Boot / Vue3 / MySQL / Redis / Koa2 / TypeScript / Docker",
        "项目经历",
        "负责直播后台系统的开发与维护，日均请求量三百万，QPS 峰值 2000",
    )
)


# ------------------------------------------------------------------ 正常路径


def test_normal_docx_yields_all_facts() -> None:
    result = parse_docx(build_docx(_LONG_BODY))

    assert result.document_format == "docx"
    assert result.page_count == 1          # DOCX 没有「页」的概念，约定填 1（不是 0/None）
    assert result.encrypted is False       # OOXML 的密码保护是整包加密，那种文件连 zip 都打不开
    assert result.has_text_layer is True
    assert result.text.split("\n")[0] == "教育背景"
    assert "直播后台系统" in result.text


def test_paragraphs_are_joined_one_per_line_in_document_order() -> None:
    data = build_docx(para("第一段") + para("第二段") + para("第三段"))

    assert parse_docx(data).text.split("\n") == ["第一段", "第二段", "第三段"]


def test_manual_line_break_and_tab_are_preserved() -> None:
    """`w:br` → 换行、`w:tab` → 制表符。清洗层会把制表符统一成空格，这里先原样留着。"""
    body = "<w:p><w:r><w:t>Java</w:t><w:br/><w:t>Spring</w:t><w:tab/><w:t>Boot</w:t></w:r></w:p>"

    assert parse_docx(build_docx(body)).text == "Java\nSpring\tBoot"


def test_revision_deleted_text_is_excluded() -> None:
    """只读 `w:t`，不读 `w:delText` —— 修订删除的内容不是简历正文。"""
    body = (
        "<w:p><w:r><w:t>Java</w:t></w:r>"
        "<w:del><w:r><w:delText>PHP</w:delText></w:r></w:del></w:p>"
    )

    assert parse_docx(build_docx(body)).text == "Java"


def test_table_cell_text_is_not_lost() -> None:
    """表格只按出现顺序取文字（不还原行列），但**文字不能丢** —— 简历大量用表格排版。"""
    body = (
        "<w:tbl><w:tr>"
        "<w:tc><w:p><w:r><w:t>2021-2023</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>XX 大学</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl>"
    )

    assert parse_docx(build_docx(body)).text.split("\n") == ["2021-2023", "XX 大学"]


def test_short_document_reports_no_text_layer_without_raising() -> None:
    """与 PDF 同构的取舍：文本太少**不抛错**，只把 `has_text_layer` 置 False。"""
    result = parse_docx(build_docx(para("Page 1")))

    assert result.has_text_layer is False
    assert result.page_count == 1


# ------------------------------------------------------------------ 拒绝路径


def test_empty_bytes_are_rejected() -> None:
    with pytest.raises(UnsupportedFormatError) as exc:
        parse_docx(b"")

    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_non_zip_bytes_are_rejected_as_unsupported() -> None:
    with pytest.raises(UnsupportedFormatError) as exc:
        parse_docx(b"%PDF-1.4\nthis is actually a pdf")

    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT
    assert exc.value.http_status == 415


def test_legacy_doc_binary_gives_an_actionable_message() -> None:
    """旧版 `.doc` 是 OLE2 复合文档，不是 zip。识别出来是为了给一句**能照做的**提示。"""
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512

    with pytest.raises(UnsupportedFormatError) as exc:
        parse_docx(ole2)

    assert ".docx" in exc.value.message      # 「请另存为 .docx」—— 用户能照着做


def test_zip_without_the_document_part_is_rejected() -> None:
    """`PK\\x03\\x04` 只是粗筛：xlsx / pptx / jar 共用它，所以真正判断在 parse 里。"""
    data = build_docx(_LONG_BODY, main_part="word/other.xml")

    with pytest.raises(UnsupportedFormatError):
        parse_docx(data)


def test_malformed_document_xml_raises_analysis_failed() -> None:
    """内容坏了 ≠ 格式不认识：给 `ANALYSIS_FAILED`(422)，不要掉进 500 兜底。"""
    data = build_docx("<w:p><w:r><w:t>标签没闭合")

    with pytest.raises(AppException) as exc:
        parse_docx(data)

    assert exc.value.code is ErrorCode.ANALYSIS_FAILED
    assert exc.value.http_status == 422


def test_zip_bomb_is_rejected_before_decompressing(monkeypatch: pytest.MonkeyPatch) -> None:
    """防 zip 炸弹：**解压前**先看声明的解压后大小，不能读进来再判 —— 那正是炸弹想要的结果。

    这里把阈值调小来测（真造 20 MB 样本既慢又占内存）；测的是**判定与时机**，
    不是那个具体数字（数字在 `docx_parser._MAX_MAIN_PART_BYTES` 里）。
    """
    monkeypatch.setattr(docx_parser, "_MAX_MAIN_PART_BYTES", 1024)
    data = build_docx(para("x" * 4096))

    with pytest.raises(AppException) as exc:
        parse_docx(data)

    assert exc.value.code is ErrorCode.ANALYSIS_FAILED


# ------------------------------------------------------------------ 插件协议


def test_docx_parser_sniffs_the_zip_magic_number() -> None:
    assert PARSER.sniff(b"PK\x03\x04") is True
    assert PARSER.sniff(b"%PDF-1.4") is False


def test_docx_parser_matches_the_document_parser_protocol() -> None:
    assert isinstance(PARSER, DocumentParser)
    assert PARSER.document_format == "docx"


def test_default_registry_routes_docx_bytes_to_the_docx_parser() -> None:
    """注册表按 magic number 分派 —— 加格式时调用方一行都不用改。"""
    registry = default_registry()
    data = build_docx(_LONG_BODY)

    detected = registry.detect(data)

    assert detected is not None
    assert detected.document_format == "docx"
    assert detected.parse(data).document_format == "docx"
