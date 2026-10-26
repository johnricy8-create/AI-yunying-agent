# Shopify 目录 + 模拟销售演示

## 1. 目的

你提供的 Shopify 数据只有商品目录和价格/库存事件，没有订单、销售额、PV/UV。为了让完整日报 Agent 能直接跑起来，我用**真实商品目录 + 明确标注的模拟销售/流量字段**生成了一份演示数据。

> 这份演示数据只用于看完整效果，**不能用于真实业务阈值校准**，也不能把模拟销售当成真实销售。

## 2. 数据来源

- 真实部分：`catalog_sample_500.csv`
  - 500 个变体、494 个商品、154 个店铺；
  - 商品名称、店铺、类目、单价、可用状态来自目录快照；
  - 快照日期 2026-08-01。
- 模拟部分：
  - 日期：2026-06-02 ~ 2026-07-31，共 60 天；
  - 订单量、PV、UV、销售额、退款、成本、库存；
  - 按商品价格、类目、可用状态生成，带周末波动和随机噪声；
  - 最后一天故意埋入少量零转化、PV 骤降、订单骤降、高浏览低转化样本，便于验证规则。

目录样本许可为 **CC BY-NC 4.0（非商业评估）**，商用前需确认完整数据集的商业许可。

## 3. 生成与运行

```powershell
# 1) 生成演示销售数据
.venv\Scripts\python.exe tools\build_shopify_sales_demo.py `
  --catalog "D:\olist电商数据\shopify-products-dataset-sample\data\catalog_sample_500.csv" `
  --days 60 --end-date 2026-07-31

# 2) 数据画像
.venv\Scripts\python.exe tools\profile_data.py --data data\derived\shopify_catalog_sales_demo.csv

# 3) 生成日报（不调用大模型，稳定出报告）
.venv\Scripts\python.exe run.py `
  --data data\derived\shopify_catalog_sales_demo.csv `
  --date 2026-07-31 --no-ai --report-dir reports\shopify_demo
```

输出：

- `data/derived/shopify_catalog_sales_demo.csv`（已 gitignore，可随时重建）
- `data/derived/manifest.json`（真实/模拟字段清单，已 gitignore）
- `reports/shopify_demo/2026-07-31_daily_report.md`

## 4. 本次结果

| 项目 | 结果 |
|---|---:|
| 行数 | 30,000 |
| 商品数 | 500 |
| 天数 | 60 |
| 有效/隔离行 | 30,000 / 0 |
| 总浏览量 | 64,888 |
| 总订单量 | 1,480 |
| 总销售额 | ¥70,726.69 |
| 整体转化率 | 2.85% |
| 浏览量变化率 | -0.67% |
| 异常商品 | 98 |

日报 Top 异常主要是零转化和订单骤降，商品名称/店铺/类目来自你的目录，例如：

- `cookiecutterlady.com` 的 cookie cutter 商品；
- `www.wholesaleaccessorymarket.com` 的 T 恤；
- `shopifysweetshapesco.com` 的 cookie cutter；
- `www.confluencerunning.com` 的跑鞋。

## 5. 边界说明

- 订单、PV/UV、销售额、退款、成本、库存是模拟值，不是 Shopify 真实经营数据；
- 不能用这份演示数据决定真实阈值；
- 真实日报需要 Shopify Orders + Analytics + Inventory 导出；
- 免费 GLM-4.7-Flash 高峰期可能超时，降级为规则型报告；本次演示最终使用规则型报告；
- 商品目录样本与价格事件样本没有交集，目录报告和销售演示是两条独立线。

## 6. 文件位置

| 文件 | 说明 |
|---|---|
| `ecom_ops/demo/shopify_sales.py` | 模拟销售面板生成 |
| `tools/build_shopify_sales_demo.py` | 命令行入口 |
| `tests/test_shopify_sales.py` | 演示数据校验 |
| `data/derived/` | 生成的演示数据（gitignore） |
| `reports/shopify_demo/` | 演示日报（gitignore） |
