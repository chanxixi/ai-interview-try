"""M2.6 门禁：真实脱敏简历样本 + 「PDF 未复制进 `apps/`」。

**为什么这条门禁必须存在**：单测的 PDF 是手搓的（ASCII、一页一句话），
而真实简历是双栏 / 表格 / 图标字体 / 换行全靠绝对定位 —— 两者能通过同一批断言的概率很低。
M2 的验收标准是「真实 PDF 抽出干净文本」，只有真样本能证明。

**为什么缺样本时跳过而不是失败**：`脱敏资料/` 是**样本目录，不入库**
（简历是 PII，spec §2.8）。克隆到一台没有样本的机器上时，这套断言无从执行 ——
跳过并说明原因，比伪造一个假的绿色勾要好。
"""

from __future__ import annotations
import pathlib
import pytest
from app.core.constants import PDF_MAX_PAGES, PDF_MIN_TEXT_LAYER_CHARS, RESUME_MAX_LENGTH
from app.service.document.cleaner import clean, is_printable_ratio
from app.service.document.pdf_parser import parse_pdf

_ANALYZER_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _find_samples_dir() -> pathlib.Path | None:
    """从本文件往上找 `脱敏资料/` —— 不写死相对层数，仓库挪个位置也不会失效。"""
    for parent in pathlib.Path(__file__).resolve().parents:
        candidate = parent / "脱敏资料"
        if candidate.is_dir():
            return candidate
    return None


SAMPLES_DIR = _find_samples_dir()
SAMPLE_PDFS = sorted(SAMPLES_DIR.glob("*.pdf")) if SAMPLES_DIR else []

pytestmark = pytest.mark.skipif(
    not SAMPLE_PDFS,
    reason="未找到 脱敏资料/*.pdf（样本目录不入库），跳过真样本门禁",
)


# ------------------------------------------------------------------ 真样本解析


@pytest.mark.parametrize("pdf_path", SAMPLE_PDFS, ids=lambda path: path.name)
def test_real_resume_yields_usable_clean_text(pdf_path: pathlib.Path) -> None:
    """一份真实简历走完「解析 → 清洗」后，必须是能直接喂给下一层的正经文本。"""
    parsed = parse_pdf(pdf_path.read_bytes())

    assert parsed.has_text_layer is True, f"{pdf_path.name} 抽出的文本不足以当正文"
    assert 1 <= parsed.page_count <= PDF_MAX_PAGES

    cleaned = clean(parsed.text)

    assert len(cleaned.text) >= PDF_MIN_TEXT_LAYER_CHARS
    assert len(cleaned.text) <= RESUME_MAX_LENGTH
    assert is_printable_ratio(cleaned.text) > 0.95
    assert not any("\ue000" <= ch <= "\uf8ff" for ch in cleaned.text)   # 图标字形已清掉
    assert "\ufffd" not in cleaned.text                                # 没有解码失败的替换字符


def test_the_whole_corpus_produces_clean_text() -> None:
    """整批的汇总断言：20 份里允许有排版极端的样本，但**不能有解析失败**。"""
    failures: list[str] = []
    for pdf_path in SAMPLE_PDFS:
        parsed = parse_pdf(pdf_path.read_bytes())
        cleaned = clean(parsed.text)
        if not parsed.has_text_layer or len(cleaned.text) < PDF_MIN_TEXT_LAYER_CHARS:
            failures.append(pdf_path.name)

    assert failures == []


def test_at_least_half_of_the_corpus_yields_a_detected_section() -> None:
    """章节切块是**保守**的（宁可漏切），所以不要求 100%。

    但整批里若连一半都切不出章节，说明别名表或行结构处理出了系统性问题 ——
    这条断言就是那个下限（当前实测 20/20 都有至少一个具名章节）。
    """
    with_section = [
        pdf_path.name
        for pdf_path in SAMPLE_PDFS
        if set(clean(parse_pdf(pdf_path.read_bytes()).text).sections) - {"header"}
    ]

    assert len(with_section) >= len(SAMPLE_PDFS) / 2


# ------------------------------------------------------------------ 仓库门禁


def test_no_sample_pdf_was_copied_into_the_app() -> None:
    """★ M2.6 点名的门禁：**PDF 未复制进 `apps/`**。

    简历是 PII。样本只该留在仓库外的 `脱敏资料/`，任何进 `apps/` 的副本
    都会被打进镜像、跟着仓库走 —— 这是 spec §2.8「上传不落盘」同一条精神。
    """
    stray = [
        path
        for path in _ANALYZER_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".pdf", ".docx", ".doc"}
        and ".venv" not in path.parts
    ]

    assert stray == [], f"发现被复制进来的样本文件：{stray}"


def test_no_uploaded_file_is_ever_written_to_disk() -> None:
    """「上传不落盘」在代码层的体现：解析器只接受 `bytes`，没有任何 open/write 路径。

    这是**静态**断言（读源码），因为它要防的正是「以后有人顺手加一句落盘」。
    """
    service_dir = _ANALYZER_ROOT / "app" / "service"
    offenders: list[str] = []
    for module in sorted(service_dir.glob("*_parser.py")):
        source = module.read_text(encoding="utf-8")
        for needle in ("open(", ".write(", "tempfile", "Path(", "os.makedirs"):
            if needle in source:
                offenders.append(f"{module.name}: {needle}")

    assert offenders == []


def test_only_the_pdf_parser_module_imports_pypdf() -> None:
    """plan §7 的「唯一职责文件」：换库（ADR-103：pypdf → pdfplumber）只该改一个文件。

    这条约束靠自觉是守不住的 —— 顺手在别处 `from pypdf import ...` 太容易了，
    而一旦散开，「换库成本被挡住」这个设计目标就悄悄没了。
    """
    import re

    pattern = re.compile(r"^\s*(?:import|from)\s+pypdf", re.MULTILINE)
    offenders = [
        str(path.relative_to(_ANALYZER_ROOT))
        for path in sorted((_ANALYZER_ROOT / "app").rglob("*.py"))
        if path.name != "pdf_parser.py" and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
