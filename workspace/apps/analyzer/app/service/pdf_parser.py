"""PDF 解析 —— 本仓库**唯一**允许 `import pypdf` 的地方（plan §7「唯一职责文件」）。

**为什么 PDF 解析在 Python、不在 Java**（ADR-102）：解析属于「算」。
Java 只搬运字节（`grep -rn "pdf" src/main/java` 只应出现在校验与转发两处）。
这样做的代价是文件要多搬一跳 —— 10 MB 以内可接受。

**换库成本被这层挡住**：ADR-103 说 pypdf 抽出乱序就换 `pdfplumber`。
换的时候只改本文件，`cleaner` 与上层一行都不动。

**本文件不做什么**（越界了就等于把责任搞混）：
- 不判 magic number / MIME / 大小 → BFF 的活（spec §2.8 / M6.2）。analyzer 收到就说明已经过了闸。
- 不清洗文本 → `cleaner.py` 的活。这里原样返回，连换行都不动。
- 不写日志打正文 → spec §2.8 明令禁止（简历是 PII）。只允许打字节数 / 页数 / 文本长度。
"""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.constants import PDF_MAX_PAGES
from app.core.exceptions import AppException, ErrorCode
from app.service.parser_plugin import ParseResult, judge_has_text_layer

logger = logging.getLogger(__name__)

#: tasks.md M2.2 用这个名字描述返回值。这里做成**别名**而不是再定义一个类 ——
#: 两个类长得一样却互不兼容，是纯粹的自找麻烦。
PdfParseResult = ParseResult


def _fail(code: ErrorCode, message: str) -> AppException:
    """PDF 类错误的统一构造。HTTP 语义：四个码都是 422（spec §2.5）。"""
    return AppException(code, message, http_status=422)


def parse_pdf(data: bytes) -> ParseResult:
    """把 PDF 字节变成「可判定的事实」。

    四条边界的处理方式**故意不同**：

    | 情况 | 行为 | 为什么 |
    |---|---|---|
    | 损坏 / 截断 | 抛 `PDF_PARSE_FAILED` | 连事实都拿不到 |
    | 加密且空密码打不开 | 抛 `PDF_ENCRYPTED` | 同上 |
    | 页数 > 10 | 抛 `PDF_TOO_MANY_PAGES` | 拒绝继续读，不为 200 页文件白烧 CPU |
    | 读完但文本太少 | **正常返回**，`has_text_layer=False` | ★ 它必须带着「已抽出的文本 + 页数」返回 |

    ★ 最后一条是关键设计：把「没有文本层」也做成异常，会把**文本长度**和**页数**这两样事实
    一起丢掉 —— 上层要写日志、要区分「完全没文本」与「有文本层但极短」就没了依据。
    所以解析器只报事实，**要不要因此报 `PDF_NO_TEXT_LAYER` 是上层的策略**（M4 的流式编排）。
    """
    if not data:
        raise _fail(ErrorCode.PDF_PARSE_FAILED, "文件为空，无法解析")

    # ---- 打开文档 ----------------------------------------------------------
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        # pypdf 对畸形文件抛的是 PdfReadError 子类（含 xref 损坏、无 %%EOF 等）
        logger.warning("pdf 打开失败 bytes=%d err=%s", len(data), type(exc).__name__)
        raise _fail(ErrorCode.PDF_PARSE_FAILED, "PDF 文件损坏或格式不合法") from exc
    except Exception as exc:  # noqa: BLE001 —— 第三方库对畸形输入会抛各种类型
        logger.warning("pdf 打开异常 bytes=%d err=%s", len(data), type(exc).__name__)
        raise _fail(ErrorCode.PDF_PARSE_FAILED, "PDF 文件损坏或格式不合法") from exc

    # ---- 加密 --------------------------------------------------------------
    # 注意 True 不等于失败：只设了「所有者密码」的 PDF 能用空密码打开，
    # 这时 encrypted=True 且文本照常抽出 —— 所以先尝试空密码，失败才算错。
    encrypted = bool(reader.is_encrypted)
    if encrypted:
        try:
            opened = bool(reader.decrypt(""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf 解密异常 err=%s", type(exc).__name__)
            opened = False
        if not opened:
            logger.warning("pdf 已加密且空密码打不开 bytes=%d", len(data))
            raise _fail(ErrorCode.PDF_ENCRYPTED, "PDF 已加密，需要密码才能打开")

    # ---- 页数 --------------------------------------------------------------
    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdf 读取页数失败 err=%s", type(exc).__name__)
        raise _fail(ErrorCode.PDF_PARSE_FAILED, "PDF 文件损坏或格式不合法") from exc

    if page_count == 0:
        raise _fail(ErrorCode.PDF_PARSE_FAILED, "PDF 不包含任何页面")
    if page_count > PDF_MAX_PAGES:
        logger.warning("pdf 页数超限 pages=%d limit=%d", page_count, PDF_MAX_PAGES)
        raise _fail(
            ErrorCode.PDF_TOO_MANY_PAGES,
            f"PDF 页数 {page_count} 超过上限 {PDF_MAX_PAGES} 页",
        )

    # ---- 逐页抽文本 --------------------------------------------------------
    # 单页抽取失败不整体失败：真实简历里偶尔有一页是纯图片，为它丢掉另外九页不划算。
    # 抽不出来就当空页，最后由 has_text_layer 统一兜底判断。
    chunks: list[str] = []
    failed_pages = 0
    for index, page in enumerate(reader.pages):
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            failed_pages += 1
            logger.warning(
                "pdf 第 %d 页抽取失败，按空页处理 err=%s", index + 1, type(exc).__name__
            )
            chunks.append("")

    text = "\n".join(chunks)
    has_text_layer = judge_has_text_layer(text)

    # 只打数字，绝不打正文（spec §2.8）
    logger.info(
        "pdf parsed bytes=%d pages=%d failed_pages=%d text_chars=%d encrypted=%s has_text_layer=%s",
        len(data), page_count, failed_pages, len(text), encrypted, has_text_layer,
    )

    return ParseResult(
        text=text,
        page_count=page_count,
        encrypted=encrypted,
        has_text_layer=has_text_layer,
        document_format="pdf",
    )


class PdfParser:
    """`DocumentParser` 协议的 PDF 实现（结构匹配即可，不继承）。"""

    document_format = "pdf"
    magic_prefixes = (b"%PDF-",)

    def sniff(self, data: bytes) -> bool:
        return data.startswith(b"%PDF-")

    def parse(self, data: bytes) -> ParseResult:
        return parse_pdf(data)


#: 供 `parser_plugin.default_registry()` 装配
PARSER = PdfParser()
