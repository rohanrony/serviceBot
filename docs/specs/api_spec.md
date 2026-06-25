# API Specification (VoiceAI)

This document outlines the API contracts for the VoiceAI server. The server acts as a coordinator between telephony/voice providers (Twilio & ElevenLabs), the configuration portal, and internal integrations (Mock CRM & SQLite databases).

---

## 1. Webhook APIs (Voice & Telephony Integration)

### 1.1 Inbound Call Webhook (Twilio)
Triggered by Twilio when an inbound call is received on the provisioned number.

* **Endpoint:** `POST /api/v1/telephony/inbound`
* **Content-Type:** `application/x-www-form-urlencoded`
* **Request Payload (Twilio Standard):**
  ```json
  {
    "CallSid": "CAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "From": "+15551234567",
    "To": "+15557654321",
    "Direction": "inbound"
  }
  ```
* **Response:** Twilio Markup Language (TwiML) to forward the audio stream to ElevenLabs Conversational AI, resolving the `agentId` dynamically based on the configured model/voice in the portal or environment settings (ADR 7).
  ```xml
  <Response>
      <Connect>
          <!-- agentId is dynamically resolved based on current portal configuration -->
          <ConversationAgent url="https://api.elevenlabs.io/v1/convai/conversation/stream" agentId="{resolved_agent_id}" />
      </Connect>
  </Response>
  ```

---

### 1.2 Post-Call Webhook (ElevenLabs Event Webhook)
Triggered by ElevenLabs when a conversation concludes and analysis is complete. It updates the customer profile and records call summary and turn-by-turn transcript logs in `crm_notes`.

* **Endpoint:** `POST /api/v1/telephony/webhook`
* **Content-Type:** `application/json`
* **Request Payload (ElevenLabs Event Notification):**
  ```json
  {
    "type": "post_call_transcription",
    "event_timestamp": 1700000000,
    "data": {
      "conversation_id": "conv_xxxx",
      "agent_id": "agt_xxxx",
      "analysis": {
        "summary": "Customer called reporting brake issues..."
      },
      "metadata": {
        "from_number": "+15551234567"
      },
      "transcript": [
        {
          "role": "user",
          "message": "My brakes are squealing."
        },
        {
          "role": "agent",
          "message": "Let me help schedule repair."
        }
      ]
    }
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "success": true
  }
  ```

---

### 1.3 ElevenLabs Custom Tool Integration (Function Webhooks)
ElevenLabs invokes this endpoint when the Conversational AI agent triggers a custom function calling block.

* **Endpoint:** `POST /api/v1/voice/tools`
* **Payload Support:** This endpoint accepts **both** the ElevenLabs standard wrapped format and a flat key-value parameter format (e.g. for direct webhooks or simplified tool configurations).

#### Format A: ElevenLabs Standard Wrapped Format
```json
{
  "tool_call_id": "call_abc123",
  "name": "create_service_request",
  "arguments": {
    "customer_name": "Sarah Johnson",
    "phone": "555-123-4567",
    "make": "Honda",
    "model": "Civic",
    "year": 2020,
    "service_type": "Brake repair",
    "issue_description": "Grinding noise when stopping"
  }
}
```

#### Format B: Flat Parameter Format
```json
{
  "tool_call_id": "call_flat",
  "make": "Honda",
  "model": "Civic",
  "year": 2020,
  "issue_description": "Grinding noise when stopping"
}
```

#### Available Custom Tools

##### 1. `check_availability`
Checks available unbooked slots on or after preferred_date.
* **Arguments:**
  - `preferred_date` / `preferredDate` (string, format: `YYYY-MM-DD` or similar)
* **Response Result:**
  ```json
  {
    "success": true,
    "available_slots": [
      {
        "id": 1,
        "slot_datetime": "2026-06-09 14:00:00",
        "is_booked": false,
        "staff_agent_id": 1
      }
    ],
    "message": "Found 1 available slots on/after 2026-06-09."
  }
  ```

##### 2. `create_service_request`
Gathers vehicle details and auto issue to register a service ticket.
* **Arguments:**
  - `customer_name` / `name` (string)
  - `phone` (string, validated to be a valid 10-digit number; formatting is automatically stripped/normalized)
  - `make` (string)
  - `model` (string)
  - `year` (integer)
  - `issue_description` / `issue` (string)
  - `service_type` / `serviceType` (string, optional, defaults to `"Repair"`)
* **Response Result:**
  ```json
  {
    "success": true,
    "service_request_id": 12345,
    "message": "Service request created successfully."
  }
  ```

##### 3. `book_appointment`
Locks a calendar slot and links it to the active service request.
* **Arguments:**
  - `phone` (string)
  - `appointment_datetime` / `appointmentDatetime` / `datetime` (string, format: `YYYY-MM-DD HH:MM:SS`)
  - `service_type` / `serviceType` (string, optional)
* **Response Result:**
  ```json
  {
    "success": true,
    "appointment_id": 42,
    "message": "Appointment booked successfully."
  }
  ```

##### 4. `query_knowledge_base` / `faq_lookup`
Runs vector database semantic search against cached store files.
* **Arguments:**
  - `query_text` / `query` (string)
* **Response Result:**
  ```json
  {
    "success": true,
    "answer": "Regular oil changes at Christian Brothers Automotive cost between $79 and $119 depending on motor oil type."
  }
  ```

##### 5. `cba_webbook` / `cba_webhook` / `transfer_call` / `handoff`
Triggers immediate handoff to a human representative, generating a brief transcript summary.
* **Arguments:**
  - `phone` (string, optional)
  - `customer_name` / `name` (string, optional)
  - `issue_description` (string, optional)
* **Response Result:**
  ```json
  {
    "success": true,
    "message": "Call transferred to human customer service representative successfully.",
    "summary": "- Customer Name: Sarah Johnson\n- Active Service Request ID: 12345\n- Urgency Level: HIGH\n- Appointment Scheduled: None"
  }
  ```

---

## 2. Portal REST APIs (Business Configuration)

### 2.1 Dynamic Prompt & System Settings Configuration

#### Get Active Settings
* **Endpoint:** `GET /api/v1/portal/config`
* **Response (200 OK):**
  ```json
  {
    "required_fields": {
      "customer_name": true,
      "phone_number": true,
      "vehicle_details": true,
      "issue_description": true,
      "location": true
    },
    "prompts": {
      "router": "Intent classifier prompt content...",
      "service_request": "Intake agent prompt content...",
      "appointment": "Booking assistant prompt...",
      "faq": "RAG answering instructions...",
      "handoff": "Summary compiling instructions..."
    }
  }
  ```

#### Save Updated Settings
* **Endpoint:** `POST /api/v1/portal/config`
* **Request Payload:** Same structure as the config response.
* **ElevenLabs Integration:** Saves configurations locally to `config.json` and dynamically compiles a master instruction prompt combining all 5 sub-prompts. It then synchronizes this combined prompt directly to the ElevenLabs Conversational AI agent via `PATCH https://api.elevenlabs.io/v1/convai/agents/{agent_id}` using the XI-API-Key headers.
* **Response (200 OK):**
  ```json
  {
    "success": true
  }
  ```

---

### 2.2 Services Catalog CRUD API

#### Fetch Catalog
* **Endpoint:** `GET /api/v1/portal/services`
* **Database Behavior:** Dynamically queries the SQLite database. If duplicate services with the same name exist, it automatically runs a cleanup query that deduplicates entries by name, keeping the one with the lowest ID (first inserted) and removing others.
* **Response (200 OK):**
  ```json
  [
    {
      "id": 1,
      "name": "Oil Change",
      "description": "Full synthetic oil change...",
      "price_range": "$79-119",
      "duration_minutes": 45,
      "req_customer_name": true,
      "req_phone_number": true,
      "req_vehicle_details": true,
      "req_issue_description": true,
      "req_location": true
    }
  ]
  ```

#### Create Service offering
* **Endpoint:** `POST /api/v1/portal/services`
* **Duplication Prevention:** Before inserting a new service catalog entry, the backend checks if a service with the same name already exists. If it does, a `400 Bad Request` HTTP exception is raised with the detail `"Service with this name already exists in the catalog"`.
* **Request Payload:**
  ```json
  {
    "name": "Brake Repair",
    "description": "Front/Rear brake pad replacement",
    "price_range": "$150-400",
    "duration_minutes": 90,
    "req_customer_name": true,
    "req_phone_number": true,
    "req_vehicle_details": true,
    "req_issue_description": true,
    "req_location": false
  }
  ```
* **Response (201 Created):**
  ```json
  {
    "id": 2,
    "name": "Brake Repair",
    "success": true
  }
  ```

#### Update Service offering
* **Endpoint:** `PUT /api/v1/portal/services/{service_id}`
* **Request Payload:** Same structure as POST.
* **Response (200 OK):**
  ```json
  {
    "id": 2,
    "name": "Brake Repair",
    "success": true
  }
  ```

#### Delete Service offering
* **Endpoint:** `DELETE /api/v1/portal/services/{service_id}`
* **Response (200 OK):**
  ```json
  {
    "id": 2,
    "success": true
  }
  ```

---

### 2.3 Knowledge Base File Management

#### Upload and Index Document
* **Endpoint:** `POST /api/v1/portal/kb/upload`
* **Content-Type:** `multipart/form-data`
* **Request Payload:** File attachment (e.g., UTF-8 `.txt` file)
* **Response (200 OK):**
  ```json
  {
    "file_id": "kb_doc_pricing.txt",
    "filename": "pricing.txt",
    "chunk_count": 12,
    "success": true
  }
  ```

#### List Uploaded Documents
* **Endpoint:** `GET /api/v1/portal/kb`
* **Response (200 OK):**
  ```json
  [
    {
      "filename": "pricing.txt",
      "size_bytes": 1024
    }
  ]
  ```

#### View File Content
* **Endpoint:** `GET /api/v1/portal/kb/view/{filename}`
* **Response (200 OK):**
  ```json
  {
    "filename": "pricing.txt",
    "content": "Raw file text string content here..."
  }
  ```

#### Download Document File
* **Endpoint:** `GET /api/v1/portal/kb/download/{filename}`
* **Response:** File payload stream (binary/octet-stream).

#### Delete Document and Purge Embeddings
* **Endpoint:** `DELETE /api/v1/portal/kb/{filename}`
* **Response (200 OK):**
  ```json
  {
    "filename": "pricing.txt",
    "success": true
  }
  ```

---

### 2.4 Staff Calendars & Booking Slots

#### List Available Staff Agents
* **Endpoint:** `GET /api/v1/portal/agents`
* **Response (200 OK):**
  ```json
  [
    {
      "id": 1,
      "name": "John Doe",
      "role": "Master Mechanic"
    }
  ]
  ```

#### Fetch Calendar for Specific Staff
* **Endpoint:** `GET /api/v1/portal/agents/{agent_id}/calendar`
* **Response (200 OK):**
  ```json
  [
    {
      "id": 1,
      "slot_datetime": "2026-06-09 14:00:00",
      "is_booked": false,
      "staff_agent_id": 1
    }
  ]
  ```

#### Add New Calendar Slot
* **Endpoint:** `POST /api/v1/portal/agents/{agent_id}/calendar`
* **Request Payload:**
  ```json
  {
    "slot_datetime": "2026-06-10 10:00:00",
    "is_booked": false
  }
  ```
* **Response (201 Created):**
  ```json
  {
    "id": 5,
    "slot_datetime": "2026-06-10 10:00:00",
    "success": true
  }
  ```

#### Update Slot Status
* **Endpoint:** `PATCH /api/v1/portal/calendar/{slot_id}`
* **Request Payload:**
  ```json
  {
    "is_booked": true
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "id": 5,
    "slot_datetime": "2026-06-10 10:00:00",
    "is_booked": true,
    "success": true
  }
  ```

#### Delete Calendar Slot
* **Endpoint:** `DELETE /api/v1/portal/calendar/{slot_id}`
* **Response (200 OK):**
  ```json
  {
    "id": 5,
    "success": true
  }
  ```

---

### 2.5 ElevenLabs Platform Integration

#### Fetch Voices List
* **Endpoint:** `GET /api/v1/portal/elevenlabs/voices`
* **Headers:** XI-API-Key (read from server settings)
* **Response:** Pass-through JSON payload from ElevenLabs `/v1/voices` endpoint.

#### Update ElevenLabs Agent Configuration
* **Endpoint:** `PATCH /api/v1/portal/elevenlabs/agent`
* **Request Payload:**
  ```json
  {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "model": "gemini-1.5-flash"
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "success": true,
    "data": {
      "agent_id": "target-agent-id",
      "updated_at": "..."
    }
  }
  ```

---

### 2.6 Call Summary Logs

#### Fetch Call Logs (Joined with Customer profile)
* **Endpoint:** `GET /api/v1/portal/calls`
* **Response (200 OK):**
  ```json
  [
    {
      "id": 1,
      "call_id": "CA12345",
      "customer_name": "Sarah Johnson",
      "phone": "555-123-4567",
      "summary": "Customer called reporting grinding noise on Honda Civic. Service request created (ID: 12345). Appointment booked for Tuesday 4PM.",
      "transcript": "Customer: Hello...\nAI: Hi there...",
      "created_at": "2026-06-08T14:30:00Z"
    }
  ]
  ```

---

## 3. Frontend Static Routing

To serve the Business Configuration Portal, the FastAPI application mounts a static assets folder.

* **Asset Mapping:**
  - Mounted directory: `serviceBot/static/`
  - URL Base Prefix: `/portal` (e.g. `http://localhost:8000/portal/`)
  - Subpaths:
    - `/portal` or `/portal/index.html` -> Serves HTML Dashboard
    - `/portal/style.css` -> Serves stylesheet
    - `/portal/app.js` -> Serves frontend Javascript logics
