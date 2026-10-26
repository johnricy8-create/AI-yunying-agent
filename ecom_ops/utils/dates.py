"""日期与时区工具。

业务统一使用北京时间。Windows 不自带 IANA 时区数据库，
因此项目依赖 tzdata；若运行环境仍缺失，则回退到固定 UTC+8。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo

    APP_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 仅在缺少 tzdata 时触发
    APP_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d")


def now() -> datetime:
    """返回带北京时区的当前时间。"""
    return datetime.now(tz=APP_TZ)


def today() -> date:
    """返回北京时间的今天。"""
    return now().date()


def default_stat_date(base: date | None = None) -> date:
    """默认统计日期为运行日的前一天。

    每天 09:00 执行时，当天数据通常尚未完整，因此默认分析 D-1。
    """
    return (base or today()) - timedelta(days=1)


def parse_date(value: Any) -> date:
    """把常见日期表示解析为 date。

    支持 date / datetime / pandas Timestamp / 字符串。
    解析失败抛出 ValueError，由校验器转成数据质量问题。
    """
    if value is None:
        raise ValueError("日期为空")

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    # pandas Timestamp 是 datetime 的子类，通常已被上面覆盖；
    # 这里兼容其他带 date() 方法的对象。
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            result = value.date()
            if isinstance(result, date):
                return result
        except Exception:
            pass

    text = str(value).strip()
    if not text:
        raise ValueError("日期为空")

    # 去掉可能的时间部分，例如 2026-10-25 00:00:00
    if " " in text:
        text = text.split(" ", 1)[0]
    if "T" in text:
        text = text.split("T", 1)[0]

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"无法识别的日期格式: {value!r}")


def format_date(value: date | datetime | None) -> str:
    """统一输出 YYYY-MM-DD；空值输出短横线。"""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%Y-%m-%d")


def format_datetime(value: datetime | None = None) -> str:
    """输出北京时间 YYYY-MM-DD HH:MM:SS。"""
    value = value or now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TZ)
    else:
        value = value.astimezone(APP_TZ)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def date_range(start: date, end: date):
    """闭区间日期迭代器。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
