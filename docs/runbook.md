# 运行手册（阶段一）

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

---

## 3. 运行

```powershell
.venv\Scripts\python.exe run.py
```

预期输出：

```text
阶段一运行完成
run_id       : auto-20261026-...
统计日期     : 2026-10-25
参与商品数   : 196
异常商品数   : 34
有效/隔离行  : 2770 / 6
报告路径     : D:\ai运营agent\reports\2026-10-25_daily_report.md
```

报告位置：`reports/2026-10-25_daily_report.md`。
日志位置：`logs/ecom_ops.log`。

### 指定日期/数据/Top-N

```powershell
.venv\Scripts\python.exe run.py --date 2026-10-24
.venv\Scripts\python.exe run.py --data data\mock\sales_mock.csv --date 2026-10-25
.venv\Scripts\python.exe run.py --top-n 5
.venv\Scripts\python.exe run.py --report-dir reports --log-dir logs
```

不传 `--date` 时默认 D-1（北京时间）；如果数据中不存在 D-1，会自动回退到最新可用日期，并在日志中给出 warning。

---

## 4. 测试

```powershell
.venv\Scripts\python.exe -m pytest
```

预期：

```text
38 passed
```

测试覆盖指标、基线、异常边界、数据校验、端到端工作流、报告章节、同日覆盖、日志 run_id、缺失文件快速失败。

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

### 密钥

阶段一不需要任何密钥。阶段二再把对话模型密钥写入项目根目录 `.env`：

```text
SILICONFLOW_API_KEY=...
SILICONFLOW_BASE_URL=...
LLM_MODEL=...
```

`.env` 已被 `.gitignore` 排除；不要把密钥写进 `settings.yaml`、README、日志或任务计划程序参数。

---

## 6. 数据替换

阶段一仅支持 CSV。可以把任意符合字段字典的 CSV 传给 `--data`：

```powershell
.venv\Scripts\python.exe run.py --data D:\data\sales_2026-10-25.csv --date 2026-10-25
```

要求：

- 必须有 `stat_date`、`product_id`、`product_name`、`price`、`stock`、`pv`、`orders`、`sales_amount`；
- 中文表头可通过 `config/fields.yaml` 的 `aliases` 映射；
- 编码优先 UTF-8 with BOM，也兼容 UTF-8/GBK；
- Excel（`.xlsx/.xls`）阶段一不支持，会明确提示留到阶段三；
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
| `统计日期 ... 没有可用数据` | 指定日期不在数据中 | 查看日志中的可用日期范围，换 `--date` |
| `数据校验后没有可用行` | 数据质量问题太多 | 查看报告/日志中的数据质量摘要，修正源数据 |
| `报告写入失败` | 文件被占用/无权限 | 关闭打开的 Excel/Markdown 预览，或换 `--report-dir` |
| YAML 解析错误 | 缩进/冒号写错 | 按 `settings.yaml` 原有缩进修正 |
| `pytest` 命令找不到 | 未激活虚拟环境 | 使用 `.venv\Scripts\python.exe -m pytest` |

---

## 8. 阶段一验收清单

- [ ] `run.py` 能生成 `reports/YYYY-MM-DD_daily_report.md`
- [ ] 报告包含 12 个章节
- [ ] 指标、基线、异常规则与手算/测试一致
- [ ] 坏行被隔离并在报告中统计
- [ ] 日志含 run_id、节点、状态、报告路径
- [ ] 同日重复运行覆盖报告，不重复追加
- [ ] 无网络请求、无 LLM 调用、无外部写操作
- [ ] `pytest` 全部通过
- [ ] `.env` 未被提交，报告/日志/真实数据均被 gitignore

---

## 9. 阶段一之后

- 阶段二：接入对话模型，替换 `ai_recommend`，增加超时/限流/重试与失败降级。
- 阶段三：真实 CSV/Excel、字段映射、数据质量。
- 阶段四：APScheduler 每日 09:00、并发防护、Windows 任务计划程序。
- 阶段五：历史记录、建议有效性、可选 RAG（BGE-M3）、通知与看板。

阶段一不提供定时任务；电脑关机、休眠或程序退出时不会自动执行，这是阶段四要解决的问题。
