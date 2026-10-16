"""文档 → 干净文本：解析插件框架 + 各格式实现 + 清洗。

依赖方向：`parser_plugin` 是抽象层，`pdf_parser` / `docx_parser` 是实现，
`cleaner` 是解析之后的第二道工序。**四者同属「把文件变成可用文本」这一件事**，
所以放一组；换解析库（比如 pypdf → pdfplumber）只动 `pdf_parser` 一个文件。
"""
