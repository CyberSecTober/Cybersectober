
import unittest

from prompttrace.engine import run_experiment


class TestPromptTraceEngine(unittest.TestCase):
    def test_direct_injection_blocked_in_defended_mode(self):
        result = run_experiment("direct-injection", "defended")

        self.assertEqual(result["policy_decision"], "blocked")
        self.assertFalse(result["tool_executed"])
        self.assertFalse(result["simulated_action_accepted"])
        self.assertEqual(
            result["proposed_action"], "export_customer_records"
        )

    def test_indirect_injection_blocked_in_defended_mode(self):
        result = run_experiment("indirect-injection", "defended")

        self.assertEqual(result["policy_decision"], "blocked")
        self.assertFalse(result["tool_executed"])
        self.assertFalse(result["simulated_action_accepted"])

    def test_vulnerable_mode_demonstrates_the_risk(self):
        result = run_experiment("direct-injection", "vulnerable")

        self.assertEqual(result["policy_decision"], "allowed")
        self.assertFalse(result["tool_executed"])
        self.assertTrue(result["simulated_action_accepted"])
        self.assertIn("authorization was skipped", result["summary"])
        self.assertIn("configured injection pattern", result["summary"])

    def test_benign_request_succeeds_in_defended_mode(self):
        result = run_experiment("benign-support", "defended")

        self.assertEqual(result["policy_decision"], "allowed")
        self.assertFalse(result["tool_executed"])
        self.assertTrue(result["simulated_action_accepted"])
        self.assertEqual(
            result["proposed_action"], "answer_support_question"
        )

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            run_experiment("direct-injection", "invalid")

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            run_experiment("unknown-scenario", "defended")

    def test_trace_contains_structured_events(self):
        result = run_experiment("indirect-injection", "defended")

        self.assertGreater(len(result["trace"]), 0)
        for event in result["trace"]:
            self.assertIn("stage", event)
            self.assertIn("source", event)
            self.assertIn("status", event)
            self.assertIn("message", event)
            self.assertIn("timestamp", event)


if __name__ == "__main__":
    unittest.main()
