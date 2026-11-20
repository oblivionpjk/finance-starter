"""PDF 渲染器（主交付格式）。

只按 ReportBlock 排版，不计算、不改写任何数字。中文优先注册系统 TTF/OTF，
找不到时回退 reportlab 内置 CID 中文字体，保证服务器上不会出现方块字。
"""
from __future__ import annotations

import html
from pathlib import Path

from app import config
from app.domain.model import ReportDocument

_FONT_NAME: str | None = None

CJK_KEYWORDS = ("pingfang", "heiti", "songti", "arial unicode",
                "noto sans cjk", "wenquanyi", "simhei", "source han")
FALLBACK_FONT_PATHS = (
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def get_font() -> str:
    global _FONT_NAME
    if _FONT_NAME:
        return _FONT_NAME
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates: list[str] = []
    try:
        from matplotlib import font_manager
        for f in font_manager.fontManager.ttflist:
            if (f.fname.lower().endswith((".ttf", ".otf"))
                    and any(k in f.name.lower() for k in CJK_KEYWORDS)):
                candidates.append(f.fname)
    except Exception:
        pass
    candidates.extend(p for p in FALLBACK_FONT_PATHS if Path(p).exists())

    for path in candidates:
        try:
            pdfmetrics.registerFont(TTFont("FinanceCJK", path))
            _FONT_NAME = "FinanceCJK"
            return _FONT_NAME
        except Exception:
            continue
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT_NAME = "STSong-Light"
    return _FONT_NAME


def _esc(text: object) -> str:
    return html.escape(str(text))


def render_pdf(doc: ReportDocument, out_path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    font = get_font()
    page_w = A4[0] - 80
    styles = {
        1: ParagraphStyle("h1", fontName=font, fontSize=17, leading=24,
                          spaceAfter=10, wordWrap="CJK"),
        2: ParagraphStyle("h2", fontName=font, fontSize=13, leading=19,
                          spaceBefore=12, spaceAfter=7, wordWrap="CJK",
                          textColor=colors.HexColor("#1F3A5F")),
        3: ParagraphStyle("h3", fontName=font, fontSize=11, leading=16,
                          spaceBefore=8, spaceAfter=4, wordWrap="CJK"),
        "body": ParagraphStyle("body", fontName=font, fontSize=9.5, leading=15,
                               spaceAfter=5, wordWrap="CJK"),
        "small": ParagraphStyle("small", fontName=font, fontSize=8, leading=12,
                                wordWrap="CJK", textColor=colors.HexColor("#555555")),
        "callout": ParagraphStyle("callout", fontName=font, fontSize=9, leading=14,
                                  wordWrap="CJK", backColor=colors.HexColor("#F1F5FA"),
                                  borderPadding=6, spaceBefore=6, spaceAfter=8),
    }

    def make_table(payload: dict) -> Table:
        header = [_esc(x) for x in payload.get("header", [])]
        rows = [[_esc(x) for x in row] for row in payload.get("rows", [])]
        data = [header] + rows
        n = max(1, len(header))
        first_w = min(130, page_w / n * 1.6)
        widths = [first_w] + [(page_w - first_w) / (n - 1)] * (n - 1) if n > 1 else [page_w]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 7.6),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B9C6D4")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    story = []
    for block in doc.blocks:
        kind, p = block.type, block.payload
        if kind == "heading":
            story.append(Paragraph(_esc(p["text"]), styles[int(p.get("level", 2))]))
        elif kind == "paragraph":
            story.append(Paragraph(_esc(p), styles["body"]))
        elif kind == "bullets":
            for item in p:
                story.append(Paragraph("· " + _esc(item), styles["body"]))
        elif kind == "callout":
            story.append(Paragraph(_esc(p), styles["callout"]))
        elif kind == "table":
            story.append(make_table(p))
            story.append(Spacer(1, 6))
        elif kind == "image":
            path = Path(p["path"])
            if path.exists():
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(path) as im:
                        ratio = im.size[1] / im.size[0]
                except Exception:
                    ratio = 0.52
                width = page_w
                story.append(Image(str(path), width=width, height=width * ratio))
                story.append(Paragraph(_esc(p.get("caption", "")), styles["small"]))
                story.append(Spacer(1, 8))
        elif kind == "pagebreak":
            story.append(PageBreak())

    meta = doc.source_meta

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(font, 7.5)
        source = str(meta.get("数据来源", ""))[:46]
        canvas.drawString(40, 28, f"数据入口：{meta.get('数据入口', '')} | 来源：{source}")
        canvas.drawRightString(A4[0] - 40, 28, f"第 {doc_.page} 页")
        canvas.setFont(font, 7)
        bench = meta.get("对标基准")
        left = (f"对标基准：{bench} | " if bench else "") + \
               "本报告仅供参考，不构成投资建议；上传数据未做外部核验。"
        canvas.drawString(40, 16, left[:70])
        canvas.drawRightString(A4[0] - 40, 16, f"标的：{meta.get('标的', '')}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=38, bottomMargin=42,
        title=doc.title, subject=getattr(doc, "subject", ""), author="finance-starter",
    )
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return out_path
