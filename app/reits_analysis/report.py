"""PDF 数据分析报告：确定性模板，所有数值经 NumberRegistry 注入并可回溯。

章节结构固定；每个数字必须来自 metrics / quality_report / 配置对照值，
禁止叙述层自行产生数字。verify() 未通过时调用方必须中止交付。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from app import config as app_config
from app.domain.model import ReportBlock, ReportDocument
from app.domain.numbers import NumberRegistry, verify
from app.reits_analysis import config as cfg
from app.reits_analysis.model import AnalysisTask

# 扩展章节生成者：(task, metrics, registry, charts) -> list[ReportBlock]
SECTION_BUILDERS: dict[str, Any] = {}


def register_section(dimension: str, fn: Any) -> None:
    """扩展入口：注册新维度的报告章节生成者。"""
    SECTION_BUILDERS[dimension] = fn


def _table(header: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {"header": header, "rows": rows}


def _quote_sections(task: AnalysisTask, q: dict[str, Any], reg: NumberRegistry,
                    charts: dict[str, Path]) -> list[ReportBlock]:
    blocks: list[ReportBlock] = []
    rows = q["series"]
    bench = q.get("benchmark") or next((r for r in rows if r["code"] == q["benchmark_code"]), None)
    bench_name = bench["name"] if bench else q["benchmark_code"]
    bench_code = q["benchmark_code"]

    blocks.append(ReportBlock("heading", {"text": "3. 基准标的市场表现", "level": 2}))
    if bench is None:
        blocks.append(ReportBlock("paragraph",
            f"未识别到所选基准标的（{bench_code}），本节留空。"))
    else:
        blocks.append(ReportBlock("paragraph",
            f"基准标的：{bench_name}（{bench_code}）。"
            f"期末收盘价 {reg.amount(bench['snapshot_close'], 3, '元')}；"
            f"年初至今 {reg.pct(bench['ytd_return'])}，基准日为 {bench['ytd_base_date'] or '—'}；"
            f"公共窗口收益 {reg.pct(bench['window_return'])}；"
            f"年化波动率 {reg.pct(bench['annualized_volatility'])}；"
            f"最大回撤 {reg.pct(bench['max_drawdown'])}；"
            f"日均成交额 {reg.amount(bench['avg_amount_million'], 2, '百万元')}。"))
        blocks.append(ReportBlock("table", _table(
            ["指标", "数值", "口径"],
            [
                ["期末收盘价", reg.amount(bench["snapshot_close"], 3, "元"), q["snapshot_date"]],
                ["年初至今涨跌幅", reg.pct(bench["ytd_return"]), "上年最后一个交易日基准"],
                ["上市至今涨跌幅", reg.pct(bench["since_listing_return"]), "上市首日基准"],
                ["公共窗口收益", reg.pct(bench["window_return"]),
                 f"{q['window']['start']} ~ {q['window']['end']}"],
                ["年化波动率", reg.pct(bench["annualized_volatility"]), "日收益标准差 × √252"],
                ["最大回撤", reg.pct(bench["max_drawdown"]), "公共窗口峰值至谷底"],
                ["日均成交额", reg.amount(bench["avg_amount_million"], 2, "百万元"),
                 "剔除上市首日" if q.get("exclude_listing_day") else "含上市首日"],
            ])))

    blocks.append(ReportBlock("heading", {"text": f"4. 横向对标（基准：{bench_name}）", "level": 2}))
    blocks.append(ReportBlock("paragraph",
        f"本章基准标的为 {bench_name}（{bench_code}），由对标参数选择决定；"
        "横向对比统一使用公共窗口，上市时间不同的标的不用全样本直接排名。"
        "图中基准标的高亮，A 股惯例涨为红、跌为绿。"))

    def add_figure(key: str, title: str, caption: str) -> None:
        path = charts.get(key)
        if path is not None:
            prefix = title.split(" ", 1)[0]
            if "." in prefix:
                reg.literal(prefix)   # 章节号（4.1 等）也纳入白名单
            blocks.append(ReportBlock("heading", {"text": title, "level": 3}))
            blocks.append(ReportBlock("image", {"path": str(path), "caption": caption}))

    def rank_line(key: str, label: str, formatter: Callable[[float], str]) -> str:
        ranking = q["rankings"].get(key) or []
        if not ranking:
            return f"{label}：无有效样本。"
        top, bottom = ranking[0], ranking[-1]
        return (f"{label}：居前 {top['name']}（{formatter(top['value'])}），"
                f"居后 {bottom['name']}（{formatter(bottom['value'])}）。")

    add_figure("price_trend", "4.1 归一化走势",
               f"图：{len(rows)} 只 REIT 公共窗口归一化累计收益，基准 {bench_name} 加粗。")
    blocks.append(ReportBlock("paragraph", rank_line(
        "window_return", "区间收益", lambda v: reg.pct(v))))
    add_figure("ytd_return", "4.2 年初至今涨跌幅", "图：上年最后交易日基准，红涨绿跌。")
    blocks.append(ReportBlock("paragraph", rank_line(
        "ytd_return", "年初至今", lambda v: reg.pct(v))))
    add_figure("since_listing", "4.3 上市至今涨跌幅", "图：各标的上市首日起算，样本长度不同。")
    blocks.append(ReportBlock("paragraph", rank_line(
        "since_listing_return", "上市至今", lambda v: reg.pct(v))
        if "since_listing_return" in q["rankings"] else "上市至今：无有效样本。"))
    add_figure("close_price", "4.4 期末收盘价", "图：单一时点收盘价横向对比。")
    add_figure("vol_return_scatter", "4.5 风险收益散点", "图：年化波动率与公共窗口收益。")
    add_figure("drawdown", "4.6 最大回撤", "图：公共窗口峰值至谷底最大跌幅。")
    blocks.append(ReportBlock("paragraph", rank_line(
        "max_drawdown", "最大回撤（绝对值越小越稳）", lambda v: reg.pct(v))))
    add_figure("liquidity", "4.7 流动性对比", "图：日均成交金额，基准高亮。")
    blocks.append(ReportBlock("paragraph", rank_line(
        "avg_amount_million", "日均成交额", lambda v: reg.amount(v, 2, "百万元"))))
    add_figure("corr_heatmap", "4.8 日收益相关性", "图：公共窗口日收益相关系数矩阵，基准行/列加框。")
    return blocks


def _difference_section(task: AnalysisTask, metrics: dict[str, Any],
                        reg: NumberRegistry) -> list[ReportBlock]:
    q = metrics.get("quote")
    rows = {r["code"]: r for r in q["series"]} if q else {}
    table_rows: list[list[str]] = []
    for ref in cfg.PDF_REPORT_REFERENCE["values"]:
        recomputed: str
        if ref["field"] == "收盘价(元)":
            series = rows.get(ref["code"])
            recomputed = reg.amount(series["snapshot_close"], 3, "元") if series else "—"
        elif ref["field"] == "年初至今涨跌幅(%)":
            series = rows.get(ref["code"])
            recomputed = reg.pct(series["ytd_return"]) if series else "—"
        else:
            recomputed = "—"
        table_rows.append([
            ref["name"], ref["field"], reg.ratio(ref["report_value"], 2),
            recomputed, ref["note"],
        ])
    return [
        ReportBlock("heading", {"text": "5. 与集团报告数值差异说明（固定对照项）", "level": 2}),
        ReportBlock("paragraph",
            "本节对照值固定摘自集团报告 PDF 第三部分，与第 4 章选择的对标基准无关；"
            "表中 WIND 重算值取对应标的自身序列，也不随基准切换改变。"
            "集团报告正文的个别收盘价与 WIND 原始行情不一致，系统一律从 WIND 原始行情重算，"
            "不照抄报告结论，也不修改或背书原报告；差异原因标注为疑似，不做定性结论。"),
        ReportBlock("table", _table(
            ["标的", "指标", "集团报告值", "WIND 重算值", "差异说明"], table_rows)),
        ReportBlock("callout",
            "固定对照项：集团报告的年初至今跌幅与本系统重算值一致（四舍五入差异），"
            "反证其正文收盘价可能混用了其他口径（如基金净值）或存在错填。"),
    ]


def _gap_section(quality: dict[str, Any]) -> list[ReportBlock]:
    blocks = [ReportBlock("heading", {"text": "6. 数据缺口清单", "level": 2})]
    gaps = quality.get("gaps") or []
    if not gaps:
        blocks.append(ReportBlock("paragraph", "暂无已知缺口。"))
    for gap in gaps:
        blocks.append(ReportBlock("bullets", [
            f"{gap['label']}：待补。{gap['reason']}"
        ]))
    blocks.append(ReportBlock("callout",
        "以上维度本份 WIND Excel 无对应字段，报告中一律留空，不估算、不补零。"
        "后续上传相应 Excel 并注册解析器后即可扩展。"))
    return blocks


def _safe_cell(text: object, reg: NumberRegistry) -> str:
    """附加表的原始列名可能含小数，统一登记后再进报告，避免误报未登记数值。"""
    value = str(text)
    for token in re.findall(r"\d+\.\d+", value):
        reg.literal(token)
    return value


def _attachment_section(task: AnalysisTask, reg: NumberRegistry) -> list[ReportBlock]:
    ds = task.datasets.get("attachments")
    if ds is None:
        return []
    rows = []
    for sheet, frame in (getattr(ds, "tables", {}) or {}).items():
        rows.append([
            _safe_cell(sheet, reg),
            str(len(frame)),
            _safe_cell("、".join(str(c) for c in frame.columns), reg),
        ])
    return [
        ReportBlock("heading", {"text": "7. 附加上传数据（结构概览）", "level": 2}),
        ReportBlock("paragraph", "以下 Excel 未识别为专用维度，系统只做结构概览，不对其数值做任何推断。"),
        ReportBlock("table", _table(["工作表", "数据行数", "列名"], rows)),
        ReportBlock("callout",
            "需要把附加数据纳入正式分析（分派率、财务、运营、评估、指数等）时，"
            "只需为该维度注册解析器与指标提供者，管道、报告与下载链路无需改动。"),
    ]


def build_report(task: AnalysisTask, metrics: dict[str, Any], charts: dict[str, Path],
                 quality: dict[str, Any]) -> tuple[ReportDocument, dict[str, Any]]:
    """组装报告并做数字一致性校验；校验结果由调用方决定是否交付。"""
    reg = NumberRegistry()
    q = metrics.get("quote")
    source = task.source_files[0].original_name if task.source_files else "未记录"
    snapshot = q["snapshot_date"] if q else "—"
    n_series = len(q["series"]) if q else 0
    if q:
        bench_row = q.get("benchmark") or next(
            (r for r in q["series"] if r["code"] == q.get("benchmark_code")), None)
    else:
        bench_row = None
    bench_label = (f"{bench_row['name']}（{bench_row['code']}）" if bench_row
                   else (q["benchmark_code"] if q else "未选择"))

    blocks: list[ReportBlock] = [
        ReportBlock("heading", {"text": "REITs 行情分析与横向对标报告", "level": 1}),
        ReportBlock("paragraph",
            f"数据时点：{snapshot}；数据源：WIND：{source}；"
            f"标的数量：{n_series} 只；对标基准：{bench_label}；"
            f"生成时间：{task.created_at}。"),
        ReportBlock("callout",
            "本报告仅覆盖二级市场行情维度，不构成投资建议。基本面对标因源数据缺失列为待补，"
            "未做任何估算或补零。"),

        ReportBlock("heading", {"text": "1. 数据说明与口径", "level": 2}),
        ReportBlock("bullets", [
            f"输入文件：{source}；工作簿按「一表一标的」组织，逐 sheet 解析。",
            f"价格口径：{cfg.PRICE_BASIS['label']}。{cfg.PRICE_BASIS['source']}",
            f"口径依据：{cfg.PRICE_BASIS['basis']}",
            f"数据时点：{snapshot}；报告所有期末价与涨跌幅锁定该时点。",
            (f"公共窗口：{q['window']['start']} ~ {q['window']['end']}，"
             f"{q['window']['days']} 个交易日；横向排名仅在该窗口内进行。") if q else "公共窗口：—。",
            f"质量提示：阻断 {quality.get('issue_counts', {}).get('block', 0)} 条 / "
            f"告警 {quality.get('issue_counts', {}).get('warn', 0)} 条 / "
            f"说明 {quality.get('issue_counts', {}).get('info', 0)} 条。",
        ]),
        ReportBlock("paragraph", quality.get("note", "")),
    ]

    if q:
        blocks.append(ReportBlock("heading", {"text": "2. 标的概览", "level": 2}))
        blocks.append(ReportBlock("paragraph",
            f"本次对标基准为 {bench_label}；第 3、4 章与全部 8 张图表均以该标的为基准，"
            "可在页面「对标参数」中切换后重新生成。"))
        blocks.append(ReportBlock("table", _table(
            ["代码", "简称", "市场", "上市日", "期末收盘价", "期末日"],
            [[r["code"], r["name"], r["market"], r["listing_date"],
              reg.amount(r["snapshot_close"], 3, "元"), r["end_date"]]
             for r in q["series"]])))
        blocks.extend(_quote_sections(task, q, reg, charts))
        blocks.extend(_difference_section(task, metrics, reg))
    else:
        blocks.append(ReportBlock("paragraph",
            "尚未上传可识别的行情 Excel，行情对标章节留空；缺口清单如下。"))

    for dimension, builder in SECTION_BUILDERS.items():
        if dimension in metrics:
            blocks.extend(builder(task, metrics, reg, charts))

    blocks.extend(_gap_section(quality))
    blocks.extend(_attachment_section(task, reg))
    blocks.extend([
        ReportBlock("heading", {"text": "附录：解析规则与字段字典", "level": 2}),
        ReportBlock("bullets", [
            "代码提取：表头「简称['代码]」中的 6 位数字；提取失败即报错，不猜测。",
            "尾部清洗：空行与「数据来源：Wind」注释行剔除；价格非正或日期无效的行剔除并登记。",
            "成交金额：表头标注百万元，直接采用，不做换算。",
            "归一化：公共窗口首日 = 100；年化波动率 = 日收益标准差 × √252；最大回撤取峰值至谷底。",
            "缺失值：一律留白并标注待补，不插值、不补零。",
        ]),
    ])

    doc = ReportDocument(
        title="REITs 行情分析与横向对标报告",
        subject=f"{bench_label} 与同业横向对标",
        blocks=blocks,
        source_meta={
            "数据入口": "WIND Excel 上传",
            "数据来源": f"WIND：{source}"[:100],
            "标的": f"{n_series} 只消费 REIT",
            "对标基准": bench_label,
            "数据时点": snapshot,
        },
        disclaimer=app_config.DISCLAIMER,
    )
    passed, unknown = verify(doc, reg)
    return doc, {"passed": passed, "unknown": unknown, "registered": sorted(reg.tokens)}
