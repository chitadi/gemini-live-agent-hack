# gemini-live-agent-hack

Boilerplate for a Google ADK Python project with a live Gemini coordinator agent, pluggable tools, and subagents.

## ADK Flow Diagram

```mermaid
flowchart TD
    U[User]
    A[Main Agent<br/>agents/agent.py (root_agent)]
    I[Coordinator Instructions<br/>agents/instructions.md]
    S1[Subagent 1<br/>subagents/subagent1/agent_factory.py]
    S2[Subagent 2<br/>subagents/subagent2/agent_factory.py]
    T1[Tool 1<br/>tools/tool1.py]
    T2[Tool 2<br/>tools/tool2.py]
    L[Tool Loader<br/>loader.py]

    U -->|Request| A
    I -->|System instructions| A
    L -->|Load tool callables| A
    A -->|Instructions + task context| S1
    A -->|Instructions + task context| S2
    S1 -->|Tool call| T1
    S2 -->|Tool call| T2
    T1 -->|Tool output| S1
    T2 -->|Tool output| S2
    S1 -->|Subagent result| A
    S2 -->|Subagent result| A
    A -->|Final response| U
```

## Directory Structure

```txt
gemini-live-agent-hack/
├── agents/
│   ├── __init__.py
│   ├── agent.py
│   └── instructions.md
├── subagents/
│   ├── __init__.py
│   ├── subagent1/
│   │   ├── __init__.py
│   │   ├── agent_factory.py
│   │   └── instructions.md
│   └── subagent2/
│       ├── __init__.py
│       ├── agent_factory.py
│       └── instructions.md
├── loader.py
├── tools/
│   ├── __init__.py
│   ├── tool1.py
│   └── tool2.py
├── refs/
│   ├── llms.txt
│   └── llms-full.txt
├── .gitignore
└── README.md
```

## ADK Notes

- `agents/agent.py` defines `root_agent` (ADK convention).
- `agents/__init__.py` exposes the module for ADK discovery.
- `loader.py` centralizes tool registration for the coordinator.
- Default model is `gemini-2.5-flash-live-001`; override with `ADK_LIVE_MODEL`.

## Quick Start

1. Install ADK:

```bash
pip install google-adk
```

2. Configure `.env` in repo root:

```env
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=<your-key>
ADK_LIVE_MODEL=gemini-2.5-flash-live-001
```

3. Run ADK web UI from repo root:

```bash
adk web
```

Then select the `agents` package in the UI.
