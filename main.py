"""IssueOps Agent 命令行入口。"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent.graph import build_agent_graph
from agent.schemas import Evidence, ExecutionError, TaskAnalysis, TaskPlan, ToolResultRecord
from tools.runtime import build_tool_runtime


def configure_output_encoding() -> None:
    """确保 Windows 和重定向场景稳定输出 UTF-8。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="运行 IssueOps Agent 最小工作流。")
    parser.add_argument("user_query", nargs="?", help="需要分析的软件研发任务。")
    return parser


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
    result = {
        **analysis.model_dump(),
        "plan": [step.model_dump() for step in plan.steps],
        "tool_calls": final_state.get("tool_calls", []),
        "tool_results": [
            {
                "step_id": item.step_id,
                "tool_name": item.result.tool_name,
                "success": item.result.success,
                "error_code": item.result.error_code,
            }
            for item in tool_results
        ],
        "evidence": [item.model_dump(exclude={"raw_result"}) for item in evidence],
        "errors": [item.model_dump() for item in errors],
        "final_answer": final_state.get("final_answer", ""),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """运行 CLI，并以退出码表达执行结果。"""

    configure_output_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.user_query is None:
        parser.print_usage(sys.stderr)
        print("错误：必须提供用户请求。", file=sys.stderr)
        return 2

    user_query = args.user_query.strip()
    if not user_query:
        print("错误：用户请求不能为空。", file=sys.stderr)
        return 2

    try:
        runtime = build_tool_runtime(Path.cwd())
        graph = build_agent_graph(runtime)
        final_state = graph.invoke({"user_query": user_query})
        print(format_result(final_state))
    except (ValueError, ValidationError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
