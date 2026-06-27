

## **1. Product Overview**

### **1.1 Executive Summary**

VoiceAI is an AI-powered inbound call handling platform for small-to-medium service businesses (SMBs) designed to solve the problem of lost revenue from missed calls and high front-desk operational overhead. By replacing rigid traditional IVR menus with a sub-second latency, multi-agent conversational assistant, VoiceAI automates call triage, intake, calendar bookings, and email notifications. The platform features agent-level Google Calendar OAuth integrations for live schedule checking and Gmail integrations (OAuth/SMTP) for automatic customer and staff alerts, resulting in 100% call coverage, a 40-60% reduction in support costs, and seamless human handoff with full context.

### **1.2 What We're Building**

An AI-powered inbound call handling platform (like Retell AI) that enables businesses to automate customer service, fuzzy catalog matching, appointment booking, and email alerts for phone calls. The system uses conversational AI to understand intent, capture customer/vehicle information, perform actions (database/CRM updates, live Google Calendar bookings, automated Gmail notifications), and handoff to humans when needed.

### **1.3 Problem Statement**

- **Businesses lose revenue** from missed calls, long wait times, and unavailable staff
- **Customer service teams** are overwhelmed with repetitive tasks (appointment booking, FAQ, status updates)
- **Existing solutions** (Retell, ElevenLabs) require technical expertise to configure complex call flows
- **No easy way** to customize call patterns, service types, and CRM integrations without coding


### **1.4 Target Market**

- **Primary:** Small-to-medium service businesses (automotive shops, dental clinics, medical offices, home services)
- **Secondary:** Enterprise contact centers looking for AI triage layer
- **Example Customer:** Christian Brothers Automotive (multi-location auto service chain)


### **1.5 Value Proposition**

| For Businesses | For Customers Calling |
| :-- | :-- |
| Answer 100% of inbound calls instantly | Get immediate assistance, no waiting |
| Reduce customer service costs by 40-60% | Book appointments 24/7 without staff |
| Automate repetitive tasks (booking, FAQs) | Natural conversation, not robotic IVR |
| Capture complete call data in CRM | Choose preferred LLM model and voice |
| Scale without adding staff | Enter info via keypad (DTMF) when needed |


***

## **2. Success Metrics (KPIs)**

### **2.1 MVP Success Criteria**

| Metric | Target | Measurement |
| :-- | :-- | :-- |
| **Call Answer Rate** | 100% | All inbound calls answered within 1 second |
| **Intent Classification Accuracy** | >90% | Correct intent detection from first statement |
| **First Call Resolution (FCR)** | >80% | Calls completed without human handoff |
| **Average Call Response Latency** | <800ms | Time from user stops speaking to AI responds |
| **CRM Integration Success Rate** | >95% | Service requests/appointments saved correctly |
| **Human Handoff Satisfaction** | >85% | Users satisfied with handoff context transfer |

### **2.2 Business Outcomes (Post-MVP)**

- **Revenue Impact:** Increase appointment booking rate by 25%
- **Cost Savings:** Reduce customer service staff hours by 40%
- **Customer Satisfaction:** Improve NPS from 35 to 50+

***

## **3. User Personas**

### **3.1 Primary Persona: Business Owner/Manager**

**Name:** "Mike, Owner of Christian Brothers Automotive"
**Demographics:** 45 years old, owns 3-location auto shop, 25 employees
**Goals:**

- Answer every customer call immediately (even after hours)
- Reduce front desk workload by automating appointment booking
- Capture complete customer info in CRM without manual entry
- Scale service capacity without hiring more staff

**Pain Points:**

- Missed calls = lost revenue (\$150-400 per missed service appointment)
- Front desk overwhelmed with repetitive booking calls
- Staff forget to capture complete info in CRM
- Can't afford enterprise contact center solutions (\$500+/month)

**Use Cases:**

1. **Configure Services:** Add new service types (oil change, brake repair) with pricing
2. **Set Call Flows:** Define what info to capture for each intent (new SR vs. existing SR)
3. **Monitor Calls:** Review call transcripts, CRM updates, appointment bookings
4. **Override Handoff:** Manually trigger human transfer when system misinterprets

### **3.2 Secondary Persona: Customer Calling In**

**Name:** "Sarah, Customer calling for brake repair"
**Demographics:** 35 years old, Honda Civic owner, works 9-5
**Goals:**

- Get help immediately without waiting
- Book appointment for next week conveniently
- Get pricing info without calling back
- Talk to human if AI can't help

**Use Cases:**

1. **New Service Request:** "I'm a new customer, need brake repair on my 2020 Honda Civic"
2. **Appointment Booking:** "Schedule oil change for Tuesday afternoon"
3. **FAQ:** "How much does tire replacement cost?"
4. **Human Handoff:** "I want to talk to a manager"

### **3.3 Technical Persona: Developer/Integrator**

**Name:** "Alex, IT Manager at dental clinic"
**Demographics:** 30 years old, manages clinic tech stack
**Goals:**

- Integrate with existing CRM (HubSpot, Salesforce)
- Connect to calendar system (Google Calendar, Outlook)
- Customize call flows without coding
- Select preferred LLM (OpenAI vs. Claude)

***

## **4. User Scenarios \& Journey Maps**

### **4.1 Business Owner: Configure Call Flow for New Service Request**

**Journey:**

```
1. Login to portal → Dashboard
2. Click "Configure Call Flows" → Intent Management
3. Select "New Customer Service Request" intent
4. Add required fields:
   - Customer Name (text)
   - Phone (tel)
   - Vehicle Make (dropdown: Honda, Toyota, Ford, etc.)
   - Vehicle Model (text)
   - Vehicle Year (number)
   - Service Type (dropdown: oil change, brake repair, etc.)
   - Issue Description (long text)
5. Set follow-up question: "Would you like to book an appointment?"
6. Save configuration → Instantly active for inbound calls
```

**Success Criteria:**

- Configuration saved in <2 seconds
- Changes live immediately (no deployment needed)
- No coding required


### **4.2 Customer: New Service Request + Appointment Booking**

**Journey:**

```
1. Call business phone number
2. AI: "Hello! Welcome to Christian Brothers Automotive. How can I help?"
3. Customer: "I'm new here, need brake repair on my 2020 Honda Civic. Grinding noise when stopping."
4. AI: (Pre-call CRM lookup → customer not found) "Thanks, Sarah. Let me capture your info."
   - "What's your full name?" → "Sarah Johnson"
   - "Phone number?" → "555-123-4567"
   - "Vehicle details (Year, Make, Model)?" → "2020 Honda Civic"
   - "Service type?" → "Brake repair" (Fuzzy matched to 'Brake Repair' catalog entry)
   - "Describe issue?" → "Grinding noise when I stop, started 3 days ago"
5. AI: (Creates SR & registers/resolves vehicle in DB → ID: 12345) "Service request created (ID: 12345). Would you like to book an appointment?"
6. Customer: "Yes, next Tuesday afternoon"
7. AI: (Checks calendar availability via live Google Calendar/mock slots → offers slots) "Available: Tuesday 2PM, 4PM, or Wednesday 10AM. Which works?"
8. Customer: "Tuesday 4PM"
9. AI: (Books appointment → ID: 6789. Blocks slot in mock DB + creates event on assigned agent's Google Calendar. Triggers automated Gmail notification to staff and customer) "Appointment booked for Tuesday, June 10 at 4PM. Confirmation sent to your email."
10. AI: "Anything else I can help with?"
11. Customer: "No, thanks"
12. AI: (Post-call summary → CRM) "Call complete. Thanks for calling!"
```

**Success Criteria:**

- Complete SR captured in <3 minutes
- Appointment booked with 2 slot options offered
- SMS/Email confirmation sent automatically
- No human needed


### **4.3 Customer: Human Handoff Request**

**Journey:**

```
1. Call business
2. AI: "Hello! How can I help?"
3. Customer: "I want to talk to a human about my bill"
4. AI: (Intent: human_handoff → triggers handoff flow) "I'll transfer you to a billing specialist now."
5. AI: (Generates summary → transfers with context)
   - Transcript: "Customer requested to talk to human about bill"
   - Customer: Sarah Johnson, 555-123-4567
   - Open SR: None
   - Upcoming Appointment: Tuesday 4PM (brake repair)
   - Urgency: Medium
   - Specialist: Billing
6. Human: (Receives call with full context) "Hi Sarah, I'm Mike from billing. I see you mentioned an issue with your bill?"
7. Customer: (No need to repeat info) "Yes, I was charged twice for my last oil change"
```

**Success Criteria:**

- Handoff triggered immediately on user request
- Human receives full transcript + CRM context
- Customer doesn't need to repeat information

***

## **5. Functional Requirements**

### **5.1 Core Features (MVP - P0)**

#### **FR-1: Intent Classification \& Routing**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-1.1** | Detect intent from user's first statement | P0 |
| **FR-1.2** | Support 7 intents: new SR, existing SR update, appointment booking, reschedule, cancel, FAQ, human handoff | P0 |
| **FR-1.3** | Route to specialized sub-agent based on intent | P0 |
| **FR-1.4** | Allow business to customize intent triggers via portal | P0 |
| **FR-1.5** | Pre-call CRM lookup for existing customers (before routing) | P0 |

**Acceptance Criteria:**

- Intent detected with >90% accuracy from first 2 sentences
- Routing to sub-agent happens in <500ms
- Business can add/edit intent triggers without code


#### **FR-2: Service Request Management**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-2.1** | Capture required fields for new SR (customer info, vehicle info, service type, issue) | P0 |
| **FR-2.2** | Configurable fields per intent (business defines what to capture) | P0 |
| **FR-2.3** | Create SR in CRM (mock DB for MVP, real CRM API post-MVP) | P0 |
| **FR-2.4** | Update existing SR with additional notes | P0 |
| **FR-2.5** | Lookup SR status by phone number or SR ID | P0 |
| **FR-2.6** | Ask if user wants to book appointment after SR creation | P0 |
| **FR-2.7** | Automatically resolve and register vehicle make, model, and year in the database, with fallbacks to default values if not provided. | P0 |
| **FR-2.8** | Match user-mentioned service names to the catalog using fuzzy similarity metrics (Jaccard token matching). | P0 |

**Acceptance Criteria:**

- All required fields captured in natural conversation flow
- SR created in <2 seconds
- Business can configure which fields are required per intent
- Fuzzy service catalog lookup resolves synonyms and partial queries accurately (Jaccard similarity >= 0.25)


#### **FR-3: Appointment Scheduling**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-3.1** | Check calendar availability for service type + date | P0 |
| **FR-3.2** | Offer 2-3 specific time slots (not open-ended "what works") | P0 |
| **FR-3.3** | Book appointment in calendar (Google Calendar API for MVP, with mock DB fallback) | P0 |
| **FR-3.4** | Reschedule existing appointment | P0 |
| **FR-3.5** | Cancel appointment | P0 |
| **FR-3.6** | Send SMS/email confirmation alerts (using Gmail SMTP or OAuth 2.0 REST API) | P0 |
| **FR-3.7** | Link appointment to service request (optional) | P0 |
| **FR-3.8** | Perform live checks against multiple connected staff Google Calendars concurrently using ThreadPoolExecutor. | P0 |

**Acceptance Criteria:**

- Availability check returns in <1 second
- At least 2 slots offered when available
- Confirmation sent via Gmail (SMTP or OAuth) within 5 seconds of booking
- Concurrent calendar lookups do not block the request loop


#### **FR-4: FAQ \& Business Knowledge (RAG)**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-4.1** | Stream knowledge base content during conversation | P0 |
| **FR-4.2** | Support PDF, text files as knowledge sources | P0 |
| **FR-4.3** | Answer pricing, service descriptions, hours, location | P0 |
| **FR-4.4** | Escalate to human if question outside knowledge base | P0 |
| **FR-4.5** | Business can upload/edit knowledge base via portal | P0 |

**Acceptance Criteria:**

- KB search returns results in <500ms
- Answers accurate from KB only (no hallucination)
- Business can add new KB file without code


#### **FR-5: Human Handoff**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-5.1** | Trigger handoff on explicit user request ("talk to human") | P0 |
| **FR-5.2** | Trigger handoff on planned call flows (e.g., billing dispute, complex technical issue) | P0 |
| **FR-5.3** | **NOT** trigger on confidence threshold (removed from MVP) | N/A |
| **FR-5.4** | Generate 3-5 bullet summary for human | P0 |
| **FR-5.5** | Transfer full transcript + CRM context (SR ID, appointment ID, customer history) | P0 |
| **FR-5.6** | Offer callback if human unavailable | P0 |
| **FR-5.7** | Support specialist routing (technician, billing, manager) | P0 |

**Acceptance Criteria:**

- Handoff triggered immediately on user request
- Human receives complete context within 1 second
- Callback offered if wait time >5 minutes


#### **FR-6: LLM \& Voice Selection**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-6.1** | Allow customer to select LLM model (OpenAI GPT-4 vs. Claude 3.5) | P0 |
| **FR-6.2** | Allow customer to select voice (ElevenLabs provides 10+ voices) | P0 |
| **FR-6.3** | Business configures available models/voices in portal | P0 |
| **FR-6.4** | API keys entered in portal (business provides their own) | P0 |
| **FR-6.5** | Switch model mid-call if needed | P1 |

**Acceptance Criteria:**

- Model selection available at call start ("Which voice do you prefer?")
- Voice changes instantly after selection
- API keys stored securely (encrypted)


#### **FR-7: DTMF (Keypad Input)**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-7.1** | Support DTMF tones (0-9, *, \#) | P0 |
| --- | --- | --- |
| **FR-7.2** | Service type selection from menu via keypad | P0 |
| **FR-7.3** | Date/time selection from available slots via keypad | P0 |
| **FR-7.4** | Enable when user mentions "press numbers" or "keypad" | P0 |
| **FR-7.5** | Visual feedback on portal (show which option selected) | P1 |

**Acceptance Criteria:**

- DTMF detected within 200ms of press
- Menu options clearly announced before DTMF enabled
- No confusion between voice and keypad input


### **5.2 Portal Features (MVP - P0)**

#### **FR-8: Business Configuration Portal**

| Requirement | Description | Priority |
| :-- | :-- | :-- |
| **FR-8.1** | Login/authentication (email + password) | P0 |
| **FR-8.2** | Dashboard: call stats, recent transcripts, CRM updates, active appointments with vehicle data, callback requests | P0 |
| **FR-8.3** | Intent Management: add/edit/triggers, required fields | P0 |
| **FR-8.4** | Service Management: add services (name, description, price range, duration) | P0 |
| **FR-8.5** | Knowledge Base: upload PDFs, text files | P0 |
| **FR-8.6** | API Key Management: encrypted (AES-256) storage for OpenAI, Claude, ElevenLabs, Twilio | P0 |
| **FR-8.7** | Voice Selection: choose from ElevenLabs voices | P0 |
| **FR-8.8** | CRM Integration: mock DB (MVP), HubSpot/Salesforce (post-MVP) | P0 |
| **FR-8.9** | Calendar Integration: Google Calendar OAuth 2.0 connection per agent with slot pre-population | P0 |
| **FR-8.10** | Email Config: Gmail system alerts setup with dual support for SMTP and Google OAuth 2.0 flow | P0 |

**Acceptance Criteria:**

- All configurations saved in <2 seconds
- Changes live immediately (no deployment)
- No coding required for any feature
- Dashboard updates automatically to show incoming call summaries, callback requests, and detailed appointment info


### **5.3 Non-Functional Requirements (P0)**

#### **NFR-1: Performance**

| Requirement | Target | Measurement |
| :-- | :-- | :-- |
| **NFR-1.1** | Call response latency | <800ms |
| **NFR-1.2** | Intent classification time | <500ms |
| **NFR-1.3** | CRM lookup time | <300ms |
| **NFR-1.4** | RAG search time | <500ms |
| **NFR-1.5** | Appointment availability check | <1s |

#### **NFR-2: Scalability**

| Requirement | Target | Measurement |
| :-- | :-- | :-- |
| **NFR-2.1** | Concurrent calls | 100+ |
| **NFR-2.2** | Calls per day | 10,000+ |
| **NFR-2.3** | Database size | 1M+ records |

#### **NFR-3: Security**

| Requirement | Implementation |
| :-- | :-- |
| **NFR-3.1** | API key encryption |
| **NFR-3.2** | Customer data privacy |
| **NFR-3.3** | Authentication |
| **NFR-3.4** | Call data retention |

#### **NFR-4: Reliability**

| Requirement | Target |
| :-- | :-- |
| **NFR-4.1** | Uptime |
| **NFR-4.2** | Call failure rate |
| **NFR-4.3** | CRM sync success rate |


***

## **6. Technical Architecture**

### **6.1 Architecture Decision: Multi-Agent vs. Single React Agent**

**Decision:** **Multi-Agent with Intent Routing + LangGraph** (NOT single React agent)

**Reasoning:**


| Factor | Multi-Agent (Selected) | Single React Agent |
| :-- | :-- | :-- |
| **Complex Workflows** | ✅ Excellent (separate SR, appointment, FAQ agents) | ❌ Poor (everything in one agent) |
| **Intent Control** | ✅ Explicit routing (intent → sub-agent) | ❌ Implicit (agent decides internally) |
| **Error Handling** | ✅ Per-agent error recovery | ❌ Global error handling |
| **Customization** | ✅ Business configures each agent separately | ❌ Hard to modify specific flows |
| **Performance** | ✅ Parallel execution (SR + appointment) | ❌ Sequential (everything linear) |
| **Scalability** | ✅ Add new agents without breaking existing | ❌ Agent gets larger, slower |

**Reference:** LangGraph provides explicit DAG control for call flows, branching logic, and error handling

### **6.2 System Architecture Diagram**

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CUSTOMER CALLS IN                           │
│                    (Phone via Twilio/ElevenLabs)                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         TWILIO WEBHOOK                                │
│  (Receives inbound call → forwards to ElevenLabs Conversational AI) │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ELEVENLABS CONVERSATIONAL AI                       │
│  - Sub-second latency STT (speech-to-text)                          │
│  - LLM reasoning (OpenAI or Claude, selected by user)                │
│  - TTS (text-to-speech) with user-selected voice                     │
│  - DTMF tone detection (keypad input)                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      LANGGRAPH CALL FLOW (graph.py)                   │
│                                                                       │
│  greeting → intent_classification → pre_call_crm_lookup              │
│                     │                                                  │
│                     ├─► new SR ──► service_request_agent              │
│                     ├─► existing SR ──► service_request_agent         │
│                     ├─► appointment ──► appointment_agent             │
│                     ├─► FAQ ──► faq_rag_agent                         │
│                     └─► human handoff ──► handoff_agent               │
│                                                                       │
│                     └─► post_call_summary ──► End                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ├───────────────────────────────────────┐
                               │                                       │
                               ▼                                       ▼
┌─────────────────────────────────────┐  ┌─────────────────────────────────────┐
│         SERVICE REQUEST AGENT        │  │         APPOINTMENT AGENT            │
│  - Capture required fields          │  │  - check_availability()              │
│  - create_service_request()         │  │  - book_appointment()                │
│  - update_service_request()         │  │  - reschedule_appointment()          │
│  - Ask: "Book appointment?"         │  │  - cancel_appointment()              │
└─────────────────────────────────────┘  └─────────────────────────────────────┘
                                         
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DATA LAYER & INTEGRATIONS                        │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Mock CRM DB   │  │ Google Cal   │  │ RAG KB       │               │
│  │ (SQLite)     │  │ (API)        │  │ (ChromaDB)   │               │
│  │ - customers  │  │ - availability│ │ - pricing    │               │
│  │ - vehicles   │  │ - book       │  │ - services   │               │
│  │ - SRs        │  │ - reschedule │  │ - FAQs       │               │
│  │ - appointments│ │ - cancel     │  │              │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │ Twilio SMS   │  │ LLM APIs     │                                  │
│  │ (confirmations│  │ - OpenAI     │                                  │
│  │ )            │  │ - Claude     │                                  │
│  └──────────────┘  └──────────────┘                                  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      BUSINESS CONFIGURATION PORTAL                    │
│  (User-facing web app for configuring intents, services, KB, API keys)│
│                                                                       │
│  - Intent Management                                                 │
│  - Service Management                                                 │
│  - Knowledge Base Upload                                              │
│  - API Key Configuration (OpenAI, Claude, ElevenLabs, Twilio)        │
│  - Voice Selection                                                    │
│  - Dashboard (call stats, transcripts)                                │
└─────────────────────────────────────────────────────────────────────┘
```


### **6.3 Agent Prompts (Detailed)**

#### **Prompt 1: Intent Classification Agent**

```
You are an intent classifier for Christian Brothers Automotive.

ANALYZE the caller's statement and DETERMINE intent.

AVAILABLE INTENTS:
1. new_customer_service_request - New customer needing service
2. existing_customer_service_update - Existing customer updating SR
3. appointment_booking - Schedule new appointment
4. appointment_reschedule - Change existing appointment
5. appointment_cancel - Cancel appointment
6. faq_business_knowledge - Pricing, services, hours, FAQs
7. human_handoff - User wants to talk to human

RULES:
- Return JSON: {"intent": "<intent_name>", "reasoning": "<why"}
- If user explicitly says "talk to human", "representative", "manager" → human_handoff
- If intent is unclear after 2 questions → human_handoff
- Do NOT use confidence threshold (removed from MVP)

USER INPUT: "{user_statement}"

OUTPUT:
```


#### **Prompt 2: Service Request Agent**

```
You are a service request triage agent for Christian Brothers Automotive.

GOAL: Capture complete service request information naturally.

REQUIRED FIELDS (capture based on intent configuration):
{required_fields_from_config}

FLOW:
1. Ask questions naturally (NOT checklist-style)
2. If existing customer, use CRM data (vehicle info pre-filled)
3. After capturing all fields, call create_service_request()
4. Confirm: "Service request created (ID: {sr_id}). Would you like to book an appointment?"
5. If yes → transition to appointment_agent

BEHAVIORS:
- Ask 1 question at a time
- Acknowledge responses ("Thanks, that helps")
- If user mentions budget, probe importance ("Is this urgent or can it wait?")
- If user says "press numbers" or "keypad" → enable DTMF for service type selection

TONE: Friendly, professional, efficient
```


#### **Prompt 3: Appointment Agent**

```
You are an appointment scheduling agent for Christian Brothers Automotive.

GOAL: Book/reschedule/cancel appointments based on calendar availability.

PRE-CALL: Check if caller has existing appointment (from CRM lookup)

FOR NEW BOOKING:
1. Confirm service type: "You need {service_type}. Correct?"
2. Call check_appointment_availability(service_type, preferred_date)
3. Offer 2-3 SPECIFIC time slots (NOT "what time works?")
   Example: "Available: Tuesday 2PM, 4PM, or Wednesday 10AM. Which works?"
4. Once confirmed, call book_appointment()
5. Confirm: "Appointment booked for {datetime}. Confirmation sent to your phone."

FOR RESCHEDULE:
1. Get existing appointment ID
2. Ask: "What's your new preferred date/time?"
3. Call check_appointment_availability() for new date
4. Call reschedule_appointment()
5. Confirm changes

FOR CANCEL:
1. Get appointment ID
2. Confirm: "Cancel appointment for {datetime}? This is free."
3. Call cancel_appointment()
4. Offer: "Would you like to book a new appointment?"

TONE: Efficient, helpful, confirmatory
```


#### **Prompt 4: FAQ Agent (with RAG)**

```
You are a knowledge agent for Christian Brothers Automotive.

RULES:
- Answer ACCURATELY from knowledge base ONLY (no hallucination)
- Use streaming RAG: fetch KB content DURING conversation
- Keep responses CONCISE (voice conversation)
- If question outside KB: "I don't have that information. Let me transfer you to a human."

KNOWLEDGE SOURCES:
{kb_sources_from_config}

EXAMPLES:
- "How much oil change?" → "Basic oil change: $49-69 depending on oil type. Synthetic is $69."
- "What services?" → "We offer: oil change ($49-69), brake repair ($150-400), tire replacement ($200-600), inspection ($89-129)."
- "Hours?" → "We're open Monday-Friday 8AM-6PM, Saturday 8AM-4PM. Closed Sundays."

FUNCTION: streaming_rag_search(query) → returns relevant KB snippets

TONE: Informative, helpful, concise
```


#### **Prompt 5: Human Handoff Agent**

```
You are a human handoff coordinator.

WHEN TO TRANSFER:
1. User explicitly requests human ("talk to human", "representative", "manager")
2. Planned call flows trigger handoff (billing dispute, complex technical issue)
3. **NOT** on confidence threshold (removed from MVP)

BEFORE TRANSFER:
1. Generate 3-5 bullet summary:
   - Customer intent
   - Actions taken (SR created, appointment booked)
   - SR ID (if created)
   - Appointment ID (if booked)
   - Urgency (low/medium/high)
   - Specialist type (technician/billing/manager)

2. Call transfer_to_human():
   {
     "transcript": "{full_transcript}",
     "sr_id": "{sr_id}",
     "appointment_id": "{appointment_id}",
     "urgency": "{urgency}",
     "specialist_type": "{specialist}"
   }

3. Say: "I'll transfer you to a {specialist} now. They have your full conversation history."

AFTER TRANSFER: If human unavailable, offer callback:
"Current wait time is 10 minutes. Would you like a callback instead?"
```


***

## **7. MVP Scope \& Out-of-Scope**

### **7.1 MVP In-Scope (P0)**

✅ Multi-agent architecture with intent routing (LangGraph)
✅ 7 intents: new SR, existing SR, appointment booking/reschedule/cancel, FAQ, human handoff
✅ Service request creation/update in mock CRM (SQLite) with auto-resolution of vehicle details (make, model, year)
✅ Appointment booking/reschedule/cancel via Google Calendar API (live OAuth 2.0 checks + mock slot fallback)
✅ RAG-powered FAQ with streaming KB
✅ Human handoff with full context (transcript + CRM data)
✅ LLM selection: OpenAI GPT-4 vs. Claude 3.5 (user chooses)
✅ Voice selection: 10+ ElevenLabs voices (user chooses)
✅ DTMF support for keypad input
✅ Business configuration portal (intents, services, KB, API keys)
✅ Twilio + ElevenLabs native integration (10-15 min setup)
✅ Post-call summary generation to CRM
✅ Gmail alerting system with support for SMTP and Google OAuth 2.0
✅ Fuzzy catalog matching via Jaccard token similarity for service classification
✅ Dashboard reporting views for call transcripts, active appointments, and callback lists

### **7.2 MVP Out-of-Scope (P2 - Post-MVP)**

❌ Real CRM integrations (HubSpot, Salesforce) - use mock DB for MVP
❌ Outlook Calendar integration - Google Calendar only for MVP
❌ SMS/email confirmation templates customization - basic templates for MVP
❌ Multi-language support - English only for MVP
❌ Advanced analytics dashboard - basic stats for MVP
❌ Custom agent training on business data - use general LLM for MVP
❌ Voice biometrics for customer authentication - phone number lookup for MVP
❌ Mobile app for business owners - web portal only for MVP

***

## **8. Dependencies \& Risks**

### **8.1 Technical Dependencies**

| Dependency | Status | Risk |
| :-- | :-- | :-- |
| **ElevenLabs API** | ✅ Available | Low (stable API, 99.9% uptime) |
| **Twilio API** | ✅ Available | Low (industry standard) |
| **OpenAI API** | ✅ Available | Medium (pricing changes, rate limits) |
| **Claude API (Anthropic)** | ✅ Available | Medium (newer provider) |
| **Google Calendar API** | ✅ Available | Low (stable, well-documented) |
| **LangGraph** | ✅ Available | Medium (new framework, evolving) |
| **ChromaDB** | ✅ Available | Low (stable RAG solution) |

### **8.2 Business Risks**

| Risk | Probability | Impact | Mitigation |
| :-- | :-- | :-- | :-- |
| **ElevenLabs pricing increases** | Medium | Medium | Support multiple voice providers (Retell, Vapi as backups) |
| **LLM API rate limits** | Low | High | Cache responses, use multiple API keys |
| **Google Calendar API changes** | Low | Medium | Use official SDK, monitor for breaking changes |
| **Human handoff latency** | Medium | Medium | Pre-warm human agents, offer callback option |
| **DTMF detection failures** | Low | Low | Always offer voice alternative |

### **8.3 Compliance \& Legal**

| Requirement | Implementation |
| :-- | :-- |
| **GDPR compliance** | No PII in logs, 90-day data retention |
| **TCPA (phone automation)** | Consent required for automated calls (business configures) |
| **API key security** | AES-256 encryption, secure storage |


***

## **9. Timeline \& Milestones**

### **9.1 MVP Development Timeline (4 Weeks)**

| Week | Milestone | Deliverables |
| :-- | :-- | :-- |
| **Week 1** | Foundation | - Project setup in Antigravity<br>- Twilio + ElevenLabs integration<br>- Basic LangGraph call flow<br>- Mock CRM database |
| **Week 2** | Core Agents | - Intent classification agent<br>- Service request agent<br>- Appointment agent<br>- API integration (CRM, Calendar) |
| **Week 3** | Advanced Features | - FAQ agent with RAG<br>- Human handoff agent<br>- LLM/voice selection<br>- DTMF support<br>- Post-call summary |
| **Week 4** | Portal \& Testing | - Business configuration portal<br>- End-to-end testing<br>- Demo script<br>- Documentation |

### **9.2 Post-MVP Roadmap (Q3-Q4 2026)**

| Quarter | Features |
| :-- | :-- |
| **Q3 2026** | - Real CRM integrations (HubSpot, Salesforce)<br>- Outlook Calendar support<br>- SMS confirmation templates<br>- Advanced analytics dashboard |
| **Q4 2026** | - Multi-language support (Spanish, etc.)<br>- Custom agent training on business data<br>- Voice biometrics authentication<br>- Mobile app for business owners |


***

## **10. Open Questions**

### **10.1 Technical**

1. **Should we support multiple voice providers?** (ElevenLabs, Retell, Vapi)
→ Decision: Start with ElevenLabs only for MVP, add providers post-MVP
2. **How to store API keys securely?**
→ Decision: AES-256 encryption in database, encrypted at rest
3. **Should post-call summary use same LLM as call, or separate?**
→ Decision: Use same LLM (user's selected model) for consistency

### **10.2 Business**

1. **What's the pricing model?** (per call, per month, per seat)
→ Decision: MVP = free (internal testing), Post-MVP = \$99/month + \$0.10/call
2. **Which CRM integrations first?** (HubSpot vs. Salesforce)
→ Decision: HubSpot first (smaller businesses), Salesforce post-MVP
3. **Do we need phone number provisioning?** (Twilio number vs. business's existing number)
→ Decision: Support both (Twilio provisioning + import existing number)

***

## **11. Appendices**

### **11.1 Glossary**

| Term | Definition |
| :-- | :-- |
| **SR** | Service Request (customer's service issue) |
| **DTMF** | Dual-Tone Multi-Frequency (keypad tones 0-9, *, \#) |
| **RAG** | Retrieval-Augmented Generation (KB search during conversation) |
| **STT** | Speech-to-Text (convert voice to text) |
| **TTS** | Text-to-Speech (convert text to voice) |
| **LangGraph** | AI agent orchestration framework (DAG control) |

### **11.2 Mock CRM Schema**

```sql
-- Full schema in db/schema.sql (see code section)
customers → vehicles → service_requests → appointments → crm_notes
```
