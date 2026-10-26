# 运行手册（阶段一至三）

## 1. 环境准备

```powershell
# 创建项目内虚拟环境
uv venv --python 3.12 .venv

# 安装锁定依赖
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

验证：

```powershell
.venv\Scripts\python.exe --version
# 预期：Python 3.12.15
```

> 不要直接使用系统 `python`：本机它指向 Microsoft Store 占位程序，会提示“Python was not found”。

---

## 2. 生成模拟数据

```powershell
.venv\Scripts\python.exe tools\generate_mock_data.py
```

预期：

```text
已生成模拟数据: data\mock\sales_mock.csv
行数: 2776，商品数: 200，日期数: 15
日期范围: 2026-10-12 ~ 2099-01-01
```

说明：15 个日期中包含 1 条固定的未来日期异常样本（2099-01-01），用于验证校验器；有效业务日期为 2026-10-12 ~ 2026-10-25。

自定义参数：

```powershell
.venv\Scripts\python.exe tools\generate_mock_data.py --products 200 --days 14 --seed 42
.venv\Scripts\python.exe tools\generate_mock_data.py --end-date 2026-10-25
```

### 2.1 生成真实数据模板

```powershell
.venv\Scripts\python.exe tools\create_data_template.py
```

输出：

- `data/templates/sales_data_template.csv`：UTF-8 with BOM，中文表头。
- `data/templates/sales_data_template.xlsx`：含“销售数据”和“字段说明”两个工作表。

模板表头是中文别名，加载器会通过 `config/fields.yaml` 自动映射；不要随意改表头，除非同步增加别名。

### 2.2 真实数据画像

拿到真实 CSV/Excel 后，先做数据画像，不生成报告、不调用大模型：

```powershell
.venv\Scripts\python.exe tools\profile_data.py --data data\raw\销售数据.csv
.venv\Scripts\python.exe tools\profile_data.py --data data\raw\销售数据.xlsx --sheet 销售数据 --top 10
```

画像会输出：表头映射、空值、重复/错误/警告、日期覆盖、缺日商品、数值分位数、转化率分布，以及阈值校准提示。

> 画像输出可能包含真实业务数据，不要直接公开粘贴。

### 2.3 公开参考样本

仓库附带 UCI Online Retail 派生参考样本：

```powershell
.venv\Scripts\python.exe tools\profile_data.py --data data\reference\online_retail_reference.csv
.venv\Scripts\python.exe run.py --data data\reference\online_retail_reference.csv --no-ai --report-dir reports\reference_test
```

- 300 商品 × 180 天，54,000 行；
- PV/UV、成本、库存、店铺/平台/类目为派生字段，不是真实业务数据；
- 用于验证规模、数据质量、Excel/CSV 接入与阈值敏感度；
- 详细说明见 `data/reference/README.md`。

参考样本画像显示：54,000 行全部有效、0 隔离行、521 行警告；统计日 2011-11-27 触发 119 个异常，说明 v0.1 在该分布下偏敏感，真实数据校准是必要的。

### 2.4 阈值敏感度工程测试

```powershell
.venv\Scripts\python.exe tools\threshold_sensitivity.py
```

默认使用参考样本最后 30 天、固定基线配置，只改变异常阈值，输出：

- `docs/threshold_sensitivity_reference.md`：Markdown 摘要；
- `reports/threshold_sensitivity/ofat.csv`：单参数敏感度；
- `reports/threshold_sensitivity/grid.csv`：二维网格；
- `reports/threshold_sensitivity/profiles.csv`：工程档位对比。

参考样本结果：v0.1 日均异常 98.8 个、异常率 32.9%、高危日均 43.03；工程严格档约 36 个/天、12.0%。这只能说明阈值方向，**不修改 v0.1，也不作为业务定案**。

### 2.5 商品目录/价格监控（独立分支）

你提供的 Shopify 目录样本可以生成独立的目录报告：

```powershell
.venv\Scripts\python.exe tools\catalog_report.py `
  --catalog "D:\olist电商数据\shopify-products-dataset-sample\data\catalog_sample_500.csv" `
  --changes "D:\olist电商数据\shopify-products-dataset-sample\data\price_changes_sample.csv"
```

输出：`reports/catalog/2026-08-01_catalog_report.md`

内容包括：目录规模、价格带、类目/店铺分布、零价格、缺货、降价/涨价、新上架、待人工确认、数据限制。

注意：

- 该分支不计算订单、销售额、PV/UV，也不调用大模型；
- 目录样本与价格事件样本可能没有变体交集，不能直接关联；
- 数据许可为 CC BY-NC 4.0，商用前需确认商业许可。

### 2.6 完整日报演示（真实目录 + 模拟销售）

```powershell
# 生成 60 天模拟销售面板
.venv\Scripts\python.exe tools\build_shopify_sales_demo.py `
  --catalog "D:\olist电商数据\shopify-products-dataset-sample\data\catalog_sample_500.csv" `
  --days 60 --end-date 2026-07-31

# 跑完整日报
.venv\Scripts\python.exe run.py `
  --data data\derived\shopify_catalog_sales_demo.csv `
  --date 2026-07-31 --no-ai --report-dir reports\shopify_demo
```

- 真实字段：商品ID、名称、店铺、类目、单价；
- 模拟字段：订单、PV/UV、销售额、退款、成本、库存；
- 只用于看完整 Agent 效果，**不能用于真实阈值校准**；
- 详见 `docs/shopify_sales_demo.md`。

### 2.7 一键演示

```powershell
# 目录报告 + 目录/模拟销售日报
.venv\Scripts\python.exe tools\run_demo.py

# 尝试 AI（免费模型可能 1305/超时，失败自动降级）
.venv\Scripts\python.exe tools\run_demo.py --with-ai

# 强制重建模拟销售数据
.venv\Scripts\python.exe tools\run_demo.py --rebuild
```

日报会把数据来源说明写入报告顶部；演示数据的销售/流量/成本/库存会明确标注为模拟值。

---

## 3. 运行

### 3.1 首次准备 RAG

```powershell
# 可选：生成历史日报语料
.venv\Scripts\python.exe tools\build_history.py

# 构建/重建向量索引
.venv\Scripts\python.exe tools\build_rag_index.py
```

预期：

```text
语料块数: 141（knowledge=29, history=112）
索引已保存: data\rag
向量矩阵: (141, 1024), 模型: embedding-3
```

### 3.2 运行日报

```powershell
.venv\Scripts\python.exe run.py
```

预期输出（AI 成功时）：

```text
运营分析运行完成
run_id       : auto-20261026-...
统计日期     : 2026-10-25
参与商品数   : 196
异常商品数   : 34
有效/隔离行  : 2770 / 6
AI 状态      : ok
RAG 检索块   : 12 / 索引 141
报告路径     : D:\ai运营agent\reports\2026-10-25_daily_report.md
```

如果智谱免费模型返回 `1305`，AI 状态会显示 `failed`，报告仍会生成，并在第 6 节说明已回退规则型建议。

报告位置：`reports/2026-10-25_daily_report.md`。
日志位置：`logs/ecom_ops.log`。

### 指定日期/数据/Top-N

```powershell
.venv\Scripts\python.exe run.py --date 2026-10-24
.venv\Scripts\python.exe run.py --data data\mock\sales_mock.csv --date 2026-10-25
.venv\Scripts\python.exe run.py --top-n 5
.venv\Scripts\python.exe run.py --report-dir reports --log-dir logs
.venv\Scripts\python.exe run.py --no-ai          # 只出规则型报告
.venv\Scripts\python.exe run.py --no-rag         # 不启用检索
.venv\Scripts\python.exe run.py --refresh-ai     # 忽略 AI 缓存
.venv\Scripts\python.exe run.py --data data\raw\销售数据.xlsx --sheet 销售数据
```

不传 `--date` 时默认 D-1（北京时间）；如果数据中不存在 D-1，会自动回退到最新可用日期，并在日志中给出 warning。

### 3.3 定时任务（阶段四）

```powershell
# 常驻进程，每天北京时间 09:00 执行
.venv\Scripts\python.exe scheduler.py

# 立即执行一次，便于测试
.venv\Scripts\python.exe scheduler.py --run-now --no-ai --data data\derived\shopify_catalog_sales_demo.csv --date 2026-07-31

# 临时改成 09:05 触发（不用等到第二天）
.venv\Scripts\python.exe scheduler.py --time 09:05

# 定时任务不调用 AI
.venv\Scripts\python.exe scheduler.py --no-ai
```

机制：

- APScheduler `CronTrigger`，时区 `Asia/Shanghai`；
- `max_instances=1` + `logs/scheduler.lock` 文件锁，防止定时任务和手动运行并发；
- 锁文件超过 6 小时视为上次进程异常退出，会自动清理；
- 失败最多重试 2 次，每次间隔 300 秒（可在 `settings.yaml` 的 `scheduler` 段调整）；
- 每次执行都走完整工作流，日志记录 run_id、状态、报告路径。

Windows 任务计划程序建议：

1. 创建任务，触发器选“登录时”或“计算机启动时”；
2. 操作：启动程序
   - 程序：`D:\ai运营agent\.venv\Scripts\python.exe`
   - 参数：`D:\ai运营agent\scheduler.py`
   - 起始于：`D:\ai运营agent`
3. 勾选“不管用户是否登录都要运行”（需要保存凭据）；
4. 勾选“如果错过计划开始时间，请尽快启动任务”；
5. 如需休眠中唤醒，勾选“唤醒计算机运行此任务”。

注意：电脑关机、休眠、程序退出时定时任务不会执行；任务计划程序只负责把常驻进程拉起来，真正 09:00 触发由 APScheduler 负责。

---

## 4. 测试

```powershell
.venv\Scripts\python.exe -m pytest
```

预期：

```text
70 passed
```

测试覆盖指标、基线、异常边界、数据校验、RAG 切分/检索、AI JSON 解析/重试/缓存/降级、端到端工作流、报告章节、同日覆盖、日志 run_id、缺失文件快速失败。

---

## 5. 配置调整

### 修改阈值

编辑 `config/settings.yaml` 的 `anomaly` 段。例如把订单骤降阈值从 0.7 放宽到 0.6：

```yaml
anomaly:
  order_drop_ratio: 0.60
```

YAML 对缩进敏感，修改后先运行 `pytest` 或 `run.py` 验证。

### 修改基线窗口

编辑 `config/settings.yaml` 的 `baseline` 段：

```yaml
baseline:
  windows: [3, 5, 7]
  cv_low: 0.15
  cv_high: 0.30
  min_valid_days: 3
```

`lookback_days` 不能小于最大窗口；否则配置加载会报错。

### 修改 Top-N

命令行 `--top-n 5` 优先于 `settings.yaml` 的 `report.top_n`。

### 修改字段映射

阶段三接入真实数据时，在 `config/fields.yaml` 的 `aliases` 中增加中文表头映射，不要改分析代码。

### 密钥与 AI/RAG 配置

阶段二把智谱密钥写入项目根目录 `.env`：

```text
ZHIPU_API_KEY=...
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4.7-flash
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=1024
```

`.env` 已被 `.gitignore` 排除；不要把密钥写进 `settings.yaml`、README、日志或任务计划程序参数。

AI 与 RAG 参数在 `config/settings.yaml` 的 `llm` / `rag` 段：

- `llm.max_attempts`：总尝试次数，默认 3。
- `llm.retry_backoff_seconds`：退避间隔，默认 `[5, 15]`。
- `llm.max_anomalies`：送模型的异常数量，默认 10。
- `llm.cache_enabled`：是否缓存成功结果，默认 true。
- `rag.top_k`：每个商品检索块数，默认 4。
- `rag.max_selected_chunks`：合并后最多保留块数，默认 12。
- `rag.max_context_chars`：提示词中检索文本上限，默认 4000。

语料或嵌入模型变化后，重新运行 `tools/build_rag_index.py`。

---

## 6. 数据替换

当前仅支持 CSV。可以把任意符合字段字典的 CSV 传给 `--data`：

```powershell
# CSV
.venv\Scripts\python.exe run.py --data D:\data\sales_2026-10-25.csv --date 2026-10-25

# Excel（默认第一个工作表）
.venv\Scripts\python.exe run.py --data D:\data\sales_2026-10-25.xlsx --date 2026-10-25

# Excel 指定工作表
.venv\Scripts\python.exe run.py --data D:\data\sales_2026-10-25.xlsx --sheet 销售数据 --date 2026-10-25
```

要求：

- 必须有 `stat_date`、`product_id`、`product_name`、`price`、`stock`、`pv`、`orders`、`sales_amount`；
- 中文表头可通过 `config/fields.yaml` 的 `aliases` 映射；
- CSV 编码优先 UTF-8 with BOM，也兼容 UTF-8/GBK；
- Excel 支持 `.xlsx`；旧版 `.xls` 请另存为 `.xlsx`；
- 先用 `tools/profile_data.py` 做画像，再跑分析；
- 不要假设已有真实电商平台 API。

---

## 7. 常见报错

| 现象 | 原因 | 处理 |
|---|---|---|
| `Python was not found` | 系统 `python` 是 Store 占位 | 使用 `.venv\Scripts\python.exe` |
| `无法加载文件 ... Activate.ps1` | PowerShell 执行策略限制 | 不激活，直接调用 `.venv\Scripts\python.exe` |
| `ModuleNotFoundError` | 依赖未安装到当前环境 | `uv pip install -r requirements.txt` |
| `ZoneInfoNotFoundError` | 缺少 tzdata | 安装 `tzdata`（已在 requirements.txt） |
| 控制台中文乱码 | 终端编码与 UTF-8 不一致 | 报告和日志文件本身是 UTF-8；可换 Windows Terminal 或 `chcp 65001` |
| `数据文件不存在` | 路径错误或未生成模拟数据 | 运行 `tools/generate_mock_data.py`，或检查 `--data` |
| `旧版 .xls 不支持` | 文件是旧版 Excel | 用 Excel 另存为 `.xlsx` |
| `Excel 工作表不存在` | `--sheet` 名称不对 | 用 Excel 查看工作表名，或先运行 `profile_data.py` |
| `Excel 工作表没有数据行` | 选错工作表或表为空 | 检查 `--sheet` 与模板 |
| `统计日期 ... 没有可用数据` | 指定日期不在数据中 | 查看日志中的可用日期范围，换 `--date` |
| `数据校验后没有可用行` | 数据质量问题太多 | 查看报告/日志中的数据质量摘要，修正源数据 |
| `报告写入失败` | 文件被占用/无权限 | 关闭打开的 Excel/Markdown 预览，或换 `--report-dir` |
| YAML 解析错误 | 缩进/冒号写错 | 按 `settings.yaml` 原有缩进修正 |
| `pytest` 命令找不到 | 未激活虚拟环境 | 使用 `.venv\Scripts\python.exe -m pytest` |
| `1305 该模型当前访问量过大` | 智谱免费模型平台过载 | 等待后重跑；可临时用 `--no-ai` 出规则型报告 |
| `未找到 RAG 索引` | 未构建索引或索引目录被删 | 运行 `tools/build_rag_index.py` |
| AI 状态 `failed` / `not_configured` | 限流、网络、JSON 无效或缺少 Key | 查看报告第 6 节与日志；补 Key 或稍后 `--refresh-ai` 重跑 |
| AI 结果一直不更新 | 命中缓存 | 加 `--refresh-ai` 强制重新调用 |

---

## 8. 验收清单

- [ ] `run.py` 能生成 `reports/YYYY-MM-DD_daily_report.md`
- [ ] 报告包含 12 个章节
- [ ] 指标、基线、异常规则与手算/测试一致
- [ ] 坏行被隔离并在报告中统计
- [ ] 日志含 run_id、节点、状态、报告路径
- [ ] 同日重复运行覆盖报告，不重复追加
- [ ] CSV 与 `.xlsx` 均可读取，Excel 可用 `--sheet` 指定工作表
- [ ] `tools/create_data_template.py` 能生成 CSV/Excel 模板
- [ ] `tools/profile_data.py` 能输出表头、空值、质量、日期覆盖、数值分布
- [ ] `tools/catalog_report.py` 能生成目录/价格监控报告
- [ ] `tools/build_shopify_sales_demo.py` 能生成可跑通的模拟销售演示数据
- [ ] `tools/run_demo.py` 能一键生成目录报告和演示日报
- [ ] 日报顶部有数据来源说明（演示数据会标注模拟字段）
- [ ] `scheduler.py --run-now` 能执行一次并释放锁
- [ ] `scheduler.py` 能常驻并按 09:00 触发
- [ ] 两次执行不会并发（文件锁生效）
- [ ] RAG 索引可构建，检索结果带来源与相似度
- [ ] AI 成功时报告包含摘要、事实、原因、建议、引用
- [ ] AI 失败时报告仍生成，并明确标注规则型降级
- [ ] 没有外部业务写操作
- [ ] `pytest` 全部通过
- [ ] `.env` 未被提交，报告/日志/真实数据/索引/缓存均被 gitignore

---

## 9. 后续阶段

- 阶段三：CSV/Excel、模板、数据画像已完成；等待脱敏真实样例后校准阈值。
- 阶段四：已完成 APScheduler 每日 09:00、文件锁、有限重试、Windows 任务计划程序说明。
- 阶段五：历史记录、建议有效性、通知与看板；可评估其他嵌入模型。

当前不提供定时任务；电脑关机、休眠或程序退出时不会自动执行，这是阶段四要解决的问题。
