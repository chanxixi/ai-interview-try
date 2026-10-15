#!/usr/bin/env python3
"""生成降级演练需要的**两个假样本**（tasks.md M8.3）。

为什么要造样本，而不是用 `脱敏资料/` 里的真简历：

* **AC12** 要的是「改名为 `.pdf` 的 docx」—— 真样本里没有 docx，而且我们**不希望**
  仓库里出现 docx（门禁①：`apps/` 下不得有样本文件；`脱敏资料/` 也不该混进 Word）。
* **AC14** 要的是「扫描件 / 纯图片 PDF」—— 真简历 20 份**全部**有文本层
  （DELIVERY §2.3 实测），拿不出反例。

两个样本都只有几十到几百字节，现场生成比把二进制塞进仓库好：
**二进制文件在 review 里是黑盒**，而这里的每一字节都是可读的构造过程。

用法：

    python scripts/drill_fixtures.py [输出目录]      # 默认 workspace/.logs/drills

文件名用下划线（而不是 `drill-fixtures.py`）是为了能被 `drill_degradation.py` 直接 import ——
样本只有**一份**构造逻辑，演练脚本不另抄一遍。
"""

from __future__ import annotations

import io
import pathlib
import sys
import zipfile

# --------------------------------------------------------------------------- ①
# 改名为 .pdf 的 docx。
#
# docx 本质就是一个 zip（`[Content_Types].xml` + `word/document.xml`）。
# 这里**故意**造一个内容像模像样的 Word 文档：如果 BFF 只看扩展名或 MIME，
# 它就会被放行到 Python 解析器里，然后在最深处才炸 —— 那正是 AC12 要防的。
# 正确的行为是**在门口就 415**（magic number 不是 `%PDF-`）。
DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    "</Types>"
)

DOCX_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>这是一份 Word 文档，被改名成了 .pdf</w:t></w:r></w:p></w:body>"
    "</w:document>"
)


def build_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES)
        archive.writestr("word/document.xml", DOCX_DOCUMENT)
    return buffer.getvalue()


# --------------------------------------------------------------------------- ②
# 扫描件（纯图片 PDF）。
#
# 真扫描件的页面上**一个文字对象都没有**，整页是一张图。但抽出来的文本通常
# 也不是空的 —— 页眉 / 页码 / 水印里的几个字符仍会被抽到，这就是为什么
# 「有没有文本层」必须用**非空白字符数**判（阈值 100），不能用 `len()`。
#
# 这里手搓一个正文只有一个 "1" 的 PDF，等价于那份情形：
# 解析**成功**（有 1 页、抽出 1 个字符），但 `has_text_layer=False`。
# 于是它同时压住了两件事：① 解析器不抛异常（只报事实）；
# ② 编排层必须据此发 `error(PDF_NO_TEXT_LAYER)`，而不是产出一份 0 技能的 result。
def _pdf_escape(text: str) -> str:
    """PDF 字面量字符串里的 `\\` `(` `)` 必须转义，否则内容流直接语法错误。"""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(page_texts: list[str]) -> bytes:
    """手搓一个 pypdf 能正确解析的最小 PDF（ASCII 正文 + 标准 Helvetica）。

    自己拼 xref 而不用库写：样本要能被完全掌控 —— 页数与每页文本都得是**我们说多少就是多少**。
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
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
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
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


def main(argv: list[str]) -> int:
    target = pathlib.Path(argv[1] if len(argv) > 1 else ".logs/drills")
    target.mkdir(parents=True, exist_ok=True)

    docx = build_docx_bytes()
    (target / "renamed-docx.pdf").write_bytes(docx)
    print(f"renamed-docx.pdf : {len(docx):>5} bytes  head={docx[:4]!r}   （期望被 415 拦下）")

    scanned = build_pdf(["1"])
    (target / "scanned.pdf").write_bytes(scanned)
    print(f"scanned.pdf      : {len(scanned):>5} bytes  head={scanned[:5]!r}  （期望 error(PDF_NO_TEXT_LAYER)）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
