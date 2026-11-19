"""生成多 sheet 的 Excel 财务分析报告。"""
import pandas as pd

from . import config
from .io_utils import check_balance_identity, check_cash_ties, item


def _fmt_sheet(writer, df: pd.DataFrame, sheet: str, is_pct: bool = False):
    """把 DataFrame 写入指定 sheet，自动列宽。"""
    df.to_excel(writer, sheet_name=sheet)
    ws = writer.sheets[sheet]
    ws.column_dimensions["A"].width = 24
    for col in ws.columns:
        letter = col[0].column_letter
        ws.column_dimensions[letter].width = max(12, ws.column_dimensions[letter].width or 12)
        if is_pct:
            for cell in col[1:]:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = "0.0%"


def build_report(inc, bs, cf, ratio_summary, out_path=None, amount_unit="万元") -> str:
    """汇总三大报表 + 比率 + 勾稽校验，写入一个 Excel 文件。

    amount_unit 只影响概览页的列名，调用方需先把金额数据换算到该单位。
    """
    out_path = out_path or config.REPORT_XLSX

    # 概览：核心指标一览
    prof = ratio_summary["盈利能力"]
    overview = pd.DataFrame({
        f"营业收入({amount_unit})": item(inc, "营业收入"),
        f"净利润({amount_unit})": item(inc, "净利润"),
        f"经营现金流({amount_unit})": item(cf, "经营活动产生的现金流量净额"),
        "毛利率": prof["毛利率"],
        "净利率": prof["净利率"],
        "ROE": prof["ROE(净资产收益率)"],
    }).T
    overview.index.name = "指标"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        _fmt_sheet(writer, overview, "概览")
        _fmt_sheet(writer, inc, "利润表")
        _fmt_sheet(writer, bs, "资产负债表")
        _fmt_sheet(writer, cf, "现金流量表")

        pct_sheets = {"盈利能力", "成长能力"}
        for name, df in ratio_summary.items():
            _fmt_sheet(writer, df, name, is_pct=name in pct_sheets)

        check = pd.concat([
            check_balance_identity(bs).assign(校验项="资产=负债+权益"),
            check_cash_ties(cf, bs).rename(columns={
                "期末现金(现金流量表)": "项目A", "货币资金(资产负债表)": "项目B",
                "差额(应为0)": "差额(应为0)", "是否一致": "是否平衡",
            }).assign(校验项="期末现金=货币资金"),
        ])
        _fmt_sheet(writer, check, "勾稽校验")

    return str(out_path)
