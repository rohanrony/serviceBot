# VoiceAI Implementation Checklist (tasks.md)

This document serves as the master checklist to implement the VoiceAI inbound call handling platform. Development must follow a strict **TDD (Test-Driven Development)** pattern (Red, Green, Refactor) inside each story.

---

## Workspace References & Skill Guide

Before starting any task, read these specs and use the recommended workspace skills:
*   **Architectural Decisions**: [adr.md](file:///Users/rohanroy/voiceService/docs/specs/adr.md)
*   **Database Design**: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md) — active skill: [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design)
*   **API & Integration Contracts**: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md) — active skill: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro)
*   **LangGraph Orchestration**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md) — active skill: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph)
*   **Python Best Practices**: [SKILLS_USAGE.md](file:///Users/rohanroy/voiceService/docs/SKILLS_USAGE.md) — active skill: [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro)
*   **RAG Ingestion & Querying**: active skills: [`rag-engineer`](file:///Users/rohanroy/voiceService/.agents/skills/rag-engineer), [`rag-implementation`](file:///Users/rohanroy/voiceService/.agents/skills/rag-implementation)

---

## Project Directory Scaffolding Structure

```
voiceService/
├── serviceBot/
│   ├── __init__.py
│   ├── main.py                 # FastAPI Web Server Entry Point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── telephony.py        # Twilio & ElevenLabs Telephony Webhooks
│   │   └── portal.py           # Portal Configuration & Dashboard APIs
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py       # SQLite Pool & Context Manager
│   │   └── queries.py          # CRM Lookup & Update Queries
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py            # LangGraph State Schema (AgentState)
│   │   ├── nodes.py            # Sub-agent implementations (nodes)
│   │   └── routing.py          # LangGraph Workflow compilation & conditional edges
│   └── services/
│       ├── __init__.py
│       └── rag.py              # ChromaDB client & vector search utilities
├── tests/
│   ├── __init__.py
│   ├── test_db_connection.py   # DB setup tests
│   ├── test_db_queries.py      # CRM lookup tests
│   ├── test_telephony_webhook.py # Twilio/TwiML response tests
│   ├── test_intent_classifier.py # Intent classification tests
│   ├── test_service_request_agent.py # Service request collection tests
│   ├── test_appointment_agent.py # Calendar booking slots tests
│   ├── test_rag_faq.py          # FAQ semantic retrieval tests
│   ├── test_handoff.py          # Handoff context & summary tests
│   └── test_portal_api.py       # Config REST API tests
└── voice_service.db             # Local SQLite database (Auto-created)
```

---

## 🛠️ Step-by-Step Implementation Stories

### Story 1: Project Setup & Database Schema Initialization
*   **Goal**: Initialize folders, connection manager, and create SQLite schemas/mock tables.
*   **Skills**: [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design), [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_db_connection.py`. Assert that connection manager exists, database file compiles, foreign keys are turned ON (`PRAGMA foreign_keys = ON;`), and all tables (`customers`, `vehicles`, `service_requests`, `appointments`, `crm_notes`, `mock_calendar_slots`) exist. Verify test fails.
    - [x] Create folder scaffolding structure.
    - [x] **TDD Green**: Implement `serviceBot/db/connection.py` connection manager context block using raw sqlite3.
    - [x] **TDD Green**: Run DDL script to generate database schemas on application startup.
    - [x] **TDD Green**: Create `serviceBot/db/seed.py` script to seed initial demo data (Sarah Johnson, Honda Civic, Brake repair request, mock calendar times).
    - [x] **TDD Refactor**: Run `pytest tests/test_db_connection.py` and ensure they pass. Refactor context block for safety.
*   **CLI Verification**:
    ```bash
    python3 -m serviceBot.db.seed
    sqlite3 voice_service.db "SELECT * FROM customers;"
    sqlite3 voice_service.db "SELECT * FROM mock_calendar_slots;"
    ```

---

### Story 2: Pre-Call CRM Lookup Endpoint & Queries
*   **Goal**: Create optimized SQL queries to query active caller context by phone number.
*   **Skills**: [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_db_queries.py`. Assert that `lookup_customer_by_phone("+15551234567")` returns full profile details, vehicle array, and active/pending service request. Assert unknown phone numbers return empty fields instead of throwing exceptions. Verify test fails.
    - [x] **TDD Green**: Implement `serviceBot/db/queries.py` using LEFT JOIN statements to match specs.
    - [x] **TDD Refactor**: Run tests to ensure complete coverage. Check query efficiency and resource closing.
*   **CLI Verification**:
    ```bash
    pytest tests/test_db_queries.py -v
    ```

---

### Story 3: Inbound Call Telephony Webhook (Twilio Route)
*   **Goal**: Accept Twilio telephony payload and return dynamic ElevenLabs Agent ID TwiML.
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_telephony_webhook.py` asserting that `POST /api/v1/telephony/inbound` returns `application/xml` headers and includes the correct ElevenLabs `<ConversationAgent>` details. Verify test fails.
    - [x] **TDD Green**: Initialize FastAPI server entry in `serviceBot/main.py`.
    - [x] **TDD Green**: Create webhook route in `serviceBot/api/telephony.py` resolving configured `agentId` dynamically from settings/env.
    - [x] **TDD Refactor**: Refactor XML string formatting to use safe builders.
*   **CLI Verification**:
    ```bash
    pytest tests/test_telephony_webhook.py -v
    ```

---

### Story 4: LangGraph Intent Classifier Node & Routing Graph
*   **Goal**: Initialize LangGraph DAG state workflow and build intent classifier LLM prompt routing.
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_intent_classifier.py` asserting that invoking the compiled state graph with booking or FAQ queries routes execution to target sub-agent states correctly. Verify test fails.
    - [x] **TDD Green**: Define state schema in `serviceBot/graph/state.py`.
    - [x] **TDD Green**: Build the intent classifier LLM parsing logic returning structured JSON.
    - [x] **TDD Green**: Set up routing conditional transitions inside `serviceBot/graph/routing.py`.
    - [x] **TDD Refactor**: Clean up the LLM prompting structure to avoid classification drift.
*   **CLI Verification**:
    ```bash
    pytest tests/test_intent_classifier.py -v
    ```

---

### Story 5: Service Request Node & CRM Updates
*   **Goal**: Create sub-agent node that gathers details sequentially and saves a new service request.
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_service_request_agent.py` asserting that user inputs representing name, phone, make, model, year, and issue populate the state, call DB query inserts, and update state with `service_request_id`. Verify test fails.
    - [x] **TDD Green**: Write `service_request_node` in `serviceBot/graph/nodes.py`.
    - [x] **TDD Green**: Implement SQLite queries for inserting requests and vehicles.
    - [x] **TDD Refactor**: Ensure node doesn't loop forever if details are missing.
*   **CLI Verification**:
    ```bash
    pytest tests/test_service_request_agent.py -v
    ```

---

### Story 6: Appointment Booking Node & Scheduling Integrations
*   **Goal**: Query availability slots and schedule appointments against local mock calendar data.
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_appointment_agent.py` asserting checking availability returns database records, and booking writes slot state as booked. Verify test fails.
    - [x] **TDD Green**: Create `appointment_booking_node` logic.
    - [x] **TDD Green**: Implement local mock calendar check and update queries.
    - [x] **TDD Refactor**: Ensure slot locking handles race conditions safely.
*   **CLI Verification**:
    ```bash
    pytest tests/test_appointment_agent.py -v
    ```

---

### Story 7: FAQ RAG Node (Vector Store Search)
*   **Goal**: Chunk and store knowledge data in ChromaDB, and query semantic context for natural voice replies.
*   **Skills**: [`rag-engineer`](file:///Users/rohanroy/voiceService/.agents/skills/rag-engineer), [`rag-implementation`](file:///Users/rohanroy/voiceService/.agents/skills/rag-implementation)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_rag_faq.py` asserting search queries retrieve corresponding database chunks, and LLM utilizes only the provided search results to answer. Verify test fails.
    - [x] **TDD Green**: Set up persistent local ChromaDB helper in `serviceBot/services/rag.py`.
    - [x] **TDD Green**: Build `faq_node` execution logic returning context-based streaming prompts.
    - [x] **TDD Refactor**: Validate performance latency is strictly below 500ms.
*   **CLI Verification**:
    ```bash
    pytest tests/test_rag_faq.py -v
    ```

---

### Story 8: Human Handoff Node
*   **Goal**: Summarize active conversation context to construct transfer telemetry payload.
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_handoff.py` verifying caller transcripts compile into a clear 3-5 bullet summary containing customer identity and issue context. Verify test fails.
    - [x] **TDD Green**: Create `handoff_node` and summary templates.
    - [x] **TDD Refactor**: Clean up the summary prompt format to preserve context structure.
*   **CLI Verification**:
    ```bash
    pytest tests/test_handoff.py -v
    ```

---

### Story 9: Configuration Portal REST APIs
*   **Goal**: Expose management endpoints for services listing, logs retrieval, and secure API key storage.
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_portal_api.py` asserting portal CRUD and API key encryption operations validate payload structure correctly. Verify test fails.
    - [x] **TDD Green**: Create router `serviceBot/api/portal.py` implementing REST schemas.
    - [x] **TDD Green**: Implement AES-256 encryption helper utilizing local key storage.
    - [x] **TDD Refactor**: Verify secure payload encryption integrity.
*   **CLI Verification**:
    ```bash
    pytest tests/test_portal_api.py -v
    ```

---

### Story 10: Backend Portal Enhancements (Call Logs & KB Indexing API)
*   **Goal**: Implement the remaining backend endpoints for fetching caller transcript logs and uploading/indexing documents in ChromaDB.
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design), [`rag-engineer`](file:///Users/rohanroy/voiceService/.agents/skills/rag-engineer)
*   **Tasks**:
    - [x] **TDD Red**: Add tests to `tests/test_portal_api.py` asserting `GET /api/v1/portal/calls` and `POST /api/v1/portal/kb/upload` endpoints return structured logs and chunk counts. Verify tests fail.
    - [x] **TDD Green**: Implement SQLite queries joining `crm_notes` and `customers` to retrieve call history.
    - [x] **TDD Green**: Implement the `/api/v1/portal/calls` endpoint.
    - [x] **TDD Green**: Write `/api/v1/portal/kb/upload` endpoint using `UploadFile` and process bytes using ChromaDB client helpers.
    - [x] **TDD Refactor**: Ensure resources are handled cleanly and tests pass.
*   **CLI Verification**:
    ```bash
    pytest tests/test_portal_api.py -v
    ```

---

### Story 11: Configuration Portal Frontend (HTML/CSS/JS Assets)
*   **Goal**: Implement the client-side single page app for the configuration dashboard.
*   **Skills**: [`webapp-testing`](file:///Users/rohanroy/voiceService/.agents/skills/webapp-testing), [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro)
*   **Tasks**:
    - [x] **TDD Red**: Create a basic Playwright UI test verifying that the portal frontend loads, displays dynamic sections, and exposes configuration tabs. Verify tests fail.
    - [x] **TDD Green**: Mount static assets directory `/serviceBot/static` in `serviceBot/main.py`.
    - [x] **TDD Green**: Create `serviceBot/static/index.html` structure with responsive grid cards and form fields.
    - [x] **TDD Green**: Implement `serviceBot/static/style.css` glassmorphic theme.
    - [x] **TDD Green**: Write `serviceBot/static/app.js` routing logic and AJAX requests.
    - [x] **TDD Refactor**: Refactor styles and animations for high-end look and feel.
*   **CLI Verification**:
    - Manually test: Open browser to `http://localhost:8000/` and verify layout.
