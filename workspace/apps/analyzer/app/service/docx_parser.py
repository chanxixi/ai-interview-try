"""Word（.docx）解析 —— **自己实现**，只用标准库（`zipfile` + `xml.etree`）。

**为什么不引 `python-docx`**：
`python-docx` 为了读写文档模型拉进来一整套 API，而我们只要「按顺序把文字抠出来」。
.docx 本质就是一个 zip，正文在 `word/document.xml`，文本在 `<w:t>` 里、段落是 `<w:p>` ——
读这两样用标准库 40 行就够，还能省掉一个依赖（受限网络下少一个包就少一个失败面）。

**⚠️ 本期它不在上传链路上**（spec §1：DOCX 属 Out of Scope；AC12 要求改名成 `.pdf` 的 docx
被 415 拒）。这里是**预留的可插拔能力**：入口放开只需改 BFF 白名单 + spec 变更记录，
本文件一行都不用动。详见 `workspace/DELIVERY.md` 的偏离登记 D-2。

**安全边界**（spec §2.8 的同一条精神，PDF 那边也适用）：
- 全程在内存里读，**绝不落盘**、绝不解压到目录；
- **绝不执行**宏 / 外链 / 嵌入对象 —— 只读 `word/document.xml` 的文本节点，
  `.docm` 里的 VBA 代码根本不会被碰；
- 防御 zip 炸弹：解压前先看声明的解压后大小，超上限直接拒。

**已知缺口**（诚实登记）：
- 不读页眉 / 页脚 / 脚注 / 批注（`word/header*.xml` 等）—— 简历正文极少放那里；
- 不还原表格的行列结构，只按出现顺序取文字（表格里的文字不会丢，但会失去二维形状）；
- 不解析样式，加粗 / 字号等信息全部丢弃 —— 清洗层用不上，也不该用（用样式猜「章节标题」太脆）。
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile

from app.core.exceptions import AppException, ErrorCode
from app.service.parser_plugin import (
    ParseResult,
    UnsupportedFormatError,
    judge_has_text_layer,
)

logger = logging.getLogger(__name__)

#: OOXML 主命名空间。**必须带命名空间**匹配：不同版本的 Word 会加 `w14:` 等前缀，
#: 用 `element.tag.endswith("t")` 这种写法会把 `<w:tab>`、`<w:tbl>` 一起误命中。
_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_MAIN_PART = "word/document.xml"

#: 旧版 `.doc`（OLE2 复合文档）的 magic number。识别出来是为了给一句**能照做的**提示，
#: 而不是让用户对着「格式不支持」猜。
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: `word/document.xml` 解压后的大小上限。防 zip 炸弹：
#: 一个几百 KB 的 zip 可以把某个条目声明成几个 GB，直接读进来就是 OOM。
_MAX_MAIN_PART_BYTES = 20 * 1024 * 1024


def _fail(message: str) -> AppException:
    return AppException(ErrorCode.ANALYSIS_FAILED, message, http_status=422)


def _extract_paragraphs(document_xml: bytes) -> list[str]:
    """把 `word/document.xml` 变成「一段一行」的文本。

    遍历顺序即文档顺序（`ElementTree.iter()` 是深度优先、按出现顺序），
    所以表格单元格里的段落也会按它们在文档里的位置出现。
    """
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise _fail("Word 文档内容损坏，无法解析") from exc

    paragraphs: list[str] = []
    # 直接取所有 w:p：表格单元格里的段落也是 w:p，能一并拿到。
    # 只读 w:t（真正的文字）—— `w:delText`（修订删除的内容）自然被排除在外。
    for para in root.iter(f"{_NS_W}p"):
        pieces: list[str] = []
        for node in para.iter():
            tag = node.tag
            if tag == f"{_NS_W}t":
                pieces.append(node.text or "")
            elif tag in (f"{_NS_W}br", f"{_NS_W}cr"):
                pieces.append("\n")          # 手动换行：同一段里的断行，保留
            elif tag == f"{_NS_W}tab":
                pieces.append("\t")          # 制表位：保留，清洗层会统一成空格
        paragraphs.append("".join(pieces))
    return paragraphs


def parse_docx(data: bytes) -> ParseResult:
    """把 .docx 字节变成与 PDF 同构的 `ParseResult`（`page_count` 固定 1）。

    与 `parse_pdf` 一致的取舍：**格式不对 / 内容坏了才抛错**；
    文本太少不抛错，只把 `has_text_layer` 置 False，把判断权留给上层。
    """
    if not data:
        raise UnsupportedFormatError("文件为空")

    if data.startswith(_OLE2_MAGIC):
        raise UnsupportedFormatError("旧版 .doc 二进制格式，请另存为 .docx 后重试")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsupportedFormatError("不是有效的 .docx（zip 结构损坏）") from exc

    with archive:
        names = set(archive.namelist())
        if _MAIN_PART not in names:
            raise UnsupportedFormatError("不是有效的 .docx（缺少 word/document.xml）")

        info = archive.getinfo(_MAIN_PART)
        if info.file_size > _MAX_MAIN_PART_BYTES:
            # 不读进来再判 —— 那正是 zip 炸弹想要的结果
            raise _fail("Word 文档正文过大，拒绝解析")

        try:
            document_xml = archive.read(_MAIN_PART)
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise _fail("Word 文档内容损坏，无法解析") from exc

    paragraphs = _extract_paragraphs(document_xml)
    text = "\n".join(paragraphs)
    has_text_layer = judge_has_text_layer(text)

    # 只打数字，绝不打正文（spec §2.8）
    logger.info(
        "docx parsed bytes=%d paragraphs=%d text_chars=%d has_text_layer=%s",
        len(data), len(paragraphs), len(text), has_text_layer,
    )

    return ParseResult(
        text=text,
        page_count=1,          # DOCX 没有页的概念（分页由渲染决定），固定 1 便于上层不分支
        encrypted=False,       # OOXML 的「密码保护」是整包加密，那种文件连 zip 都打不开
        has_text_layer=has_text_layer,
        document_format="docx",
    )


class DocxParser:
    """`DocumentParser` 协议的 Word 实现。"""

    document_format = "docx"

    #: 与 xlsx / pptx / jar 共用 `PK\\x03\\x04`，所以 `sniff` **只是粗筛**，
    #: 真正判断「是不是 docx」在 `parse` 里（看有没有 word/document.xml）。
    magic_prefixes = (b"PK\x03\x04",)

    def sniff(self, data: bytes) -> bool:
        return data.startswith(b"PK\x03\x04")

    def parse(self, data: bytes) -> ParseResult:
        return parse_docx(data)


#: 供 `parser_plugin.default_registry()` 装配
PARSER = DocxParser()
