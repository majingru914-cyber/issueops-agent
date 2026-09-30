"""唯一正式 Tool 执行入口与默认 Registry 构建器。"""

import logging
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.base import ToolAttemptRecord, ToolResult
from tools.filesystem import ListDirectoryTool, ReadFileTool
from tools.github import GetGitHubIssueTool, GetGitHubPullRequestTool
from tools.github_client import GitHubClient
from tools.registry import ToolNotFoundError, ToolRegistry
from tools.reliability import ErrorCode, ReliabilityPolicy, is_retryable
from tools.repository import SearchCodeTool


LOGGER = logging.getLogger("issueops.tools")


@dataclass(frozen=True)
class _SeriesOutcome:
    """Runtime 内部一次 Tool 及其 Retry 序列的结果。"""

    result: ToolResult
    attempts: list[ToolAttemptRecord]
    retry_count: int
    retries_exhausted: bool = False
    budget_exhausted: bool = False


class ToolRuntime:
    """通过 Registry 查找并统一调用 Tool。"""

    def __init__(
        self,
        registry: ToolRegistry,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or ReliabilityPolicy()

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        attempt_budget: int | None = None,
        task_id: str = "standalone",
        step_id: int = 0,
    ) -> ToolResult:
        """通过唯一入口执行受 Retry、Timeout、Fallback 和预算保护的请求。"""

        started_at = perf_counter()
        budget = self.policy.max_tool_calls if attempt_budget is None else attempt_budget
        if budget < 0:
            raise ValueError("attempt_budget 不能小于 0。")
        if budget == 0:
            return self._budget_exceeded_result(
                tool_name=tool_name,
                started_at=started_at,
                attempts=[],
                retry_count=0,
                task_id=task_id,
                step_id=step_id,
            )

        primary = self._execute_series(
            tool_name=tool_name,
            arguments=arguments,
            task_id=task_id,
            step_id=step_id,
            attempt_offset=0,
            attempt_budget=budget,
            is_fallback=False,
        )
        attempts = list(primary.attempts)
        retry_count = primary.retry_count

        if primary.budget_exhausted:
            return self._budget_exceeded_result(
                tool_name=tool_name,
                started_at=started_at,
                attempts=attempts,
                retry_count=retry_count,
                task_id=task_id,
                step_id=step_id,
                last_error_code=primary.result.error_code,
            )

        fallback_name = self.policy.fallback_for(tool_name, primary.result)
        if fallback_name is not None:
            LOGGER.warning(
                "event=tool_fallback task_id=%s step_id=%s original_tool=%s "
                "fallback_tool=%s reason=%s",
                task_id,
                step_id,
                tool_name,
                fallback_name,
                primary.result.error_code,
            )
            remaining_budget = budget - len(attempts)
            if remaining_budget <= 0:
                return self._budget_exceeded_result(
                    tool_name=tool_name,
                    started_at=started_at,
                    attempts=attempts,
                    retry_count=retry_count,
                    task_id=task_id,
                    step_id=step_id,
                    last_error_code=primary.result.error_code,
                )
            fallback = self._execute_series(
                tool_name=fallback_name,
                arguments=arguments,
                task_id=task_id,
                step_id=step_id,
                attempt_offset=len(attempts),
                attempt_budget=remaining_budget,
                is_fallback=True,
            )
            attempts.extend(fallback.attempts)
            retry_count += fallback.retry_count
            if fallback.budget_exhausted:
                return self._budget_exceeded_result(
                    tool_name=fallback_name,
                    started_at=started_at,
                    attempts=attempts,
                    retry_count=retry_count,
                    task_id=task_id,
                    step_id=step_id,
                    last_error_code=fallback.result.error_code,
                    fallback_from=tool_name,
                )
            final_result = self._exhaustion_result(fallback) or fallback.result
            return self._finalize_result(
                final_result,
                started_at=started_at,
                attempts=attempts,
                retry_count=retry_count,
                fallback_from=tool_name,
            )

        final_result = self._exhaustion_result(primary) or primary.result
        return self._finalize_result(
            final_result,
            started_at=started_at,
            attempts=attempts,
            retry_count=retry_count,
        )

    def _execute_series(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        task_id: str,
        step_id: int,
        attempt_offset: int,
        attempt_budget: int,
        is_fallback: bool,
    ) -> _SeriesOutcome:
        """执行一个 Tool 及其有限 Retry，不递归触发 Fallback。"""

        attempts: list[ToolAttemptRecord] = []
        retry_count = 0
        maximum_attempts = self.policy.max_retries + 1
        last_result: ToolResult | None = None

        for local_index in range(maximum_attempts):
            if len(attempts) >= attempt_budget:
                if last_result is None:
                    last_result = ToolResult(
                        success=False,
                        tool_name=tool_name or "unknown",
                        error_code=ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
                        error_message="Tool execution attempt 预算已耗尽。",
                    )
                return _SeriesOutcome(
                    result=last_result,
                    attempts=attempts,
                    retry_count=retry_count,
                    budget_exhausted=True,
                )

            attempt_number = attempt_offset + len(attempts) + 1
            if is_fallback:
                phase = "fallback" if local_index == 0 else "fallback_retry"
            else:
                phase = "initial" if local_index == 0 else "retry"
            if local_index > 0:
                retry_count += 1

            result, attempt = self._execute_attempt(
                tool_name=tool_name,
                arguments=arguments,
                attempt_number=attempt_number,
                phase=phase,
                task_id=task_id,
                step_id=step_id,
            )
            attempts.append(attempt)
            last_result = result

            if result.success or not is_retryable(result):
                return _SeriesOutcome(result, attempts, retry_count)
            if local_index + 1 < maximum_attempts:
                if len(attempts) >= attempt_budget:
                    return _SeriesOutcome(
                        result=result,
                        attempts=attempts,
                        retry_count=retry_count,
                        budget_exhausted=True,
                    )
                LOGGER.warning(
                    "event=tool_retry task_id=%s step_id=%s tool=%s retry=%s "
                    "reason=%s",
                    task_id,
                    step_id,
                    tool_name,
                    local_index + 1,
                    result.error_code,
                )

        assert last_result is not None
        return _SeriesOutcome(
            result=last_result,
            attempts=attempts,
            retry_count=retry_count,
            retries_exhausted=self.policy.max_retries > 0,
        )

    def _execute_attempt(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        attempt_number: int,
        phase: str,
        task_id: str,
        step_id: int,
    ) -> tuple[ToolResult, ToolAttemptRecord]:
        """在 daemon thread 中执行一次 Tool，并施加通用 wall-clock timeout。"""

        started_at = perf_counter()
        normalized_tool_name = tool_name or "unknown"
        try:
            tool = self.registry.get(tool_name)
        except ToolNotFoundError:
            result = ToolResult(
                success=False,
                tool_name=normalized_tool_name,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                error_message=f"未找到 Tool：{tool_name}",
                retryable=False,
                latency_ms=_elapsed_ms(started_at),
            )
        else:
            result_queue: queue.Queue[ToolResult | Exception] = queue.Queue(maxsize=1)

            def invoke_tool() -> None:
                """在线程边界内捕获 Runtime 之外的意外异常。"""

                try:
                    result_queue.put(tool.invoke(arguments))
                except Exception as error:  # pragma: no cover - 防御性边界
                    result_queue.put(error)

            worker = threading.Thread(
                target=invoke_tool,
                name=f"issueops-tool-{normalized_tool_name}",
                daemon=True,
            )
            worker.start()
            worker.join(self.policy.timeout_seconds)
            if worker.is_alive():
                result = ToolResult(
                    success=False,
                    tool_name=normalized_tool_name,
                    error_code=ErrorCode.TIMEOUT,
                    error_message=(
                        "Tool execution 超过通用 timeout："
                        f"{self.policy.timeout_seconds:g} 秒。"
                    ),
                    retryable=True,
                    latency_ms=_elapsed_ms(started_at),
                )
            else:
                try:
                    outcome = result_queue.get_nowait()
                except queue.Empty:  # pragma: no cover - 防御性边界
                    outcome = RuntimeError("Tool worker 未返回结果。")
                if isinstance(outcome, Exception):
                    result = ToolResult(
                        success=False,
                        tool_name=normalized_tool_name,
                        error_code=ErrorCode.EXECUTION_FAILED,
                        error_message=f"Tool Runtime 执行失败：{outcome}",
                        retryable=False,
                        latency_ms=_elapsed_ms(started_at),
                    )
                else:
                    result = outcome

        latency_ms = _elapsed_ms(started_at)
        attempt = ToolAttemptRecord(
            attempt=attempt_number,
            task_id=task_id,
            step_id=step_id,
            tool_name=result.tool_name,
            arguments=arguments,
            phase=phase,
            success=result.success,
            error_code=result.error_code,
            latency_ms=latency_ms,
        )
        LOGGER.info(
            "event=tool_execute task_id=%s step_id=%s tool=%s attempt=%s "
            "phase=%s success=%s error_code=%s latency_ms=%.3f",
            task_id,
            step_id,
            result.tool_name,
            attempt_number,
            phase,
            str(result.success).lower(),
            result.error_code or "none",
            latency_ms,
        )
        return result, attempt

    @staticmethod
    def _exhaustion_result(outcome: _SeriesOutcome) -> ToolResult | None:
        """Retry 真正发生且耗尽时返回稳定的终态错误。"""

        if not outcome.retries_exhausted:
            return None
        return ToolResult(
            success=False,
            tool_name=outcome.result.tool_name,
            error_code=ErrorCode.MAX_RETRIES_EXCEEDED,
            error_message=(
                "Tool Retry 已耗尽；最后错误为 "
                f"{outcome.result.error_code}：{outcome.result.error_message}"
            ),
            retryable=False,
            last_error_code=outcome.result.error_code,
        )

    @staticmethod
    def _finalize_result(
        result: ToolResult,
        *,
        started_at: float,
        attempts: list[ToolAttemptRecord],
        retry_count: int,
        fallback_from: str | None = None,
    ) -> ToolResult:
        """把最终结果与完整 trace 合并为权威 ToolResult。"""

        payload = result.model_dump(
            exclude={"latency_ms", "attempts", "retry_count", "fallback_from"}
        )
        return ToolResult.model_validate(
            {
                **payload,
                "latency_ms": _elapsed_ms(started_at),
                "attempts": [item.model_dump() for item in attempts],
                "retry_count": retry_count,
                "fallback_from": fallback_from,
            }
        )

    def _budget_exceeded_result(
        self,
        *,
        tool_name: str,
        started_at: float,
        attempts: list[ToolAttemptRecord],
        retry_count: int,
        task_id: str,
        step_id: int,
        last_error_code: str | None = None,
        fallback_from: str | None = None,
    ) -> ToolResult:
        """返回并记录全局 Tool attempt 预算耗尽结果。"""

        LOGGER.error(
            "event=tool_budget_exceeded task_id=%s step_id=%s tool=%s "
            "max_tool_calls=%s",
            task_id,
            step_id,
            tool_name or "unknown",
            self.policy.max_tool_calls,
        )
        return ToolResult(
            success=False,
            tool_name=tool_name or "unknown",
            error_code=ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
            error_message=(
                "Tool execution attempt 已达到上限 "
                f"{self.policy.max_tool_calls}，停止继续执行。"
            ),
            retryable=False,
            latency_ms=_elapsed_ms(started_at),
            attempts=attempts,
            retry_count=retry_count,
            fallback_from=fallback_from,
            last_error_code=last_error_code,
        )


def build_default_registry(
    workspace_root: Path,
    github_client: GitHubClient | None = None,
) -> ToolRegistry:
    """构建包含本地 Repository Tool 和只读 GitHub Tool 的 Registry。"""

    registry = ToolRegistry()
    registry.register(ListDirectoryTool(workspace_root))
    registry.register(ReadFileTool(workspace_root))
    registry.register(SearchCodeTool(workspace_root))
    shared_github_client = (
        github_client
        if github_client is not None
        else GitHubClient(token=os.getenv("GITHUB_TOKEN"))
    )
    registry.register(GetGitHubIssueTool(shared_github_client))
    registry.register(GetGitHubPullRequestTool(shared_github_client))
    return registry


def build_tool_runtime(
    workspace_root: Path,
    github_client: GitHubClient | None = None,
    policy: ReliabilityPolicy | None = None,
) -> ToolRuntime:
    """构建可直接使用的默认 ToolRuntime。"""

    return ToolRuntime(
        build_default_registry(workspace_root, github_client),
        policy=policy,
    )


def _elapsed_ms(started_at: float) -> float:
    """计算 Runtime 边界观察到的非负毫秒耗时。"""

    return max(0.0, (perf_counter() - started_at) * 1000)
