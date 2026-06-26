# VoiceAI - Autonomous Inbound Call Handling Platform

VoiceAI is a sub-second latency, multi-agent inbound call handling platform designed specifically for small-to-medium service businesses (SMBs) like auto repair shops and clinics. VoiceAI replaces traditional IVR systems with a natural, conversational voice assistant that automates call routing, customer intake, appointments scheduling, and FAQ resolution.

---

## 🛠️ Core Feature Set

1. **Conversational Voice Gateway**
   - **Twilio Telephony Hook**: Automatically routes incoming telephone calls to ElevenLabs streams using dynamic XML TwiML generation.
   - **Sub-Second Speech Loop**: Integrates ElevenLabs Conversational AI WebSockets for speech-to-text (STT), low-latency LLM reasoning (`gpt-4o-mini`), and natural text-to-speech (TTS) voice generation.
   - **Keypad DTMF Decoder**: Decodes DTMF keypad tones (`0-9`, `*`, `#`) during calls to capture user inputs for menu selection.
   - **Smart Filler Audio**: Emits contextual filler responses (e.g. *"Let me check our calendar..."*) while executing background APIs to prevent awkward latency silences.

2. **LangGraph Multi-Agent Orchestrator**
   - **Intent Classifier**: Automatically routes callers to specialized agents based on their queries (`new_customer_service_request`, `appointment_booking`, `appointment_reschedule`, `appointment_cancel`, `faq_business_knowledge`, `human_handoff`).
   - **Pre-Call CRM Lookup**: Queries SQLite by the caller's phone number upon connection to load historical customer profiles, vehicle histories, and active service requests.
   - **Sequential Intake Agent**: Captures customer name, phone, vehicle profile (make, model, year), and issues to register new service tickets.
   - **FAQ RAG Agent**: Connects a local ChromaDB vector store to answer pricing, location, and service questions without hallucinations.
   - **Contextual Handoff**: Generates a structured 3-5 bullet point call transcript summary and forwards calls to a human line.
   - **Callback Scheduling**: Offers callers the option to request a phone callback at a preferred time if they choose not to schedule a live appointment.

3. **Google Calendar & OAuth Integration**
   - **Agent-level OAuth 2.0 Flow**: Staff members can connect their individual Google Calendar accounts via the dashboard.
   - **Live Availability Filtering**: Queries free/busy status from the Google Calendar API in real-time when callers schedule slots.
   - **Write-Back Calendaring**: Automatically schedules and inserts events directly into the assigned technician's Google Calendar.
   - **Auto-Sync Background Loop**: Periodically syncs connected agent calendar events into the SQLite mock slots database.

4. **Gmail Notification System**
   - **Gmail REST API & OAuth 2.0**: Authorizes system email sending and dispatches HTML booking confirmations directly through Google's APIs.
   - **SMTP App Passwords fallback**: Supports standard secure SMTP connections.
   - **Aesthetic HTML Layouts**: Formats rich, responsive transaction confirmations sent automatically to customers and team members.

5. **Business Configuration Portal**
   - **Glassmorphic SPA**: Served locally at `/portal` using a premium dark-themed layout (`index.html`, `style.css`, `app.js`).
   - **Stats Dashboard**: Displays real-time metrics (calls count, booked slots, active service requests, pending callbacks).
   - **Intents & Prompts Manager**: Dynamically updates agent prompts and required intake fields.
   - **Staff & Calendar Dashboard**: Displays calendar slots, enabling managers to connect/disconnect agent Google accounts and pre-populate availability slots.
   - **Services CRUD Manager**: Manages services catalogs and automatically updates FAQ search databases.
   - **Transcripts Viewer**: View call logs, AI summaries, and full turn-by-turn speech transcripts.
   - **Secrets Encryption**: Encrypts sensitive API tokens (Twilio, ElevenLabs, OpenAI/Claude) in transit and at rest using AES-256.

---

## 📐 System Architecture

### Telephony & Data Flows
```
[Caller Phone] ──► [Twilio Hook] ──► [ElevenLabs WebSockets]
                                              │
                                              ▼ (JSON Webhook Tool Calls)
                                      [FastAPI Web Server]
                                              │
                                              ▼ (LangGraph Execution)
                                       Greeting Node
                                              │
                                              ▼
                                      Intent Classifier
                                     /    |     |      \
                                    /     |     |       \
                                   ▼      ▼     ▼        ▼
                               [Intake] [Book] [FAQ]  [Handoff]
                                  │       │     │        │
                                  ▼       ▼     ▼        ▼
                              [SQLite]  [GCal] [RAG]  [Human]
```

---

## 📁 Repository Directory Layout

*   [serviceBot/](file:///Users/rohanroy/Coding/voiceService/serviceBot/): Main source codebase directory.
    - [api/](file:///Users/rohanroy/Coding/voiceService/serviceBot/api/): FastAPI controllers.
      * [telephony.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/api/telephony.py): Webhooks for Twilio calls, ElevenLabs stream triggers, and voice custom tools.
      * [portal.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/api/portal.py): REST endpoints for configuration portal.
    - [db/](file:///Users/rohanroy/Coding/voiceService/serviceBot/db/): SQLite models and logic.
      * [connection.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/db/connection.py): DDL schema, migrations, and connection context block.
      * [queries.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/db/queries.py): Database query executions.
    - [graph/](file:///Users/rohanroy/Coding/voiceService/serviceBot/graph/): LangGraph state machine workflow.
      * [state.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/graph/state.py): Graph State schema (`AgentState`).
      * [nodes.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/graph/nodes.py): Sub-agent nodes.
      * [routing.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/graph/routing.py): Conditional router edges.
    - [services/](file:///Users/rohanroy/Coding/voiceService/serviceBot/services/): Third-party clients.
      * [encryption.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/services/encryption.py): AES-256 encryption.
      * [gmail.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/services/gmail.py): Gmail API and SMTP email dispatch.
      * [google_calendar.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/services/google_calendar.py): Google Calendar client.
      * [rag.py](file:///Users/rohanroy/Coding/voiceService/serviceBot/services/rag.py): ChromaDB client.
    - [static/](file:///Users/rohanroy/Coding/voiceService/serviceBot/static/): Dashboard assets.
      * [index.html](file:///Users/rohanroy/Coding/voiceService/serviceBot/static/index.html): SPA dashboard markup.
      * [style.css](file:///Users/rohanroy/Coding/voiceService/serviceBot/static/style.css): Responsive CSS.
      * [app.js](file:///Users/rohanroy/Coding/voiceService/serviceBot/static/app.js): AJAX controllers.
*   [docs/](file:///Users/rohanroy/Coding/voiceService/docs/): Specifications and documentation guides.
    - [PRD.md](file:///Users/rohanroy/Coding/voiceService/docs/PRD.md): Product requirements.
    - [specs/](file:///Users/rohanroy/Coding/voiceService/docs/specs/): Detailed system specs.
      * [adr.md](file:///Users/rohanroy/Coding/voiceService/docs/specs/adr.md): Architectural decisions.
      * [database_spec.md](file:///Users/rohanroy/Coding/voiceService/docs/specs/database_spec.md): Schema blueprints.
      * [api_spec.md](file:///Users/rohanroy/Coding/voiceService/docs/specs/api_spec.md): Webhook and REST API specs.
      * [agent_orchestration_spec.md](file:///Users/rohanroy/Coding/voiceService/docs/specs/agent_orchestration_spec.md): LangGraph blueprints.
*   [tests/](file:///Users/rohanroy/Coding/voiceService/tests/): Comprehensive TDD test files.

---

## ⚡ Quickstart Guide

### 1. Environment Configuration
Create a `.env` file in the root directory:
```ini
DATABASE_URL=voice_service.db
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_AGENT_ID=your_agent_id
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_claude_key
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
```

### 2. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Initialize & Seed Database
Initialize SQLite schemas and seed mock data:
```bash
python3 -m serviceBot.db.seed
```

To load the specific CBA auto services catalog offering list:
```bash
python3 serviceBot/seed_cba_services.py
```

### 4. Index Knowledge Base (RAG)
Ingest information documents inside the `kb_documents` folder into ChromaDB:
```bash
python3 serviceBot/db/index_kb.py
```

### 5. Launch Server
Start the local FastAPI server:
```bash
.venv/bin/uvicorn serviceBot.main:app --reload --port 8000
```
Open [http://localhost:8000/portal](http://localhost:8000/portal) to access the Dashboard configuration settings.

---

## 🧪 Testing

We verify system workflows, database queries, and agent nodes using `pytest`. Run the tests command:
```bash
pytest
```
Currently, **74+ test cases** pass with a 100% success rate.
