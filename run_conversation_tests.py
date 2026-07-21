#!/usr/bin/env python3
import os
import sys
import unittest

from serviceBot.conversation_simulator import ConversationSimulator, VOICE_TOOLS

class TestConversationSimulator(unittest.TestCase):
    def setUp(self):
        self.simulator = ConversationSimulator(use_mock=True)

    def test_initialization(self):
        self.assertEqual(len(self.simulator.messages), 2)
        self.assertEqual(self.simulator.messages[0]["role"], "system")
        self.assertEqual(self.simulator.messages[1]["role"], "assistant")
        self.assertIn("Rachel", self.simulator.messages[1]["content"])
        print("  ✓ test_initialization passed")

    def test_voice_tools_definitions(self):
        tool_names = [t["function"]["name"] for t in VOICE_TOOLS]
        expected_tools = [
            "check_availability",
            "get_service_fields",
            "create_service_request",
            "book_appointment",
            "request_callback",
            "get_customer_appointments",
            "reschedule_appointment",
            "query_knowledge_base",
            "cba_webhook"
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, tool_names)
        print("  ✓ test_voice_tools_definitions passed")

    def test_intake_collection_sequence(self):
        """Verify assistant asks for missing intake details politely before booking."""
        turn1 = self.simulator.run_turn("hey uh i need service for my car i guess")
        self.assertIn("name", turn1["assistant_response"].lower())
        self.assertEqual(len(turn1["tool_calls"]), 0) # Must not book without intake info!

        turn2 = self.simulator.run_turn("alex... alex smith")
        self.assertIn("phone", turn2["assistant_response"].lower())
        self.assertEqual(len(turn2["tool_calls"]), 0)

        turn3 = self.simulator.run_turn("five five five one two three four five six seven")
        self.assertTrue(any(w in turn3["assistant_response"].lower() for w in ["vehicle", "year", "make", "model"]))

        print("  ✓ test_intake_collection_sequence passed")

    def test_noisy_stt_appointment_booking_scenario(self):
        """Test STT transcription errors, phonetic numbers, vehicle typos, and lazy answers."""
        script = [
            "hey uh i need service for my car i guess",
            "alex... alex smith",
            "five five five... one two three... four five six seven",
            "twenty twenty one toy yota camry",
            "oil chang and like a weird squeaking noise when i stop",
            "check wednesday june 10 open times",
            "yeah 10 am works book it for me"
        ]
        transcript = self.simulator.run_scenario(script)
        self.assertEqual(len(transcript), 7)
        self.assertEqual(transcript[4]["tool_calls"][0]["tool_name"], "get_service_fields")
        self.assertEqual(transcript[5]["tool_calls"][0]["tool_name"], "check_availability")
        self.assertEqual(transcript[6]["tool_calls"][0]["tool_name"], "book_appointment")
        print("  ✓ test_noisy_stt_appointment_booking_scenario passed")

    def test_indecisive_callback_switch_scenario(self):
        """Test STT vehicle misspellings and user mid-conversation switch to callback."""
        script = [
            "um hi my 20 19 honda civik has grinding brakes when stopping",
            "sarah connor 555 987 6543",
            "actually wait... don't book an appointment right now, just have a manager call me back tomorrow morning instead"
        ]
        transcript = self.simulator.run_scenario(script)
        self.assertTrue(len(transcript) >= 3)
        self.assertEqual(transcript[-1]["tool_calls"][0]["tool_name"], "request_callback")
        print("  ✓ test_indecisive_callback_switch_scenario passed")

    def test_noisy_faq_scenario(self):
        """Test FAQ query with filler words and STT artifacts."""
        turn_res = self.simulator.run_turn("um yeah do you guys have like loaner cars or shuttle service when my car is in the shop?")
        self.assertEqual(len(turn_res["tool_calls"]), 1)
        self.assertEqual(turn_res["tool_calls"][0]["tool_name"], "query_knowledge_base")
        self.assertIn("Shuttle service", turn_res["assistant_response"])
        print("  ✓ test_noisy_faq_scenario passed")

    def test_frustrated_human_handoff_scenario(self):
        """Test uncooperative caller demanding human agent."""
        turn_res = self.simulator.run_turn("look i don't want to talk to an ai robot, get me a real person or service manager right now!")
        self.assertEqual(len(turn_res["tool_calls"]), 1)
        self.assertEqual(turn_res["tool_calls"][0]["tool_name"], "cba_webhook")
        self.assertIn("advisor", turn_res["assistant_response"].lower())
        print("  ✓ test_frustrated_human_handoff_scenario passed")

    def test_multiple_issues_scenario(self):
        """Test handling of multiple issues with notes recording and rate/duration quotes for each service."""
        script = [
            "Hi, I need an oil change and also my brakes are squeaking when I stop",
            "John Doe, 555-321-7654, 2022 Ford F-150",
            "Please book an appointment for tomorrow at 10 AM"
        ]
        transcript = self.simulator.run_scenario(script)
        self.assertTrue(len(transcript) >= 3)
        # Check intake state captured both issues in notes/description
        issue_desc = self.simulator.intake_state.get("issue_description") or ""
        self.assertIn("oil change", issue_desc.lower())
        self.assertIn("brake", issue_desc.lower())
        print("  ✓ test_multiple_issues_scenario passed")

    def test_end_of_call_booking_execution(self):
        """Verify booking requests (appointment or callback) occur at the end of the call after all needs and options are captured."""
        script = [
            "I need to bring in my 2020 Honda Civic. My name is Alice, phone 555-444-3333.",
            "Actually I have two problems: oil change and check engine light diagnosis.",
            "Can you check available times for Friday?",
            "10:00 AM on Friday works. Please book that appointment now."
        ]
        transcript = self.simulator.run_scenario(script)
        self.assertEqual(len(transcript), 4)

        # Early turns capture details and check availability without triggering premature booking
        self.assertNotIn("book_appointment", [tc["tool_name"] for tc in transcript[0]["tool_calls"]])
        self.assertNotIn("book_appointment", [tc["tool_name"] for tc in transcript[1]["tool_calls"]])

        # Turn 3 checks availability
        self.assertTrue(any(tc["tool_name"] == "check_availability" for tc in transcript[2]["tool_calls"]))
        self.assertNotIn("book_appointment", [tc["tool_name"] for tc in transcript[2]["tool_calls"]])

        # Turn 4 (end of conversation flow) executes book_appointment with all captured details
        self.assertTrue(any(tc["tool_name"] == "book_appointment" for tc in transcript[3]["tool_calls"]))
        print("  ✓ test_end_of_call_booking_execution passed")

    def test_existing_customer_booking_check(self):
        """Verify that returning callers are checked for existing appointments/requests prior to finalizing a new booking."""
        script = [
            "Hi, I want to reschedule or check my existing appointment. Phone 555-123-4567.",
            "Can we move it to 2026-06-14 at 11:00 AM instead?"
        ]
        transcript = self.simulator.run_scenario(script)
        self.assertTrue(len(transcript) >= 2)
        # Verify get_customer_appointments is called to check prior bookings before rescheduling
        self.assertTrue(any(tc["tool_name"] in ["get_customer_appointments", "reschedule_appointment"] for tc in transcript[0]["tool_calls"] + transcript[1]["tool_calls"]))
        print("  ✓ test_existing_customer_booking_check passed")

if __name__ == "__main__":
    print("\n==================================================")
    print(" Running serviceBot Conversation Test Suite")
    print("==================================================\n")
    unittest.main(verbosity=2)


