"""把 ToolResult 转换为可追踪 Evidence 或 ExecutionError。"""

import json
from typing import Any

from agent.schemas import Evidence, ExecutionError, ToolResultRecord
from agent.state import AgentState


def collect_evidence(state: AgentState) -> dict[str, object]:
    """处理最近一次 ToolResult，不执行重试或重新规划。"""

    raw_results = state.get("tool_results", [])
    if not raw_results:
        return {}

    result_record = ToolResultRecord.model_validate(raw_results[-1])
    result = result_record.result
    if result.success:
        evidence = Evidence(
            step_id=result_record.step_id,
            source=result.tool_name,
            summary=_summarize_result(result.tool_name, result.data),
            raw_result=result.data,
        )
        return {
            "evidence": [
                *state.get("evidence", []),
                evidence.model_dump(),
            ]
        }

    error = ExecutionError(
        step_id=result_record.step_id,
        source=result.tool_name,
        error_code=result.error_code or "EXECUTION_FAILED",
        error_message=result.error_message or "Tool 执行失败。",
    )
    return {
        "errors": [
            *state.get("errors", []),
            error.model_dump(),
        ]
    }


def _summarize_result(tool_name: str, data: Any) -> str:
    """仅依据真实 Tool data 生成确定性摘要。"""

    if not isinstance(data, dict):
        return f"{tool_name} 返回：{_compact(data)}"

    if tool_name == "list_directory":
        entries = data.get("entries", [])
        names = [entry.get("name", "") for entry in entries if isinstance(entry, dict)]
        return (
            f"目录 {data.get('path', '.')} 包含 {len(entries)} 个直接子项："
            f"{', '.join(names[:12]) or '无'}。"
        )
    if tool_name == "read_file":
        content = str(data.get("content", ""))
        preview = " ".join(content.split())[:240]
        return (
            f"已读取 {data.get('path', '')}，得到 {len(content)} 个字符，"
            f"truncated={bool(data.get('truncated'))}；内容摘要：{preview}"
        )
    if tool_name == "search_code":
        matches = data.get("matches", [])
        locations = []
        for match in matches[:8]:
            if isinstance(match, dict):
                locations.append(
                    f"{match.get('path', '')}:{match.get('line_number', '')} "
                    f"{match.get('line', '')}"
                )
        return (
            f"搜索 {data.get('query', '')!r} 得到 {len(matches)} 处匹配："
            f"{'；'.join(locations) or '无匹配'}。"
        )
    if tool_name == "get_github_issue":
        return (
            f"GitHub Issue {data.get('owner')}/{data.get('repo')}#{data.get('number')} "
            f"标题为“{data.get('title', '')}”，状态为 {data.get('state', '')}，"
            f"评论数 {data.get('comments', 0)}。"
        )
    if tool_name == "get_github_pr":
        return (
            f"GitHub PR {data.get('owner')}/{data.get('repo')}#{data.get('number')} "
            f"标题为“{data.get('title', '')}”，状态为 {data.get('state', '')}，"
            f"分支 {data.get('head_branch', '')} → {data.get('base_branch', '')}。"
        )
    return f"{tool_name} 返回：{_compact(data)}"


def _compact(value: Any) -> str:
    """生成有长度上限的 JSON 摘要。"""

    return json.dumps(value, ensure_ascii=False, default=str)[:300]
