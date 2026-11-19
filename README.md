# 财会数据分析入门环境

一套**开箱可跑**的 Python 财会数据分析项目。面向企业财会方向，含三大报表勾稽校验、五大类财务比率、杜邦分解、可视化和 Excel 报告。

## 目录结构

```
finance-starter/
├── data/
│   ├── demo/                # 演示数据（虚构公司，仅教学用）
│   │   ├── income_statement.csv    利润表
│   │   ├── balance_sheet.csv       资产负债表
│   │   └── cash_flow.csv           现金流量表
│   └── raw/                 # akshare 拉取的真实数据放这里
├── src/                     # 核心代码模块
│   ├── config.py           路径与全局配置
│   ├── io_utils.py         数据加载 + 勾稽校验
│   ├── ratios.py           财务比率 + 杜邦分解
│   ├── visualize.py        图表（自动处理中文字体）
│   └── reports.py          Excel 多 sheet 报告
├── scripts/
│   ├── check_env.py        环境自检
│   ├── run_demo_analysis.py ★ 主入口：一键跑完整流程
│   └── fetch_akshare.py    可选：拉 A 股真实财务数据
├── notebooks/              探索性分析
├── output/                 运行产物（图表 + Excel 报告）
├── requirements.txt
└── README.md
```

## 快速开始

项目已建好虚拟环境 `.venv`（隔离，不污染系统 Python）。在项目根目录执行：

```bash
cd finance-starter

# 1. 自检环境
.venv/bin/python scripts/check_env.py

# 2. 一键跑完整分析流程
.venv/bin/python scripts/run_demo_analysis.py
```

跑完在 `output/` 下得到：
- `财务分析报告.xlsx` — 含概览、三大报表、六类比率、勾稽校验共 11 个 sheet
- `趋势分析.png` — 收入/净利润/现金流趋势 + 毛利率
- `能力雷达图.png` — 五维能力雷达

## 按需扩展

```bash
# 装拉真实数据的库（可选）
.venv/bin/pip install akshare

# 拉某只 A 股真实财报（代码如 600519 贵州茅台）
.venv/bin/python scripts/fetch_akshare.py 600519

# 用 Jupyter 交互式探索
.venv/bin/jupyter lab
```

## 指标口径

| 类别 | 指标 | 口径 |
|---|---|---|
| 偿债 | 流动比率 | 流动资产 / 流动负债 |
| 偿债 | 速动比率 | (流动资产 − 存货) / 流动负债 |
| 偿债 | 资产负债率 | 负债合计 / 资产总计 |
| 盈利 | 毛利率 | (营业收入 − 营业成本) / 营业收入 |
| 盈利 | 净利率 | 净利润 / 营业收入 |
| 盈利 | ROE | 净利润 / 所有者权益合计（期末值） |
| 营运 | 应收账款周转率 | 营业收入 / 应收账款平均余额 |
| 营运 | 存货周转率 | 营业成本 / 存货平均余额 |
| 成长 | 营收/净利增速 | 同比（首年无基数，记为 NaN） |
| 现金流 | 净利润现金含量 | 经营现金流净额 / 净利润 |
| 杜邦 | ROE | 净利率 × 总资产周转率 × 权益乘数 |

> 平均余额用期初期末均值；首年无期初数据则退回期末值。
> 增速类指标首年为 NaN 是正常现象。

## 数据来源与免责

`data/demo/` 是**合成的虚构公司数据**，三大报表已交叉勾稽（资产=负债+权益、期末现金=货币资金），仅用于教学演示，**不代表任何真实企业**。真实分析请通过 akshare 或企业 ERP 导出数据，并自行核对口径。

本项目为数据分析工具演示，不构成任何投资建议。
