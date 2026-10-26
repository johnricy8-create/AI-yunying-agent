# 公开参考样本：UCI Online Retail

本目录用于阶段三的数据接入、数据质量、规模和阈值敏感度测试，**不是你的真实业务数据**。

## 1. 来源

- 数据集：UCI Machine Learning Repository — Online Retail
- 页面：https://archive.ics.uci.edu/dataset/352/online+retail
- 原始数据：2010-12-01 至 2011-12-09，541,909 行，4,070 个商品，25,900 张发票
- 内容：英国在线礼品零售商的真实交易数据
- 使用前请遵循 UCI 数据集页面的许可与引用要求

原始文件约 23MB，放在 `data/reference/raw/Online Retail.xlsx`，已被 `.gitignore` 排除，不提交到 Git。

## 2. 派生样本

文件：`online_retail_reference.csv`（UTF-8 with BOM，约 8MB）

| 项目 | 值 |
|---|---:|
| 时间窗口 | 2011-06-01 ~ 2011-11-27 |
| 商品数 | 300 |
| 天数 | 180 |
| 行数 | 54,000（完整商品 × 日期面板） |
| 总销售额 | 约 309 万元（样本内） |
| 总订单量 | 约 10.3 万（按商品/日去重发票） |

生成命令：

```powershell
.venv\Scripts\python.exe tools\build_reference_sample.py --products 300 --days 180
```

## 3. 字段真实性说明

### 来自源数据的字段

- `stat_date`：交易日期
- `product_id`：StockCode
- `product_name` / `product_desc`：Description（截断到 200 字）
- `orders`：当日包含该商品的去重发票数
- `sales_amount`：正向交易销售额减退款，净额
- `refund_amount`：负向数量交易的退款金额（按当日毛销售额封顶）

### 派生/模拟字段（不是源数据真实值）

| 字段 | 生成方式 |
|---|---|
| price | 当日正向交易加权平均单价；无销售日取商品级均价 |
| cost | 商品级模拟成本，约为售价的 55%–70% |
| stock | 基于平均订单量模拟初始库存与补货，**不是真实库存** |
| pv | 基于商品平均订单量和模拟转化率生成，**不是真实流量** |
| uv | 约等于 PV 的 72%–85%，并保证不小于订单量 |
| shop | 固定为 `UCI Online Retail` |
| platform | 固定为 `UK Online Retail` |
| category | 根据商品描述关键词映射为家居/餐厨/灯饰等 |

因此，**不要用本样本推断真实业务结论**；它只用于验证：
- 大数据量下的读取、校验、指标、报告性能；
- 缺失日期、重复、退款、价格波动等数据质量；
- 阈值 v0.1 在真实分布下是否过于敏感。

## 4. 已知观察

用 `tools/profile_data.py` 检查本样本：

- 54,000 行全部有效，0 个隔离行；
- 521 行带警告（299 行成本高于当日售价，223 行有订单但净销售额为 0）；
- 180 天完整面板，无缺日；
- 转化率 P50≈1.09%，P90≈3.95%；
- 统计日 2011-11-27（周日）触发 119 个异常，2011-11-25（周五）触发 106 个异常（300 个商品中），说明 v0.1 阈值在这个分布下偏敏感，阶段三真实数据校准是必要的。

> 退款金额大于净销售额是允许的：销售额已经是净额，退款可能超过当日净销售额。校验器已移除该误报规则。

## 5. 重建

```powershell
# 1) 下载原始文件（约 23MB）
# 放到 data/reference/raw/Online Retail.xlsx
# 2) 生成派生样本
.venv\Scripts\python.exe tools\build_reference_sample.py --products 300 --days 180
# 3) 查看画像
.venv\Scripts\python.exe tools\profile_data.py --data data/reference/online_retail_reference.csv
```
