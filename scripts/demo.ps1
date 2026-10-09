[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$BaseUrl = "http://127.0.0.1:8000",

    [ValidateNotNullOrEmpty()]
    [string]$Query = "查找项目中 AgentState 的定义",

    [ValidateRange(1, 240)]
    [int]$MaxPollAttempts = 80,

    [ValidateRange(50, 10000)]
    [int]$PollIntervalMs = 250
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd("/")

$health = Invoke-RestMethod -Method Get -Uri "$base/health" -TimeoutSec 5
if ($health.status -ne "healthy") {
    throw "服务健康检查失败：status=$($health.status)"
}

$payload = @{ query = $Query } | ConvertTo-Json -Compress
$body = [System.Text.Encoding]::UTF8.GetBytes($payload)
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$created = Invoke-RestMethod `
    -Method Post `
    -Uri "$base/tasks" `
    -ContentType "application/json; charset=utf-8" `
    -Body $body `
    -TimeoutSec 10
$watch.Stop()

if ([string]::IsNullOrWhiteSpace($created.task_id)) {
    throw "POST /tasks 未返回 task_id。"
}

$task = $null
for ($attempt = 1; $attempt -le $MaxPollAttempts; $attempt++) {
    $task = Invoke-RestMethod `
        -Method Get `
        -Uri "$base/tasks/$($created.task_id)" `
        -TimeoutSec 5

    if ($task.status -in @("completed", "partial", "failed")) {
        break
    }

    Start-Sleep -Milliseconds $PollIntervalMs
}

if ($null -eq $task -or $task.status -notin @("completed", "partial", "failed")) {
    throw "任务未在有限轮询内进入终态：task_id=$($created.task_id)"
}

$trace = Invoke-RestMethod `
    -Method Get `
    -Uri "$base/trace?task_id=$($created.task_id)" `
    -TimeoutSec 5

[pscustomobject]@{
    service = $health.service
    health = $health.status
    post_latency_ms = $watch.ElapsedMilliseconds
    task_id = $created.task_id
    initial_status = $created.status
    final_status = $task.status
    review_passed = $task.review_passed
    tool_call_count = $task.tool_call_count
    retry_count = $task.retry_count
    reflection_count = $task.reflection_count
    final_answer = $task.final_answer
    trace_event_count = @($trace.events).Count
    trace_event_types = @($trace.events | ForEach-Object { $_.event_type })
} | ConvertTo-Json -Depth 8
