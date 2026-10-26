# 电商运营 Agent

面向销售 Excel 模板、办公资料、电子资料等数字商品的每日运营分析 Agent。

当前完成 **阶段一**：读取模拟销售数据 → 校验 → 计算指标 → 自适应基线 → 识别异常 → 严重度排序 → 生成 Markdown 日报 → 记录日志。

> 阶段一**不调用任何大模型、不访问网络、不操作真实电商账户**。AI 章节为显式占位，报告中不会出现伪造的模型结论。

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

# 4) 运行
.venv\Scripts\python.exe run.py
```

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

# 指定数据文件
.venv\Scripts\python.exe run.py --data data\mock\sales_mock.csv

# 只展示 Top 5 异常
.venv\Scripts\python.exe run.py --top-n 5

# 指定报告/日志目录
.venv\Scripts\python.exe run.py --report-dir reports --log-dir logs
```

不传 `--date` 时，默认统计日期为运行日的前一天（北京时间 D-1）；若该日期不在数据中，会回退到最新可用日期并在日志中告警。

---

## 3. 输出

| 输出 | 路径 |
|---|---|
| 日报 | `reports/YYYY-MM-DD_daily_report.md` |
| 日志 | `logs/ecom_ops.log`（按天轮转，默认保留 30 天） |
| 模拟数据 | `data/mock/sales_mock.csv` |
| 真实数据（阶段三） | `data/raw/`（已 gitignore） |

报告默认展示异常 Top 10 的详情，其余异常只统计数量与类型。同日重复运行会覆盖同名报告，run_id 记录在报告和日志中。

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
│  ├─ report/                   # Jinja2 报告渲染与模板
│  └─ utils/                    # 日期、时区、文件工具
├─ tools/generate_mock_data.py  # 模拟数据生成器
├─ data/
│  ├─ mock/                     # 模拟数据
│  └─ raw/                      # 真实数据（阶段三）
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

当前测试覆盖：

- 指标计算与昨日对比、UV/PV 分母、缺失昨日、昨日为 0；
- 3/5/7 自适应基线、历史不足、新品首日/第二天、均值为 0；
- 四类核心异常的触发边界、最小样本、低置信、库存规则关闭；
- 数据校验：缺字段、负值、订单大于浏览、退款大于销售、重复行、未来日期、警告；
- LangGraph 端到端、报告 12 个章节、同日覆盖、日志 run_id、缺失文件快速失败。

---

## 6. 配置说明

- `config/settings.yaml`：业务阈值、基线窗口、Top-N、日志保留、目录。
- `config/fields.yaml`：字段定义、必填/类型、中文表头别名。
- `.env`：只放密钥与机器相关环境变量，**不提交到 Git**。阶段一不需要任何密钥。

配置优先级：命令行参数 > 环境变量 > `settings.yaml` 默认值。

---

## 7. 阶段一已知限制

- 转化率分母优先 UV，缺失时回退浏览量；当前模拟数据没有独立 UV。
- 基线使用 3/5/7 日均值，无法处理周内规律与季节性；开学季等正常波动可能被误判。
- 缺失日期不插值，昨日为 0 或缺失时浏览量变化率显示“—”。
- 销售额为已扣退款、不含税净额；退款金额不再二次扣减。
- 库存仅展示与校验，不参与异常判定。
- 阈值是阶段一默认值，尚未用真实数据校准，可能偏敏感或偏保守。
- 阶段一不接大模型、不做定时调度、不读真实 Excel/CSV 业务数据。

---

## 8. 后续阶段

| 阶段 | 内容 |
|---|---|
| 阶段二 | 对话模型接入、结构化建议、超时/限流/重试、失败降级、证据约束 |
| 阶段三 | 真实 CSV/Excel、字段映射、数据质量、缺失日期处理 |
| 阶段四 | APScheduler 每日 09:00、并发防护、Windows 任务计划程序 |
| 阶段五 | 历史记录、日期对比、建议有效性、可选 RAG（BGE-M3）、通知与看板 |

BGE-M3 属于嵌入模型，阶段一、阶段二核心流程均不使用；仅在阶段五评估历史报告语义检索时再引入。

---

## 9. 文档

- `docs/architecture.md`：架构、模块、工作流、状态契约
- `docs/field_dictionary.md`：字段字典、校验规则、数据质量代码
- `docs/decisions.md`：需求口径、架构决策、技术栈决策
- `docs/runbook.md`：运行、排错、配置调整、数据替换

## 10. 安全

- `.env` 已被 `.gitignore` 排除；不要把密钥写入 `settings.yaml`、README 或日志。
- 报告与日志不写入客户个人信息。
- 阶段一没有任何外部写操作。
- 如密钥曾在聊天/截图中出现，请立即到服务商控制台轮换。
