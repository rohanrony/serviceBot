# VoiceAI Development & Skill Mapping Guide

This document maps our active workspace skills to specific modules and coding files to ensure we adhere to best practices throughout the implementation.

---

## 1. Skill-to-Module Mapping

| Workspace Skill | Application in VoiceAI Codebase | Core Rules & Standards |
| :--- | :--- | :--- |
| [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro) | All Python files (`.py` backend and graph files) | - Use explicit typing (`typing.Dict`, `typing.Optional`, etc.).<br>- Strictly separate schemas, config, and logic.<br>- Maintain clean docstrings on all nodes and helper functions. |
| [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro) | API routes (`serviceBot/api/`) and server configurations | - Define clear Pydantic request/response schemas.<br>- Utilize dependency injection (`Depends`) for DB sessions and API clients.<br>- Use structured error handling (`HTTPException`). |
| [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design) | SQLite database manager (`serviceBot/db/`) | - Ensure foreign key support is enabled explicitly (`PRAGMA foreign_keys = ON`).<br>- Use connection context managers to prevent pool leakage.<br>- Place indexes on foreign keys and search columns (`phone`, `appointment_datetime`). |
| [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph) | Agent state engine (`serviceBot/graph/`) | - Define state explicitly with `TypedDict` and type annotations.<br>- Keep agent nodes pure (actions and messages transition in/out).<br>- Avoid routing logic inside agents; delegate to conditional router edges. |
| [`agent-evaluation`](file:///Users/rohanroy/voiceService/.agents/skills/agent-evaluation) | Testing suite (`tests/`) | - Mock external model APIs (OpenAI, Claude, ElevenLabs).<br>- Run assertion checks on intent classification accuracy and RAG precision.<br>- Maintain a regression transcript suite. |
| [`concise-planning`](file:///Users/rohanroy/voiceService/.agents/skills/concise-planning) | Task list tracking (`task.md`) | - Break work down into atomic, checklist-style items before coding.<br>- Mark progress incrementally (`[ ]` to `[/]` to `[x]`). |

---

## 2. Directory Structure Conventions

```
voiceService/
├── serviceBot/
│   ├── __init__.py
│   ├── main.py                 # FastAPI Entry Point (fastapi-pro)
│   ├── api/
│   │   ├── telephony.py        # Twilio & ElevenLabs Webhooks (fastapi-pro)
│   │   └── portal.py           # Portal Configuration REST APIs
│   ├── db/
│   │   ├── connection.py       # Connection pooling & managers (database-design)
│   │   └── queries.py          # CRM lookup & update queries
│   ├── graph/
│   │   ├── state.py            # TypedDict state definition (langgraph)
│   │   ├── nodes.py            # Agent nodes (service request, appointment, FAQ)
│   │   └── routing.py          # Conditional edge routing logic
│   └── services/
│       ├── calendar.py         # Google Calendar client
│       └── rag.py              # ChromaDB vector search utility (rag-implementation)
├── docs/
│   ├── PRD.md
│   └── specs/
│       ├── database_spec.md
│       ├── api_spec.md
│       └── agent_orchestration_spec.md
└── tests/                      # Verification testing suite (agent-evaluation)
```
