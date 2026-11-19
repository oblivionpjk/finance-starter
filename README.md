# 财会数据分析入门环境

一套**开箱可跑**的 Python 财会数据分析项目。面向企业财会方向，含三大报表勾稽校验、五大类财务比率、杜邦分解、可视化和 Excel 报告。演示数据与 AKShare 拉取的真实财报**采用完全相同的结构**（新浪口径「报告日 × 科目」宽表、单位元），共用一套加载与分析代码，无字段适配层。既能教学演示，也能一键分析 A 股真实财报。

## 目录结构

```
finance-starter/
├── data/
│   ├── demo/                # 演示数据（虚构公司，仅教学用）
│   │   ├── income_statement.csv    利润表
│   │   ├── balance_sheet.csv       资产负债表
│   │   └── cash_flow.csv           现金流量表（结构与真实财报相同，单位元）
│   ├── raw/                 # akshare 拉取的真实数据放这里（结构同上）
│   └── demo-backup/         # 演示数据结构改造前的备份（不入库，可删）
├── src/                     # 核心代码模块
│   ├── config.py           路径与全局配置
│   ├── io_utils.py         统一数据加载（演示/真实共用）+ 勾稽校验
│   ├── ratios.py           财务比率 + 杜邦分解
│   ├── visualize.py        图表（自动处理中文字体）
│   └── reports.py          Excel 多 sheet 报告
├── scripts/
│   ├── check_env.py        环境自检
│   ├── run_demo_analysis.py   主入口：演示数据一键分析
│   ├── run_real_analysis.py ★ 主入口：真实数据一键分析
│   └── fetch_akshare.py    拉 A 股真实财务数据
├── notebooks/              探索性分析（含真实数据接入流程）
├── output/                 运行产物（图表 + Excel 报告）
├── requirements.txt
├── .gitignore              忽略虚拟环境 / 真实数据 / 产物 / 备份
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
- `财务分析报告.xlsx` — 含概览、三大报表、五大类比率、杜邦分解、勾稽校验共 11 个 sheet
- `趋势分析.png` — 收入/净利润/现金流趋势 + 毛利率
- `能力雷达图.png` — 五维能力雷达

## 真实数据分析（一条命令出报告）

```bash
# 1. 装依赖（首次）
.venv/bin/python -m pip install akshare

# 2. 拉取某只 A 股真实财报（代码如 600519 贵州茅台、000001 平安银行）
.venv/bin/python scripts/fetch_akshare.py 600519

# 3. 一键分析，产出真实数据的图表和 Excel 报告
.venv/bin/python scripts/run_real_analysis.py 600519          # 默认近 10 年
.venv/bin/python scripts/run_real_analysis.py 600519 -n 5     # 近 5 年
.venv/bin/python scripts/run_real_analysis.py 600519 --all    # 全部年份
```

产物在 `output/` 下，带股票代码前缀（`600519_财务分析报告.xlsx`、`600519_趋势分析.png`、`600519_能力雷达图.png`），不会覆盖演示数据的结果。

演示与真实财报结构完全相同，程序对以下差异做了统一处理：
- **金额单位**：CSV 保存新浪原始金额（单位「元」），程序统一换算成「亿元」展示（比率是比值，不受单位影响）。核对时请按年份降序取最新年报——CSV 行按公告时间倒序排列，直接取末行会拿到最早年份的数据。
- **勾稽口径**：资产负债表「资产=负债+权益」严格校验；「期末现金=货币资金」在真实财报中通常不等（货币资金含受限资金），只作提示不中断。
- **行业科目差异**：一般企业与金融业（银行）科目名不同（如「股东权益」与「所有者权益(或股东权益)合计」），`io_utils.load_statement()` 加载时归一到统一口径；缺失科目补 NaN 不伪造数据。全部原始科目保留在 CSV 中可做自定义分析。

## 交互式探索（Jupyter）

```bash
.venv/bin/jupyter lab
```

真实财报接入交互分析的完整流程见 `notebooks/01_getting_started.ipynb` 第 4 节：拉取 → 用统一 `load_all(source='real', code=...)` 加载 → 复用比率模块。

## 版本管理（Git / GitHub）

项目已用 Git 做版本管理。`.gitignore` 已排除虚拟环境、`data/raw/`（真实财报）、`output/`（可重生成产物）与重建备份，这些不会进版本库。

首次提交前需配置提交身份（姓名与邮箱），然后提交：

```bash
git config user.name  "你的名字"      # 去掉 --global 只对本项目生效
git config user.email "你的邮箱"
git add .
git commit -m "初始化财会数据分析项目"
```

查看配置及其来源：`git config --list --show-origin`（可加 `--global` / `--local` 只看某级）。日常用 `git status` 看状态、`git log` 看历史。

连接 GitHub 远程仓库（SSH 方式免密推送）：

```bash
# 1. 生成密钥（若已有 ~/.ssh/id_ed25519 可跳过）
ssh-keygen -t ed25519 -C "your-email@example.com" -f ~/.ssh/id_ed25519 -N ""

# 2. 复制公钥内容，粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key
cat ~/.ssh/id_ed25519.pub

# 3. 测试连通（看到 Hi <用户名>! 即成功，首次问 yes/no 输入 yes）
ssh -T git@github.com

# 4. 在 GitHub 建一个空仓库（不要勾选 README/.gitignore/license），关联并首次推送
git remote add origin git@github.com:<用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

私钥 `id_ed25519` 绝不外传、不提交；`-u` 绑定后日常只需 `git push`。

## 指标口径

共六大类、26 项指标（含杜邦分解）：偿债 6、盈利 5、营运 3、成长 4、现金流 3、杜邦 5。比率均为无量纲比值，与金额单位（元 / 万元 / 亿元）无关。

| 类别 | 指标 | 口径 |
|---|---|---|
| 偿债 | 流动比率 | 流动资产 / 流动负债 |
| 偿债 | 速动比率 | (流动资产 − 存货) / 流动负债 |
| 偿债 | 现金比率 | 货币资金 / 流动负债 |
| 偿债 | 资产负债率 | 负债合计 / 资产总计 |
| 偿债 | 产权比率 | 负债合计 / 所有者权益 |
| 偿债 | 经营现金流/负债 | 经营活动现金流净额 / 负债合计 |
| 盈利 | 毛利率 | (营业收入 − 营业成本) / 营业收入 |
| 盈利 | 营业利润率 | 营业利润 / 营业收入 |
| 盈利 | 净利率 | 净利润 / 营业收入 |
| 盈利 | ROE | 净利润 / 所有者权益（期末值） |
| 盈利 | ROA | 净利润 / 资产总计（期末值） |
| 营运 | 应收账款周转率 | 营业收入 / 应收账款平均余额 |
| 营运 | 存货周转率 | 营业成本 / 存货平均余额 |
| 营运 | 总资产周转率 | 营业收入 / 资产总计平均余额 |
| 成长 | 营业收入增速 | 营业收入同比（首年无基数，记为 NaN） |
| 成长 | 净利润增速 | 净利润同比（首年无基数，记为 NaN） |
| 成长 | 总资产增速 | 资产总计同比（首年无基数，记为 NaN） |
| 成长 | 净资产增速 | 所有者权益同比（首年无基数，记为 NaN） |
| 现金流 | 经营现金流净额 | 经营活动产生的现金流量净额（绝对额） |
| 现金流 | 净利润现金含量 | 经营现金流净额 / 净利润 |
| 现金流 | 经营现金流/营收 | 经营现金流净额 / 营业收入 |
| 杜邦 | 净利率 | 净利润 / 营业收入 |
| 杜邦 | 总资产周转率 | 营业收入 / 资产总计 |
| 杜邦 | 权益乘数 | 资产总计 / 所有者权益 |
| 杜邦 | ROE（分解乘积） | 净利率 × 总资产周转率 × 权益乘数 |
| 杜邦 | ROE（直接计算） | 净利润 / 所有者权益 |

> 平均余额用期初期末均值；首年无期初数据则退回期末值。
> 增速类指标首年为 NaN 是正常现象。
> 杜邦分解中「分解乘积」与「直接计算」恒等，用于验证分解正确性。
> 演示数据未单列利息费用，故不计算「利息保障倍数」。

## 数据来源与免责

`data/demo/` 是**合成的虚构公司数据**，三大报表已交叉勾稽（资产=负债+权益、期末现金=货币资金），仅用于教学演示，**不代表任何真实企业**。

真实数据来自新浪财经免费接口（经 akshare），接口字段与口径可能随平台调整而变动或限流；拉取失败或科目改名时，需相应更新 `scripts/fetch_akshare.py` 与 `src/io_utils.py` 的行业科目归一规则。真实分析请自行核对科目口径，必要时与企业 ERP 导出数据交叉验证。

本项目为数据分析工具演示，不构成任何投资建议。
