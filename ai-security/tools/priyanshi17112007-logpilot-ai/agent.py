"""LangGraph investigation workflow for LOGPILOT AI.

The workflow is deterministic and offline-capable after dependencies are
installed. It does not call an LLM, access external systems, or take actions.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class InvestigationState(TypedDict):
    """State passed between investigation nodes."""

    input_report: dict[str, Any]
    evidence: list[dict[str, Any]]
    investigations: list[dict[str, Any]]
    analyst_summary: str
    recommendations: list[str]
    final_report: dict[str, Any]


def collect_evidence(state: InvestigationState) -> dict[str, Any]:
    """Extract the detector's findings as investigation evidence."""
    report = state["input_report"]

    evidence = []
    for finding in report.get("findings", []):
        evidence.append(
            {
                "rule_id": finding["rule_id"],
                "severity": finding["severity"],
                "title": finding["title"],
                "source_ip": finding["source_ip"],
                "description": finding["description"],
                "evidence": finding["evidence"],
            }
        )

    return {"evidence": evidence}


def investigate_evidence(state: InvestigationState) -> dict[str, Any]:
    """Group findings by source IP without asserting unproven attribution."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for item in state["evidence"]:
        grouped.setdefault(item["source_ip"], []).append(item)

    investigations = []
    for source_ip, items in sorted(grouped.items()):
        rule_ids = sorted({item["rule_id"] for item in items})
        investigations.append(
            {
                "source_ip": source_ip,
                "finding_count": len(items),
                "rule_ids": rule_ids,
                "assessment": (
                    "Multiple configured detection rules were triggered."
                    if len(rule_ids) > 1
                    else "A configured detection rule was triggered."
                ),
                "confidence_note": (
                    "This assessment reflects configured log patterns only. "
                    "It does not establish attacker identity or intent."
                ),
            }
        )

    return {"investigations": investigations}


def explain_findings(state: InvestigationState) -> dict[str, Any]:
    """Create a concise evidence-based summary and safe recommendations."""
    evidence = state["evidence"]
    investigations = state["investigations"]

    if not evidence:
        summary = (
            "No configured detection rules were triggered by the accepted "
            "events. This does not prove that the environment is free of threats."
        )
        recommendations = [
            "Review detection thresholds against the environment's normal "
            "authentication activity.",
            "Ensure relevant authentication events are being collected.",
        ]
    else:
        affected_ips = sorted({item["source_ip"] for item in evidence})
        rule_ids = sorted({item["rule_id"] for item in evidence})

        summary = (
            f"The detector produced {len(evidence)} finding(s) across "
            f"{len(affected_ips)} source IP address(es). Triggered rules: "
            f"{', '.join(rule_ids)}. These are suspicious patterns that "
            "require analyst validation, not proof of a successful attack."
        )

        recommendations = [
            "Review the relevant authentication events and timestamps.",
            "Correlate failures with successful logins, account lockouts, "
            "and other available security telemetry.",
            "Validate whether the activity is expected before changing "
            "access controls or blocking a source.",
        ]

        if any("AUTH-002" in item["rule_ids"] for item in investigations):
            recommendations.append(
                "Check for possible password spraying or username enumeration "
                "using additional authentication evidence."
            )

    return {
        "analyst_summary": summary,
        "recommendations": recommendations,
    }


def build_final_report(state: InvestigationState) -> dict[str, Any]:
    """Combine detector output with the investigation results."""
    report = dict(state["input_report"])
    report["investigation"] = {
        "workflow": "LOGPILOT AI LangGraph investigation",
        "mode": "deterministic",
        "analyst_summary": state["analyst_summary"],
        "source_investigations": state["investigations"],
        "recommendations": state["recommendations"],
        "llm_used": False,
        "automated_response_performed": False,
    }
    return {"final_report": report}


def build_investigation_graph():
    """Build and compile the investigation graph."""
    graph = StateGraph(InvestigationState)

    graph.add_node("collect_evidence", collect_evidence)
    graph.add_node("investigate_evidence", investigate_evidence)
    graph.add_node("explain_findings", explain_findings)
    graph.add_node("build_final_report", build_final_report)

    graph.add_edge(START, "collect_evidence")
    graph.add_edge("collect_evidence", "investigate_evidence")
    graph.add_edge("investigate_evidence", "explain_findings")
    graph.add_edge("explain_findings", "build_final_report")
    graph.add_edge("build_final_report", END)

    return graph.compile()


def run_investigation(report: dict[str, Any]) -> dict[str, Any]:
    """Run the workflow and return the enhanced JSON-serializable report."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dictionary")

    graph = build_investigation_graph()
    result = graph.invoke(
        {
            "input_report": report,
            "evidence": [],
            "investigations": [],
            "analyst_summary": "",
            "recommendations": [],
            "final_report": {},
        }
    )
    return result["final_report"]
