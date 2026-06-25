# AI Agent Implementation Prompts (tasks-prompts.md)

This document contains isolated, copy-pasteable prompts designed to direct AI coding agents to implement and verify each story phase-by-phase.

> [!IMPORTANT]
> **Instructions for the Agent:**
> 1. For each Story, execute the **[RED] Prompt** first to define the test contract.
> 2. Once the test fails, execute the **[GREEN/REFACTOR] Prompt** to implement the logic.
> 3. Verify all tests pass, then edit the master checklist in [tasks.md](file:///Users/rohanroy/voiceService/docs/tasks.md) and cross off (`[x]`) completed tasks.

---

## Story 1: Project Setup & Database Schema Initialization

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are an expert QA and backend engineer initializing the database layer of the VoiceAI platform.
Your task is to write a failing test file establishing the SQLite database schema and connection contract.

Please implement:
1. File: `tests/test_db_connection.py`
2. Assertions:
   - Verify that an SQLite connection can be opened.
   - Assert that 'PRAGMA foreign_keys = ON;' is successfully enforced on connection initialization.
   - Assert that these tables exist: `customers`, `vehicles`, `service_requests`, `appointments`, `crm_notes`, and `mock_calendar_slots`.
3. Validation: Run `pytest tests/test_db_connection.py` and verify that it fails (due to missing module/database).

References:
- Database Schema details: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
- Architectural context: [adr.md](file:///Users/rohanroy/voiceService/docs/specs/adr.md)
- Skills to use: 'python-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a backend engineer. Having written the failing connection test, your task is to implement the connection manager and table creation.

Please implement:
1. File: `serviceBot/db/connection.py`
   - Setup a context manager (e.g., `get_db_connection()`) yielding a connection.
   - Execute DDL schemas on startup matching [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md).
2. File: `serviceBot/db/seed.py`
   - Seed initial records: customer (Sarah Johnson), vehicle (Honda Civic), pending service requests, and mock calendar slots.
3. Validation: Run the seed script and then run pytest to ensure tests pass.
   - Run `python3 -m serviceBot.db.seed`
   - Run `pytest tests/test_db_connection.py`
4. Checklist Update: Mark Story 1 as complete ([x]) inside `docs/tasks.md`.

Skills to use: 'database-design', 'python-pro', 'tdd-workflow'
```

---

## Story 2: Pre-Call CRM Lookup Endpoint & Queries

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a QA engineer. Your task is to write a failing test checking the pre-call CRM lookup queries.

Please implement:
1. File: `tests/test_db_queries.py`
2. Assertions:
   - Mock a database session with seeded customer data.
   - Assert that `lookup_customer_by_phone("+15551234567")` returns the matching customer dictionary shape defined in `database_spec.md` Section 3.1.
   - Assert that lookup for a new phone number returns empty details instead of throwing exceptions.
3. Validation: Run `pytest tests/test_db_queries.py` and confirm the tests fail.

References:
- Query contracts: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
- Skills to use: 'python-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a database engineer. Your task is to implement the pre-call CRM queries so our test suite passes.

Please implement:
1. File: `serviceBot/db/queries.py`
   - Write `lookup_customer_by_phone(phone: str) -> dict` using raw LEFT JOINs across customers, vehicles, and pending service requests.
2. Validation: Run `pytest tests/test_db_queries.py` and ensure they pass. Refactor database resource cleanup.
3. Checklist Update: Mark Story 2 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'database-design', 'python-pro', 'tdd-workflow'
```

---

## Story 3: Inbound Call Telephony Webhook (Twilio Route)

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are an API tester. Your task is to write a failing test verifying the inbound Twilio telephony webhook.

Please implement:
1. File: `tests/test_telephony_webhook.py`
2. Assertions:
   - Use `fastapi.testclient.TestClient`.
   - Assert that `POST /api/v1/telephony/inbound` returns HTTP 200 OK.
   - Assert that the response Content-Type is `application/xml`.
   - Assert that the response body contains TwiML `<Connect>` and `<ConversationAgent>` tags wrapping the resolved `agentId` variable.
3. Validation: Run `pytest tests/test_telephony_webhook.py` and confirm that it fails.

References:
- Telephony specifications: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
- Skills to use: 'fastapi-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a backend API engineer. Your task is to implement the webhook routing.

Please implement:
1. File: `serviceBot/main.py`
   - Initialize FastAPI app with `GET /health` returning status healthy.
2. File: `serviceBot/api/telephony.py`
   - Create router endpoint `POST /api/v1/telephony/inbound`.
   - Read ElevenLabs Agent ID configurations from `.env` dynamically and respond with structured TwiML XML.
3. Validation: Run `pytest tests/test_telephony_webhook.py` and ensure it passes.
4. Checklist Update: Mark Story 3 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'fastapi-pro', 'python-pro', 'tdd-workflow'
```

---

## Story 4: LangGraph Intent Classifier Node & Routing Graph

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a LangGraph QA Engineer. Your task is to write a failing test verifying the intent classifier node routing.

Please implement:
1. File: `tests/test_intent_classifier.py`
2. Assertions:
   - Initialize dummy graph execution.
   - Mock LLM invocation.
   - Assert that passing "I need to schedule brake repair" updates state `current_agent = "appointment"`.
   - Assert that greeting inputs update state `current_agent = "classifier"`.
3. Validation: Run `pytest tests/test_intent_classifier.py` and confirm that it fails.

References:
- Graph definitions: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
- Skills to use: 'langgraph', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are an AI Agent Architect. Your task is to build the LangGraph intent routing layer.

Please implement:
1. File: `serviceBot/graph/state.py`
   - Define the shared `AgentState` TypedDict structure.
2. File: `serviceBot/graph/nodes.py`
   - Write `intent_classifier_node(state: AgentState)` executing LLM calls with structured JSON output templates.
3. File: `serviceBot/graph/routing.py`
   - Define routing edges compiling the state graph workflow.
4. Validation: Run `pytest tests/test_intent_classifier.py` and ensure they pass. Refactor prompts to prevent classification errors.
5. Checklist Update: Mark Story 4 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'langgraph', 'python-pro', 'tdd-workflow'
```

---

## Story 5: Service Request Node & CRM Updates

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a QA engineer. Your task is to write a failing test verifying service request collection state.

Please implement:
1. File: `tests/test_service_request_agent.py`
2. Assertions:
   - Mock the graph and LLM responses.
   - Assert that if vehicle fields are missing, the agent emits follow-up questions.
   - Assert that once name, phone, make, model, year, and issue are present, the agent invokes `create_service_request()` and updates `service_request_id`.
3. Validation: Run `pytest tests/test_service_request_agent.py` and confirm it fails.

References:
- Node definitions: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
- Skills to use: 'langgraph', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a LangGraph developer. Your task is to implement the service request node.

Please implement:
1. File: `serviceBot/graph/nodes.py`
   - Write `service_request_node` logic prompt and functional tool `create_service_request()`.
2. Validation: Run the test suite to ensure the node gathers fields and inserts SQLite records correctly.
3. Checklist Update: Mark Story 5 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'langgraph', 'database-design', 'tdd-workflow'
```

---

## Story 6: Appointment Booking Node & Scheduling Integrations

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a QA engineer. Your task is to write a failing test verifying the mock calendar scheduling logic.

Please implement:
1. File: `tests/test_appointment_agent.py`
2. Assertions:
   - Mock appointment states and calendar queries.
   - Assert `check_availability()` returns only unbooked slots.
   - Assert `book_appointment()` changes the database slot state `is_booked = 1`.
3. Validation: Run `pytest tests/test_appointment_agent.py` and verify it fails.

References:
- Database spec: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
- Skills to use: 'langgraph', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a LangGraph developer. Your task is to implement the appointment scheduling node.

Please implement:
1. File: `serviceBot/graph/nodes.py`
   - Write `appointment_booking_node` logic.
   - Bind database helper tools checking and reserving local mock calendar slots.
2. Validation: Ensure tests pass. Refactor slots query code to enforce transactional safety.
3. Checklist Update: Mark Story 6 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'langgraph', 'database-design', 'tdd-workflow'
```

---

## Story 7: FAQ RAG Node (Vector Store Search)

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a vector search QA engineer. Your task is to write a failing test verifying semantic FAQ lookup.

Please implement:
1. File: `tests/test_rag_faq.py`
2. Assertions:
   - Initialize a temporary vector collection.
   - Assert that queries retrieve relevant pricing/operation document chunks.
   - Assert the FAQ agent answers user questions strictly using retrieved snippets without hallucination.
3. Validation: Run `pytest tests/test_rag_faq.py` and confirm that it fails.

References:
- Architectural context: [adr.md](file:///Users/rohanroy/voiceService/docs/specs/adr.md)
- Skills to use: 'rag-engineer', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a RAG engineer. Your task is to implement the FAQ retrieval node.

Please implement:
1. File: `serviceBot/services/rag.py`
   - Initialize an in-process ChromaDB client mapping file chunks.
2. File: `serviceBot/graph/nodes.py`
   - Write the `faq_node` routing semantic matches to caller replies.
3. Validation: Confirm RAG queries return in <500ms and tests pass.
4. Checklist Update: Mark Story 7 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'rag-implementation', 'rag-engineer', 'tdd-workflow'
```

---

## Story 8: Human Handoff Node

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a QA engineer. Your task is to write a failing test verifying the handoff payload.

Please implement:
1. File: `tests/test_handoff.py`
2. Assertions:
   - Assert that transitioning to handoff compiles a 3-5 bullet point transcript summary.
   - Assert the summary contains customer name, active service request ID, and urgency indicator.
3. Validation: Run `pytest tests/test_handoff.py` and confirm that it fails.

References:
- Handoff contract: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
- Skills to use: 'langgraph', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a LangGraph developer. Your task is to implement the handoff summarization node.

Please implement:
1. File: `serviceBot/graph/nodes.py`
   - Write `handoff_node` logic generating summary logs and call routing transfer payload.
2. Validation: Run test suites and verify that the graph terminates cleanly after handoff.
3. Checklist Update: Mark Story 8 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'langgraph', 'python-pro', 'tdd-workflow'
```

---

## Story 9: Configuration Portal REST APIs

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are an API tester. Your task is to write a failing test verifying portal configuration REST endpoints.

Please implement:
1. File: `tests/test_portal_api.py`
2. Assertions:
   - Test GET/POST endpoints for service lists.
   - Test key encryption functions (assert that API keys are stored encrypted and match decrypted values when retrieved).
3. Validation: Run `pytest tests/test_portal_api.py` and verify it fails.

References:
- API specification: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
- Skills to use: 'fastapi-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a backend API engineer. Your task is to implement the portal REST APIs.

Please implement:
1. File: `serviceBot/api/portal.py`
   - Setup endpoints CRUD operations and AES-256 API key encryption helper.
2. Validation: Ensure tests pass and REST response speeds are <300ms.
3. Checklist Update: Mark Story 9 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'fastapi-pro', 'python-pro', 'tdd-workflow'
```

---

## Story 10: Backend Portal Enhancements (Call Logs & KB Indexing API)

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a QA engineer. Your task is to append unit tests verifying the call logs and file upload endpoints.

Please implement:
1. File: `tests/test_portal_api.py` (Add these tests to the existing file)
2. Assertions:
   - Send `GET /api/v1/portal/calls` and assert it returns a list of calls with fields (`id`, `call_id`, `customer_name`, `phone`, `summary`, `created_at`).
   - Send `POST /api/v1/portal/kb/upload` with a mock `.txt` file attachment and assert it returns status 200 and a JSON payload containing `chunk_count` and `success: true`.
3. Validation: Run `pytest tests/test_portal_api.py` and confirm that the new tests fail.

References:
- API spec: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
- Skills to use: 'fastapi-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a backend engineer. Your task is to implement the call logs and file upload backend handlers.

Please implement:
1. File: `serviceBot/api/portal.py`
   - Implement `GET /api/v1/portal/calls` executing a SELECT query that joins `crm_notes` and `customers` to compile the call log history.
   - Implement `POST /api/v1/portal/kb/upload` using FastAPI `UploadFile`. Ingest text contents by forwarding them to the ChromaDB helper client in `serviceBot/services/rag.py` to chunk and insert.
2. Validation: Run `pytest tests/test_portal_api.py` and verify all tests pass.
3. Checklist Update: Mark Story 10 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'fastapi-pro', 'database-design', 'rag-engineer', 'tdd-workflow'
```

---

## Story 11: Configuration Portal Frontend (HTML/CSS/JS Assets)

### 📋 [RED] Phase Prompt (Test Contract)
```markdown
You are a frontend QA engineer. Your task is to implement a failing integration test for the dashboard UI.

Please implement:
1. File: `tests/test_ui.py`
2. Assertions:
   - Use `fastapi.testclient.TestClient` or a basic HTML parser (like `BeautifulSoup` or static file checker) to verify that `GET /` or `GET /portal` returns HTML containing core layout elements (e.g. sidebar navigation, metrics cards, form inputs for keys, uploader component).
3. Validation: Run `pytest tests/test_ui.py` and confirm that it fails (due to static route not being mounted or files missing).

References:
- Frontend specification: [portal_frontend_spec.md](file:///Users/rohanroy/voiceService/docs/specs/portal_frontend_spec.md)
- Skills to use: 'fastapi-pro', 'tdd-workflow'
```

### 📋 [GREEN/REFACTOR] Phase Prompt (Implementation)
```markdown
You are a senior frontend designer-engineer. Your task is to implement the static business configuration dashboard.

Please implement:
1. File: `serviceBot/main.py`
   - Import and mount `StaticFiles` from `fastapi.staticfiles` mapping the local directory `serviceBot/static` to `/portal`.
2. File: `serviceBot/static/index.html`
   - Build a layout including sidebar panel tabs, overview metric containers, a call history log table, a service form list, a drag-and-drop document upload block, and API Key input forms.
3. File: `serviceBot/static/style.css`
   - Implement a responsive glassmorphism dark-mode style matching the HSL variables and fade-in animations specified in [portal_frontend_spec.md](file:///Users/rohanroy/voiceService/docs/specs/portal_frontend_spec.md).
4. File: `serviceBot/static/app.js`
   - Handle interactive screen toggling.
   - Fetch services, voice selections, and calls from endpoints, and submit form updates.
5. Validation: Run the tests to ensure the assets are served and manual visual verification works.
6. Checklist Update: Mark Story 11 as complete ([x]) in `docs/tasks.md`.

Skills to use: 'fastapi-pro', 'python-pro', 'tdd-workflow'
```
