"""规则型核查方向。

销售报告和历史追踪共用，避免文案散落在多个模块。
"""

from __future__ import annotations

RULE_DIRECTIONS: dict[str, list[str]] = {
    "zero_conversion": [
        "核对商品详情页、价格与库存是否正常可见",
        "检查下单与支付链路是否存在故障",
        "核对流量来源是否精准，排除无效流量或统计异常",
    ],
    "pv_drop": [
        "核对平台搜索排名、活动结束时间与商品是否下架",
        "检查竞品动作、站外流量与投放变化",
        "确认数据采集是否漏数或日期错位",
    ],
    "order_drop": [
        "检查价格、优惠、评价与售后变化",
        "核对库存、支付故障与下单链路",
        "复盘流量结构是否发生明显变化",
    ],
    "high_pv_low_cr": [
        "优化详情页首屏卖点与信息完整度",
        "检查价格竞争力、评价与信任信息",
        "核对流量关键词与商品匹配度",
    ],
    "stock_out": [
        "确认补货计划与到货时间",
        "评估是否暂停投放或临时下架",
    ],
    "overstock": [
        "评估促销、组合销售或清仓方案",
        "控制后续采购与投放节奏",
    ],
}

TYPE_CODE_MAP = {
    "零转化": "zero_conversion",
    "浏览量骤降": "pv_drop",
    "订单量骤降": "order_drop",
    "高浏览低转化": "high_pv_low_cr",
    "断货风险": "stock_out",
    "库存积压": "overstock",
}


def directions_for_code(code: str) -> list[str]:
    return list(RULE_DIRECTIONS.get(code, []))


def directions_for_types(labels: list[str]) -> list[str]:
    result: list[str] = []
    for label in labels:
        code = TYPE_CODE_MAP.get(label, label)
        for direction in RULE_DIRECTIONS.get(code, []):
            if direction not in result:
                result.append(direction)
    return result
