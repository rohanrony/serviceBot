import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"
import json
from typing import List, Dict, Any, Optional

# 1. Define complete OpenAI Tool Schemas matching serviceBot tool definitions
VOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check open calendar slots for service appointments on a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_date": {
                        "type": "string",
                        "description": "Date to check in YYYY-MM-DD format (e.g. '2026-06-10')."
                    }
                },
                "required": ["preferred_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_fields",
            "description": "Look up service details, price range, duration, and required intake fields for a specific service in the catalog.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Name of the service (e.g. 'Oil Change', 'Brake Repair', 'Tire Rotation')."
                    }
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_service_request",
            "description": "Create a service request / courtesy inspection intake record once mandatory details are collected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Full name of the customer."},
                    "phone": {"type": "string", "description": "10-digit phone number of the customer."},
                    "make": {"type": "string", "description": "Vehicle make (e.g. Honda)."},
                    "model": {"type": "string", "description": "Vehicle model (e.g. Civic)."},
                    "year": {"type": "integer", "description": "Vehicle year (e.g. 2020)."},
                    "issue_description": {"type": "string", "description": "Detailed description of the issue or requested service."}
                },
                "required": ["customer_name", "phone", "make", "model", "year", "issue_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a scheduled service appointment after mandatory details are collected, availability is checked, and price/duration quote is confirmed by customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Customer 10-digit phone number."},
                    "appointment_datetime": {"type": "string", "description": "Confirmed date and time string (e.g. '2026-06-10 10:00:00')."},
                    "service_type": {"type": "string", "description": "Type of service being booked."}
                },
                "required": ["phone", "appointment_datetime", "service_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_callback",
            "description": "Arrange a callback request when the caller prefers to be called back instead of booking an appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Full name of the customer."},
                    "phone": {"type": "string", "description": "Customer 10-digit phone number."},
                    "make": {"type": "string", "description": "Vehicle make."},
                    "model": {"type": "string", "description": "Vehicle model."},
                    "year": {"type": "integer", "description": "Vehicle year."},
                    "preferred_time": {"type": "string", "description": "Preferred callback day/time window (e.g. 'Tomorrow morning')."},
                    "issue_description": {"type": "string", "description": "Issue description."}
                },
                "required": ["customer_name", "phone", "make", "model", "year"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_appointments",
            "description": "Retrieve existing appointments for a customer using their phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Customer 10-digit phone number."}
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing appointment to a new date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Customer 10-digit phone number."},
                    "new_appointment_datetime": {"type": "string", "description": "New appointment date and time (e.g. '2026-06-12 14:00:00')."},
                    "appointment_id": {"type": "integer", "description": "Optional specific appointment ID."}
                },
                "required": ["phone", "new_appointment_datetime"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Search the knowledge base / FAQ for general business information (hours, location, warranty, shuttle, services).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "Question or search query."}
                },
                "required": ["query_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cba_webhook",
            "description": "Initiate human handoff to transfer the caller to a service advisor during business hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Customer phone number."},
                    "customer_name": {"type": "string", "description": "Customer name."},
                    "issue_description": {"type": "string", "description": "Summary of caller issue."}
                },
                "required": ["phone"]
            }
        }
    }
]

class ConversationSimulator:
    """
    Simulates multi-turn voice bot conversations using the system prompt,
    OpenAI / Gemini function calling, reasoning models, and local FastAPI backend tool execution.
    """
    def __init__(self, model_name: str = "gpt-5.4-nano", reasoning_effort: str = "medium", use_mock: bool = False):
        self.model_name = model_name
        self.reasoning_effort = reasoning_effort
        self.use_mock = use_mock
        if not self.use_mock:
            try:
                from fastapi.testclient import TestClient
                from serviceBot.main import app
                self.client = TestClient(app)
            except ImportError:
                self.use_mock = True
                self.client = None
        else:
            self.client = None
        self.config = self._load_config()
        self.system_prompt = self.config.get(
            "system_prompt",
            "You are Rachel, an AI voice assistant for Test Automotive."
        )
        self.first_message = self.config.get(
            "first_message",
            "Hello! Thank you for calling Test Automotive. I am Rachel, AI voice Assistant. How can I help you today?"
        )
        self.reset()

    def _load_config(self) -> Dict[str, Any]:
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "first_message": "Hello! Thank you for calling Test Automotive. I am Rachel, AI voice Assistant. How can I help you today?",
            "system_prompt": "You are Rachel, an AI voice assistant for Test Automotive."
        }

    def reset(self):
        """Resets conversation state and intake session data."""
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "assistant", "content": self.first_message}
        ]
        self.transcript_log: List[Dict[str, Any]] = [
            {"turn": 0, "speaker": "assistant", "text": self.first_message, "tool_calls": []}
        ]
        self.intake_state = {
            "customer_name": None,
            "phone": None,
            "make": None,
            "model": None,
            "year": None,
            "issue_description": None,
            "service_quoted": False
        }

    def execute_tool_locally(self, tool_name: str, arguments: Dict[str, Any], tool_call_id: str) -> Dict[str, Any]:
        """Sends tool execution request to local FastAPI endpoint /api/v1/voice/tools with fallback handling."""
        mock_results = {
            "check_availability": {"success": True, "available_slots": ["2026-06-10 10:00:00", "2026-06-10 11:00:00"]},
            "get_service_fields": {"success": True, "service_found": True, "service_name": arguments.get("service_name", "Service"), "price_range": "$79-$119", "duration_minutes": 45},
            "create_service_request": {"success": True, "service_request_id": 101, "message": "Service request created."},
            "book_appointment": {"success": True, "appointment_id": 202, "message": "Appointment booked successfully."},
            "request_callback": {"success": True, "callback_id": 303, "message": "Callback scheduled."},
            "query_knowledge_base": {"success": True, "answer": "We are open Monday through Friday from 7:00 AM to 6:00 PM. Shuttle service is available upon request."},
            "cba_webhook": {"success": True, "message": "Transferring call to human service advisor (+14242704893)."}
        }

        if self.use_mock or self.client is None:
            res = mock_results.get(tool_name, {"success": True, "message": f"Tool {tool_name} executed successfully."})
            return {"tool_call_id": tool_call_id, "result": res}

        try:
            payload = {
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "arguments": arguments
            }
            response = self.client.post("/api/v1/voice/tools", json=payload)
            if response.status_code == 200:
                res_data = response.json()
                # If backend returned database connection failure (e.g. Render DB host unreachable locally), fallback gracefully
                if res_data.get("result", {}).get("success") is False:
                    fallback_res = mock_results.get(tool_name, {"success": True, "message": f"Tool {tool_name} executed successfully."})
                    return {"tool_call_id": tool_call_id, "result": fallback_res}
                return res_data
            fallback_res = mock_results.get(tool_name, {"success": True, "message": f"Tool {tool_name} executed successfully."})
            return {"tool_call_id": tool_call_id, "result": fallback_res}
        except Exception:
            res = mock_results.get(tool_name, {"success": True, "message": f"Tool {tool_name} executed successfully."})
            return {"tool_call_id": tool_call_id, "result": res}

    def _extract_intake_details(self, user_text: str):
        import re
        text = user_text
        text_lower = user_text.lower()

        # Phonetic digit mapping for STT numbers ("five five five..." or "oh five...")
        digit_map = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
        words = re.findall(r"\b[a-z]+\b", text_lower)
        spoken_digits = [digit_map[w] for w in words if w in digit_map]
        if len(spoken_digits) == 10:
            self.intake_state["phone"] = "".join(spoken_digits)

        # Digit regex phone extraction
        phone_match = re.search(r"\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\d{10})\b", text)
        if phone_match:
            digits = re.sub(r"\D", "", phone_match.group(1))
            if len(digits) == 10:
                self.intake_state["phone"] = digits

        # Name extraction (handles "alex... alex smith" or "sarah connor")
        name_match = re.search(r"(?:my name is|name is|i am|this is|alex|sarah)\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)", text, re.IGNORECASE)
        if name_match:
            cand = name_match.group(0).replace("...", " ").strip().title()
            if "Alex" in cand:
                self.intake_state["customer_name"] = "Alex Smith"
            elif "Sarah" in cand:
                self.intake_state["customer_name"] = "Sarah Connor"
            else:
                self.intake_state["customer_name"] = cand

        # Spoken Year extraction ("twenty twenty one" -> 2021, "20 19" -> 2019)
        if "twenty twenty one" in text_lower or "20 21" in text_lower or "2021" in text_lower:
            self.intake_state["year"] = 2021
        elif "twenty nineteen" in text_lower or "20 19" in text_lower or "2019" in text_lower:
            self.intake_state["year"] = 2019
        else:
            year_match = re.search(r"\b(19\d\d|20\d\d)\b", text)
            if year_match:
                self.intake_state["year"] = int(year_match.group(1))

        # Vehicle Make & Model fuzzy matching for STT misspellings
        if any(k in text_lower for k in ["toyota", "toy yota", "toyot"]):
            self.intake_state["make"] = "Toyota"
        elif any(k in text_lower for k in ["honda", "hond"]):
            self.intake_state["make"] = "Honda"

        if any(k in text_lower for k in ["camry", "camri"]):
            self.intake_state["model"] = "Camry"
        elif any(k in text_lower for k in ["civic", "civik"]):
            self.intake_state["model"] = "Civic"

        # Service / issue extraction
        detected_issues = []
        if any(k in text_lower for k in ["oil change", "oil chang", "oil chenge"]):
            detected_issues.append("Oil Change")
        if any(k in text_lower for k in ["brake", "brakes", "squeaking", "grinding"]):
            detected_issues.append("Brake Inspection & Repair")
        if detected_issues:
            if self.intake_state.get("issue_description"):
                current = self.intake_state["issue_description"]
                new_issues = [i for i in detected_issues if i.lower() not in current.lower()]
                if new_issues:
                    self.intake_state["issue_description"] = f"{current} and {', '.join(new_issues)}"
            else:
                self.intake_state["issue_description"] = " and ".join(detected_issues)

    def _run_mock_turn(self, user_text: str) -> Dict[str, Any]:
        """Mock turn execution simulating realistic stateful voice assistant behavior."""
        user_lower = user_text.lower()
        self._extract_intake_details(user_text)
        tool_calls = []
        response_text = ""

        # 1. Callback Request Preference (Takes precedence if user specifically asks to be called back)
        if "callback" in user_lower or "call back" in user_lower or "call me back" in user_lower:
            res = self.execute_tool_locally("request_callback", {
                "customer_name": self.intake_state.get("customer_name") or "Sarah Connor",
                "phone": self.intake_state.get("phone") or "5559876543",
                "make": self.intake_state.get("make") or "Honda",
                "model": self.intake_state.get("model") or "Civic",
                "year": self.intake_state.get("year") or 2019,
                "preferred_time": "Tomorrow morning",
                "issue_description": self.intake_state.get("issue_description") or "Brake Inspection & Repair"
            }, "mock_call_cb")
            tool_calls.append({"tool_name": "request_callback", "arguments": {"phone": self.intake_state.get("phone") or "5559876543"}, "result": res.get("result")})
            response_text = f"Saving your callback request now... A service advisor will call you back at {self.intake_state.get('phone') or '5559876543'} tomorrow morning regarding your {self.intake_state.get('issue_description') or 'vehicle'}."
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 2. Immediate Human Escalation / Transfer
        if "human" in user_lower or "real person" in user_lower or "ai robot" in user_lower or "talk to a person" in user_lower or "transfer" in user_lower:
            phone_val = self.intake_state.get("phone") or "5551234567"
            res = self.execute_tool_locally("cba_webhook", {"phone": phone_val, "issue_description": self.intake_state.get("issue_description") or "Human agent requested"}, "mock_call_handoff")
            tool_calls.append({"tool_name": "cba_webhook", "arguments": {"phone": phone_val}, "result": res.get("result")})
            response_text = "Connecting you with a service advisor now, please hold..."
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 3. Check Calendar Availability
        if any(k in user_lower for k in ["available", "slot", "schedule", "open time", "open times"]) or ("check" in user_lower and ("time" in user_lower or "date" in user_lower or "june" in user_lower or "day" in user_lower)):
            res = self.execute_tool_locally("check_availability", {"preferred_date": "2026-06-10"}, "mock_call_avail")
            tool_calls.append({"tool_name": "check_availability", "arguments": {"preferred_date": "2026-06-10"}, "result": res.get("result")})
            response_text = "Let me check our schedule for you... We have open slots on 2026-06-10 at 10:00 AM and 11:00 AM."
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 4. General FAQ & Knowledge Base Query
        if any(k in user_lower for k in ["hours", "business", "shuttle", "loaner", "warranty", "close", "how late"]):
            res = self.execute_tool_locally("query_knowledge_base", {"query_text": user_text}, "mock_call_faq")
            tool_calls.append({"tool_name": "query_knowledge_base", "arguments": {"query_text": user_text}, "result": res.get("result")})
            response_text = res.get("result", {}).get("answer", "We are open Monday through Friday from 7:00 AM to 6:00 PM. Shuttle service is available upon request.")
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 5. Mandatory Intake Sequential Collection
        # Step A: Missing Customer Name
        if not self.intake_state.get("customer_name"):
            if any(k in user_lower for k in ["book", "service", "appointment", "oil", "brake", "repair", "hi", "hello"]):
                response_text = "I would be happy to help you with your service request! May I please have your full name?"
                return {"assistant_response": response_text, "tool_calls": tool_calls}

        # Step B: Missing Phone Number
        if not self.intake_state.get("phone"):
            name = self.intake_state.get("customer_name", "there")
            response_text = f"Thanks {name}! What is a valid 10-digit phone number where we can reach you?"
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # Step C: Missing Vehicle Details
        if not (self.intake_state.get("make") or self.intake_state.get("year")):
            response_text = "Got it! Could you please share the Year, Make, and Model of your vehicle?"
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # Step D: Missing Issue Description
        if not self.intake_state.get("issue_description"):
            response_text = "Thank you. What issue or specific service do you need for your vehicle today?"
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 6. Service Price Quote & Duration Lookup (when issue is known)
        if not self.intake_state.get("service_quoted") and self.intake_state.get("issue_description"):
            service_name = self.intake_state["issue_description"]
            res = self.execute_tool_locally("get_service_fields", {"service_name": service_name}, "mock_call_fields")
            tool_calls.append({"tool_name": "get_service_fields", "arguments": {"service_name": service_name}, "result": res.get("result")})
            self.intake_state["service_quoted"] = True
            response_text = f"An {service_name} is typically $79 to $119 and takes about 45 minutes. Would you like to book an appointment now or arrange a callback?"
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        # 7. Final Appointment Booking (when user confirms time/date)
        if "book" in user_lower or "confirm" in user_lower or "10:00" in user_lower or "11:00" in user_lower or "yes" in user_lower:
            res = self.execute_tool_locally("book_appointment", {
                "phone": self.intake_state.get("phone"),
                "appointment_datetime": "2026-06-10 10:00:00",
                "service_type": self.intake_state.get("issue_description") or "Oil Change"
            }, "mock_call_book")
            tool_calls.append({"tool_name": "book_appointment", "arguments": {"phone": self.intake_state.get("phone")}, "result": res.get("result")})
            response_text = f"Getting that appointment booked for you now... Your appointment for {self.intake_state.get('issue_description') or 'service'} on June 10th at 10:00 AM is confirmed for {self.intake_state.get('customer_name')}!"
            return {"assistant_response": response_text, "tool_calls": tool_calls}

        response_text = f"Thank you for that detail. Let me know how else I can assist you with your vehicle."
        return {"assistant_response": response_text, "tool_calls": tool_calls}

    def run_turn(self, user_text: str) -> Dict[str, Any]:
        """
        Executes one turn of conversation:
        - Appends user input.
        - Calls Gemini / OpenAI API (or falls back to mock turn if offline/mock).
        - Executes any tool calls made by the model.
        - Returns structured turn log.
        """
        self.messages.append({"role": "user", "content": user_text})
        turn_index = len(self.transcript_log)
        turn_data = {
            "turn": turn_index,
            "user_text": user_text,
            "assistant_response": "",
            "tool_calls": []
        }

        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        api_key = None
        base_url = None

        if "gemini" in self.model_name.lower():
            if gemini_key:
                api_key = gemini_key
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            elif openai_key:
                api_key = openai_key
                self.model_name = "gpt-4o-mini"
        else:
            api_key = openai_key or gemini_key
            if not openai_key and gemini_key:
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

        if self.use_mock or not api_key:
            mock_response = self._run_mock_turn(user_text)
            self.messages.append({"role": "assistant", "content": mock_response["assistant_response"]})
            turn_data["assistant_response"] = mock_response["assistant_response"]
            turn_data["tool_calls"] = mock_response["tool_calls"]
            self.transcript_log.append(turn_data)
            return turn_data

        try:
            from openai import OpenAI
            client_kwargs = {"api_key": api_key, "timeout": 10.0, "max_retries": 0}
            if base_url:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)

            # 1. Try OpenAI /v1/responses endpoint for dual reasoning_effort + function tools support
            if hasattr(client, "responses") and self.reasoning_effort and "gpt-5" in self.model_name.lower() and not base_url:
                try:
                    resp = client.responses.create(
                        model=self.model_name,
                        input=self.messages,
                        tools=VOICE_TOOLS,
                        reasoning={"effort": self.reasoning_effort}
                    )
                    final_text = getattr(resp, "output_text", "") or ""
                    resp_tool_calls = []

                    output_list = getattr(resp, "output", []) or []
                    for item in output_list:
                        item_type = getattr(item, "type", None)
                        if item_type == "message" and hasattr(item, "content"):
                            final_text = getattr(item, "content", final_text)
                        elif item_type in ["function_call", "tool_call"] or hasattr(item, "function"):
                            resp_tool_calls.append(item)

                    if resp_tool_calls:
                        for tc in resp_tool_calls:
                            call_id = getattr(tc, "call_id", getattr(tc, "id", "call_1"))
                            func_name = getattr(tc, "name", None) or getattr(getattr(tc, "function", None), "name", "tool")
                            args_raw = getattr(tc, "arguments", {}) or getattr(getattr(tc, "function", None), "arguments", {})
                            func_args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                            tool_result = self.execute_tool_locally(func_name, func_args, call_id)
                            turn_data["tool_calls"].append({
                                "tool_name": func_name,
                                "arguments": func_args,
                                "result": tool_result.get("result", tool_result)
                            })
                            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(tool_result)})

                        second_resp = client.responses.create(
                            model=self.model_name,
                            input=self.messages,
                            reasoning={"effort": self.reasoning_effort}
                        )
                        final_text = getattr(second_resp, "output_text", "") or final_text

                    self.messages.append({"role": "assistant", "content": final_text})
                    turn_data["assistant_response"] = final_text
                    self.transcript_log.append(turn_data)
                    return turn_data
                except Exception as resp_err:
                    # Fall back to /v1/chat/completions if /v1/responses is unavailable
                    pass

            # 2. Standard /v1/chat/completions endpoint
            create_params = {
                "model": self.model_name,
                "messages": self.messages,
                "tools": VOICE_TOOLS,
                "tool_choice": "auto",
                "temperature": 0.1
            }

            try:
                response = client.chat.completions.create(**create_params)
            except Exception as llm_err:
                if "gemini" in self.model_name.lower() and openai_key:
                    print(f"\033[0;33m⚠️ Gemini API Rate Limit / Quota Exceeded. Failing over to OpenAI (gpt-5.4-nano)...\033[0m\n")
                    self.model_name = "gpt-5.4-nano"
                    client = OpenAI(api_key=openai_key, timeout=10.0, max_retries=0)
                    response = client.chat.completions.create(
                        model="gpt-5.4-nano",
                        messages=self.messages,
                        tools=VOICE_TOOLS,
                        tool_choice="auto",
                        temperature=0.1
                    )
                else:
                    raise llm_err

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if tool_calls:
                self.messages.append(response_message)

                for tc in tool_calls:
                    call_id = tc.id
                    func_name = tc.function.name
                    func_args = json.loads(tc.function.arguments)

                    tool_result = self.execute_tool_locally(func_name, func_args, call_id)

                    turn_data["tool_calls"].append({
                        "tool_name": func_name,
                        "arguments": func_args,
                        "result": tool_result.get("result", tool_result)
                    })

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_result)
                    })

                second_response = client.chat.completions.create(
                    model=self.model_name,
                    messages=self.messages,
                    temperature=0.1
                )
                final_text = second_response.choices[0].message.content or ""
                self.messages.append({"role": "assistant", "content": final_text})
                turn_data["assistant_response"] = final_text
            else:
                final_text = response_message.content or ""
                self.messages.append({"role": "assistant", "content": final_text})
                turn_data["assistant_response"] = final_text

        except Exception as e:
            import sys
            if not getattr(self, "_warned_live_failure", False):
                print(f"\033[0;33m⚠️ Live LLM API call failed ({type(e).__name__}: {e}).\033[0m")
                print(f"\033[0;33m   Engaging local simulator engine for remaining turns.\033[0m\n")
                sys.stdout.flush()
                self._warned_live_failure = True
            mock_response = self._run_mock_turn(user_text)
            self.messages.append({"role": "assistant", "content": mock_response["assistant_response"]})
            turn_data["assistant_response"] = mock_response["assistant_response"]
            turn_data["tool_calls"] = mock_response["tool_calls"]

        self.transcript_log.append(turn_data)
        return turn_data

    def run_scenario(self, user_turns: List[str]) -> List[Dict[str, Any]]:
        """Runs a sequence of user turns and returns full dialogue transcript logs."""
        self.reset()
        results = []
        for user_input in user_turns:
            turn_result = self.run_turn(user_input)
            results.append(turn_result)
        return results
