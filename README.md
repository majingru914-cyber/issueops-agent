# IssueOps Agent

## Overview

IssueOps Agent is a LangGraph-based autonomous agent for software engineering
tasks such as GitHub Issue analysis, repository inspection, tool execution,
evidence collection, review, reflection and replanning.

This repository currently contains only the project foundation. Agent behavior
and integrations will be implemented incrementally in later stages.

## Goal

Build a reliable, locally runnable, and evaluable software-engineering agent
with a clear architecture and verifiable behavior.

## Core Pipeline

The planned pipeline is:

```text
Analyze
→ Plan
→ Execute
→ Evidence
→ Generate
→ Review
→ Reflect
→ Re-plan
→ Final
```

## Current Status

**Stage 00 — Repository Bootstrap**

Only the repository structure, dependency declarations, engineering rules, and
bootstrap tests are present. Tool calling, GitHub Issue analysis, reflection,
evaluation, API endpoints, and deployment are future work and are not yet
implemented.

## Project Structure

```text
issueops-agent/
├── agent/          # Future agent package
├── api/            # Future API package
├── docs/           # Project documentation
├── eval/           # Future evaluation assets and reports
├── examples/       # Usage examples added in later stages
├── memory/         # Future persistence package
├── tests/          # Automated tests
└── tools/          # Future tool package
```

## Requirements

- Python 3.12 or newer
- `venv` support
- `pip`

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Tests

Run the test suite from the repository root:

```bash
python -m pytest
```

## Development Roadmap

- Stage 00: repository bootstrap
- Stage 01 onward: introduce the agent workflow in small, tested increments

The implementation roadmap is intentionally prospective; Stage 00 does not
claim any agent workflow or external integration as complete.
