# 电商运营 Agent

面向销售 Excel 模板、办公资料、电子资料等数字商品的每日运营分析 Agent。

当前完成 **阶段一 + 阶段二**，并已具备**阶段三数据接入基础设施**：

1. 读取模拟/真实销售数据（CSV、Excel）→ 校验 → 计算指标 → 自适应基线 → 识别异常 → 严重度排序 → 生成 Markdown 日报 → 记录日志。
2. 对 Top-N 异常，通过 **RAG（知识库 + 历史日报）** 检索相关经验，调用 **智谱 GLM-4.7-Flash** 生成结构化原因分析与建议；模型限流、超时或输出无效时自动回退到规则型报告。
3. 提供 CSV/Excel 数据模板、Excel 工作表选择、数据画像工具，用于真实数据接入前的检查和阈值评估。

> 阶段二只做分析与建议，**不自动改价、不自动发布、不操作真实电商账户**。所有涉及业务动作的建议都标记为需人工确认。

---

## 1. 环境

- Windows
- Python 3.12.15（由 uv 管理，项目内 `.venv`）
- uv 0.13.5
- 依赖版本见 `requirements.txt`，全部精确锁定

> 本机系统级 `python` 指向 Microsoft Store 占位程序，直接执行会失败。请使用项目虚拟环境，或直接调用 `.venv\Scripts\python.exe`。

---

## 2. 快速开始

```powershell
# 1) 创建虚拟环境（已创建可跳过）
uv venv --python 3.12 .venv

# 2) 安装依赖
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# 3) 生成模拟数据（已生成可跳过）
.venv\Scripts\python.exe tools\generate_mock_data.py

# 3.1) 生成真实数据导入模板（CSV + Excel）
.venv\Scripts\python.exe tools\create_data_template.py

# 3.2) 有真实数据时，先做数据画像（不调用大模型）
.venv\Scripts\python.exe tools\profile_data.py --data data\raw\销售数据.xlsx --sheet 销售数据

# 3.3) 阈值敏感度工程测试（默认用公开参考样本，不改线上配置）
.venv\Scripts\python.exe tools\threshold_sensitivity.py

# 4) 生成历史日报语料（可选，用于 RAG 历史案例）
.venv\Scripts\python.exe tools\build_history.py

# 5) 构建 RAG 索引（首次或语料变化后）
.venv\Scripts\python.exe tools\build_rag_index.py

# 6) 运行（需要 .env 中的 ZHIPU_API_KEY；没有 Key 会自动降级）
.venv\Scripts\python.exe run.py
```

`.env` 配置样例见 `.env.example`，复制为 `.env` 后填入 `ZHIPU_API_KEY`。`.env` 已被 `.gitignore` 排除。

也可以先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

如果 PowerShell 禁止执行激活脚本，直接用 `.venv\Scripts\python.exe` 即可，不影响运行。

### 常用参数

```powershell
# 指定统计日期
.venv\Scripts\python.exe run.py --date 2026-10-25

# 指定数据文件（CSV 或 .xlsx）
.venv\Scripts\python.exe run.py --data data\mock\sales_mock.csv

# Excel 指定工作表
.venv\Scripts\python.exe run.py --data data\raw\销售数据.xlsx --sheet 销售数据

# 只展示 Top 5 异常
.venv\Scripts\python.exe run.py --top-n 5

# 指定报告/日志目录
.venv\Scripts\python.exe run.py --report-dir reports --log-dir logs

# 本次不调用大模型（只出规则型报告）
.venv\Scripts\python.exe run.py --no-ai

# 忽略 AI 结果缓存，强制重新调用
.venv\Scripts\python.exe run.py --refresh-ai

# 本次不启用 RAG 检索
.venv\Scripts\python.exe run.py --no-rag
```

不传 `--date` 时，默认统计日期为运行日的前一天（北京时间 D-1）；若该日期不在数据中，会回退到最新可用日期并在日志中告警。

---

## 3. 输出

| 输出 | 路径 |
|---|---|
| 日报 | `reports/YYYY-MM-DD_daily_report.md` |
| 历史日报语料 | `reports/history/`（已 gitignore，可重建） |
| RAG 索引 | `data/rag/`（已 gitignore，可重建） |
| AI 缓存 | `data/cache/ai/`（已 gitignore） |
| 日志 | `logs/ecom_ops.log`（按天轮转，默认保留 30 天） |
| 运营知识库 | `knowledge/`（需业务方审核） |
| 模拟数据 | `data/mock/sales_mock.csv` |
| 数据模板 | `data/templates/sales_data_template.csv` / `.xlsx` |
| 公开参考样本 | `data/reference/online_retail_reference.csv`（300 商品 × 180 天，派生字段） |
| 真实数据（阶段三） | `data/raw/`（已 gitignore） |

报告默认展示异常 Top 10 的详情，其余异常只统计数量与类型。同日重复运行会覆盖同名报告，run_id 记录在报告和日志中。

> 公开参考样本来自 UCI Online Retail，仅用于规模、数据质量和阈值敏感度测试。PV/UV、成本、库存、店铺/平台/类目为派生字段，不代表真实业务；详见 `data/reference/README.md`。

---

## 4. 项目结构

```text
├─ run.py                       # 手动运行入口
├─ requirements.txt             # 精确锁定依赖
├─ .python-version              # 3.12
├─ .env.example                 # 配置样例（不含密钥）
├─ config/
│  ├─ settings.yaml             # 阈值、基线、Top-N、目录、日志
│  └─ fields.yaml               # 字段契约与中文表头别名
├─ ecom_ops/
│  ├─ config.py                 # 配置加载与校验
│  ├─ context.py                # 单次运行上下文
│  ├─ data/                     # 读取、校验、模拟数据、字段契约
│  ├─ analysis/                 # 指标、基线、异常、严重度
│  ├─ graph/                    # LangGraph 状态、节点、工作流
│  ├─ llm/                      # GLM 客户端、提示词、结构化输出、AI 服务
│  ├─ rag/                      # 语料切分、向量索引、检索器
│  ├─ report/                   # Jinja2 报告渲染与模板
│  └─ utils/                    # 日期、时区、文件工具
├─ knowledge/                   # 运营知识库（示例 SOP，需业务方审核）
├─ tools/
│  ├─ generate_mock_data.py     # 模拟数据生成器
│  ├─ create_data_template.py   # 生成 CSV/Excel 数据模板
│  ├─ profile_data.py           # 真实数据画像与质量检查
│  ├─ threshold_sensitivity.py  # 阈值敏感度工程测试
│  ├─ build_reference_sample.py # 构建 UCI 参考样本
│  ├─ build_history.py          # 生成历史日报语料
│  └─ build_rag_index.py        # 构建本地向量索引
├─ data/
│  ├─ mock/                     # 模拟数据
│  ├─ raw/                      # 真实数据（gitignore）
│  ├─ templates/                # 数据模板（CSV/Excel）
│  ├─ reference/                # UCI 公开参考样本（派生字段说明见 README）
│  ├─ rag/                      # 向量索引（gitignore）
│  └─ cache/                    # AI 缓存（gitignore）
├─ reports/                     # 日报输出
├─ logs/                        # 运行日志
├─ tests/                       # pytest 测试
└─ docs/                        # 架构、字段、决策、运行手册
```

---

## 5. 测试

```powershell
.venv\Scripts\python.exe -m pytest
```

当前共 **60 个测试**，覆盖：

- 指标计算与昨日对比、UV/PV 分母、缺失昨日、昨日为 0；
- 3/5/7 自适应基线、历史不足、新品首日/第二天、均值为 0；
- 四类核心异常的触发边界、最小样本、低置信、库存规则关闭；
- 数据校验：缺字段、负值、订单大于浏览、重复行、未来日期、警告；退款大于净销售额不被误判；
- RAG：Markdown 切分、知识库/历史日报过滤、向量检索、日期过滤、索引持久化；
- AI：JSON 解析容错、未知来源过滤、限流重试、缓存命中、失败降级、方向一致性检查；
- Excel：中文表头映射、工作表选择、旧版 .xls 拒绝、模板生成、Excel 端到端；
- LangGraph 端到端、报告 12 个章节、AI 报告渲染、同日覆盖、日志 run_id、缺失文件快速失败。

---

## 6. 配置说明

- `config/settings.yaml`：业务阈值、基线窗口、Top-N、LLM/RAG 参数、日志、目录。
- `config/fields.yaml`：字段定义、必填/类型、中文表头别名。
- `.env`：只放密钥与机器相关环境变量，**不提交到 Git**。阶段二需要 `ZHIPU_API_KEY`；没有 Key 时自动降级为规则型报告。
- `knowledge/`：运营知识库，当前为示例 SOP，需业务方审核后替换。

配置优先级：命令行参数 > 环境变量 > `settings.yaml` 默认值。

---

## 7. 已知限制

- 转化率分母优先 UV，缺失时回退浏览量；当前模拟数据没有独立 UV。
- 基线使用 3/5/7 日均值，无法处理周内规律与季节性；开学季等正常波动可能被误判。
- 缺失日期不插值，昨日为 0 或缺失时浏览量变化率显示“—”。
- 销售额为已扣退款、不含税净额；退款金额不再二次扣减。
- 库存仅展示与校验，不参与异常判定。
- 阈值 v0.1 保持不变，尚未用真实数据校准，可能偏敏感或偏保守。
- GLM-4.7-Flash 免费模型可能返回 `1305 平台过载`；已实现退避重试与规则降级，但高峰期可能拿不到 AI 分析。
- 当前知识库为示例 SOP，不是真实平台政策；RAG 检索结果可能不完整。
- Excel 支持 `.xlsx`；旧版 `.xls` 需另存为 `.xlsx`。默认读取第一个工作表，可用 `--sheet` 指定。
- 不假设已有真实电商平台 API；阶段三只处理本地 CSV/Excel。
- 不做定时调度；阶段四处理。

---

## 8. 后续阶段

| 阶段 | 内容 |
|---|---|
| 阶段二 | 已完成：GLM-4.7-Flash、RAG、结构化建议、限流重试、失败降级、缓存 |
| 阶段三 | 基础设施已就绪：CSV/Excel、模板、数据画像、字段映射；等待脱敏真实样例后校准阈值 |
| 阶段四 | APScheduler 每日 09:00、并发防护、Windows 任务计划程序 |
| 阶段五 | 历史记录、日期对比、建议有效性、通知与看板；可选其他嵌入模型 |

RAG 当前使用智谱 `embedding-3`（1024 维），与 GLM 共用一把 Key；BGE-M3 不再作为默认方案。

---

## 9. 文档

- `docs/architecture.md`：架构、模块、工作流、状态契约
- `docs/field_dictionary.md`：字段字典、校验规则、数据质量代码
- `docs/decisions.md`：需求口径、架构决策、技术栈决策
- `docs/runbook.md`：运行、排错、配置调整、数据替换
- `docs/threshold_sensitivity_reference.md`：参考样本阈值敏感度工程测试结果（不作为业务定案）

## 10. 安全

- `.env` 已被 `.gitignore` 排除；不要把密钥写入 `settings.yaml`、README 或日志。
- 报告与日志不写入客户个人信息。
- 阶段二只调用模型推理接口，没有任何外部业务写操作。
- 如密钥曾在聊天/截图中出现，请立即到智谱控制台轮换，并更新本地 `.env`。
