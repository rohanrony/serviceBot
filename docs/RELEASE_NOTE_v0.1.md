# VoiceAI Platform - Version 0.1 Release Notes

**Release Date:** June 11, 2026  
**Status:** MVP Released  
**Author:** Product Management & Core Engineering  

---

## Executive Summary
Version 0.1 of the **VoiceAI Platform** represents the successful delivery of our Minimum Viable Product (MVP) for autonomous inbound call handling. Designed specifically for small-to-medium service businesses (SMBs) like auto repair shops and medical clinics, VoiceAI integrates Twilio, ElevenLabs Conversational AI, and LangGraph-driven multi-agent workflows. It classifies call intent, pulls customer records, registers service requests, books calendar slots, answers FAQs via semantic search (RAG), and executes seamless human handoffs with context summaries.

All core infrastructure and features outlined in [PRD_v0.1.md](file:///Users/rohanroy/voiceService/PRD_v0.1.md) have been successfully built, verified, and are passing 74 comprehensive test suites.

---

## Key Features Shipped

### 1. Conversational AI Engine & Telephony Gateway
* **Twilio Inbound Calling:** Secure webhook endpoints dispatch TwiML to establish bidirectional WebSocket streams between incoming phone calls and ElevenLabs.
* **ElevenLabs Stream Integration:** Direct integration supporting sub-second speech-to-text (STT), low-latency LLM reasoning (using `gpt-4o-mini`), and natural text-to-speech (TTS) voice generation.
* **DTMF Keypad Support:** Enables callers to interact and make selections using dual-tone multi-frequency signals (keypad entry).

### 2. Multi-Agent LangGraph Orchestrator
* **Intent Classification & Routing:** Classifies caller inputs into 7 predefined intents (*new customer intake, appointment booking, rescheduling, cancellations, FAQ, human handoff, greetings*) with a specialized LLM classifier node.
* **Pre-Call CRM Lookup:** Automatically queries SQLite upon connection using Twilio caller ID (`caller_id`/`From` phone number) to load customer names, vehicles, and active service requests.
* **Service Intake Agent:** Captures customer names, phone numbers, vehicle profiles, and issue descriptions to register new service requests.
* **Appointment Booking & Rescheduling:** Automatically retrieves unbooked slots, presents specific calendar times, schedules appointments within business workhours (Monday-Friday 7 AM - 6 PM Eastern), and handles rescheduling/cancellations.
* **FAQ Semantic Search (RAG):** Integrates ChromaDB vector store to search indexed business documentation, ensuring precise, hallucination-free answers.
* **Contextual Human Handoff:** Packages conversation history and active service profiles into a 3-5 bullet point summary payload before transferring calls to human specialists.

### 3. Business Configuration Web Portal
* **Glassmorphic Single Page App (SPA):** High-fidelity dark-themed web dashboard for business managers located at `/portal` (`index.html`, `style.css`, `app.js`).
* **Real-time Live Sync:** Allows configuration of custom prompts, voice selections, and API key credentials.
* **Services Catalog Management:** CRUD interfaces to manage service catalogs, pricing structures, and fields required for intake.
* **Call Logs & Transcripts Viewer:** View recent calls, detailed summaries, and full conversation transcripts.

### 4. Security & Compliance
* **API Key Encryption:** AES-256 encryption using standard salts to safeguard third-party tokens (Twilio, ElevenLabs, OpenAI/Claude) in SQLite.
* **PII & Data Retention Hygiene:** Automated GDPR-compliant deletion of call logs and transcripts after 90 days.

---

## Technical Specifications & DB Schema
This version employs an **SQLite database** containing the following key tables:
* `customers` & `vehicles` (Customer profiles and vehicle history)
* `service_requests` (Consolidated table tracking customer car issues, maintenance tickets, appointments, and callback requests with booking type, booking time, and ASAP support)
* `mock_calendar_slots` (Staff availability slots)
* `services` (Configured business service catalog)
* `crm_notes` (Call transcript details and AI-generated summaries)

---

## Testing & Verification
We have verified system correctness, database queries, API endpoints, and graph nodes using `pytest`.
* **Total Automated Tests:** 74
* **Result:** **74 Passed (100% success rate)**
* **Coverage Highlights:**
  * **Database layer:** `test_db_connection.py`, `test_db_queries.py`
  * **Graph nodes:** `test_intent_classifier.py`, `test_service_request_agent.py`, `test_appointment_agent.py`, `test_rag_faq.py`, `test_handoff.py`
  * **API Controllers:** `test_telephony_webhook.py`, `test_portal_api.py`, `test_voice_tools.py`, `test_post_call_webhook.py`, `test_dynamic_config.py`
  * **Frontend Asset serving:** `test_ui.py`

---

## How to Get Started

### 1. Database Seeding & Setup
Generate initial mock customer data, vehicles, staff slots, and services:
```bash
python3 -m serviceBot.db.seed
```

To seed the specific Christian Brothers Automotive (CBA) service catalog:
```bash
python3 serviceBot/seed_cba_services.py
```

### 2. Ingesting FAQ Knowledge Base
Index text documents inside the `kb_documents` folder into ChromaDB:
```bash
python3 serviceBot/db/index_kb.py
```

### 3. Starting the Server
Run the FastAPI application locally:
```bash
.venv/bin/uvicorn serviceBot.main:app --reload --port 8000
```
Open [http://localhost:8000/portal](http://localhost:8000/portal) to access the Business Configuration Portal.
