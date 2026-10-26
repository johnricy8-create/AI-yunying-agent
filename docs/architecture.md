# 架构说明（阶段一至五）

## 1. 目标与边界

阶段一用模拟数据跑通基础闭环：

```text
读取模拟数据 → 校验 → 指标计算 → 基线计算 → 异常识别 → 严重度排序 → Markdown 报告 → 日志
```

阶段二在此之上增加：

```text
Top-N 异常 → RAG 检索（知识库 + 历史日报）→ GLM-4.7-Flash → 结构化 JSON → 报告 AI 章节
```

AI 调用失败、限流、超时或 JSON 无效时，自动回退到规则型建议，任务本身不失败。

不包含：真实数据接入、定时调度、历史库、通知、看板、任何外部业务写操作。

设计原则：

1. 所有可精确计算的数值由 Python/Pandas 完成，大模型不参与计算。
2. 规则先于模型：异常由明确规则判定，后续模型只解释。
3. 计算层与报告层分离，报告不重新计算指标。
4. 坏行隔离，不让单行脏数据拖垮整批任务。
5. 配置外置，阈值可调，密钥只进 `.env`。
6. 保持简单：单机、无数据库、无 Web 服务、无容器。

---

## 2. 分层与模块

| 层 | 模块 | 职责 |
|---|---|---|
| 入口层 | `run.py` | 参数解析、配置加载、日志初始化、调用工作流、退出码 |
| 配置层 | `ecom_ops/config.py`、`config/*.yaml` | 配置加载、校验、路径解析 |
| 数据层 | `ecom_ops/data/` | CSV/Excel 读取、表头归一化、行级校验、模拟数据生成、数据模板 |
| 分析层 | `ecom_ops/analysis/` | 指标、基线、异常规则、严重度评分 |
| RAG 层 | `ecom_ops/rag/`、`knowledge/` | 语料切分、向量索引、余弦检索 |
| 目录分支 | `ecom_ops/catalog/` | Shopify 目录快照、价格/库存事件、目录报告；与销售日报独立 |
| 演示分支 | `ecom_ops/demo/` | 用目录 + 明确标注的模拟销售字段跑通完整日报 |
| 调度层 | `scheduler.py`、`ecom_ops/scheduler/` | 每日 09:00、文件锁、有限重试、Windows 常驻 |
| 历史层 | `ecom_ops/history/`、`data/history/` | SQLite 历史、重复异常、商品对比、建议后续观察 |
| 看板层 | `ecom_ops/dashboard/`、`tools/build_dashboard.py` | 本地静态 HTML 看板；无服务器/外部 CDN |
| 大模型层 | `ecom_ops/llm/` | GLM 客户端、提示词、JSON 校验、重试、缓存、降级 |
| 编排层 | `ecom_ops/graph/` | StateGraph、状态契约、节点实现 |
| 报告层 | `ecom_ops/report/` | Jinja2 模板、Markdown 渲染、原子写入 |
| 公共层 | `ecom_ops/utils/`、`context.py`、`exceptions.py` | 时区、文件、运行上下文、异常分类 |

---

## 3. LangGraph 工作流

```text
START
  │
  ▼
load_data         读取 CSV，表头映射，行级校验，确定统计日期
  │
  ▼
analyze_data      指标、3/5/7 自适应基线、异常规则、严重度、全局汇总
  │
  ▼
ai_recommend      RAG 检索 → GLM-4.7-Flash → 结构化 JSON；失败降级
  │
  ▼
generate_report   渲染 Markdown（规则结果 + AI 章节），写入 reports/
  │
  ▼
END
```

节点契约：

| 节点 | 输入 | 输出 |
|---|---|---|
| load_data | source_path、可选 stat_date | data（有效行）、data_quality、stat_date |
| analyze_data | data、stat_date | metrics、baselines、anomalies、global_summary |
| ai_recommend | anomalies、metrics、stat_date | ai_result（ok / failed / disabled / not_configured / skipped） |
| generate_report | 全部上游结果 | report_path、status=completed |

节点失败时记录完整堆栈并向上抛出；入口层统一返回非零退出码，不生成误导性报告。

---

## 4. 状态设计

`AgentState`（TypedDict）字段：

- `run_id`、`stat_date`、`source_path`
- `data`、`data_quality`
- `metrics`、`baselines`、`anomalies`、`global_summary`
- `ai_result`、`force_refresh_ai`、`report_path`
- `status`、`errors`

阶段一/二没有检查点/持久化需求，状态直接携带 DataFrame 与明细结果，实现简单。阶段五引入历史与断点续跑时，再迁移为“状态只放引用，明细由运行上下文/存储层持有”。

---

## 5. 数据流与关键计算

### 5.1 读取与校验

- `loader`：支持 CSV 与 `.xlsx`；CSV 按 UTF-8-SIG → UTF-8 → GBK 尝试；Excel 用 openpyxl，默认第一个工作表，可用 `--sheet` 指定；全部按字符串读取；表头归一化。
- `validator`：逐行类型转换与业务校验；错误行隔离；可选字段缺失给默认值与警告；重复键保留最后一条。
- 模板：`tools/create_data_template.py` 生成中文表头 CSV/Excel；`tools/profile_data.py` 在正式分析前做数据画像。
- 参考样本：`tools/build_reference_sample.py` 从 UCI Online Retail 生成 300 商品 × 180 天的派生样本，用于规模与数据质量测试；PV/UV/成本/库存为派生字段。
- 阈值敏感度：`tools/threshold_sensitivity.py` 在固定数据上做 OFAT + 2D 网格，不改生产配置，也不把参考样本结果当业务定案。
- 没有可用行时任务失败。

### 5.2 指标

- 今日/昨日浏览量、订单量、销售额、退款；
- 转化率分母优先 `uv > 0`，否则 `pv`；
- 浏览量变化率 `(今日 − 昨日) ÷ 昨日`，昨日为 0 或缺失则为空；
- 全局汇总使用可比商品计算整体变化率。

### 5.3 基线

对每个商品的 `pv`、`orders` 分别计算：

1. 取统计日之前最近 7 个自然日内的有效数据；
2. 计算变异系数 `CV = 标准差 ÷ 均值`；
3. `CV < 0.15` → 7 日；`0.15 ≤ CV < 0.30` → 5 日；`CV ≥ 0.30` → 3 日；
4. 有效天数不足 3 天、或窗口被缩短、或最近窗口缺数据时，标记低置信；
5. 新品首日豁免；第 2 天起参与判定并标记低置信；
6. 均值为 0 时不计算比率类规则。

### 5.4 异常规则

| 规则 | 默认条件 | 基础分 |
|---|---|---|
| 零转化 | 浏览量 ≥ 100 且订单量 = 0 | 50 |
| 浏览量骤降 | 今日 PV ≤ 基线 × 0.7，且基线 PV ≥ 50 | 30 |
| 订单量骤降 | 今日订单 ≤ 基线 × 0.7，且基线订单 ≥ 3 | 30 |
| 高浏览低转化 | 今日 PV ≥ 基线 × 1.2，今日转化率 ≤ 基线转化率 × 0.6，且今日 PV ≥ 100 | 25 |

严重度：单规则基础分 × 幅度系数（1.0–2.0），多规则累加封顶 100；≥70 高危，≥40 中危，其余低危。

库存规则默认关闭，当前库存只展示与校验。

### 5.5 报告

固定 12 个章节：数据概览、全局指标、异常 Top-N、异常详情、未入 Top-N、AI 原因分析、运营建议（AI + 规则型）、待人工确认、数据限制、执行状态、统计口径、字段说明。

AI 成功时展示摘要、事实、可能原因、建议、人工核查与引用资料；AI 失败时明确标注并回退规则型建议。

报告只渲染，不计算；指标数字来自 `analyze_data`，AI 内容来自 `ai_result`。同日重复运行覆盖同名报告。

---

## 6. 配置、日志与错误处理

### 配置

- `.env`：密钥与机器相关变量，不提交。
- `config/settings.yaml`：阈值、基线窗口、Top-N、LLM/RAG 参数、目录、日志。
- `config/fields.yaml`：字段契约与中文别名。
- 优先级：命令行 > 环境变量 > `settings.yaml`。

### 日志

- 标准库 `logging`，控制台 + 文件。
- `TimedRotatingFileHandler` 按天轮转，默认保留 30 天，UTF-8。
- 每条日志包含 run_id、节点、状态、耗时/摘要；异常堆栈只进日志。
- 不记录客户个人信息、不打印密钥或请求头。

### 错误处理

| 场景 | 行为 |
|---|---|
| 数据文件缺失/空/缺必填列 | 快速失败，退出码非零 |
| 单行数据问题 | 隔离该行，继续，报告列明 |
| 校验后无有效行 | 失败退出 |
| 统计日期无数据 | 报错并提示可用日期范围 |
| 报告写入失败 | 失败退出，记录路径与原因 |
| 未预期异常 | 记录完整堆栈，退出码非零 |

AI 调用按限流/超时/5xx 退避重试；阶段四的调度重试另行设计。

---

## 7. 阶段二：LLM 与 RAG

### 7.1 调用链

```text
Top-N 异常
  → 为每个商品构造检索 query
  → embedding-3 批量向量化
  → 本地余弦检索（知识库 + 历史日报，按日期过滤）
  → 合并高分片段，编号 K1..Kn
  → GLM-4.7-Flash（thinking disabled）
  → JSON 校验（Pydantic）
  → 成功：报告 AI 章节；失败：规则型降级
```

### 7.2 语料与索引

- 知识库：`knowledge/**/*.md`，全部索引。
- 历史日报：`reports/history/**/*.md`，只索引“异常详情（4.x）”和“运营建议（7.x）”。
- 切分：按 Markdown 标题切块，长章节按 900 字、120 字重叠再切。
- 向量：智谱 `embedding-3`，1024 维。
- 索引：`data/rag/vectors.npz` + `chunks.json` + `manifest.json`，NumPy 余弦检索。
- 重建：`tools/build_rag_index.py`；历史日报由 `tools/build_history.py` 生成。
- 检索时过滤 `date >= stat_date` 的历史日报，避免把当天/未来信息泄漏进分析。

### 7.3 提示词与输出约束

- 只允许使用输入指标和检索资料。
- 区分“数据事实”和“可能原因”；可能原因必须给置信度与证据。
- 引用资料编号；不得编造平台政策、竞品动作、价格或库存。
- 涉及改价、发布、资金、批量操作的建议必须 `needs_human=true`。
- 只输出 JSON，由 Pydantic 校验；无效输出触发重试/降级。

### 7.4 重试、缓存与降级

- 重试：`1305/429/408/5xx/超时/连接错误` 按 5s、15s 退避，默认最多 3 次。
- 缓存：按统计日期 + 输入 + 检索块 + 模型 + 提示词版本生成 key，成功后缓存到 `data/cache/ai/`。
- 降级：重试后仍失败、无 Key、JSON 无效时，`ai_result.status=failed/not_configured/disabled`，报告继续生成并使用规则型建议。
- 单次只分析严重度最高的 `max_anomalies` 个商品；检索块上限 `max_selected_chunks`，避免提示词过长。

### 7.5 安全

- 密钥只从 `.env` 的 `ZHIPU_API_KEY` 读取，不写入配置、日志或报告。
- 请求日志只记录模型、耗时、检索块数、错误类型，不记录完整提示词或密钥。

---

## 8. 商品目录/价格监控分支

独立于每日销售日报：

```text
Shopify catalog 快照 + price_changes 事件
  → 目录质量/价格带/类目/店铺统计
  → 降价/涨价/缺货/补货/新上架
  → Markdown 目录报告
```

- 入口：`tools/catalog_report.py`
- 模块：`ecom_ops/catalog/`
- 不做订单、销售额、PV/UV、转化率；不调用大模型。
- 输出：`reports/catalog/YYYY-MM-DD_catalog_report.md`
- 适用于单日目录快照；目录与事件样本可能无交集，不做强行关联。

### 目录 + 模拟销售演示

- 入口：`tools/build_shopify_sales_demo.py`
- 真实字段：商品ID、名称、店铺、类目、单价；
- 模拟字段：日期、订单、PV/UV、销售额、退款、成本、库存；
- 输出到 `data/derived/`（gitignore），只用于演示，不能用于真实阈值校准。

---

## 9. 定时执行

- 入口：`scheduler.py`
- 调度：APScheduler `BlockingScheduler` + `CronTrigger`，每天 `Asia/Shanghai` 09:00。
- 防并发：`max_instances=1` + `logs/scheduler.lock` 文件锁；锁超过 6 小时自动清理。
- 重试：失败最多 2 次，间隔 300 秒，可配置。
- 手动测试：`--run-now`；临时改时间：`--time HH:MM`。
- Windows：任务计划程序在登录/开机时启动 `scheduler.py`；关机/休眠/进程退出不会执行，需要唤醒与“错过任务后尽快启动”设置。

---

## 10. 历史与建议追踪

- 入口：`tools/history_report.py`
- 历史库：SQLite `data/history/ops_history.db`
- 写入：`run.py` / `scheduler.py` 成功生成日报后自动写入；同日覆盖。
- 表：`runs`、`product_metrics`、`recommendations`。
- 查询：重复异常商品、商品最近 N 天指标、建议之后的订单/转化率变化。
- 效果分类：改善 / 恶化 / 持平 / 无后续数据；只是观察，不是因果。
- 历史库不保存客户个人信息。

---

## 11. 可视化看板

- 入口：`tools/build_dashboard.py`
- 输出：`reports/dashboard/index.html`
- 数据：历史库 + 可选目录/价格事件。
- 内容：每日趋势、最新异常、重复异常、建议观察、目录价格事件。
- 技术：Jinja2 静态 HTML + 内联 CSS；无服务器、无外部 CDN、不调用大模型。

---

## 12. 扩展点

| 阶段 | 扩展方式 |
|---|---|
| 阶段三 | Excel 分支、模板、数据画像已完成；等待真实样例校准阈值 |
| 阶段四 | 新增 `scheduler.py` 与 `ecom_ops/scheduler/`；复用工作流 |
| 阶段五 | 新增 `ecom_ops/history/`；状态改为引用式；可评估其他嵌入模型 |

BGE-M3 属于嵌入模型，当前默认方案不使用；阶段五如需历史语义检索，可在 `embedding-3` 与 BGE-M3 之间做对比。
