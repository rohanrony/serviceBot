# Architectural Decision Record (ADR) - VoiceAI

This document records the key architectural decisions made for the VoiceAI platform development, detailing the context, options evaluated, and chosen solutions.

---

## ADR 1: Integration Flow (LangGraph & ElevenLabs)

### Context
VoiceAI requires sub-second latency voice interactions (<800ms) with stateful routing logic (LangGraph) for multi-agent execution (service requests, appointment booking, FAQ lookup, human handoff).

### Evaluated Options
*   **Option A: Webhook-Driven LangGraph (Selected)**
    *   *Mechanism*: Twilio streams audio directly to ElevenLabs Conversational AI. When ElevenLabs triggers a custom function, it invokes a FastAPI webhook (`POST /api/v1/voice/tools`). The FastAPI server executes the LangGraph DAG, updates the SQLite database state, and returns the response payload.
    *   *Latency Impact*: Under 800ms (industry standard).
*   **Option B: Middleman WebSocket Proxy**
    *   *Mechanism*: Twilio streams audio to FastAPI, which processes/streams audio to ElevenLabs/OpenAI on every single speak-turn.
    *   *Latency Impact*: High (1.5s - 3s), prone to dropped packets.

### Decision
We will use **Option A** to ensure sub-second conversational latency.

---

## ADR 2: Database Integration & Context Synchronization

### Context
FastAPI handles webhooks asynchronously, while SQLite is a file-based synchronous database. We need a clean, non-blocking connection pool without incurring the overhead of complex async ORMs.

### Decision
We will use **raw SQLite with a synchronous connection context manager**.
*   We will explicitly enable `PRAGMA foreign_keys = ON` on connection creation.
*   Connections will be closed/disposed immediately using context managers (`with get_db_connection() as conn:`) to prevent connection pool leakage and database locking.

---

## ADR 3: RAG & Knowledge Base Vector DB Setup

### Context
The FAQ agent requires semantic search capability (RAG) over business uploaded documents (PDFs, text files). 

### Decision
We will use **ChromaDB with an in-process client** (`chromadb.PersistentClient`).
*   The vector DB index will be persisted locally (e.g., `./chroma_db` directory) to avoid Docker/external service dependencies for the local MVP.

---

## ADR 4: Configuration & Secrets Storage

### Context
The server needs access to various API keys (OpenAI, Claude, ElevenLabs, Twilio). 

### Decision
*   We will store credentials in a local `.env` file in the project root.
*   The business configuration portal will read config variables using environment fallbacks.

---

## ADR 5: Keypad Input (DTMF) Strategy

### Context
Customers might want to select options using physical telephone buttons (DTMF). 

### Evaluated Options
*   **Option A1: Voice-Activated Menu Fallback (Selected)**
    *   *Mechanism*: We configure ElevenLabs to accept natural voice prompts (e.g., "Press 1 or say Oil Change" is handled by the user saying *"One"* or *"Oil Change"*). The LLM tool parser matches the spoken intent.
*   **Option A2: Twilio DTMF Stream Intercept**
    *   *Mechanism*: Intercept DTMF mid-stream on Twilio, pause ElevenLabs, process, and resume. Highly complex and prone to latency/glitches.

### Decision
We will use **Option A1** (Voice-first menu selection) to handle selection flows cleanly without complex stream routing.

---

## ADR 6: Google Calendar & OAuth Integration

### Context
The appointment agent needs to check availability and book calendar slots against real-time staff schedules. Staff members may also manage their own calendars independently.

### Decision
We will support **Agent-level OAuth 2.0 Google Calendar integration**:
* Individual staff members can connect their Google Calendar accounts via OAuth.
* The system queries live free/busy schedules directly from the Google Calendar API when callers check availability, falling back to SQLite mock calendar slots.
* Newly booked appointments automatically insert events into the agent's Google Calendar with write scope.
* A background thread loops periodically to refresh agent slots and keep the local DB database in sync.

---

## ADR 7: Dynamic Voice & Model Routing

### Context
The configuration portal allows the business to choose between OpenAI (GPT-4) and Anthropic (Claude 3.5), along with ElevenLabs voices.

### Decision
We will use **Option C1: Configured ElevenLabs Agent IDs**.
*   We will set up separate ElevenLabs Agent IDs (pre-configured in the ElevenLabs dashboard with the target model and voice).
*   FastAPI will select and return the appropriate `Agent ID` in the Twilio `<Connect>` TwiML response based on the portal's active configuration.

---

## ADR 8: Email & Gmail Notification Integration

### Context
Businesses need automatic email confirmations sent to both customers and team members when appointments are booked, rescheduled, or callbacks are requested.

### Decision
We will implement a hybrid **Gmail Integration system**:
* **App Passwords / SMTP**: Standard SMTP connection with STARTTLS for quick setup using a generic/shared account.
* **OAuth 2.0 Gmail REST API**: Secure OAuth flow allowing the system (or individual connected agents) to send highly formatted HTML notifications directly through Google's Gmail API.
* All configuration details are stored in the configuration portal with password fields encrypted using AES-256.
