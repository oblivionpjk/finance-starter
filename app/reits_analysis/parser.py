"""WIND Excel 解析层：文件 → 按维度的数据集。

确定性规则，不做运行时猜测：
  * 一表一标的；表头 `<简称>['<6位代码>]` 提取代码；
  * 尾部「数据来源：Wind」与空行剔除；
  * 日期升序、价格 > 0、同日去重；异常行只告警并剔除，不静默补数。

扩展：register_parser(dim_key, fn) 注册新维度解析器，detect_dimension 负责识别文件归属。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app import config as app_config
from app.domain.model import QualityIssue
from app.errors import AnalysisError
from app.reits_analysis import config as cfg
from app.reits_analysis.model import GenericDataset, QuoteDataset, ReitSeries, SourceFile


def _extract_code(header: object) -> str | None:
    m = re.search(cfg.CODE_HEADER_REGEX, str(header))
    return m.group(1) if m else None


def _is_source_note(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text == "" or text.lower() == "nat" or any(k in text for k in cfg.SOURCE_NOTE_KEYWORDS)


def _looks_like_quote(cells: list[object] | tuple[object, ...]) -> bool:
    """只识别表头结构，不关心标的名；用于整份文件归属判定。"""
    if len(cells) < 3:
        return False
    names = [str(x).strip() for x in cells]
    return ("日期" in names[0]
            and any(_extract_code(c) for c in names[1:])
            and any(("成交" in c or "金额" in c) for c in names[2:]))


def detect_dimension(path: Path) -> str | None:
    """探测文件属于哪个已声明维度；无法识别返回 None（不报错，交给上层提示）。"""
    if path.suffix.lower() not in cfg.ALLOWED_SUFFIXES:
        raise AnalysisError("REIT_SUFFIX_UNSUPPORTED",
                            f"不支持的文件格式：{path.suffix}",
                            f"仅支持 {', '.join(cfg.ALLOWED_SUFFIXES)}")
    if path.stat().st_size > cfg.MAX_UPLOAD_BYTES:
        raise AnalysisError("REIT_FILE_TOO_LARGE", "文件超过上传上限")
    try:
        book = pd.ExcelFile(path)
    except Exception as exc:
        raise AnalysisError("REIT_FILE_UNREADABLE",
                            f"工作簿无法读取：{path.name}",
                            f"{type(exc).__name__}: {exc}") from exc
    try:
        for sheet in book.sheet_names[:cfg.MAX_SHEETS]:
            head = pd.read_excel(book, sheet_name=sheet, header=None, nrows=1)
            if not head.empty and _looks_like_quote(head.iloc[0].tolist()):
                return "quote"
    except Exception as exc:
        raise AnalysisError("REIT_FILE_UNREADABLE",
                            f"表头读取失败：{path.name}", str(exc)) from exc
    finally:
        book.close()
    return None


def _market_of(code: str) -> str:
    for market, prefixes in cfg.REIT_MARKET_PREFIXES:
        if code.startswith(prefixes):
            return market
    return "OTHER"


def _parse_quote_sheet(sheet: str, frame: pd.DataFrame, source_file: str) -> tuple[ReitSeries | None, list[QualityIssue]]:
    issues: list[QualityIssue] = []
    headers = [str(x) for x in frame.columns.tolist()]
    if len(headers) < 3:
        issues.append(QualityIssue("warn", "SHEET_COLUMNS_SHORT",
                                   f"工作表 {sheet} 少于 3 列，已跳过", str(len(headers))))
        return None, issues
    if not _looks_like_quote(headers):
        issues.append(QualityIssue("info", "SHEET_NOT_QUOTE",
                                   f"工作表 {sheet} 不符合行情表结构，已跳过"))
        return None, issues

    code = _extract_code(headers[1])
    if code is None:
        issues.append(QualityIssue("block", "CODE_EXTRACT_FAILED",
                                   f"工作表 {sheet} 表头无法提取 6 位代码"))
        raise AnalysisError("REIT_CODE_EXTRACT_FAILED",
                            f"工作表 {sheet} 的代码提取失败", headers[1])
    name = sheet.strip() or headers[1].split("['")[0].strip()
    market = _market_of(code)
    if market == "OTHER":
        issues.append(QualityIssue("warn", "UNKNOWN_MARKET",
                                   f"{name}（{code}）代码前缀未识别，市场标记为 OTHER", sheet))

    # frame 已用 header=0 读入，首行即第一条数据；不要再次跳过
    data = frame.iloc[:, :3].copy()
    data.columns = ["date", "price", "amount"]
    note_mask = data["date"].apply(_is_source_note)
    data = data[~note_mask]

    dates = pd.to_datetime(data["date"], errors="coerce")
    price = pd.to_numeric(data["price"], errors="coerce")
    amount = pd.to_numeric(data["amount"], errors="coerce")

    bad_date = int(dates.isna().sum())
    if bad_date:
        issues.append(QualityIssue("warn", "INVALID_DATE_ROWS",
                                   f"{name} 有 {bad_date} 行日期无法解析，已剔除", sheet))
    bad_price = int(((price <= 0) | price.isna()).sum())
    if bad_price:
        issues.append(QualityIssue("warn", "INVALID_PRICE_ROWS",
                                   f"{name} 有 {bad_price} 行价格非正或缺失，已剔除", sheet))
    bad_amount = int(amount.isna().sum())
    if bad_amount:
        issues.append(QualityIssue("warn", "INVALID_AMOUNT_ROWS",
                                   f"{name} 有 {bad_amount} 行成交额缺失，按 0 计入并标记", sheet))

    clean = pd.DataFrame({
        "date": dates, "price": price, "amount": amount.fillna(0.0),
    }).dropna(subset=["date", "price"])
    clean = clean[clean["price"] > 0]

    dup = int(clean["date"].duplicated().sum())
    if dup:
        issues.append(QualityIssue("warn", "DUPLICATE_DATES",
                                   f"{name} 有 {dup} 个重复交易日，保留最后一条", sheet))
        clean = clean.drop_duplicates(subset=["date"], keep="last")
    if len(clean) > 1 and not clean["date"].is_monotonic_increasing:
        issues.append(QualityIssue("warn", "UNSORTED_DATES",
                                   f"{name} 原始日期非升序，已按日期重排", sheet))
    clean = clean.sort_values("date")

    if clean.empty:
        issues.append(QualityIssue("warn", "EMPTY_SERIES",
                                   f"{name} 清洗后无有效行情，已跳过", sheet))
        return None, issues

    spike = False
    if len(clean) > 3:
        tail = clean["amount"].iloc[1:11]
        median = float(tail.median()) if len(tail) else 0.0
        spike = bool(median > 0 and clean["amount"].iloc[0] > cfg.LISTING_DAY_AMOUNT_SPIKE_RATIO * median)
    if spike:
        issues.append(QualityIssue("info", "LISTING_DAY_AMOUNT_SPIKE",
                                   f"{name} 上市首日成交额显著放大，已保留并标记 listing_day", sheet))

    series = ReitSeries(
        code=code, name=name, market=market, sheet=sheet,
        dates=[d.strftime("%Y-%m-%d") for d in clean["date"]],
        close=[float(v) for v in clean["price"]],
        amount_million=[float(v) for v in clean["amount"]],
        is_listing_day=[i == 0 for i in range(len(clean))],
    )
    return series, issues


def parse_quote(path: Path, source_file: SourceFile) -> QuoteDataset:
    """解析 WIND 行情工作簿（一表一标的）。"""
    try:
        book = pd.ExcelFile(path)
    except Exception as exc:
        raise AnalysisError("REIT_FILE_UNREADABLE", f"无法读取 {path.name}", str(exc)) from exc

    series: dict[str, ReitSeries] = {}
    issues: list[QualityIssue] = []
    try:
        for sheet in book.sheet_names[:cfg.MAX_SHEETS]:
            frame = pd.read_excel(book, sheet_name=sheet, header=0)
            parsed, sheet_issues = _parse_quote_sheet(sheet, frame, source_file.original_name)
            issues.extend(sheet_issues)
            if parsed is not None:
                if parsed.code in series:
                    issues.append(QualityIssue("warn", "DUPLICATE_CODE",
                                               f"代码 {parsed.code} 出现在多个工作表，保留 {parsed.sheet}",
                                               sheet))
                else:
                    series[parsed.code] = parsed
    finally:
        book.close()

    if not series:
        raise AnalysisError("REIT_NO_QUOTE_SHEET",
                            "未找到可识别的行情工作表",
                            "期望每个 sheet 含：日期 / 简称['代码] / 成交金额(百万元)['代码]")

    starts = [s.listing_date for s in series.values() if s.dates]
    ends = [s.end_date for s in series.values() if s.dates]
    common_start, common_end = max(starts), min(ends)
    # 公共窗口交易日数：取所有标的日期交集
    common_days = len(set.intersection(*(set(s.dates) for s in series.values())))
    if common_days < cfg.MIN_COMMON_DAYS:
        issues.append(QualityIssue("warn", "SHORT_COMMON_WINDOW",
                                   f"公共窗口仅 {common_days} 个交易日，横向对标样本偏短",
                                   f"{common_start} ~ {common_end}"))
    issues.append(QualityIssue("info", "PRICE_SEMANTICS_FIXED",
                               f"价格口径按 WIND 行情模板固定标注为{cfg.PRICE_BASIS['label']}；"
                               "依据与来源见报告第 1 节"))

    return QuoteDataset(
        source_file=source_file.original_name,
        series=series,
        snapshot_date=max(ends),
        common_start=common_start,
        common_end=common_end,
        quality=issues,
    )


def parse_generic(path: Path, dimension: str, source_file: SourceFile) -> GenericDataset:
    """预留解析器：保留上传表结构，待对应维度的分析器注册后启用。"""
    try:
        book = pd.ExcelFile(path)
    except Exception as exc:
        raise AnalysisError("REIT_FILE_UNREADABLE", f"无法读取 {path.name}", str(exc)) from exc
    tables: dict[str, Any] = {}
    issues: list[QualityIssue] = []
    try:
        for sheet in book.sheet_names[:cfg.MAX_SHEETS]:
            frame = pd.read_excel(book, sheet_name=sheet, header=0)
            tables[sheet] = frame
    finally:
        book.close()
    spec = cfg.DIMENSIONS.get(dimension)
    note = spec.pending_reason if spec else "维度未声明，仅保留原始表待扩展"
    issues.append(QualityIssue("info", "DIMENSION_PENDING", note, dimension))
    return GenericDataset(dimension=dimension, source_file=source_file.original_name,
                          tables=tables, quality=issues, note=note)


PARSERS: dict[str, Callable[[Path, SourceFile], Any]] = {}


def register_parser(dimension: str, fn: Callable[[Path, SourceFile], Any]) -> None:
    """扩展入口：注册新维度解析器。"""
    PARSERS[dimension] = fn


register_parser("quote", parse_quote)


def parse_uploaded(path: Path, source_file: SourceFile) -> tuple[str | None, Any | None]:
    """识别 → 解析。未识别返回 (None, None)；已声明但无解析器则返回通用数据集。"""
    dimension = detect_dimension(path)
    if dimension is None:
        return None, None
    fn = PARSERS.get(dimension)
    if fn is None:
        return dimension, parse_generic(path, dimension, source_file)
    return dimension, fn(path, source_file)
