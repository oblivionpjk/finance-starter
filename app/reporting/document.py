"""确定性模板报告：把 AnalysisResult 组装成结构化 ReportDocument。

硬约束：模板只组织文字，不产生数字。每个数值都经 NumberRegistry 格式化并登记，
渲染器只按块排版。Narrator 是可扩展接口，本次只注册 template 实现。
"""
from __future__ import annotations

from typing import Protocol

from app import config
from app.domain.model import AnalysisResult, ReportBlock, ReportDocument
from app.domain.numbers import NumberRegistry, SIGNIFICANT

# 以百分比展示的指标；其余比率以「倍/次」原值展示。
PCT_METRICS = {
    "毛利率", "营业利润率", "净利率", "ROE(净资产收益率)", "ROA(总资产收益率)",
    "资产负债率", "营业收入增速", "净利润增速", "总资产增速", "净资产增速",
    "净利率 ", "ROE(分解乘积)", "ROE(直接计算)", "经营现金流/负债", "经营现金流/营收",
}

CHAPTER_ORDER = ("盈利能力", "成长能力", "偿债能力", "营运能力", "现金流", "杜邦分解")
AMOUNT_ROWS = (
    ("营业收入", "IS"), ("营业成本", "IS"), ("营业利润", "IS"), ("净利润", "IS"),
    ("资产总计", "BS"), ("负债合计", "BS"),
    ("所有者权益(或股东权益)合计", "BS"),
    ("经营活动产生的现金流量净额", "CF"),
)


class Narrator(Protocol):
    """叙述器接口。将来接语言模型时新增一个实现并在 NARRATORS 注册即可。"""

    def build(self, result: AnalysisResult, reg: NumberRegistry,
              images: list[tuple[str, str, str]]) -> ReportDocument: ...


def _fmt_metric(value, metric: str, reg: NumberRegistry) -> str:
    return reg.pct(value) if metric in PCT_METRICS else reg.ratio(value)


def _register_engine_text(reg: NumberRegistry, text: str) -> str:
    """校验网关产出的差额数值同样来自引擎计算，显式登记进白名单。"""
    for token in SIGNIFICANT.findall(text):
        reg.literal(token)
    return text


class TemplateNarrator:
    """确定性模板：结果相同 → 报告文字逐字相同，便于回归比对。"""

    def build(self, result: AnalysisResult, reg: NumberRegistry,
              images: list[tuple[str, str, str]]) -> ReportDocument:
        blocks: list[ReportBlock] = []
        periods = result.periods
        table_periods = periods[-6:]          # 表格最多 6 期，保证 PDF 版面可读
        latest = periods[-1] if periods else ""

        blocks.append(ReportBlock("heading", {"level": 1, "text": f"{result.subject} {config.REPORT_TITLE}"}))
        blocks.append(ReportBlock("paragraph",
                                  "本报告由确定性模板生成：指标数值全部来自分析引擎的结构化结果，"
                                  "叙述文字不含任何模型推断或外部数据。"))
        blocks.append(ReportBlock("heading", {"level": 2, "text": "一、数据说明与口径"}))
        blocks.append(ReportBlock("table", {
            "header": ["项目", "说明"],
            "rows": [[k, _register_engine_text(reg, v)] for k, v in result.source_meta.items()],
        }))

        blocks.append(ReportBlock("heading", {"level": 2, "text": "二、结论摘要"}))
        blocks.append(ReportBlock("bullets",
                                  [_register_engine_text(reg, i.text) for i in result.insights]
                                  or ["无可比年度报告期，未生成结论。"]))

        blocks.append(ReportBlock("heading", {"level": 2, "text": "三、主要财务指标"}))
        blocks.append(ReportBlock("paragraph",
                                  f"下表展示最近 {len(table_periods)} 个年度报告期；"
                                  "增速类指标首期无上年基数，以「—」表示。"))
        for category in CHAPTER_ORDER:
            df = result.tables[category]
            blocks.append(ReportBlock("heading", {"level": 3, "text": category}))
            if periods:
                highlights = []
                for metric in list(df.columns)[:3]:
                    try:
                        v = df.loc[int(latest), metric]
                    except (KeyError, ValueError):
                        v = None
                    highlights.append(f"{metric} {_fmt_metric(v, metric, reg)}")
                blocks.append(ReportBlock("paragraph", f"{latest} 年：" + "、".join(highlights) + "。"))
            header = ["指标"] + table_periods
            rows = []
            for metric in df.columns:
                row = [metric]
                for p in table_periods:
                    try:
                        v = df.loc[int(p), metric]
                    except (KeyError, ValueError):
                        v = None
                    row.append(_fmt_metric(v, metric, reg))
                rows.append(row)
            blocks.append(ReportBlock("table", {"header": header, "rows": rows}))

        blocks.append(ReportBlock("heading", {"level": 2, "text": "四、三大报表主要科目"}))
        blocks.append(ReportBlock("paragraph", f"金额单位：{config.DISPLAY_UNIT}；金额由原始报表换算，未做估算。"))
        header = ["科目"] + table_periods
        rows = []
        for label, st in AMOUNT_ROWS:
            frame = result.frames[st]
            row = [label]
            for p in table_periods:
                try:
                    v = frame.loc[label, int(p)]
                except (KeyError, ValueError):
                    v = None
                row.append(reg.amount(v))
            rows.append(row)
        blocks.append(ReportBlock("table", {"header": header, "rows": rows}))

        blocks.append(ReportBlock("pagebreak", {}))
        blocks.append(ReportBlock("heading", {"level": 2, "text": "五、数据分析图"}))
        blocks.append(ReportBlock("paragraph",
                                  "图表由同一份分析结果生成，空值留白、金额单位统一，"
                                  "每张图的来源与报告期见首部数据说明。"))
        for chart_id, title, path in images:
            blocks.append(ReportBlock("image", {"path": path, "caption": title}))

        blocks.append(ReportBlock("heading", {"level": 2, "text": "六、数据质量与风险提示"}))
        quality_rows = [
            [q.level, q.code, _register_engine_text(reg, q.message),
             _register_engine_text(reg, q.detail)]
            for q in result.quality
        ]
        blocks.append(ReportBlock("table", {
            "header": ["级别", "代码", "说明", "明细"], "rows": quality_rows,
        }))
        blocks.append(ReportBlock("callout",
                                  "口径提示：净利润采用报表净利润口径，非归母净利润；"
                                  "同比为本报告期相对上年同期；周转率分母为期初期末平均余额。"))

        blocks.append(ReportBlock("heading", {"level": 2, "text": "七、科目映射审计（上传入口）"}))
        mapped = [a for a in result.mapping_audit if a.get("item_key")][:18]
        audit_rows = [[a["raw"], a.get("label", ""),
                       _register_engine_text(reg, f"{a.get('confidence', 0):.2f}"),
                       a.get("action", "")] for a in mapped]
        blocks.append(ReportBlock("table", {
            "header": ["原始科目", "标准科目", "置信度", "方式"], "rows": audit_rows,
        }))
        blocks.append(ReportBlock("paragraph",
                                  "未纳入标准词典的科目不影响本次指标计算；完整映射记录随会话临时保存，"
                                  "页面关闭后即销毁。"))
        blocks.append(ReportBlock("callout", config.DISCLAIMER))

        return ReportDocument(
            title=f"{result.subject} {config.REPORT_TITLE}",
            subject=result.subject, blocks=blocks,
            source_meta=result.source_meta, disclaimer=config.DISCLAIMER,
        )


NARRATORS: dict[str, Narrator] = {}
NARRATORS["template"] = TemplateNarrator()


def get_narrator(name: str | None = None) -> Narrator:
    """注册表取叙述器；未知名称回退确定性模板，不会悄悄切换到不可复现的实现。"""
    return NARRATORS.get(name or config.NARRATOR, NARRATORS["template"])
