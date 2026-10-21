
import unittest

from prompttrace.policy import authorize_action


class TestAuthorizationPolicy(unittest.TestCase):
    def test_sensitive_export_action_is_blocked(self):
        result = authorize_action("export_customer_records")
        self.assertEqual(result["decision"], "blocked")

    def test_private_record_access_is_blocked(self):
        result = authorize_action("read_private_records")
        self.assertEqual(result["decision"], "blocked")

    def test_permission_change_is_blocked(self):
        result = authorize_action("change_account_permissions")
        self.assertEqual(result["decision"], "blocked")

    def test_allowlisted_support_action_is_allowed(self):
        result = authorize_action("answer_support_question")
        self.assertEqual(result["decision"], "allowed")

    def test_unknown_action_is_blocked(self):
        result = authorize_action("unknown_action")
        self.assertEqual(result["decision"], "blocked")


if __name__ == "__main__":
    unittest.main()
