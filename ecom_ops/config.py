"""配置加载与校验。

配置分为三部分：
1. .env：密钥与机器相关环境变量，不提交到 Git；
2. config/settings.yaml：业务阈值、目录、日志等；
3. config/fields.yaml：数据字段契约与表头别名。

所有配置在启动时一次性校验，缺失或非法时直接给出明确错误。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from ecom_ops.exceptions import ConfigError
from ecom_ops.utils.files import resolve_path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 理论上依赖已安装
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_DTYPES = {"date", "string", "int", "float"}


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    data_file: Path
    report_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class BaselineConfig:
    windows: tuple[int, ...]
    cv_low: float
    cv_high: float
    min_valid_days: int
    lookback_days: int
    new_product_exempt_days: int


@dataclass(frozen=True)
class SeverityConfig:
    zero_conversion: float
    pv_drop: float
    order_drop: float
    high_pv_low_cr: float


@dataclass(frozen=True)
class LevelsConfig:
    high: float
    medium: float


@dataclass(frozen=True)
class InventoryConfig:
    enabled: bool
    low_stock_days: int
    overstock_days: int


@dataclass(frozen=True)
class AnomalyConfig:
    min_pv_for_ratio: int
    min_pv_for_zero_conversion: int
    min_pv_for_high_pv: int
    min_orders_for_drop: int
    pv_drop_ratio: float
    order_drop_ratio: float
    high_pv_ratio: float
    low_cr_ratio: float
    severity: SeverityConfig
    levels: LevelsConfig
    inventory: InventoryConfig


@dataclass(frozen=True)
class ReportConfig:
    top_n: int
    description_max_chars: int
    filename_pattern: str


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    filename: str
    retention_days: int


@dataclass(frozen=True)
class SchedulerConfig:
    hour: int
    minute: int
    misfire_grace_seconds: int
    max_retries: int
    retry_delay_seconds: int
    lock_file: Path
    stale_lock_seconds: int


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    max_attempts: int
    retry_backoff_seconds: tuple[int, ...]
    max_anomalies: int
    thinking: str
    cache_enabled: bool
    cache_dir: Path


@dataclass(frozen=True)
class RAGConfig:
    enabled: bool
    embedding_model: str
    embedding_dimensions: int
    index_dir: Path
    knowledge_dir: Path
    history_dir: Path
    chunk_size: int
    chunk_overlap: int
    top_k: int
    max_selected_chunks: int
    max_context_chars: int
    min_score: float
    embedding_batch_size: int


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    dtype: str
    required: bool
    description: str


@dataclass(frozen=True)
class FieldsConfig:
    fields: dict[str, FieldSpec]
    aliases: dict[str, str]

    @property
    def canonical_names(self) -> tuple[str, ...]:
        return tuple(self.fields.keys())

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.required)

    @property
    def int_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.dtype == "int")

    @property
    def float_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.dtype == "float")

    @property
    def string_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.dtype == "string")

    @property
    def date_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if spec.dtype == "date")

    @property
    def optional_names(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.fields.items() if not spec.required)

    def label(self, name: str) -> str:
        spec = self.fields.get(name)
        return spec.label if spec else name


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    baseline: BaselineConfig
    anomaly: AnomalyConfig
    report: ReportConfig
    logging: LoggingConfig
    scheduler: SchedulerConfig
    llm: LLMConfig
    rag: RAGConfig
    fields: FieldsConfig
    root: Path
    settings_path: Path
    fields_path: Path


def _read_yaml(path: Path, kind: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{kind} 文件不存在: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{kind} 文件不是 UTF-8 编码: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{kind} 文件 YAML 格式错误: {path}\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{kind} 文件顶层必须是键值映射: {path}")
    return raw


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"配置缺少 [{name}] 段，或该段不是键值映射")
    return value


def _require(section: dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigError(f"配置 [{section_name}] 缺少字段: {key}")
    return section[key]


def _as_int(value: Any, label: str) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} 必须是整数，当前值: {value!r}") from exc


def _as_float(value: Any, label: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} 必须是数字，当前值: {value!r}") from exc


def _as_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{label} 必须是 true/false，当前值: {value!r}")


def _as_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} 必须是非空字符串，当前值: {value!r}")
    return value.strip()


def _as_int_list(value: Any, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{label} 必须是非空整数列表，当前值: {value!r}")
    result: list[int] = []
    for item in value:
        number = _as_int(item, label)
        if number <= 0:
            raise ConfigError(f"{label} 中的窗口必须大于 0，当前值: {number}")
        if number not in result:
            result.append(number)
    if len(result) < 2:
        raise ConfigError(f"{label} 至少需要两个不同窗口，当前值: {value!r}")
    return tuple(sorted(result))


def _load_fields(path: Path) -> FieldsConfig:
    raw = _read_yaml(path, "字段配置")
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise ConfigError("字段配置缺少非空的 [fields] 段")

    aliases_raw = raw.get("aliases", {})
    if aliases_raw is None:
        aliases_raw = {}
    if not isinstance(aliases_raw, dict):
        raise ConfigError("字段配置的 [aliases] 必须是键值映射")

    fields: dict[str, FieldSpec] = {}
    for name, spec_raw in fields_raw.items():
        if not isinstance(name, str) or not name:
            raise ConfigError(f"字段名必须是非空字符串: {name!r}")
        if not isinstance(spec_raw, dict):
            raise ConfigError(f"字段 {name} 的配置必须是键值映射")
        dtype = _as_str(spec_raw.get("dtype"), f"字段 {name}.dtype")
        if dtype not in VALID_DTYPES:
            raise ConfigError(
                f"字段 {name}.dtype 必须是 {sorted(VALID_DTYPES)} 之一，当前值: {dtype}"
            )
        required = spec_raw.get("required", False)
        if not isinstance(required, bool):
            raise ConfigError(f"字段 {name}.required 必须是 true/false")
        label = spec_raw.get("label", name)
        if not isinstance(label, str) or not label.strip():
            raise ConfigError(f"字段 {name}.label 必须是非空字符串")
        description = spec_raw.get("description", "")
        if not isinstance(description, str):
            raise ConfigError(f"字段 {name}.description 必须是字符串")
        fields[name] = FieldSpec(
            name=name,
            label=label.strip(),
            dtype=dtype,
            required=required,
            description=description.strip(),
        )

    for core in ("stat_date", "product_id", "pv", "orders", "sales_amount"):
        if core not in fields:
            raise ConfigError(f"字段配置缺少核心字段: {core}")

    aliases: dict[str, str] = {}
    for alias, canonical in aliases_raw.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ConfigError(f"字段别名必须是非空字符串: {alias!r}")
        if not isinstance(canonical, str) or canonical not in fields:
            raise ConfigError(f"字段别名 {alias!r} 指向了不存在的字段: {canonical!r}")
        aliases[alias.strip()] = canonical

    return FieldsConfig(fields=fields, aliases=aliases)


def load_settings(
    settings_path: str | Path | None = None,
    fields_path: str | Path | None = None,
    root: str | Path | None = None,
) -> Settings:
    """加载并校验 settings.yaml 与 fields.yaml。"""
    project_root = Path(root).resolve() if root else PROJECT_ROOT
    settings_file = Path(settings_path) if settings_path else project_root / "config" / "settings.yaml"
    fields_file = Path(fields_path) if fields_path else project_root / "config" / "fields.yaml"
    if not settings_file.is_absolute():
        settings_file = project_root / settings_file
    if not fields_file.is_absolute():
        fields_file = project_root / fields_file

    if load_dotenv is not None:
        load_dotenv(project_root / ".env", override=False)

    raw = _read_yaml(settings_file, "业务配置")
    app_raw = _section(raw, "app")
    baseline_raw = _section(raw, "baseline")
    anomaly_raw = _section(raw, "anomaly")
    report_raw = _section(raw, "report")
    logging_raw = _section(raw, "logging")
    scheduler_raw = _section(raw, "scheduler")
    llm_raw = _section(raw, "llm")
    rag_raw = _section(raw, "rag")

    timezone_name = _as_str(_require(app_raw, "timezone", "app"), "app.timezone")
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ConfigError(f"app.timezone 不是有效的 IANA 时区: {timezone_name}") from exc

    data_file = resolve_path(
        _as_str(_require(app_raw, "data_file", "app"), "app.data_file"),
        project_root,
    )
    report_dir = resolve_path(
        _as_str(_require(app_raw, "report_dir", "app"), "app.report_dir"),
        project_root,
    )
    log_dir = resolve_path(
        _as_str(_require(app_raw, "log_dir", "app"), "app.log_dir"),
        project_root,
    )

    windows = _as_int_list(_require(baseline_raw, "windows", "baseline"), "baseline.windows")
    cv_low = _as_float(_require(baseline_raw, "cv_low", "baseline"), "baseline.cv_low")
    cv_high = _as_float(_require(baseline_raw, "cv_high", "baseline"), "baseline.cv_high")
    if not (0 <= cv_low < cv_high):
        raise ConfigError("baseline.cv_low 必须 >= 0 且小于 baseline.cv_high")

    min_valid_days = _as_int(
        _require(baseline_raw, "min_valid_days", "baseline"), "baseline.min_valid_days"
    )
    lookback_days = _as_int(
        _require(baseline_raw, "lookback_days", "baseline"), "baseline.lookback_days"
    )
    exempt_days = _as_int(
        _require(baseline_raw, "new_product_exempt_days", "baseline"),
        "baseline.new_product_exempt_days",
    )
    if min_valid_days < 1:
        raise ConfigError("baseline.min_valid_days 必须 >= 1")
    if lookback_days < max(windows):
        raise ConfigError("baseline.lookback_days 不能小于最大窗口")
    if exempt_days < 0:
        raise ConfigError("baseline.new_product_exempt_days 必须 >= 0")

    min_pv_ratio = _as_int(
        _require(anomaly_raw, "min_pv_for_ratio", "anomaly"), "anomaly.min_pv_for_ratio"
    )
    min_pv_zero = _as_int(
        _require(anomaly_raw, "min_pv_for_zero_conversion", "anomaly"),
        "anomaly.min_pv_for_zero_conversion",
    )
    min_pv_high = _as_int(
        _require(anomaly_raw, "min_pv_for_high_pv", "anomaly"), "anomaly.min_pv_for_high_pv"
    )
    min_orders = _as_int(
        _require(anomaly_raw, "min_orders_for_drop", "anomaly"), "anomaly.min_orders_for_drop"
    )
    pv_drop_ratio = _as_float(
        _require(anomaly_raw, "pv_drop_ratio", "anomaly"), "anomaly.pv_drop_ratio"
    )
    order_drop_ratio = _as_float(
        _require(anomaly_raw, "order_drop_ratio", "anomaly"), "anomaly.order_drop_ratio"
    )
    high_pv_ratio = _as_float(
        _require(anomaly_raw, "high_pv_ratio", "anomaly"), "anomaly.high_pv_ratio"
    )
    low_cr_ratio = _as_float(
        _require(anomaly_raw, "low_cr_ratio", "anomaly"), "anomaly.low_cr_ratio"
    )
    if min_pv_ratio < 0 or min_pv_zero < 0 or min_pv_high < 0 or min_orders < 0:
        raise ConfigError("anomaly 的最小样本门槛必须 >= 0")
    if not (0 < pv_drop_ratio < 1):
        raise ConfigError("anomaly.pv_drop_ratio 必须在 (0, 1) 之间")
    if not (0 < order_drop_ratio < 1):
        raise ConfigError("anomaly.order_drop_ratio 必须在 (0, 1) 之间")
    if high_pv_ratio < 1:
        raise ConfigError("anomaly.high_pv_ratio 必须 >= 1")
    if not (0 < low_cr_ratio < 1):
        raise ConfigError("anomaly.low_cr_ratio 必须在 (0, 1) 之间")

    severity_raw = _section(anomaly_raw, "severity")
    levels_raw = _section(anomaly_raw, "levels")
    inventory_raw = _section(anomaly_raw, "inventory")
    severity = SeverityConfig(
        zero_conversion=_as_float(
            _require(severity_raw, "zero_conversion", "anomaly.severity"),
            "anomaly.severity.zero_conversion",
        ),
        pv_drop=_as_float(
            _require(severity_raw, "pv_drop", "anomaly.severity"),
            "anomaly.severity.pv_drop",
        ),
        order_drop=_as_float(
            _require(severity_raw, "order_drop", "anomaly.severity"),
            "anomaly.severity.order_drop",
        ),
        high_pv_low_cr=_as_float(
            _require(severity_raw, "high_pv_low_cr", "anomaly.severity"),
            "anomaly.severity.high_pv_low_cr",
        ),
    )
    levels = LevelsConfig(
        high=_as_float(_require(levels_raw, "high", "anomaly.levels"), "anomaly.levels.high"),
        medium=_as_float(
            _require(levels_raw, "medium", "anomaly.levels"), "anomaly.levels.medium"
        ),
    )
    if levels.medium >= levels.high:
        raise ConfigError("anomaly.levels.medium 必须小于 anomaly.levels.high")
    inventory = InventoryConfig(
        enabled=_as_bool(
            _require(inventory_raw, "enabled", "anomaly.inventory"), "anomaly.inventory.enabled"
        ),
        low_stock_days=_as_int(
            _require(inventory_raw, "low_stock_days", "anomaly.inventory"),
            "anomaly.inventory.low_stock_days",
        ),
        overstock_days=_as_int(
            _require(inventory_raw, "overstock_days", "anomaly.inventory"),
            "anomaly.inventory.overstock_days",
        ),
    )
    if inventory.low_stock_days < 0 or inventory.overstock_days < 0:
        raise ConfigError("库存天数配置必须 >= 0")

    top_n = _as_int(_require(report_raw, "top_n", "report"), "report.top_n")
    desc_max = _as_int(
        _require(report_raw, "description_max_chars", "report"),
        "report.description_max_chars",
    )
    filename_pattern = _as_str(
        _require(report_raw, "filename_pattern", "report"), "report.filename_pattern"
    )
    if top_n < 1:
        raise ConfigError("report.top_n 必须 >= 1")
    if desc_max < 1:
        raise ConfigError("report.description_max_chars 必须 >= 1")
    if "{date}" not in filename_pattern:
        raise ConfigError("report.filename_pattern 必须包含 {date} 占位符")

    log_level = os.getenv("LOG_LEVEL", "").strip().upper() or _as_str(
        _require(logging_raw, "level", "logging"), "logging.level"
    ).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(f"logging.level 非法: {log_level}")
    log_filename = _as_str(
        _require(logging_raw, "filename", "logging"), "logging.filename"
    )
    retention_days = _as_int(
        _require(logging_raw, "retention_days", "logging"), "logging.retention_days"
    )
    if retention_days < 1:
        raise ConfigError("logging.retention_days 必须 >= 1")

    scheduler_hour = _as_int(_require(scheduler_raw, "hour", "scheduler"), "scheduler.hour")
    scheduler_minute = _as_int(
        _require(scheduler_raw, "minute", "scheduler"), "scheduler.minute"
    )
    misfire_grace = _as_int(
        _require(scheduler_raw, "misfire_grace_seconds", "scheduler"),
        "scheduler.misfire_grace_seconds",
    )
    schedule_retries = _as_int(
        _require(scheduler_raw, "max_retries", "scheduler"), "scheduler.max_retries"
    )
    retry_delay = _as_int(
        _require(scheduler_raw, "retry_delay_seconds", "scheduler"),
        "scheduler.retry_delay_seconds",
    )
    lock_file = resolve_path(
        _as_str(_require(scheduler_raw, "lock_file", "scheduler"), "scheduler.lock_file"),
        project_root,
    )
    stale_lock_seconds = _as_int(
        _require(scheduler_raw, "stale_lock_seconds", "scheduler"),
        "scheduler.stale_lock_seconds",
    )
    if not (0 <= scheduler_hour <= 23):
        raise ConfigError("scheduler.hour 必须在 0–23 之间")
    if not (0 <= scheduler_minute <= 59):
        raise ConfigError("scheduler.minute 必须在 0–59 之间")
    if misfire_grace < 0:
        raise ConfigError("scheduler.misfire_grace_seconds 必须 >= 0")
    if schedule_retries < 0:
        raise ConfigError("scheduler.max_retries 必须 >= 0")
    if retry_delay < 0:
        raise ConfigError("scheduler.retry_delay_seconds 必须 >= 0")
    if stale_lock_seconds < 1:
        raise ConfigError("scheduler.stale_lock_seconds 必须 >= 1")

    llm_enabled = _as_bool(_require(llm_raw, "enabled", "llm"), "llm.enabled")
    llm_provider = _as_str(_require(llm_raw, "provider", "llm"), "llm.provider")
    llm_model = os.getenv("LLM_MODEL", "").strip() or _as_str(
        _require(llm_raw, "model", "llm"), "llm.model"
    )
    llm_base_url = os.getenv("ZHIPU_BASE_URL", "").strip() or _as_str(
        _require(llm_raw, "base_url", "llm"), "llm.base_url"
    )
    llm_temperature = _as_float(
        _require(llm_raw, "temperature", "llm"), "llm.temperature"
    )
    llm_max_tokens = _as_int(
        _require(llm_raw, "max_tokens", "llm"), "llm.max_tokens"
    )
    llm_timeout = _as_int(
        _require(llm_raw, "timeout_seconds", "llm"), "llm.timeout_seconds"
    )
    llm_max_attempts = _as_int(
        _require(llm_raw, "max_attempts", "llm"), "llm.max_attempts"
    )
    llm_backoff = _as_int_list(
        _require(llm_raw, "retry_backoff_seconds", "llm"),
        "llm.retry_backoff_seconds",
    )
    llm_max_anomalies = _as_int(
        _require(llm_raw, "max_anomalies", "llm"), "llm.max_anomalies"
    )
    llm_thinking = _as_str(_require(llm_raw, "thinking", "llm"), "llm.thinking").lower()
    llm_cache_enabled = _as_bool(
        _require(llm_raw, "cache_enabled", "llm"), "llm.cache_enabled"
    )
    llm_cache_dir = resolve_path(
        _as_str(_require(llm_raw, "cache_dir", "llm"), "llm.cache_dir"),
        project_root,
    )
    if not (0 <= llm_temperature <= 2):
        raise ConfigError("llm.temperature 必须在 [0, 2] 之间")
    if llm_max_tokens < 1:
        raise ConfigError("llm.max_tokens 必须 >= 1")
    if llm_timeout < 1:
        raise ConfigError("llm.timeout_seconds 必须 >= 1")
    if llm_max_attempts < 1:
        raise ConfigError("llm.max_attempts 必须 >= 1")
    if len(llm_backoff) < llm_max_attempts - 1:
        raise ConfigError("llm.retry_backoff_seconds 的数量必须覆盖 max_attempts - 1")
    if llm_max_anomalies < 1:
        raise ConfigError("llm.max_anomalies 必须 >= 1")
    if llm_thinking not in {"enabled", "disabled"}:
        raise ConfigError("llm.thinking 只能是 enabled 或 disabled")

    rag_enabled = _as_bool(_require(rag_raw, "enabled", "rag"), "rag.enabled")
    embedding_model = os.getenv("EMBEDDING_MODEL", "").strip() or _as_str(
        _require(rag_raw, "embedding_model", "rag"), "rag.embedding_model"
    )
    embedding_dimensions = _as_int(
        os.getenv("EMBEDDING_DIMENSIONS", "").strip()
        or _require(rag_raw, "embedding_dimensions", "rag"),
        "rag.embedding_dimensions",
    )
    rag_index_dir = resolve_path(
        _as_str(_require(rag_raw, "index_dir", "rag"), "rag.index_dir"),
        project_root,
    )
    rag_knowledge_dir = resolve_path(
        _as_str(_require(rag_raw, "knowledge_dir", "rag"), "rag.knowledge_dir"),
        project_root,
    )
    rag_history_dir = resolve_path(
        _as_str(_require(rag_raw, "history_dir", "rag"), "rag.history_dir"),
        project_root,
    )
    rag_chunk_size = _as_int(
        _require(rag_raw, "chunk_size", "rag"), "rag.chunk_size"
    )
    rag_chunk_overlap = _as_int(
        _require(rag_raw, "chunk_overlap", "rag"), "rag.chunk_overlap"
    )
    rag_top_k = _as_int(_require(rag_raw, "top_k", "rag"), "rag.top_k")
    rag_max_selected = _as_int(
        _require(rag_raw, "max_selected_chunks", "rag"), "rag.max_selected_chunks"
    )
    rag_max_context = _as_int(
        _require(rag_raw, "max_context_chars", "rag"), "rag.max_context_chars"
    )
    rag_min_score = _as_float(
        _require(rag_raw, "min_score", "rag"), "rag.min_score"
    )
    rag_embedding_batch = _as_int(
        _require(rag_raw, "embedding_batch_size", "rag"), "rag.embedding_batch_size"
    )
    if embedding_dimensions < 1:
        raise ConfigError("rag.embedding_dimensions 必须 >= 1")
    if rag_chunk_size < 1:
        raise ConfigError("rag.chunk_size 必须 >= 1")
    if not (0 <= rag_chunk_overlap < rag_chunk_size):
        raise ConfigError("rag.chunk_overlap 必须 >= 0 且小于 chunk_size")
    if rag_top_k < 1:
        raise ConfigError("rag.top_k 必须 >= 1")
    if rag_max_selected < 1:
        raise ConfigError("rag.max_selected_chunks 必须 >= 1")
    if rag_max_context < 1:
        raise ConfigError("rag.max_context_chars 必须 >= 1")
    if not (0 <= rag_min_score <= 1):
        raise ConfigError("rag.min_score 必须在 [0, 1] 之间")
    if rag_embedding_batch < 1:
        raise ConfigError("rag.embedding_batch_size 必须 >= 1")

    fields = _load_fields(fields_file)

    return Settings(
        app=AppConfig(
            timezone=timezone_name,
            data_file=data_file,
            report_dir=report_dir,
            log_dir=log_dir,
        ),
        baseline=BaselineConfig(
            windows=windows,
            cv_low=cv_low,
            cv_high=cv_high,
            min_valid_days=min_valid_days,
            lookback_days=lookback_days,
            new_product_exempt_days=exempt_days,
        ),
        anomaly=AnomalyConfig(
            min_pv_for_ratio=min_pv_ratio,
            min_pv_for_zero_conversion=min_pv_zero,
            min_pv_for_high_pv=min_pv_high,
            min_orders_for_drop=min_orders,
            pv_drop_ratio=pv_drop_ratio,
            order_drop_ratio=order_drop_ratio,
            high_pv_ratio=high_pv_ratio,
            low_cr_ratio=low_cr_ratio,
            severity=severity,
            levels=levels,
            inventory=inventory,
        ),
        report=ReportConfig(
            top_n=top_n,
            description_max_chars=desc_max,
            filename_pattern=filename_pattern,
        ),
        logging=LoggingConfig(
            level=log_level,
            filename=log_filename,
            retention_days=retention_days,
        ),
        scheduler=SchedulerConfig(
            hour=scheduler_hour,
            minute=scheduler_minute,
            misfire_grace_seconds=misfire_grace,
            max_retries=schedule_retries,
            retry_delay_seconds=retry_delay,
            lock_file=lock_file,
            stale_lock_seconds=stale_lock_seconds,
        ),
        llm=LLMConfig(
            enabled=llm_enabled,
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url,
            temperature=llm_temperature,
            max_tokens=llm_max_tokens,
            timeout_seconds=llm_timeout,
            max_attempts=llm_max_attempts,
            retry_backoff_seconds=llm_backoff,
            max_anomalies=llm_max_anomalies,
            thinking=llm_thinking,
            cache_enabled=llm_cache_enabled,
            cache_dir=llm_cache_dir,
        ),
        rag=RAGConfig(
            enabled=rag_enabled,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            index_dir=rag_index_dir,
            knowledge_dir=rag_knowledge_dir,
            history_dir=rag_history_dir,
            chunk_size=rag_chunk_size,
            chunk_overlap=rag_chunk_overlap,
            top_k=rag_top_k,
            max_selected_chunks=rag_max_selected,
            max_context_chars=rag_max_context,
            min_score=rag_min_score,
            embedding_batch_size=rag_embedding_batch,
        ),
        fields=fields,
        root=project_root,
        settings_path=settings_file.resolve(),
        fields_path=fields_file.resolve(),
    )
