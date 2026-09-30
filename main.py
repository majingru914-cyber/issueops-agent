"""IssueOps Agent 命令行入口。"""

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent.runner import run_agent
from agent.schemas import (
    Evidence,
    ExecutionError,
    ReflectionResult,
    ReviewResult,
    TaskAnalysis,
    TaskPlan,
    ToolResultRecord,
)
from tools.runtime import build_tool_runtime
from memory import PersistenceError, SQLiteTaskStore


def configure_output_encoding() -> None:
    """确保 Windows 和重定向场景稳定输出 UTF-8。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def configure_logging() -> None:
    """为 CLI 启用可机器解析的稳定 key=value 日志。"""

    logging.basicConfig(level=logging.INFO, format="%(message)s")


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="运行 IssueOps Agent 最小工作流。")
    parser.add_argument("user_query", nargs="?", help="需要分析的软件研发任务。")
    parser.add_argument(
        "--load-task",
        metavar="TASK_ID",
        help="读取已持久化任务及其状态历史和执行 trace。",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite 文件路径；默认使用 data/issueops.db。",
    )
    return parser


def format_persisted_task(store: SQLiteTaskStore, task_id: str) -> str | None:
    """格式化任务元数据、最近状态、状态历史和 trace。"""

    task = store.load_task(task_id)
    if task is None:
        return None
    result = {
        "task": task.metadata.model_dump(mode="json"),
        "latest_state": task.latest_state,
        "state_history": [
            {
                "sequence": item.sequence,
                "stage": item.stage,
                "created_at": item.created_at.isoformat(),
            }
            for item in store.list_state_history(task_id)
        ],
        "trace": [item.model_dump(mode="json") for item in store.list_trace(task_id)],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_result(final_state: dict[str, object]) -> str:
    """验证并格式化 LangGraph 的最终状态。"""

    analysis = TaskAnalysis.model_validate(
        {
            "task_type": final_state.get("task_type"),
            "goal": final_state.get("goal"),
            "required_capabilities": final_state.get("required_capabilities"),
        }
    )
    plan = TaskPlan.model_validate({"steps": final_state.get("plan")})
    evidence = [
        Evidence.model_validate(item) for item in final_state.get("evidence", [])
    ]
    errors = [
        ExecutionError.model_validate(item) for item in final_state.get("errors", [])
    ]
    tool_results = [
        ToolResultRecord.model_validate(item)
        for item in final_state.get("tool_results", [])
    ]
    review = (
        ReviewResult.model_validate(final_state.get("review"))
        if final_state.get("review")
        else None
    )
    reflection = (
        ReflectionResult.model_validate(final_state.get("reflection"))
        if final_state.get("reflection")
        else None
    )
    result = {
        **analysis.model_dump(),
        "task_id": final_state.get("task_id", ""),
        "plan": [step.model_dump() for step in plan.steps],
        "tool_calls": final_state.get("tool_calls", []),
        "tool_results": [
            {
                "step_id": item.step_id,
                "tool_name": item.result.tool_name,
                "success": item.result.success,
                "error_code": item.result.error_code,
                "retryable": item.result.retryable,
                "attempt_count": len(item.result.attempts),
                "retry_count": item.result.retry_count,
                "fallback_from": item.result.fallback_from,
                "last_error_code": item.result.last_error_code,
            }
            for item in tool_results
        ],
        "tool_call_count": final_state.get("tool_call_count", 0),
        "retry_count": final_state.get("retry_count", 0),
        "execution_attempts": final_state.get("execution_attempts", []),
        "evidence": [item.model_dump(exclude={"raw_result"}) for item in evidence],
        "errors": [item.model_dump() for item in errors],
        "draft_answer": final_state.get("draft_answer", ""),
        "review_score": final_state.get("review_score", 0.0),
        "review_passed": final_state.get("review_passed", False),
        "review": review.model_dump() if review else None,
        "reflection_count": final_state.get("reflection_count", 0),
        "reflection": reflection.model_dump() if reflection else None,
        "replan_count": final_state.get("replan_count", 0),
        "final_answer": final_state.get("final_answer", ""),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """运行 CLI，并以退出码表达执行结果。"""

    configure_output_encoding()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.load_task and args.user_query is not None:
        print("错误：--load-task 不能与用户请求同时使用。", file=sys.stderr)
        return 2

    if args.user_query is None and not args.load_task:
        parser.print_usage(sys.stderr)
        print("错误：必须提供用户请求。", file=sys.stderr)
        return 2

    user_query = args.user_query.strip() if args.user_query is not None else ""
    if args.user_query is not None and not user_query:
        print("错误：用户请求不能为空。", file=sys.stderr)
        return 2

    try:
        database_path = args.database or Path(
            os.environ.get("ISSUEOPS_DB_PATH", "data/issueops.db")
        )
        with SQLiteTaskStore(database_path) as store:
            if args.load_task:
                persisted = format_persisted_task(store, args.load_task)
                if persisted is None:
                    print(f"错误：任务不存在：{args.load_task}", file=sys.stderr)
                    return 1
                print(persisted)
                return 0

            runtime = build_tool_runtime(Path.cwd())
            final_state = run_agent(user_query, runtime, store=store)
            print(format_result(final_state))
    except (PersistenceError, ValueError, ValidationError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
