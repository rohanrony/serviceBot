# Product Requirements Document (PRD) - serviceBot
**Version 0.1** | **Date**: June 11, 2026 | **Author**: Product Manager | **Status**: In Review

---

## 1. Executive Summary

### 1.1 Problem Statement
Small-to-medium service businesses (SMBs) lose significant revenue due to missed calls, long wait times, and high front-desk operational overhead from handling repetitive customer service inquiries. Traditional Interactive Voice Response (IVR) systems are rigid, frustrating callers and driving them to competitors. Additionally, busy front-desk staff frequently fail to capture complete lead information or update internal CRMs consistently.

### 1.2 Proposed Solution
serviceBot is an AI-powered inbound call handling platform that automates customer service and appointment booking. The system integrates Twilio, ElevenLabs Conversational AI, and LangGraph-driven routing to deliver natural, sub-second latency voice interactions. It classifies user intent, queries customer records, registers service requests, books calendar slots, answers FAQs via Retrieval-Augmented Generation (RAG), and executes seamless human handoffs (to 424 270 4893) with full conversation history. Primary appointment scheduling is handled during service request intakes, and rescheduling is handled dynamically with slot availability validation.

### 1.3 Business Impact
- **100% Inbound Call Coverage:** Eliminates missed customer calls, capturing every potential service lead 24/7.
- **40-60% Support Cost Reduction:** Automates routine triage and scheduling, letting front-desk staff focus on in-person operations.
- **Higher Booking Conversion:** Offers dynamic, personalized booking slot options in natural conversation, raising appointment capture by 25%.

### 1.4 Timeline
The MVP release is structured over a 4-week development timeline, moving from foundation architecture to core agents, advanced integrations, and the business configuration portal. General availability (GA) is targeted for Week 12.

### 1.5 Resources Required
- **Core Team:** 1 Product Manager, 1 Design Lead, 1 Backend/AI Engineer, 1 Frontend Engineer, 0.5 QA Engineer.
- **APIs & Infrastructure:** Twilio Phone Provisioning, ElevenLabs Conversational AI API, OpenAI / Anthropic APIs, Google Calendar API, and ChromaDB vector store hosting.

### 1.6 Success Metrics
- **Call Answer Rate:** 100% of incoming calls answered within 1 second.
- **Callbacks Requested:** Track and log callback requests when caller opts for callback instead of scheduling.
- **Average Call Response Latency:** <800ms from user voice termination to agent speech beginning.

---

## 2. Problem Definition

### 2.1 Customer Problem
- **Who:** Target user personas are small-to-medium service business owners (e.g., Mike, owner of a multi-location auto repair shop) and their end consumers (e.g., Sarah Johnson, a car owner needing a brake repair).
- **What:** Inbound call volume spikes frequently overwhelm staff, leading to missed calls, long hold times, and incomplete CRM data entry. Customers fail to get prompt service information or book slots outside business hours.
- **When:** Problems occur daily during business peak hours (8:00 AM - 10:00 AM, 4:00 PM - 6:00 PM) and completely block engagement after-hours.
- **Where:** Across incoming phone lines, service desk systems, and physical customer check-in areas.
- **Why:** Hiring dedicated 24/7 call centers is financially non-viable for SMBs, and existing AI call software requires extensive programming to set up complex routing flows or link to custom DBs.
- **Impact:** Each missed service appointment is estimated to cost the business \$150 to \$400 in direct lost revenue. A poor calling experience lowers customer retention and Net Promoter Scores (NPS).

### 2.2 Market Opportunity
- **Market Size (TAM, SAM, SOM):** 
  - *Total Addressable Market (TAM):* All service-based SMBs in North America (~5.2 million businesses).
  - *Serviceable Addressable Market (SAM):* Automotive repair shops, medical clinics, dental practices, and home service providers (~1.2 million businesses).
  - *Serviceable Obtainable Market (SOM):* Multi-location automotive service franchises and regional clinic networks (~10,000 locations).
- **Growth Rate:** The global Conversational AI market size was valued at \$10.9 billion in 2024 and is projected to grow at a CAGR of 23.6% from 2025 to 2030.
- **Competition:** Standard IVR platforms (e.g., RingCentral, Vonage), enterprise contact center software, and generic LLM agents. Technical voice platforms like Retell AI and Vapi provide infrastructure but lack the no-code, business-specific CRM and flow configurability tailored to SMBs.
- **Timing:** Sub-second speech-to-text (STT) and text-to-speech (TTS) streaming APIs have matured, bringing conversational latency below human-detectable limits and making phone-based AI agents highly natural.

### 2.3 Business Case
- **Revenue Potential:** By answering 100% of missed calls and scheduling appointments 24/7, a typical 3-location auto shop can expect an additional 15-25 appointments per week, translating to \$3,000 - \$8,000 in weekly gross revenue.
- **Cost Savings:** Cuts front-desk staff call-handling time by 40%, translating to roughly 15-20 hours saved per week per store, which can be redirected to customer greeting and shop management.
- **Strategic Value:** Connects SMBs' local operations directly to state-of-the-art LLMs, preparing their backend workflow for future autonomous scheduling, inventory lookup, and automated parts ordering.
- **Risk Assessment:** Failure to adopt voice automation will lead to a continued decline in lead capture, as customers choose competitors who resolve booking inquiries instantly.

---

## 3. Solution Overview

### 3.1 Proposed Solution
VoiceAI provides an intelligent inbound call agent using a multi-agent LangGraph workflow. The solution is composed of:
1. **Telephony & Voice Gateway:** A Twilio inbound call route forwarding audio streams via WebSockets to ElevenLabs.
2. **Conversational AI Engine:** Sub-second ElevenLabs STT, dynamic LLM model reasoning (OpenAI/Claude), and premium voice generation.
3. **Multi-Agent Orchestrator:** A FastAPI backend executing a LangGraph state machine. It handles caller greeting, intent classification, CRM retrieval, service requests, calendar scheduling, FAQ answering, and human transfer.
4. **Business Configuration Portal:** A glassmorphic web dashboard allowing business managers to manage services, upload PDF/text knowledge files, configure prompts, view logs, and select AI models.

```
                  ┌──────────────────────┐
                  │   Inbound Caller     │
                  └──────────┬───────────┘
                             │ (Phone Call)
                             ▼
                  ┌──────────────────────┐
                  │    Twilio Gateway    │
                  └──────────┬───────────┘
                             │ (Media Stream)
                             ▼
                  ┌──────────────────────┐
                  │ ElevenLabs Conv AI   │
                  └──────────┬───────────┘
                             │ (Custom Webhook / Tool Calls)
                             ▼
         ┌───────────────────────────────────────┐
         │       LangGraph Orchestrator          │
         │           (FastAPI App)               │
         │                                       │
         │   Greeting ──► Intent Classification  │
         │                     │                 │
         │   ┌─────────────────┼───────────────┐ │
         │   ▼                 ▼               ▼ │
         │ Service Req    Appointment       FAQ  │
         │   Agent           Agent         RAG   │
         │   (SQLite)      (Mock Cal)   (Chroma) │
         └─────────────────────┬─────────────────┘
                               │ (Optional Transfer)
                               ▼
                  ┌──────────────────────┐
                  │   Human Specialist   │
                  │   (With Transcript)  │
                  └──────────────────────┘
```

### 3.2 In Scope (MVP - P0)
- **LangGraph Multi-Agent Workflows:** Separate state nodes for routing, service intake, calendar bookings, and FAQs.
- **Intent Classification & Routing:** Classifies caller query into 7 intents: *new SR, existing SR, booking, rescheduling, cancellation, FAQ, and human handoff*.
- **Pre-Call CRM Lookup:** Inspects incoming caller phone number to pull existing customer name, vehicles, and active service requests.
- **Service Request Management:** Sequentially captures name, phone, vehicle details, and issues to save service request records in a local SQLite CRM database.
- **Mock Calendar Booking:** Verifies availability, offers 2-3 specific time slots, books appointments, and supports rescheduling and cancellation.
- **FAQ Semantic Search (RAG):** Integrates ChromaDB vector store to search uploaded documentation and streams precise answers without hallucination.
- **Human Handoff with Summary:** Generates a 3-5 bullet point conversation summary (customer identity, active SR, upcoming bookings, urgency) and sends it as transfer payload.
- **DTMF Tone Support:** Accepts keypad input (0-9, *, #) for menu and slot selection.
- **Web-Based Management Portal:** Glassmorphic dashboard to configure prompts, add services, upload KB documents, select ElevenLabs voices, enter API keys, and review call log transcripts.

### 3.3 Out of Scope (Post-MVP)
- **Real CRM Integrations:** Direct HubSpot, Salesforce, or Mitchell1 connectors (MVP uses a local SQLite mock database).
- **Outlook Calendar Sync:** Only SQLite mock calendar and Google Calendar API are in scope for MVP.
- **Multi-Language Support:** The system will process and reply only in English for Version 0.1.
- **Custom Model Fine-tuning:** Training domain-specific weights is out of scope; prompt engineering and vector RAG are used instead.

### 3.4 MVP Definition
- **Core Value Proposition:** A call handling system that handles 100% of customer service intake and schedules calendar slots autonomously.
- **Success Criteria:** 
  1. A caller successfully creates a service request and books an appointment over the phone.
  2. The business manager logs into the portal and views the call log, transcript, and scheduled booking.
- **MVP Delivery Date:** July 10, 2026.
- **Learning Goals:** Validate latency threshold satisfaction (<800ms) under concurrent call loads and test intent classification accuracy against real-world customer transcripts.

---

## 4. User Stories & Requirements

### 4.1 User Stories

#### Story A: Business Owner Configuration
> **As a** Business Owner (Mike)  
> **I want to** log into a web configuration portal, upload our pricing sheets, and select our agent's voice  
> **So that** the voice assistant answers customer FAQs accurately and matches our brand identity.
>
> **Acceptance Criteria:**
> - [x] Manager can upload text files and index them into ChromaDB vector store.
> - [x] Manager can choose from a list of ElevenLabs voices.
> - [x] Configuration changes sync immediately to ElevenLabs and reflect in subsequent calls.

#### Story B: Customer Intake & Scheduling
> **As a** Customer calling in (Sarah)  
> **I want to** explain my car issue and pick a convenient appointment slot during the phone call  
> **So that** I don't have to wait on hold or fill out manual web forms.
>
> **Acceptance Criteria:**
> - [x] AI agent pre-fills customer vehicle history using a phone-number lookup.
> - [x] Agent asks intake questions naturally and avoids asking for details already in the database.
> - [x] Agent offers 2-3 specific appointment slots and records the booking in the database.

#### Story C: Human Handoff Coordinator
> **As a** Service Representative at the front desk  
> **I want to** receive a transferred call with a summary of the customer's identity and issues on my screen  
> **So that** I can help the customer immediately without asking them to repeat themselves.
>
> **Acceptance Criteria:**
> - [x] System detects handoff request (e.g. "I want to talk to a manager").
> - [x] Handoff node generates a 3-5 bullet point summary containing active service request details.
> - [x] Call is routed to human line with transcript context payload.

### 4.2 Functional Requirements

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
| **FR-1** | **Intent Classification:** Classify caller inputs into 7 predefined intents. | P0 | Critical for routing to sub-agents. |
| **FR-2** | **CRM Lookup:** Automatically query SQLite database using Twilio caller ID. | P0 | Restores client profile on call connection. |
| **FR-3** | **Service Intake:** Capture name, vehicle details, and auto issues in conversation. | P0 | Saves record to `service_requests` table. |
| **FR-4** | **Calendar Integration:** Retrieve open slots and write appointment bookings. | P0 | Utilizes SQLite mock slots table. |
| **FR-5** | **RAG FAQ:** Search uploaded documents and answer pricing/location queries. | P0 | Runs semantic lookup in local ChromaDB. |
| **FR-6** | **Handoff Summary:** Package call context and transfer call to human representative. | P0 | Fired on user request or intake exceptions. |
| **FR-7** | **DTMF Detection:** Detect dual-tone keypad signals (0-9, *, #). | P0 | Decodes phone keypad selections. |
| **FR-8** | **Portal CRUD:** Expose CRUD REST APIs for services catalog and config settings. | P0 | Connects frontend settings to backend DB. |
| **FR-9** | **Call Logs Viewer:** List recent call details, full transcripts, and summaries. | P0 | Visible in portal dashboard. |

### 4.3 Non-Functional Requirements
- **Performance:** Avg call response latency must remain strictly under 800ms. RAG search queries must return within 500ms.
- **Scalability:** System must support at least 100 concurrent voice calls.
- **Security:** Business API keys (ElevenLabs, OpenAI, Claude) must be encrypted at rest using AES-256 before storage in the database.
- **Reliability:** The telephony service must target 99.9% uptime. Database transactions must prevent double-booking on overlapping calendar slots.
- **Usability:** The web portal must follow mobile-first layout rules, with distinct glassmorphic interactive elements.
- **Compliance:** Support TCPA phone consent guidelines and adhere to GDPR data retention rules (90-day auto-purge on customer call logs).

---

## 5. Design & User Experience

### 5.1 Design Principles
- **Aesthetic Excellence:** Visual layout must feel extremely premium, featuring a unified dark-mode theme, harmonious curated HSL colors, glassmorphic card containers, and smooth hover state transitions.
- **Accessibility:** Interactive elements must utilize high contrast ratios, semantic HTML tags, and clear ARIA descriptions for screen readers.
- **Conversational Clarity:** Voice prompts must avoid long sentences or dense tables. They must present options clearly (e.g. choosing "option 1 or option 2" rather than listing broad questions).

### 5.2 Information Architecture
The Business Portal is structured as a Single Page Application (SPA) with sidebar navigation:
- **Dashboard:** Call volume charts, recent activity logs, and real-time active call alerts.
- **Call Flows:** Manage prompts for the intent classifier, service intake, calendar booking, FAQ, and handoff nodes.
- **Services:** Catalog containing services, descriptions, prices, and required intake fields.
- **Knowledge Base:** Upload and view documents indexed for FAQ RAG.
- **API Settings:** Manage secure fields for Twilio, ElevenLabs, OpenAI, and Claude credentials.
- **Call Logs:** Detail table containing client profiles, summaries, and full conversation transcripts.

---

## 6. Technical Specifications

### 6.1 Architecture Overview
The backend is built in Python using FastAPI, Uvicorn, and LangGraph. Audio streams are handled by Twilio and ElevenLabs WebSockets. Custom agent nodes are written as pure functions mutating `AgentState` in a directed acyclic graph (DAG).

```
[Inbound Phone Call] ──► [Twilio Route] ──► [ElevenLabs WebSockets]
                                                    │
                                                    ▼ (JSON Tool Trigger)
                                            [FastAPI Webhook Server]
                                                    │
                                                    ▼
                                            [LangGraph Executor]
                                            ┌───────┴───────┐
                                            ▼               ▼
                                       [SQLite DB]     [ChromaDB]
```

### 6.2 API Design

#### POST `/api/v1/telephony/inbound`
Accepts incoming call details from Twilio and returns TwiML instructions redirecting the voice connection.
- **Request Headers:** `Content-Type: application/x-www-form-urlencoded`
- **Response TwiML (XML):**
  ```xml
  <Response>
      <Connect>
          <ConversationAgent url="https://api.elevenlabs.io/v1/convai/conversation/stream" agentId="{elevenlabs_agent_id}" />
      </Connect>
  </Response>
  ```

#### POST `/api/v1/voice/tools`
Dispatches function calls requested by ElevenLabs agents during the call.
- **Request Body:** Standard wrapped tool JSON or flat parameter format.
- **Supported Action Names:** `check_availability`, `create_service_request`, `book_appointment`, `faq_lookup`, `handoff`.

#### GET `/api/v1/portal/calls`
Retrieves call records and transcripts joined with customer details.
- **Response Schema (200 OK):**
  ```json
  [
    {
      "id": 1,
      "call_id": "CA123456",
      "customer_name": "Sarah Johnson",
      "phone": "555-123-4567",
      "summary": "Customer booked oil change...",
      "transcript": "Caller: Hello...\nAI: Hi there...",
      "created_at": "2026-06-11T00:00:00Z"
    }
  ]
  ```

### 6.3 Database Design (SQLite Schema)
The database structure is managed in SQLite with foreign keys enforced.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_customers_phone ON customers(phone);

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    make VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    year INTEGER NOT NULL,
    vin VARCHAR(17) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE INDEX idx_vehicles_customer_id ON vehicles(customer_id);

CREATE TABLE service_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    service_type VARCHAR(100) NOT NULL,
    issue_description TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_slot VARCHAR(100) DEFAULT NULL,
    booking_type VARCHAR(50) DEFAULT NULL CHECK (booking_type IN ('appointment', 'callback')),
    booking_time VARCHAR(100) DEFAULT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE RESTRICT
);
CREATE INDEX idx_service_requests_customer ON service_requests(customer_id);

CREATE TABLE crm_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id VARCHAR(255) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE INDEX idx_crm_notes_customer ON crm_notes(customer_id);

CREATE TABLE staff_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(100) DEFAULT NULL
);

CREATE TABLE mock_calendar_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_datetime TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT 0,
    staff_agent_id INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE,
    UNIQUE(slot_datetime, staff_agent_id)
);
CREATE INDEX idx_mock_calendar_slots_datetime ON mock_calendar_slots(slot_datetime);

CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_range VARCHAR(100),
    duration_minutes INTEGER,
    req_customer_name BOOLEAN DEFAULT 1,
    req_phone_number BOOLEAN DEFAULT 1,
    req_vehicle_details BOOLEAN DEFAULT 1,
    req_issue_description BOOLEAN DEFAULT 1,
    req_location BOOLEAN DEFAULT 1
);
```

### 6.4 Security Considerations
- **API Key Encryption:** Keys are encrypted using AES-256 (via cryptography library) with a secret salt configured in environmental configurations.
- **PII Hygiene:** No PII data is transmitted to ElevenLabs tool analysis payloads. Transcripts are stored locally in the secure SQLite database and auto-purged after 90 days.
- **SSL Enforcement:** All webhooks and portal endpoints are served strictly over HTTPS.

---

## 7. Go-to-Market Strategy

### 7.1 Launch Plan
- **Soft Launch (Beta Phase):** Begins Week 8, deploying the platform to 10 partner automotive shops (Christian Brothers Automotive franchise owners) to collect performance metrics and identify conversation edge-cases.
- **Full Launch (General Availability):** Begins Week 12, opening registration to all auto and medical clinics in the SAM network.
- **Marketing Channels:** Direct email campaigns to franchise lists, industry trade show demonstrations, and case studies highlighting time/revenue savings.
- **Support & Training:** Deploying standard onboarding video guides and a dedicated customer support line handled by our human agents.

### 7.2 Pricing Strategy
- **Beta Phase:** Free of charge for active partners.
- **GA Phase:** Subscription model starting at \$99 per month per store, plus a usage charge of \$0.10 per call minute to cover ElevenLabs/LLM API consumption.

### 7.3 Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Adoption Rate** | >70% of beta shops active | Daily active login tracking on configuration portal. |
| **User Satisfaction** | >45 NPS score | Post-call SMS survey sent to customers who book slots. |
| **First Call Resolution** | >80% resolution | Call logs audit checking for absence of human handoff. |
| **Call Latency** | <800ms P95 latency | Server timing log metrics on webhook round-trips. |

---

## 8. Risks & Mitigations

| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|-------------------|
| **Voice Latency Spike:** Network congestion increases ElevenLabs / LLM reply latency. | Medium | High | Select smaller model endpoints (e.g. Gemini 1.5 Flash), configure local prompt caching, and streamline JSON payloads. |
| **Hallucinated FAQ answers:** Agent quotes invalid pricing or non-existent services. | Low | High | Enforce strict instructions in the FAQ RAG system: restrict answers strictly to indexed documents and reject unknown prompts. |
| **Calendar double-booking:** Concurrent calls book the same calendar slot. | Medium | Medium | Wrap booking queries in SQL transactions (`BEGIN IMMEDIATE`) and enforce unique constraints on calendar slots. |
| **Handoff delays:** Human operator is not immediately available on transfer trigger. | High | Medium | Check operator availability status prior to transfer; offer automated SMS callback if line is occupied. |

---

## 9. Timeline & Milestones

| Milestone | Target Date | Deliverables | Success Criteria |
|-----------|-------------|--------------|-----------------|
| **Design Complete** | Week 1 | HTML Wireframes, Glassmorphic CSS | Approval from stakeholders |
| **Database & API Ready**| Week 2 | SQLite schema, FastAPI REST endpoints | All schema unit tests pass |
| **Orchestrator Complete**| Week 3 | LangGraph nodes, ElevenLabs tool webhook | E2E telephony test runs successfully |
| **Portal Integration**   | Week 4 | Configuration Dashboard, Call Logs UI | Business owner can configure settings |
| **Beta Launch**          | Week 8 | Soft deploy to 10 shop locations | >100 successful bookings achieved |
| **General Availability**  | Week 12| Public SaaS portal, full API billing | System handles >10,000 daily calls |

---

## 10. Team & Resources

### 10.1 Team Structure
- **Product Manager (1 FTE):** Defines requirements, checks user metrics, and coordinates stakeholder feedback.
- **Design Lead (0.5 FTE):** Creates responsive layouts, UI screens, and voice interaction dialogue paths.
- **Backend/AI Engineer (1 FTE):** Implements FastAPI web endpoints, LangGraph orchestrators, and DB query optimizations.
- **Frontend Engineer (1 FTE):** Implements Single Page App configuration interfaces, dashboard charts, and CSS styling.
- **QA Engineer (0.5 FTE):** Designs automated Playwright scripts and runs integration regression suites.

### 10.2 Budget
- **Development & Staffing:** \$35,000 per month
- **Infrastructure (Chroma, SQLite, Server Hosting):** \$300 per month
- **API Consumption (ElevenLabs, Twilio, OpenAI):** \$1,200 per month (based on 5,000 call minutes)
- **Total Monthly Operational Budget:** \$36,500

---

## 11. Appendix

### 11.1 Glossary
- **SR (Service Request):** A ticket registered in the database describing customer details and car issue descriptions.
- **RAG (Retrieval-Augmented Generation):** Querying a vector database to supply relevant context before generating an answer.
- **STT (Speech-to-Text):** Transcribing audio stream inputs into text strings.
- **TTS (Text-to-Speech):** Synthesizing text strings into spoken voice audio streams.
- **TwiML (Twilio Markup Language):** XML instructions instructing Twilio how to direct and connect calls.

### 11.2 Mock Database Schema (Seed Script Reference)
```bash
# Seed initial client, vehicle, service request, and slot entries:
python3 -m serviceBot.db.seed
```
*For complete schema design and table descriptions, see the [database_spec.md](file:///Users/rohanroy/voiceService/docs/specs/database_spec.md).*
