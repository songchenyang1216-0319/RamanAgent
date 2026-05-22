"""规则版 Agent 任务规划器。"""

from __future__ import annotations

from dataclasses import dataclass, field


SUPPORTED_PLAN_TOOLS = {
    "get_current_model",
    "list_history",
    "predict_methanol",
    "professional_analysis",
    "spectral_quality",
    "peak_analysis",
    "compare_history",
    "generate_report",
    "general_chat",
}


@dataclass(frozen=True)
class AgentPlanStep:
    """单个计划步骤。"""

    tool: str
    reason: str

    def to_dict(self) -> dict:
        return {"tool": self.tool, "reason": self.reason}


@dataclass(frozen=True)
class AgentPlan:
    """Agent 执行计划。"""

    steps: list[AgentPlanStep] = field(default_factory=list)

    @property
    def is_compound(self) -> bool:
        """是否属于需要规划器执行的复合任务。"""
        return len(self.steps) >= 2

    def to_dict(self) -> dict:
        return {"steps": [step.to_dict() for step in self.steps]}


class AgentPlanner:
    """基于关键词的轻量任务规划器。"""

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _add_step(self, steps: list[AgentPlanStep], tool: str, reason: str) -> None:
        if tool not in SUPPORTED_PLAN_TOOLS:
            return
        if any(step.tool == tool for step in steps):
            return
        steps.append(AgentPlanStep(tool=tool, reason=reason))

    def plan(self, message: str) -> AgentPlan:
        """把用户消息拆成一个按顺序执行的规则计划。"""
        text = (message or "").strip()
        lowered = text.lower()
        steps: list[AgentPlanStep] = []

        if not text:
            return AgentPlan([])

        wants_model = self._contains_any(text, ("当前用的模型", "当前模型", "用的模型", "哪个模型", "模型版本", "模型信息"))
        wants_history = self._contains_any(text, ("历史记录", "历史样品", "最近记录", "历史结果", "之前的样品", "之前样品", "历史"))
        wants_prediction = (
            self._contains_any(text, ("分析这个样品", "分析这个 csv", "分析这个CSV", "分析样品", "预测浓度", "预测甲醇", "预测"))
            or ("分析" in text and ("样品" in text or "csv" in lowered))
        )
        wants_quality = self._contains_any(text, ("谱图质量", "光谱质量", "质量怎么样", "信噪比", "噪声", "采集质量"))
        wants_peaks = self._contains_any(text, ("峰位", "特征峰", "峰识别", "判断峰", "这个峰", "峰大概"))
        wants_compare = self._contains_any(
            text,
            (
                "历史样品比",
                "历史样品对比",
                "和历史样品",
                "跟历史样品",
                "和之前的样品",
                "和之前样品",
                "跟之前的样品",
                "跟之前样品",
                "比一下",
                "对比一下",
            ),
        )
        wants_report = self._contains_any(text, ("生成报告", "输出报告", "出报告", "报告"))
        wants_professional = self._contains_any(text, ("是否可信", "结果可信", "靠谱吗", "专业解释", "专业分析", "输出专业解释", "解释结果"))

        if wants_model:
            self._add_step(steps, "get_current_model", "用户要求查看当前模型信息")
        if wants_history and not wants_compare:
            self._add_step(steps, "list_history", "用户要求查看历史记录")
        if wants_prediction:
            self._add_step(steps, "predict_methanol", "用户要求分析样品或预测浓度")
        if wants_quality:
            self._add_step(steps, "spectral_quality", "用户要求评估光谱质量")
        if wants_peaks:
            self._add_step(steps, "peak_analysis", "用户要求判断峰位或解释峰")
        if wants_professional:
            self._add_step(steps, "professional_analysis", "用户要求判断结果可信度或输出专业解释")
        if wants_compare:
            self._add_step(steps, "compare_history", "用户要求和历史样品对比")
        if wants_report:
            self._add_step(steps, "generate_report", "用户要求生成报告")

        if not steps and self._contains_any(text, ("聊聊", "随便", "你好", "谢谢")):
            self._add_step(steps, "general_chat", "用户要求普通对话")

        return AgentPlan(steps)
