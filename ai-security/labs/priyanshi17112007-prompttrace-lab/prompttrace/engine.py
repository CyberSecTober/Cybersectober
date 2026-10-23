"""Deterministic prompt-injection training engine.

This engine simulates agent behavior using configured patterns.
It does not call an LLM or execute real-world tools.
"""

import re

from prompttrace.policy import authorize_action
from prompttrace.scenarios import get_scenario
from prompttrace.trace import create_trace, record_event
from prompttrace.detection import analyze_injection


SENSITIVE_ACTION_PATTERNS = (
    (
        "export_customer_records",
        (
            r"\bexport(?:\s+of)?\s+(?:all\s+)?"
            r"(?:the\s+)?customer\s+(?:records|data)\b",
            r"\bexport_customer_records\b",
            r"\brequest\s+an\s+export\s+of\b.{0,100}"
            r"\bcustomer\s+(?:records|data)\b",
        ),
    ),
    (
        "read_private_records",
        (
            r"\b(?:read|access|retrieve|view)\s+"
            r"(?:all\s+)?(?:the\s+)?private\s+records\b",
            r"\bread_private_records\b",
        ),
    ),
    (
        "change_account_permissions",
        (
            r"\bchange\s+(?:the\s+)?account\s+permissions\b",
            r"\bchange_account_permissions\b",
        ),
    ),
)


def infer_proposed_action(
    user_prompt: str,
    retrieved_document: str | None,
) -> str:
    """Infer a simulated action using explicit, deterministic patterns.

    This is a teaching heuristic, not a general-purpose intent classifier.
    """
    context = f"{user_prompt}\n{retrieved_document or ''}".casefold()

    for action, patterns in SENSITIVE_ACTION_PATTERNS:
        if any(re.search(pattern, context) for pattern in patterns):
            return action

    return "answer_support_question"

def run_experiment(
    scenario_id: str | None = None,
    mode: str = "defended",
    *,
    user_prompt: str | None = None,
    retrieved_document: str | None = None,
) -> dict:
    """Run a predefined scenario or a custom-input experiment."""
    if mode not in {"vulnerable", "defended"}:
        raise ValueError("Mode must be 'vulnerable' or 'defended'.")

    if user_prompt is None:
        if scenario_id is None:
            raise ValueError("Provide a scenario_id or a custom user_prompt.")
        scenario = get_scenario(scenario_id)
        user_prompt = scenario["user_request"]
        if retrieved_document is None:
            retrieved_document = scenario.get("retrieved_document")
        scenario_id = scenario_id
    else:
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("Custom user_prompt must not be empty.")
        if retrieved_document is not None and not isinstance(
            retrieved_document, str
        ):
            raise ValueError("retrieved_document must be a string or null.")
        scenario_id = scenario_id or "custom"

    if len(user_prompt) > 4000:
        raise ValueError("User prompt must be 4000 characters or fewer.")
    if retrieved_document is not None and len(retrieved_document) > 4000:
        raise ValueError("Retrieved document must be 4000 characters or fewer.")

    trace = create_trace()

    record_event(
        trace,
        "context_inspection",
        "User prompt received and treated as untrusted input.",
        source="user_input",
        details={"character_count": len(user_prompt)},
    )

    if retrieved_document:
        record_event(
            trace,
            "context_inspection",
            "Retrieved document treated as untrusted content, not policy.",
            source="retrieved_document",
            details={"character_count": len(retrieved_document)},
        )

    combined_context = f"{user_prompt}\n{retrieved_document or ''}".lower()
    detection_result = analyze_injection(combined_context)
    matched_markers = detection_result['matched_markers']
    injection_detected = detection_result['injection_detected']

    record_event(
        trace,
        "pattern_analysis",
        (
            "A configured suspicious pattern was found."
            if injection_detected
            else "No configured suspicious pattern was found."
        ),
        source="deterministic_detector",
        status="warning" if injection_detected else "info",
        details={"matched_markers": matched_markers},
    )

    proposed_action = infer_proposed_action(
        user_prompt,
        retrieved_document,
    )

    record_event(
        trace,
        "agent_planning",
        f"Simulator proposed action: {proposed_action}.",
        source="mock_agent",
        details={"proposed_action": proposed_action},
    )

    if mode == "defended":
        authorization = authorize_action(proposed_action)
        allowed = authorization["decision"] == "allowed"
        record_event(
            trace,
            "policy_guard",
            authorization["reason"],
            source="policy",
            status="allowed" if allowed else "blocked",
            details={"decision": authorization["decision"]},
        )
    else:
        # Deliberately unsafe simulation: the independent guard is bypassed.
        allowed = True
        authorization = {
            "decision": "allowed",
            "reason": "Vulnerable mode skips independent authorization.",
        }
        record_event(
            trace,
            "policy_guard",
            authorization["reason"],
            source="policy",
            status="warning",
        )

    # This training lab never executes real tools.
    tool_executed = False
    simulated_action_accepted = bool(allowed)

    if allowed:
        record_event(
            trace,
            "mock_tool",
            (
                f"Simulated action accepted: {proposed_action}. "
                "No real tool was called."
            ),
            source="mock_tool",
            status="warning" if injection_detected else "success",
            details={
                "simulated": True,
                "real_tool_executed": False,
                "action": proposed_action,
            },
        )
    else:
        record_event(
            trace,
            "mock_tool",
            "Action blocked; no simulated tool action was performed.",
            source="mock_tool",
            status="blocked",
            details={
                "simulated": True,
                "real_tool_executed": False,
                "action": proposed_action,
            },
        )

    if injection_detected and mode == "vulnerable":
        summary = (
            "The simulator matched a configured injection pattern and "
            "accepted the proposed action because authorization was skipped."
        )
    elif injection_detected and not allowed:
        summary = (
            "The simulator matched a configured injection pattern. "
            "The independent policy guard blocked the proposed action."
        )
    elif injection_detected:
        summary = (
            "A configured pattern was detected. Review the authorization result."
        )
    else:
        summary = (
            "No configured injection pattern was found. This does not prove "
            "the input is safe."
        )

    return {
        "scenario_id": scenario_id,
        "mode": mode,
        "user_prompt": user_prompt,
        "retrieved_document": retrieved_document,
        "injection_detected": injection_detected,
        "matched_markers": matched_markers,
        "proposed_action": proposed_action,
        "policy_decision": authorization["decision"],
        "tool_executed": tool_executed,
        "simulated_action_accepted": simulated_action_accepted,
        "summary": summary,
        "trace": trace,
    }
