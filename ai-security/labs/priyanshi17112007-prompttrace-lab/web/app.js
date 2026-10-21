const scenarioSelect = document.querySelector("#scenario");
const runButton = document.querySelector("#run-button");
const runLabel = document.querySelector("#run-label");
const runStatus = document.querySelector("#run-status");
const traceList = document.querySelector("#trace-list");
const userPromptInput = document.querySelector("#user-prompt");
const retrievedDocumentInput = document.querySelector("#retrieved-document");

const scenarioDescriptions = {
  "direct-injection":
    "A user message attempts to override the support policy.",
  "indirect-injection":
    "A retrieved document contains instructions aimed at the agent.",
  "benign-support":
    "A normal support request checks that the defense preserves useful behavior."
};

scenarioSelect.addEventListener("change", () => {
  document.querySelector("#scenario-description").textContent =
    scenarioDescriptions[scenarioSelect.value] || "Selected preset scenario.";
});

function addTraceEvent(event, index) {
  const item = document.createElement("article");
  item.className = "trace-event";

  if (event.status === "blocked") {
    item.classList.add("blocked");
  }

  const marker = document.createElement("span");
  marker.className = "trace-marker";
  marker.textContent = String(index + 1).padStart(2, "0");

  const content = document.createElement("div");
  const heading = document.createElement("strong");
  heading.textContent = event.stage || "Agent event";

  const description = document.createElement("p");
  description.textContent = event.message || "Event recorded.";

  content.append(heading, description);

  if (event.details?.matched_markers?.length) {
    const evidence = document.createElement("small");
    evidence.textContent =
      `Matched patterns: ${event.details.matched_markers.join(", ")}`;
    content.append(evidence);
  }

  item.append(marker, content);
  return item;
}

function showError(message) {
  document.querySelector("#result-badge").textContent = "REQUEST FAILED";
  document.querySelector("#decision-title").textContent = "No verified result";
  document.querySelector("#decision-detail").textContent = message;
  document.querySelector("#agent-status").textContent = "UNAVAILABLE";
  document.querySelector("#connection-status").textContent = "BACKEND UNAVAILABLE";

  traceList.replaceChildren();
  const item = document.createElement("article");
  item.className = "trace-event error";
  const text = document.createElement("p");
  text.textContent = message;
  item.append(text);
  traceList.append(item);
  document.querySelector("#trace-count").textContent = "0 EVENTS";
}

async function verifyBackend() {
  try {
    const response = await fetch("/api/scenarios");
    if (!response.ok) throw new Error("Backend unavailable");

    document.querySelector("#connection-status").textContent = "BACKEND CONNECTED";
    document.querySelector("#agent-status").textContent = "READY";
    runStatus.textContent = "Ready. Select a scenario or enter a custom prompt.";
  } catch {
    document.querySelector("#connection-status").textContent = "BACKEND NOT VERIFIED";
    document.querySelector("#agent-status").textContent = "NOT VERIFIED";
    runStatus.textContent = "Start the local Python server to run experiments.";
  }
}

runButton.addEventListener("click", async () => {
  const mode = document.querySelector('input[name="mode"]:checked')?.value;
  const customPrompt = userPromptInput.value.trim();
  const customDocument = retrievedDocumentInput.value;

  const payload = { mode };

  if (customPrompt) {
    payload.user_prompt = customPrompt;
    payload.retrieved_document = customDocument.trim() || null;
    payload.scenario_id = "custom";
  } else {
    payload.scenario_id = scenarioSelect.value;
  }

  if (!mode) {
    showError("Select an execution mode first.");
    return;
  }

  if (customDocument.trim() && !customPrompt) {
    showError("Enter a custom prompt when testing a retrieved document.");
    runStatus.textContent = "Custom document testing requires a user prompt.";
    return;
  }

  runButton.disabled = true;
  runLabel.textContent = "RUNNING EXPERIMENT...";
  runStatus.textContent = "Waiting for the local Python engine...";
  document.querySelector("#result-badge").textContent = "PROCESSING";

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `Backend returned HTTP ${response.status}`);
    }

    if (!Array.isArray(data.trace)) {
      throw new Error("Backend response did not include a valid trace array.");
    }

    document.querySelector("#connection-status").textContent = "BACKEND CONNECTED";
    document.querySelector("#agent-status").textContent = "SIMULATION COMPLETE";
    document.querySelector("#result-badge").textContent = "RUN COMPLETE";
    document.querySelector("#decision-title").textContent =
      String(data.policy_decision || "Decision recorded").toUpperCase();
    document.querySelector("#decision-detail").textContent = data.summary || "Experiment completed.";
    document.querySelector("#proposed-action").textContent = data.proposed_action || "Not provided";
    document.querySelector("#tool-result").textContent =
      data.tool_executed === true ? "YES" : "NO — SIMULATION ONLY";
    document.querySelector("#simulated-action-result").textContent =
      data.simulated_action_accepted === true
        ? "ACCEPTED (SIMULATED)"
        : "BLOCKED";

    const detection = document.createElement("p");
    detection.className = "field-help";
    detection.textContent = data.injection_detected
      ? `Configured pattern detected: ${(data.matched_markers || []).join(", ") || "yes"}`
      : "No configured injection pattern was found. This does not prove the input is safe.";

    const resultSummary = document.querySelector(".result-summary");
    const previousDetection = document.querySelector("#detection-result");
    if (previousDetection) previousDetection.remove();
    detection.id = "detection-result";
    resultSummary.append(detection);

    traceList.replaceChildren();
    data.trace.forEach((event, index) => {
      traceList.append(addTraceEvent(event, index));
    });

    document.querySelector("#trace-count").textContent = `${data.trace.length} EVENTS`;
    runStatus.textContent = customPrompt
      ? "Custom experiment completed. Review detection evidence and the policy decision."
      : "Preset experiment completed. Review the trace and decision.";
  } catch (error) {
    showError(error.message || "Could not reach the local engine.");
    runStatus.textContent = "No verified result was received. Check the Python server and retry.";
  } finally {
    runButton.disabled = false;
    runLabel.textContent = "RUN EXPERIMENT";
  }
});

// PROMPTTRACE_COMPARISON_FEATURE


// PROMPTTRACE_COMPARISON_FEATURE
// Compare the same input in both simulator modes using the existing API.
const compareButton = document.querySelector("#compare-button");
const compareLabel = document.querySelector("#compare-label");
const comparisonPanel = document.querySelector("#comparison-panel");
const comparisonSummary = document.querySelector("#comparison-summary");

function buildComparisonPayload() {
  const prompt = userPromptInput.value.trim();
  const documentText = retrievedDocumentInput.value.trim();

  if (documentText && !prompt) {
    throw new Error("Enter a user prompt when testing a retrieved document.");
  }

  if (prompt) {
    return {
      scenario_id: "custom",
      user_prompt: prompt,
      retrieved_document: documentText || null
    };
  }

  return { scenario_id: scenarioSelect.value };
}

async function requestComparisonResult(basePayload, mode) {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...basePayload, mode })
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || `Backend returned HTTP ${response.status}`);
  }

  if (!Array.isArray(data.trace)) {
    throw new Error("The backend response did not include a valid trace.");
  }

  return data;
}

function appendComparisonField(parent, label, value) {
  const row = document.createElement("div");
  row.className = "comparison-field";

  const labelNode = document.createElement("span");
  labelNode.className = "comparison-field-label";
  labelNode.textContent = label;

  const valueNode = document.createElement("strong");
  valueNode.className = "comparison-field-value";
  valueNode.textContent = String(value);

  row.append(labelNode, valueNode);
  parent.append(row);
}

function renderComparisonResult(container, mode, data) {
  container.replaceChildren();

  const heading = document.createElement("h3");
  heading.textContent =
    mode === "vulnerable" ? "Vulnerable mode" : "Defended mode";

  const decision = document.createElement("p");
  const isBlocked = data.policy_decision === "blocked";
  decision.className = "comparison-decision " +
    (isBlocked ? "decision-blocked" : "decision-allowed");
  decision.textContent =
    `Policy decision: ${String(data.policy_decision || "unknown").toUpperCase()}`;

  const explanation = document.createElement("p");
  explanation.className = "comparison-explanation";
  explanation.textContent = data.summary || "No explanation was provided.";

  const fields = document.createElement("div");
  fields.className = "comparison-fields";

  appendComparisonField(
    fields,
    "Injection detection",
    data.injection_detected ? "Configured pattern detected" : "No configured pattern detected"
  );
  appendComparisonField(fields, "Proposed action", data.proposed_action || "Not provided");
  appendComparisonField(
    fields,
    "Simulated action",
    data.simulated_action_accepted ? "ACCEPTED (SIMULATED)" : "BLOCKED"
  );
  appendComparisonField(
    fields,
    "Real tool execution",
    data.tool_executed === true ? "YES — VERIFY IMMEDIATELY" : "NO — SIMULATION ONLY"
  );

  const details = document.createElement("details");
  details.className = "comparison-trace";

  const summary = document.createElement("summary");
  summary.textContent = `View execution trace (${data.trace.length} events)`;

  const list = document.createElement("ol");
  list.className = "comparison-trace-list";

  data.trace.forEach((event) => {
    const item = document.createElement("li");
    const stage = document.createElement("strong");
    stage.textContent = event.stage || "Agent event";

    const message = document.createElement("p");
    message.textContent = event.message || "Event recorded.";

    item.append(stage, message);
    list.append(item);
  });

  details.append(summary, list);
  container.append(heading, decision, explanation, fields, details);
}

compareButton.addEventListener("click", async () => {
  let basePayload;

  try {
    basePayload = buildComparisonPayload();
  } catch (error) {
    comparisonPanel.hidden = false;
    comparisonSummary.textContent = error.message;
    return;
  }

  compareButton.disabled = true;
  runButton.disabled = true;
  compareLabel.textContent = "COMPARING MODES...";
  runStatus.textContent = "Running the same input through both simulation modes...";
  comparisonPanel.hidden = false;
  comparisonSummary.textContent = "Waiting for both backend results...";

  try {
    const [vulnerable, defended] = await Promise.all([
      requestComparisonResult(basePayload, "vulnerable"),
      requestComparisonResult(basePayload, "defended")
    ]);

    renderComparisonResult(
      document.querySelector("#vulnerable-result-card"),
      "vulnerable",
      vulnerable
    );
    renderComparisonResult(
      document.querySelector("#defended-result-card"),
      "defended",
      defended
    );

    if (
      vulnerable.simulated_action_accepted &&
      !defended.simulated_action_accepted
    ) {
      comparisonSummary.textContent =
        "Security finding: vulnerable mode accepted the simulated action, " +
        "while defended mode blocked it. The authorization guard changed " +
        "the outcome; detection alone is not the security boundary.";
    } else if (
      vulnerable.proposed_action === "answer_support_question" &&
      defended.proposed_action === "answer_support_question" &&
      defended.simulated_action_accepted
    ) {
      comparisonSummary.textContent =
        "Both modes accepted the simulated support action. This can be " +
        "expected for benign requests. A suspicious-pattern match does not " +
        "automatically mean a sensitive action should be proposed.";
    } else {
      comparisonSummary.textContent =
        "Comparison complete. Review each proposed action, policy decision " +
        "and trace. The results are deterministic simulations, not proof " +
        "that an input is safe.";
    }

    runStatus.textContent =
      "Comparison complete. Review the two traces and authorization decisions.";
  } catch (error) {
    comparisonSummary.textContent =
      `Comparison failed: ${error.message || "Could not reach the backend."}`;
    runStatus.textContent =
      "No complete comparison was received. Check the local Python server and retry.";
  } finally {
    compareButton.disabled = false;
    runButton.disabled = false;
    compareLabel.textContent = "COMPARE VULNERABLE VS DEFENDED";
  }
});

verifyBackend();
