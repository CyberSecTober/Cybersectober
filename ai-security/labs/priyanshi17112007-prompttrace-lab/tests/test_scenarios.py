
import unittest

from prompttrace.scenarios import get_scenario, list_scenarios


class TestScenarios(unittest.TestCase):
    def test_all_expected_scenarios_are_available(self):
        scenarios = list_scenarios()
        scenario_ids = {item["id"] for item in scenarios}

        self.assertEqual(
            scenario_ids,
            {"direct-injection", "indirect-injection", "benign-support"},
        )

    def test_direct_injection_contains_attack(self):
        scenario = get_scenario("direct-injection")
        self.assertTrue(scenario["attack_present"])

    def test_indirect_injection_has_untrusted_document(self):
        scenario = get_scenario("indirect-injection")
        self.assertTrue(scenario["attack_present"])
        self.assertIn("UNTRUSTED INSTRUCTION", scenario["retrieved_document"])

    def test_benign_scenario_has_no_attack(self):
        scenario = get_scenario("benign-support")
        self.assertFalse(scenario["attack_present"])

    def test_unknown_scenario_raises_error(self):
        with self.assertRaises(ValueError):
            get_scenario("not-a-real-scenario")


if __name__ == "__main__":
    unittest.main()
