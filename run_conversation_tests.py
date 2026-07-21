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

if __name__ == "__main__":
    print("\n==================================================")
    print(" Running serviceBot Conversation Test Suite")
    print("==================================================\n")
    unittest.main(verbosity=2)
