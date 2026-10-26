# 数据评估：Shopify Products Catalog Sample

评估日期：2026-10-26  
数据路径：`D:\olist电商数据\shopify-products-dataset-sample`  
结论：**可用于商品目录/价格/库存监控，但不能直接用于当前每日销售运营日报，也不能用于阈值校准。**

## 1. 文件与规模

| 文件 | 行数 | 说明 |
|---|---:|---|
| `data/catalog_sample_500.csv` | 500 | 商品变体快照，21 个字段 |
| `data/price_changes_sample.csv` | 198 | 价格/库存变更事件，9 个字段 |

### 目录快照

- 500 个变体（variant），494 个商品（product），154 个店铺；
- 只有一个快照日期：`2026-08-01`（`fetched_at` 不同，但都是同一天）；
- 价格中位数 28.66，P90 179.91，最大 73,331.42；2 行价格为 0；
- 可用 443 行，不可用 57 行；
- 空值：`product_type` 178 行、`tags` 55 行、`sku` 208 行；
- 类目分布：other 161、apparel 137、food_beverage 99、shoes 27、home_garden 26 等。

### 价格/库存事件

- 198 条事件，全部发生在 `2026-08-03`；
- 44 个店铺、95 个商品、197 个变体；
- 事件类型：`out_of_stock` 86、`price_drop` 70、`price_increase` 36、`new_listing` 4、`restocked` 2；
- 与目录快照样本的店铺/变体**交集为 0**（两份文件是各自抽样，不能直接按变体关联）。

## 2. 与当前字段契约的覆盖情况

| 字段 | 状态 | 说明 |
|---|---|---|
| `stat_date` | ⚠️ 部分 | 只有 `fetched_at` 一个快照日，没有连续日期 |
| `product_id` | ✅ | 可用 `variant_id` 或 `product_id` |
| `product_name` | ✅ | `title` + `variant_title` |
| `product_desc` | ⚠️ 部分 | 无商品详情 HTML；只能用 `tags`/`product_type` 拼描述 |
| `shop` | ✅ | `store_domain` / `store_name` |
| `platform` | ✅ | 固定为 `Shopify` |
| `category` | ✅ | `niche` 或 `product_type` |
| `price` | ✅ | `price`，但有 2 行为 0 |
| `cost` | ❌ | 没有成本字段 |
| `stock` | ⚠️ 部分 | 只有 `available` 布尔值，没有库存数量 |
| `pv` | ❌ | 没有浏览量 |
| `uv` | ❌ | 没有访客数 |
| `orders` | ❌ | 没有订单量 |
| `sales_amount` | ❌ | 没有销售额 |
| `refund_amount` | ❌ | 没有退款 |

### 结论

当前 Agent 的核心链路是：

```text
商品 × 日期 → 浏览量/订单/销售额/转化率 → 基线 → 异常 → 报告
```

这份数据缺少**日期序列、订单、销售额、流量、退款、成本、库存数量**，无法计算：

- 今日/昨日浏览量、订单量、销售额；
- 转化率、浏览量变化率；
- 3/5/7 日基线；
- 零转化、浏览量骤降、订单骤降、高浏览低转化。

如果强行用随机数补齐这些字段，得到的只是**另一份模拟数据**，不能作为“真实业务阈值校准”的依据。

## 3. 数据质量观察

- 只有 1 个目录快照，无法观察时间趋势；
- 价格/库存事件也集中在 1 天，事件类型有参考价值，但不构成连续时间序列；
- 目录样本与价格事件样本没有交集，不能直接把事件关联到目录行；
- 2 行价格为 0，按当前校验规则会被隔离；
- `product_type`、`tags`、`sku` 的空值率较高；
- 数据许可为 **CC BY-NC 4.0**（非商业评估），商用需查看完整数据集的商业许可。

## 4. 这份数据适合做什么

1. **商品目录监控**：价格、可用性、变体数量、类目/店铺分布；
2. **价格与库存事件监控**：涨价、降价、缺货、补货、新上架；
3. **商品主数据补充**：用 variant/title/vendor/type/price 作为商品维度，和外部销售数据关联（需要 SKU 或 variant 对齐）；
4. **选品/竞品目录分析**：店铺、类目、价格带、变体结构。

不适合：每日销售日报、转化率分析、流量异常、订单异常、退款分析、库存周转。

## 5. 下一步可选路径

> 当前选择：**路径 B 已实现**。目录/价格监控分支位于 `ecom_ops/catalog/`，入口为 `tools/catalog_report.py`，输出 `reports/catalog/`。另外用目录 + 模拟销售字段生成了完整日报演示，详见 `docs/shopify_sales_demo.md`。每日销售日报的真实阈值校准仍需路径 A 的订单/流量数据。


### 路径 A：补充 Shopify 订单与流量数据（推荐，继续当前 Agent）

需要导出：

- Shopify Orders：订单日期、订单号、SKU/variant、数量、单价、折扣、运费、退款、财务状态；
- Shopify Analytics：按日期/商品/变体的 sessions、visitors、product views、add-to-carts、orders、conversion；
- 库存：按 variant 的可用库存数量（不是布尔值）。

拿到后可以生成当前字段契约所需的 CSV/Excel，再跑阶段三校准。

### 路径 B：新增“商品目录/价格监控”分支

用这份数据单独做一个轻量报告：

- 涨价/降价 Top 商品；
- 缺货/补货事件；
- 价格带与类目分布；
- 店铺/类目异常。

这是与“每日销售运营”并列的另一个场景，需要单独确认范围，不混入现有日报。

### 路径 C：作为商品主数据补充

将 `variant_id`/`sku`/`title`/`vendor`/`product_type`/`price` 作为商品维度，与未来的订单/流量数据关联；但销售、流量、库存数量仍需另外提供。

## 6. 建议

- **不要**用这份目录数据直接跑 `run.py` 或 `threshold_sensitivity.py`，会因缺少必填字段失败；
- 先用 `tools/profile_data.py` 检查未来拿到的订单/流量 CSV/Excel；
- 如果要做目录/价格监控，请明确选择路径 B；
- 如果要继续每日销售日报，请优先补充路径 A 的订单与流量导出。
