
"""Independent authorization checks for simulated agent actions."""

ALLOWED_ACTIONS = {
    "answer_support_question",
}

SENSITIVE_ACTIONS = {
    "export_customer_records",
    "read_private_records",
    "change_account_permissions",
}


def authorize_action(action: str) -> dict:
    """Authorize only explicitly allowed, non-sensitive actions."""
    if action in SENSITIVE_ACTIONS:
        return {
            "decision": "blocked",
            "reason": "Sensitive action is not authorized in this lab.",
        }

    if action not in ALLOWED_ACTIONS:
        return {
            "decision": "blocked",
            "reason": "Action is not on the explicit allowlist.",
        }

    return {
        "decision": "allowed",
        "reason": "Action is explicitly allowlisted.",
    }
