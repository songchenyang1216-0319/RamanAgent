"""甲醇接口请求与响应 Schema。"""

from pydantic import BaseModel


class DemoPredictRequest(BaseModel):
    """demo 样例预测请求。"""

    file_name: str


class ArtifactCheckItem(BaseModel):
    """单个 artifact 检查结果。"""

    name: str
    exists: bool
    path: str


class ArtifactCheckResponse(BaseModel):
    """artifact 总体检查结果。"""

    overall: bool
    items: list[ArtifactCheckItem]


class ExplainResultRequest(BaseModel):
    """解释预测结果请求。"""

    result: dict


class ExplainResultResponse(BaseModel):
    """解释预测结果响应。"""

    success: bool
    explanation: str | None = None
    message: str | None = None
