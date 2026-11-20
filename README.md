# 财会数据分析入门环境

一套**开箱可跑**的 Python 财会数据分析项目。面向企业财会方向，含三大报表勾稽校验、五大类财务比率、杜邦分解、可视化和 Excel 报告。演示数据与 AKShare 拉取的真实财报**采用完全相同的结构**（新浪口径「报告日 × 科目」宽表、单位元），共用一套加载与分析代码，无字段适配层。既能教学演示，也能一键分析 A 股真实财报。

项目包含两条**相互独立**的分析链路：

| 链路 | 输入 | 输出 | 入口 |
|---|---|---|---|
| A 股财务分析 | 6 位证券代码 / 上传三大报表 | PDF 报告 + PNG 图表 + Excel（命令行） | `/` |
| REITs 行情分析与横向对标 | WIND 导出的 Excel 行情工作簿 | PDF 报告 + 8 张 PNG + 质量 JSON | `/reits` |

## 目录结构

```
finance-starter/
├── app/                     # Web 服务与领域实现
│   ├── api/                 # FastAPI 路由（server.py 启动入口、reits_analysis.py）
│   ├── adapters/            # 数据源与上传适配（ FinancialSource / register_parser ）
│   ├── domain/              # 财务数据模型、科目字典、数字白名单
│   ├── engine/              # 校验与分析引擎
│   ├── reits_analysis/      # REITs：config / model / parser / quality / metrics / charts / report / service
│   ├── reporting/           # PDF 报告渲染与确定性叙述
│   ├── rendering/           # 静态 PNG 图表
│   ├── services/            # 任务编排、证券简称解析
│   └── storage/             # 会话隔离存储（临时目录 + TTL 兜底）
├── web/                     # 前端页面：index.html/app.js（A 股）、reits.html/js/css（REITs）
├── data/
│   ├── demo/                # 演示数据（虚构公司，仅教学用）
│   │   ├── income_statement.csv    利润表
│   │   ├── balance_sheet.csv       资产负债表
│   │   └── cash_flow.csv           现金流量表（结构与真实财报相同，单位元）
│   ├── raw/                 # akshare 拉取的真实数据放这里（结构同上）
│   └── demo-backup/         # 演示数据结构改造前的备份（不入库，可删）
├── src/                     # 原始命令行分析内核（指标 / 比率 / 图表 / Excel 报告）
│   ├── config.py           路径与全局配置
│   ├── io_utils.py         统一数据加载（演示/真实共用）+ 勾稽校验
│   ├── ratios.py           财务比率 + 杜邦分解
│   ├── visualize.py        图表（自动处理中文字体）
│   └── reports.py          Excel 多 sheet 报告
├── scripts/
│   ├── check_env.py           环境自检
│   ├── run_demo_analysis.py   演示数据一键分析
│   ├── run_real_analysis.py   真实数据一键分析
│   ├── run_server.py          Web 服务启动入口
│   ├── verify_system.py       端到端自检（两条链路 + PDF/图表 + 数字一致性）
│   ├── fetch_akshare.py       拉 A 股真实财务数据
│   └── fetch_company_names.py 证券简称快照维护（刷新 / 手动增删改）
├── tests/                   # 单测：test_core.py（A 股）、test_reits_*.py（REITs）
├── docs/                    # 架构介绍、REITs 行情分析与横向对标设计方案
├── deploy/                  # Dockerfile / docker-compose.yml / nginx.conf / .env.example
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

---

## 财务分析系统（Web 界面 + PDF 报告）

在原有分析内核之上新增的服务化系统：**输入 6 位 A 股代码**或**上传三大报表**，均可生成 PDF 财务分析报告与数据分析图。两条入口共用同一套「统一财务数据模型 → 校验 → 分析引擎 → 报告 / 图表」流水线，`src/` 下的 26 项指标与杜邦分解原样复用，未改动。架构说明见 `docs/财务分析系统架构介绍.md`（第 19 节记录了本次约束覆盖与实现状态）。

### 启动

```bash
cd finance-starter
.venv/bin/python scripts/run_server.py
# 浏览器打开 http://127.0.0.1:8000
```

首次使用需安装服务层依赖：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

本机默认使用 `mock` 离线快照源（读 `data/raw/`），不联网也能跑通；页面里可切换到 `akshare` 在线源（免费接口，可能限流或变动）。环境变量 `FINANCE_SOURCE=akshare` 可改默认值。

### 使用流程

| 入口 | 步骤 |
|---|---|
| A 股代码 | 输入 6 位代码（实时显示对应公司名称）→ 选择数据源与期数 → 生成报告与图表 |
| 上传三表 | 选择 1-3 个 xlsx / xls / csv → 选择金额单位 → 确认报表角色与科目映射 → 生成报告与图表 |

- **公司名称**：代码入口在输入框、结果页标题与元信息、PDF 标题 / 数据说明 / 页脚、PDF 与图表下载文件名中显示证券简称，例如 `600519 → 贵州茅台`。名称来自 `data/company_names.json` 离线快照（沪深 A 股全表，快照日期 2026-11-19）。查不到简称时仅显示代码，不影响分析；上传入口无证券代码，不虚构名称。该快照是公开基础数据，不属于上传数据留存约束范围。
- **新股上市 / 公司更名**：优先在线全量刷新 `.venv/bin/python scripts/fetch_company_names.py`；在线源不可用时手动维护 `.venv/bin/python scripts/fetch_company_names.py --set 301999 新股股份`（更名复用同一命令），退市用 `--delete 000002`。两种方式都打印新增 / 更名 / 退出明细，写入为原子替换，运行中的服务按文件指纹自动重载，**无需重启**；在线拉取失败时本地快照保持原样。名称只影响展示，不改变指标计算，也不代表该代码的财报一定能取到。
- **代码不在本地快照中**：输入 6 位后即提示该代码是否有本地财报；若无，点击生成返回错误码 `LOCAL_SNAPSHOT_MISS` 并给出「切换到在线数据源重试」与「改用上传三大报表」两个操作按钮。非法代码段、未开放市场仍按原有错误码提示；系统不会为空缺数据生成报告或补造数值。
- **简称表缺失 ≠ 无数据**：本地简称表是某日快照，之后上市的新股或快照未刷新时会出现「简称表没有、在线有数据」。此时输入仅给中性提示「未收录于本地简称表（可能是新股或快照未更新）；可切换在线源尝试取数，或刷新简称表后重试」，**不预判在线结果**；切到在线源能取到财报时分析正常完成。
- **在线取数成功后自动补录简称表**（以 `688001` 华兴源创为例）：用在线源成功取到完整三大报表、但本地全表缺该代码时，系统自动查在线简称并**原子补写**进 `data/company_names.json`，本次报告立即用上新名称（PDF 文件名也带公司名），来源标注「于今日在线补录」。只增不覆盖（手动更名不会被冲掉）；无效代码、离线源、取数失败都不会触发；名称接口抖动时本次降级为代码显示、不阻断分析，下次重试。默认开启，用 `FINANCE_NAME_BACKFILL_ONLINE=0` 可关闭。想一次性补回全部名称仍可运行 `scripts/fetch_company_names.py` 刷新全表。
- **在线源查无此股**（如 `688999` 这类简称表没有、且在线接口也返回空的代码）：只有在线接口实际返回空数据时才返回专门的 `ONLINE_CODE_NOT_FOUND`，不会再报语义不明的 `SOURCE_UNAVAILABLE` 或提示「稍后重试」（重试无效），并给出「返回核对代码」与「改用上传三大报表」两个按钮。错误原因会同时点明「简称表未收录」与「在线接口也未返回」两个证据。若代码在简称表中但在线无数据（疑似退市），原因相应说明。有效科创板代码（如 `688981`）取数不受影响。
- 报告主格式为 **PDF**（reportlab 渲染，内嵌 matplotlib 静态图），叙述为**确定性模板**，相同数据生成完全相同的文字；
- 上传仅支持年报可比期间，季报/中期会被显式排除并在报告里说明；
- 当前仅支持沪深 A 股，市场规则在 `app/config.py` 的 `MARKET_RULES` 中表驱动配置；
- 上述 **A 股链路**不做同业对标、行业分位与估值倍数，不接语言模型，不输出投资建议；REITs 链路的横向对标是独立功能，见下节。

### 数据留存

上传的原始报表、解析结果、PDF 与图表**只存在于当前页面会话**：写入系统临时目录（`FINANCE_SESSION_ROOT`），页面关闭时前端调用销毁接口，服务端另有 TTL 定时兜底与服务退出全量清理；不写数据库、不落项目仓库、不长期留存。

### 验证

```bash
# 67 项口径回归：A 股 47 项（代码校验、单位换算、科目映射、勾稽、数字一致性、简称解析与刷新、在线查无此股、会话清理等）+ REITs 20 项（解析、指标、图表/报告、服务与下载、基准切换、固定口径标注）
.venv/bin/python -m unittest discover -s tests -v

# 端到端自检：两条链路 + PDF/图表 + 数字一致性 + 会话销毁
.venv/bin/python scripts/verify_system.py
```

数字一致性校验保证报告文本里每个带小数的数值都能追溯到分析引擎结果，出现未登记数字即中止交付。

### REITs 行情分析与横向对标（独立页面）

浏览器打开 `http://127.0.0.1:8000/reits`（或从 A 股首页右上角入口进入）。这条链路与 A 股财务分析**完全独立**，只上传 WIND 导出的行情工作簿：

| 步骤 | 说明 |
|---|---|
| 上传 WIND Excel | 支持 `.xls` / `.xlsx`，一表一标的；实测 `HPCFile.xls` 含 12 只消费 REIT、日频收盘价与成交金额 |
| 价格口径 | 系统固定标注「未复权收盘价（元）」，报告写明来源（WIND 日行情导出模板）与反算校验依据，无需人工确认；换模板时由新解析器声明口径 |
| 查看质量与缺口 | 首屏展示解析标的数、数据时点、公共窗口、异常行，以及**做不到的基本面对标清单（一律待补，不估算）** |
| 生成报告与图片 | 固定生成 `PDF 报告 + 8 张 PNG`；PDF 与每张 PNG 都可直接下载，另有解析与质量 JSON |
| 横向对标 | 默认基准为华安百联消费REIT（508002），可在「对标参数」切换；**切换后报告第 3、4 章、PDF 元数据与 8 张图的标题/脚注/高亮全部跟随新基准，下方已生成结果会自动重算刷新**；上传的工作簿不含当前基准时自动切换到首只标的 |

口径红线：所有数值从 WIND 原始行情重算，不照抄集团报告正文（其 2.33 / 4.00 与原始行情冲突，报告内单列「固定对照项」差异说明，与当前选择的基准无关）；年初至今默认用上年最后交易日基准，实测华安百联为 **-19.26%**；横向排名统一使用 12 只齐全的公共窗口。

**扩展方式**：本期只实现「日频行情」维度；后续上传其他 Excel（分派率、财务、运营、评估、指数序列）可在同一任务中累积。未识别为专用维度的文件会作为 `attachments` 附加数据集保留，PDF 第 7 节给出工作表结构与行数概览，不对其数值做任何推断。新增专项维度只需三步——在 `app/reits_analysis/config.py` 的 `DIMENSIONS` 声明维度、用 `parser.register_parser` 注册解析器、按需用 `metrics.register_provider` / `report.register_section` / `charts.register_charts` 注册指标与展示；服务层、API 和页面无需改动。

独立 API（均在 `/api/v1/reits/`）：`session`、`capabilities`、`upload`、`options`、`state`、`metrics`、`generate`、`artifacts/{key}`。产物下载只认会话内已登记的文件名，不能路径穿越；所有上传与产物仅当前会话留存。

相关单测：`tests/test_reits_parser.py`、`test_reits_metrics.py`、`test_reits_report.py`、`test_reits_service.py`。设置 `REIT_TEST_XLS=/path/to/HPCFile.xls` 可额外运行真实文件关键数值回归。口径为系统固定标注（`app/reits_analysis/config.py` 的 `PRICE_BASIS`）：来源、解释、反算依据与扩展规则一并写进报告、质量 JSON 和图表脚注，不存在“待核/定稿”两态。

### 云服务器部署预留

`deploy/` 下已备好 `Dockerfile`（内置中文字体）、`docker-compose.yml`、`nginx.conf` 与 `.env.example`：

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up -d --build
```

监听地址用 `FINANCE_HOST=0.0.0.0` 覆盖；公网部署时把 `app/api/server.py` 的 CORS 白名单从 `*` 改为具体域名，并补 HTTPS 与访问认证。

---

### 扩展点（保留系统扩展能力）

| 扩展维度 | 接口 / 注册表 | 当前实现 |
|---|---|---|
| 数据源 | `app/adapters/sources.py` 的 `FinancialSource` + `register_source` | mock 离线快照、akshare 在线 |
| 证券简称来源 | `app/services/names.py` 的 `NameResolver` + `register_name_resolver` | 本地全量快照；可选在线补充（`FINANCE_NAME_ONLINE_FALLBACK=1`） |
| 证券简称快照维护 | `scripts/fetch_company_names.py` 的 `refresh_online` / `apply_manual` | 在线全量刷新；`--set` / `--delete` 手动维护；原子写入 + 文件指纹自动重载 |
| 在线取数后自动补录 | `app/services/names.py` 的 `backfill_name` / `fetch_online_name` | 在线源取数成功后只增补写本地全表；`FINANCE_NAME_BACKFILL_ONLINE` 开关；失败静默降级 |
| 上传格式 | `app/adapters/upload.py` 的 `register_parser` | xlsx / xls / csv |
| 支持市场 | `app/config.py` 的 `MARKET_RULES` | 沪深 A 股启用，北交所 / B 股配置禁用 |
| 分析指标 | `app/domain/dictionary.py` 的 `ItemSpec` + `app/engine/analysis.py` | 26 项比率、杜邦、趋势 / 结构 / 现金流质量 |
| 叙述生成 | `app/reporting/document.py` 的 `Narrator` + `NARRATORS` | 确定性模板 |
| 报告格式 | `app/reporting/pdf.py` 的渲染器（消费 `ReportDocument`） | PDF；Excel 导出仍可用 `src/reports.py` |
| 图表渲染 | `app/rendering/charts.py` 的 `ChartSpec` | matplotlib 静态 PNG；可新增交互渲染器 |
| 存储后端 | `app/storage/session.py` 的 `StorageBackend` | 会话临时目录；可换共享存储 |
| REITs 数据维度 | `app/reits_analysis/config.py` 的 `DIMENSIONS` + `parser.register_parser` | 本期仅 `quote`（WIND 日行情）；其余维度标「待补」 |
| REITs 指标 / 章节 / 图表 | `metrics.register_provider` / `report.register_section` / `charts.register_charts` | 行情指标 8 组图与固定 PDF 章节；新维度按需注册，不动服务层 / API / 页面 |
