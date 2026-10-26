"""统一异常分类。

所有可预期错误都继承 EcomOpsError，便于 run.py 统一捕获并给出友好提示；
未知异常仍由 run.py 兜底记录完整堆栈。
"""


class EcomOpsError(Exception):
    """项目内所有可预期错误的基类。"""


class ConfigError(EcomOpsError):
    """配置文件缺失、格式错误或取值非法。"""


class DataLoadError(EcomOpsError):
    """数据文件不存在、无法读取或缺少必要字段。"""


class DataValidationError(EcomOpsError):
    """数据校验后没有可用数据，或校验过程本身失败。"""


class AnalysisError(EcomOpsError):
    """指标、基线或异常分析阶段失败。"""


class ReportError(EcomOpsError):
    """报告渲染或写入失败。"""


class WorkflowError(EcomOpsError):
    """LangGraph 工作流执行失败。"""


class LLMError(EcomOpsError):
    """大模型调用失败（重试后仍失败）。"""


class AISchemaError(EcomOpsError):
    """大模型输出无法解析为约定的 JSON 结构。"""


class RAGError(EcomOpsError):
    """RAG 索引构建或检索失败。"""


class CatalogError(EcomOpsError):
    """商品目录/价格事件数据读取或分析失败。"""


class HistoryError(EcomOpsError):
    """历史记录写入或查询失败。"""


class TmallError(EcomOpsError):
    """天猫订单数据读取或分析失败。"""
