"""Stage 01 使用的结构化输出模型。"""

from pydantic import BaseModel, ConfigDict, Field


class TaskAnalysis(BaseModel):
    """任务分析节点的结构化结果。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_type: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    required_capabilities: list[str] = Field(min_length=1)


class PlanStep(BaseModel):
    """执行计划中的单个步骤。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int = Field(gt=0)
    goal: str = Field(min_length=1)
    tool_hint: str | None = None


class TaskPlan(BaseModel):
    """规划节点的结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1)
