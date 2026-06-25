# Implementation Stories Checklist (VoiceAI)

This document breaks down the VoiceAI MVP into isolated implementation stories. Each story follows the **TDD (Test-Driven Development) workflow** and references specific workspace skills and specification documents.

---

## Story 1: Project Setup & Database Schema Initialization
Set up the initial FastAPI workspace structure and compile the SQLite schema database.

*   **References**: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
*   **Skills**: [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design), [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_db_connection.py` asserting tables exist and foreign keys are explicitly enforced. Verify test fails.
    - [x] Initialize directory layout (`serviceBot/`, `tests/`, `db/`).
    - [x] **TDD Green**: Implement `serviceBot/db/connection.py` containing the database initialization script and connection pool manager (supporting `PRAGMA foreign_keys = ON;`).
    - [x] **TDD Green**: Create database schema migrations and run table creation DDL.
    - [x] **TDD Green**: Write a seed script `serviceBot/db/seed.py` that inserts mock customer (Sarah Johnson), vehicle (Honda Civic), pending service requests, and available mock calendar slots.
    - [x] **TDD Refactor**: Verify tests pass using `pytest tests/test_db_connection.py`.
*   **Verification**:
    ```bash
    python3 -m serviceBot.db.seed
    sqlite3 voice_service.db "SELECT * FROM customers;"
    sqlite3 voice_service.db "SELECT * FROM vehicles;"
    ```

---

## Story 2: Pre-Call CRM Lookup Endpoint & Queries
Implement customer lookup queries that run whenever a customer dials in.

*   **References**: [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
*   **Skills**: [`python-pro`](file:///Users/rohanroy/voiceService/.agents/skills/python-pro), [`python-testing-patterns`](file:///Users/rohanroy/voiceService/.agents/skills/python-testing-patterns), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create failing unit tests in `tests/test_db_queries.py` asserting that looking up a customer by phone number returns the expected structured profile and vehicle detail. Verify tests fail.
    - [x] **TDD Green**: Create `serviceBot/db/queries.py` containing query functions to find customer information and active service requests by phone number.
    - [x] **TDD Refactor**: Run `pytest tests/test_db_queries.py` and ensure they pass. Refactor query context managers.
*   **Verification**:
    ```bash
    pytest tests/test_db_queries.py -v
    ```

---

## Story 3: Inbound Call Telephony Webhook (Twilio Route)
Implement the initial call webhook receiver that hooks Twilio calls to the ElevenLabs Conversational agent.

*   **References**: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_telephony_webhook.py` asserting that `POST /api/v1/telephony/inbound` returns TwiML with the dynamically resolved ElevenLabs `ConversationAgent` and `agentId`. Verify tests fail.
    - [x] **TDD Green**: Set up the FastAPI server in `serviceBot/main.py` with basic GET `/health`.
    - [x] **TDD Green**: Create route `POST /api/v1/telephony/inbound` in `serviceBot/api/telephony.py`. Parse Twilio payload and return TwiML XML streaming connection payload.
    - [x] **TDD Refactor**: Run `pytest tests/test_telephony_webhook.py` to confirm green status.
*   **Verification**:
    ```bash
    pytest tests/test_telephony_webhook.py -v
    ```

---

## Story 4: LangGraph Intent Classifier Node & Routing Graph
Set up the LangGraph pipeline structure and implement the first node: Intent Classifier.

*   **References**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_intent_classifier.py` asserting that invoking the graph with sample phrases (e.g. "I need an oil change") transitions `current_agent` state to the correct value (e.g. "appointment"). Verify tests fail.
    - [x] **TDD Green**: Create `serviceBot/graph/state.py` defining the `AgentState` schema.
    - [x] **TDD Green**: Create `serviceBot/graph/nodes.py` with the `intent_classifier_node` using LLM structure.
    - [x] **TDD Green**: Define the graph edges in `serviceBot/graph/routing.py` to handle routing based on intent classification.
    - [x] **TDD Refactor**: Clean up prompt template variables and ensure routing edge behaves purely.
*   **Verification**:
    ```bash
    pytest tests/test_intent_classifier.py -v
    ```

---

## Story 5: Service Request Node & CRM Updates
Implement the Service Request node that guides the user through vehicle data gathering.

*   **References**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md), [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_service_request_agent.py` asserting that inputs containing vehicle name, model, year, and issue populate state fields and successfully call `create_service_request()` tool. Verify tests fail.
    - [x] **TDD Green**: Create `service_request_node` in `serviceBot/graph/nodes.py` to capture required fields.
    - [x] **TDD Green**: Integrate functional tool `create_service_request(customer_id, vehicle_details, issue)` to save new requests to the SQLite DB.
    - [x] **TDD Refactor**: Verify using `pytest tests/test_service_request_agent.py`.
*   **Verification**:
    ```bash
    pytest tests/test_service_request_agent.py -v
    ```

---

## Story 6: Appointment Booking Node & Scheduling Integrations
Implement the scheduling node to query availability and book calendar slots.

*   **References**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md), [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_appointment_agent.py` asserting checking availability returns free slots from SQLite, and `book_appointment()` updates slot status and creates the appointment record. Verify tests fail.
    - [x] **TDD Green**: Create `appointment_booking_node` in `serviceBot/graph/nodes.py`.
    - [x] **TDD Green**: Implement database-backed tools `check_availability(datetime)` and `book_appointment(...)` against the local SQLite mock calendar slots.
    - [x] **TDD Refactor**: Verify tests pass and check SQLite state.
*   **Verification**:
    ```bash
    pytest tests/test_appointment_agent.py -v
    ```

---

## Story 7: FAQ RAG Node (Vector Store Search)
Implement RAG search functionality to answer pricing and operational queries.

*   **References**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
*   **Skills**: [`rag-engineer`](file:///Users/rohanroy/voiceService/.agents/skills/rag-engineer), [`rag-implementation`](file:///Users/rohanroy/voiceService/.agents/skills/rag-implementation), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_rag_faq.py` asserting that query searches pull matching chunks from vector database and return accurate context-driven answers. Verify tests fail.
    - [x] **TDD Green**: Implement `serviceBot/services/rag.py` initializing a local ChromaDB collection.
    - [x] **TDD Green**: Create the `faq_node` in `serviceBot/graph/nodes.py` executing vector queries against the uploaded text files.
    - [x] **TDD Refactor**: Confirm search retrieval speeds meet target thresholds (<500ms).
*   **Verification**:
    ```bash
    pytest tests/test_rag_faq.py -v
    ```

---

## Story 8: Human Handoff Node
Implement the handoff agent to summarize context and forward the call.

*   **References**: [agent_orchestration_spec.md](file:///Users/rohanroy/voiceService/docs/specs/agent_orchestration_spec.md)
*   **Skills**: [`langgraph`](file:///Users/rohanroy/voiceService/.agents/skills/langgraph), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_handoff.py` asserting that call handoff generates a 3-5 bullet summary containing customer info, active service request ID, and urgency indicator. Verify tests fail.
    - [x] **TDD Green**: Create `handoff_node` in `serviceBot/graph/nodes.py`.
    - [x] **TDD Green**: Implement transcript summarization helper and mock the telephony transfer payload.
    - [x] **TDD Refactor**: Verify tests pass.
*   **Verification**:
    ```bash
    pytest tests/test_handoff.py -v
    ```

---

## Story 9: Configuration Portal REST APIs
Expose management APIs for the frontend configuration portal.

*   **References**: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro), [`tdd-workflow`](file:///Users/rohanroy/voiceService/.agents/skills/tdd-workflow)
*   **Tasks**:
    - [x] **TDD Red**: Create `tests/test_portal_api.py` asserting endpoints for services list and API key encryption function as expected. Verify tests fail.
    - [x] **TDD Green**: Create `serviceBot/api/portal.py` containing endpoints for managing services list, saving API Keys, and fetching summary logs.
    - [x] **TDD Green**: Implement key encryption handlers for saving secrets.
    - [x] **TDD Refactor**: Confirm API responses are fast (<300ms) and validated.
*   **Verification**:
    ```bash
    pytest tests/test_portal_api.py -v
    ```

---

## Story 10: Backend Portal Enhancements (Call Logs & KB Indexing API)
Implement the remaining backend endpoints for fetching caller transcript logs and uploading/indexing documents in ChromaDB.

*   **References**: [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md), [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md)
*   **Skills**: [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro), [`database-design`](file:///Users/rohanroy/voiceService/.agents/skills/database-design), [`rag-engineer`](file:///Users/rohanroy/voiceService/.agents/skills/rag-engineer)
*   **Tasks**:
    - [x] **TDD Red**: Add tests to `tests/test_portal_api.py` asserting `GET /api/v1/portal/calls` returns call summaries list, and `POST /api/v1/portal/kb/upload` accepts text files and returns chunk indexing counts. Verify tests fail.
    - [x] **TDD Green**: Implement `GET /api/v1/portal/calls` querying sqlite table `crm_notes` joined with `customers`.
    - [x] **TDD Green**: Implement `POST /api/v1/portal/kb/upload` endpoint using `UploadFile`. Forward text bytes to `serviceBot/services/rag.py` to chunk and ingest into the local ChromaDB vector store.
    - [x] **TDD Refactor**: Verify using `pytest tests/test_portal_api.py`.
*   **Verification**:
    ```bash
    pytest tests/test_portal_api.py -v
    ```

---

## Story 11: Configuration Portal Frontend (HTML/CSS/JS Assets)
Implement the client-side single page app for the configuration dashboard.

*   **References**: [portal_frontend_spec.md](file:///Users/rohanroy/voiceService/docs/specs/portal_frontend_spec.md), [api_spec.md](file:///Users/rohanroy/voiceService/docs/specs/api_spec.md)
*   **Skills**: [`webapp-testing`](file:///Users/rohanroy/voiceService/.agents/skills/webapp-testing), [`fastapi-pro`](file:///Users/rohanroy/voiceService/.agents/skills/fastapi-pro)
*   **Tasks**:
    - [x] **TDD Red**: Create a Playwright UI test verifying that the portal frontend loads, displays dynamic sections, and exposes configuration tabs. Verify tests fail.
    - [x] **TDD Green**: Mount static assets directory `/serviceBot/static` in `serviceBot/main.py`.
    - [x] **TDD Green**: Create `serviceBot/static/index.html` structure with responsive grid cards and form fields.
    - [x] **TDD Green**: Implement `serviceBot/static/style.css` glassmorphic theme.
    - [x] **TDD Green**: Write `serviceBot/static/app.js` routing logic and AJAX requests.
    - [x] **TDD Refactor**: Refactor styles and animations for high-end look and feel.
*   **Verification**:
    - Run `pytest tests/test_ui.py` (if playwright test is configured)
    - Manually test: Open browser to `http://localhost:8000/` and verify layout.
