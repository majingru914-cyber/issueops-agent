"""统一 Retry、Timeout、Fallback、预算和结构化日志测试。"""

import logging
import time
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.reliability import ReliabilityPolicy
from tools.runtime import ToolRuntime


class NoArgs(BaseModel):
    """无参数测试 Tool 的严格 Schema。"""

    model_config = ConfigDict(extra="forbid")


class RequiredArgs(BaseModel):
    """验证不可重试非法参数的 Schema。"""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)


class SecretArgs(BaseModel):
    """验证日志不会记录 Tool arguments。"""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1)


class FlakyTool(BaseTool):
    """第一次产生 TIMEOUT、第二次成功的测试 Tool。"""

    name: ClassVar[str] = "flaky_tool"
    description: ClassVar[str] = "验证同一逻辑 Tool call 的 Retry。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def __init__(self) -> None:
        self.call_count = 0

    def run(self, args: BaseModel) -> Any:
        """第一次失败，第二次返回固定数据。"""

        self.call_count += 1
        if self.call_count == 1:
            raise TimeoutError("模拟临时超时")
        return {"status": "ok"}


class AlwaysTimeoutTool(BaseTool):
    """始终返回可重试 TIMEOUT 的测试 Tool。"""

    name: ClassVar[str] = "always_timeout_tool"
    description: ClassVar[str] = "验证 Retry Exhaustion。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """每次执行都产生 TIMEOUT。"""

        raise TimeoutError("模拟持续超时")


class RequiredArgumentTool(BaseTool):
    """用于验证 INVALID_ARGUMENT 不重试。"""

    name: ClassVar[str] = "required_argument_tool"
    description: ClassVar[str] = "验证参数错误分类。"
    args_schema: ClassVar[type[BaseModel]] = RequiredArgs

    def run(self, args: BaseModel) -> Any:
        """参数有效时返回固定结果。"""

        return {"status": "ok"}


class SlowTool(BaseTool):
    """运行时间超过 Runtime timeout 的测试 Tool。"""

    name: ClassVar[str] = "slow_tool"
    description: ClassVar[str] = "验证通用 Tool execution timeout。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """短暂休眠，模拟卡住的同步 Tool。"""

        time.sleep(0.4)
        return {"status": "late"}


class PrimaryFailTool(BaseTool):
    """产生不可重试 EXECUTION_FAILED 的 Primary Tool。"""

    name: ClassVar[str] = "primary_tool"
    description: ClassVar[str] = "验证确定性 Fallback。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """始终失败。"""

        raise RuntimeError("模拟 Primary failure")


class FallbackSuccessTool(BaseTool):
    """固定成功的 Fallback Tool。"""

    name: ClassVar[str] = "fallback_tool"
    description: ClassVar[str] = "验证 Fallback 成功。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """返回降级结果。"""

        return {"status": "fallback_ok"}


class SecretEchoTool(BaseTool):
    """接受敏感样例参数但不把它写入日志。"""

    name: ClassVar[str] = "secret_echo_tool"
    description: ClassVar[str] = "验证日志 Secret Safety。"
    args_schema: ClassVar[type[BaseModel]] = SecretArgs

    def run(self, args: BaseModel) -> Any:
        """只返回非敏感状态。"""

        return {"status": "accepted"}


def build_runtime(*tools: BaseTool, policy: ReliabilityPolicy) -> ToolRuntime:
    """构建仅包含 tests-only Tool 的 Runtime。"""

    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolRuntime(registry, policy)


def test_retry_succeeds_and_preserves_both_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """一次逻辑调用应在第 2 次 Attempt 成功，并保留完整历史。"""

    tool = FlakyTool()
    runtime = build_runtime(tool, policy=ReliabilityPolicy(max_retries=2))
    caplog.set_level(logging.INFO, logger="issueops.tools")

    result = runtime.execute(tool.name, {}, task_id="task-retry", step_id=1)

    assert result.success is True
    assert result.data == {"status": "ok"}
    assert tool.call_count == 2
    assert result.retry_count == 1
    assert [item.success for item in result.attempts] == [False, True]
    assert [item.attempt for item in result.attempts] == [1, 2]
    assert [item.phase for item in result.attempts] == ["initial", "retry"]
    assert all(item.task_id == "task-retry" for item in result.attempts)
    assert all(item.step_id == 1 for item in result.attempts)
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_retry" in logs
    assert "retry=1" in logs
    assert "reason=TIMEOUT" in logs


def test_retry_exhaustion_is_bounded_and_keeps_last_error() -> None:
    """max_retries=2 必须严格产生 1+2 次 Attempt 后停止。"""

    runtime = build_runtime(
        AlwaysTimeoutTool(),
        policy=ReliabilityPolicy(max_retries=2),
    )

    result = runtime.execute("always_timeout_tool", {})

    assert result.success is False
    assert result.error_code == "MAX_RETRIES_EXCEEDED"
    assert result.last_error_code == "TIMEOUT"
    assert result.retryable is False
    assert result.retry_count == 2
    assert len(result.attempts) == 3


def test_non_retryable_invalid_argument_runs_once() -> None:
    """相同非法参数不得因 max_retries 配置而重复执行。"""

    runtime = build_runtime(
        RequiredArgumentTool(),
        policy=ReliabilityPolicy(max_retries=5),
    )

    result = runtime.execute("required_argument_tool", {})

    assert result.error_code == "INVALID_ARGUMENT"
    assert result.retryable is False
    assert result.retry_count == 0
    assert len(result.attempts) == 1


def test_general_tool_timeout_returns_within_finite_time() -> None:
    """同步 Tool 超过通用 timeout 时应及时返回 retryable TIMEOUT。"""

    runtime = build_runtime(
        SlowTool(),
        policy=ReliabilityPolicy(max_retries=0, timeout_seconds=0.02),
    )
    started_at = time.perf_counter()

    result = runtime.execute("slow_tool", {})
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.2
    assert result.success is False
    assert result.error_code == "TIMEOUT"
    assert result.retryable is True
    assert len(result.attempts) == 1


def test_explicit_fallback_runs_after_allowed_primary_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """只有显式映射的 EXECUTION_FAILED 才应进入一级 Fallback。"""

    runtime = build_runtime(
        PrimaryFailTool(),
        FallbackSuccessTool(),
        policy=ReliabilityPolicy(
            max_retries=2,
            fallbacks={"primary_tool": "fallback_tool"},
        ),
    )
    caplog.set_level(logging.INFO, logger="issueops.tools")

    result = runtime.execute("primary_tool", {})

    assert result.success is True
    assert result.tool_name == "fallback_tool"
    assert result.fallback_from == "primary_tool"
    assert result.data == {"status": "fallback_ok"}
    assert result.retry_count == 0
    assert [item.tool_name for item in result.attempts] == [
        "primary_tool",
        "fallback_tool",
    ]
    assert [item.phase for item in result.attempts] == ["initial", "fallback"]
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_fallback" in logs
    assert "original_tool=primary_tool" in logs
    assert "fallback_tool=fallback_tool" in logs
    assert "reason=EXECUTION_FAILED" in logs


def test_invalid_argument_does_not_trigger_configured_fallback() -> None:
    """Fallback 映射不能覆盖不允许降级的 INVALID_ARGUMENT。"""

    runtime = build_runtime(
        RequiredArgumentTool(),
        FallbackSuccessTool(),
        policy=ReliabilityPolicy(
            fallbacks={"required_argument_tool": "fallback_tool"}
        ),
    )

    result = runtime.execute("required_argument_tool", {})

    assert result.error_code == "INVALID_ARGUMENT"
    assert result.fallback_from is None
    assert len(result.attempts) == 1


def test_attempt_budget_caps_retry_inside_one_logical_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """剩余全局预算不足时，Runtime 不得发起预算外 Retry。"""

    runtime = build_runtime(
        AlwaysTimeoutTool(),
        policy=ReliabilityPolicy(max_retries=5, max_tool_calls=20),
    )
    caplog.set_level(logging.INFO, logger="issueops.tools")

    result = runtime.execute("always_timeout_tool", {}, attempt_budget=2)

    assert result.error_code == "MAX_TOOL_CALLS_EXCEEDED"
    assert result.last_error_code == "TIMEOUT"
    assert result.retry_count == 1
    assert len(result.attempts) == 2
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_budget_exceeded" in logs
    assert "max_tool_calls=20" in logs


def test_structured_logs_include_stable_fields_without_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tool 日志应包含稳定字段，且绝不输出完整 arguments。"""

    runtime = build_runtime(
        SecretEchoTool(),
        policy=ReliabilityPolicy(max_retries=0),
    )
    caplog.set_level(logging.INFO, logger="issueops.tools")

    result = runtime.execute(
        "secret_echo_tool",
        {"token": "super-secret-token"},
        task_id="task-log",
        step_id=7,
    )

    assert result.success is True
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_execute" in logs
    assert "task_id=task-log" in logs
    assert "step_id=7" in logs
    assert "tool=secret_echo_tool" in logs
    assert "attempt=1" in logs
    assert "success=true" in logs
    assert "latency_ms=" in logs
    assert "super-secret-token" not in logs


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": 6},
        {"timeout_seconds": 0},
        {"timeout_seconds": 301},
        {"max_tool_calls": 0},
        {"max_tool_calls": 1_001},
        {"fallbacks": {"same": "same"}},
    ],
)
def test_policy_rejects_unbounded_or_cyclic_configuration(kwargs: dict) -> None:
    """所有循环与 timeout 配置必须满足显式硬上限。"""

    with pytest.raises(ValidationError):
        ReliabilityPolicy(**kwargs)
