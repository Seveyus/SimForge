const ROUTES = Object.freeze({
  requirements: "/api/requirements",
  baseline: "/api/simulations/baseline",
});

const BASELINE_OPTIONS = Object.freeze({
  seed: 42,
  rollout_count: 100,
});

const EXAMPLE_DESCRIPTION =
  "We produce around one tonne of CO₂ per hour. We have two 45-tonne storage " +
  "tanks and normally one tanker collection per day. Our objective is to " +
  "minimise lost production.";

const SOURCE_LABELS = Object.freeze({
  user: "USER",
  researched: "RESEARCHED",
  estimated: "ESTIMATED",
  assumption: "ASSUMPTION",
});

const MODE_COPY = Object.freeze({
  mock: "Contract fixtures — clearly marked and never presented as live output.",
  live: "Live FastAPI responses — fixture fallback is disabled.",
});

const state = {
  mode: new URLSearchParams(window.location.search).get("mode") === "live" ? "live" : "mock",
  phase: "idle",
  busy: false,
  description: "",
  draftSpec: null,
  modelSpec: null,
  questions: [],
  assumptions: [],
  metadata: null,
  error: null,
  lastPayload: null,
  editingAssumption: null,
  approved: false,
  baselinePhase: "locked",
  baselineResult: null,
  baselineError: null,
  lastBaselinePayload: null,
};

const elements = {
  operationForm: document.querySelector("#operation-form"),
  description: document.querySelector("#operation-description"),
  descriptionError: document.querySelector("#description-error"),
  characterCount: document.querySelector("#character-count"),
  useExample: document.querySelector("#use-example"),
  reset: document.querySelector("#reset-workspace"),
  buildModel: document.querySelector("#build-model"),
  modeButtons: [...document.querySelectorAll("[data-mode]")],
  modeExplainer: document.querySelector("#mode-explainer"),
  connectionStatus: document.querySelector("#connection-status"),
  connectionLabel: document.querySelector("#connection-label"),
  steps: [...document.querySelectorAll("[data-step]")],
  agentPanel: document.querySelector("#agent-panel"),
  agentHeading: document.querySelector("#agent-heading"),
  agentState: document.querySelector("#agent-state"),
  agentContent: document.querySelector("#agent-content"),
  reviewState: document.querySelector("#review-state"),
  reviewEmpty: document.querySelector("#review-empty"),
  reviewContent: document.querySelector("#review-content"),
  objectiveText: document.querySelector("#objective-text"),
  familyLabel: document.querySelector("#family-label"),
  timeGrid: document.querySelector("#time-grid"),
  parameterList: document.querySelector("#parameter-list"),
  parameterCount: document.querySelector("#parameter-count"),
  assumptionList: document.querySelector("#assumption-list"),
  assumptionCount: document.querySelector("#assumption-count"),
  jsonPreview: document.querySelector("#json-preview"),
  copyJson: document.querySelector("#copy-json"),
  approveModel: document.querySelector("#approve-model"),
  approvalNote: document.querySelector("#approval-note"),
  baselineStatus: document.querySelector("#baseline-status"),
  baselineMetadata: document.querySelector("#baseline-metadata"),
  baselineEmpty: document.querySelector("#baseline-empty"),
  baselineEmptyTitle: document.querySelector("#baseline-empty-title"),
  baselineEmptyCopy: document.querySelector("#baseline-empty-copy"),
  runBaseline: document.querySelector("#run-baseline"),
  baselineLoading: document.querySelector("#baseline-loading"),
  baselineError: document.querySelector("#baseline-error"),
  baselineErrorTitle: document.querySelector("#baseline-error-title"),
  baselineErrorMessage: document.querySelector("#baseline-error-message"),
  retryBaseline: document.querySelector("#retry-baseline"),
  baselineContent: document.querySelector("#baseline-content"),
  metricGrid: document.querySelector("#metric-grid"),
  metricSummaryCount: document.querySelector("#metric-summary-count"),
  metricsEmpty: document.querySelector("#metrics-empty"),
  chartFrame: document.querySelector("#chart-frame"),
  storageChart: document.querySelector("#storage-chart"),
  chartLegend: document.querySelector("#chart-legend"),
  chartTooltip: document.querySelector("#chart-tooltip"),
  chartEmpty: document.querySelector("#chart-empty"),
  chartKeyboardSummary: document.querySelector("#chart-keyboard-summary"),
  timeseriesTableDisclosure: document.querySelector("#timeseries-table-disclosure"),
  timeseriesTable: document.querySelector("#timeseries-table"),
  eventList: document.querySelector("#event-list"),
  eventCount: document.querySelector("#event-count"),
  eventsEmpty: document.querySelector("#events-empty"),
  toast: document.querySelector("#toast"),
};

const fixtureCache = new Map();
let toastTimer = null;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function clear(element) {
  element.replaceChildren();
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function humanise(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: 3,
  }).format(value);
}

function formatValue(value, unit) {
  const display = typeof value === "number" ? formatNumber(value) : String(value);
  return unit ? `${display} ${unit}` : display;
}

function sourceClass(source) {
  return `source-${Object.hasOwn(SOURCE_LABELS, source) ? source : "estimated"}`;
}

function presentationUnit(key) {
  if (key.endsWith("_t")) return "t";
  if (key.endsWith("_hours")) return "h";
  if (key.endsWith("_minutes")) return "min";
  if (key.endsWith("_seconds")) return "s";
  if (key.endsWith("_gbp")) return "GBP";
  if (key.endsWith("_usd")) return "USD";
  if (key.endsWith("_eur")) return "EUR";
  if (key.endsWith("_probability") || key.endsWith("_utilisation") || key.endsWith("_utilization")) return "%";
  return "";
}

function presentNumericValue(key, value) {
  const unit = presentationUnit(key);
  const displayValue = unit === "%" ? value * 100 : value;
  return {
    display: formatNumber(displayValue),
    unit,
  };
}

function createSvgElement(tag, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  return element;
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => {
    elements.toast.classList.remove("is-visible");
  }, 2800);
}

async function loadFixture(name) {
  if (!fixtureCache.has(name)) {
    const response = await fetch(`./fixtures/${name}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Fixture ${name} could not be loaded.`);
    fixtureCache.set(name, await response.json());
  }
  return deepClone(fixtureCache.get(name));
}

function unpackAnswer(rawAnswer) {
  if (rawAnswer && typeof rawAnswer === "object" && "value" in rawAnswer) {
    return { value: rawAnswer.value, unit: rawAnswer.unit ?? null };
  }
  return { value: rawAnswer, unit: null };
}

function applyMockAnswer(modelSpec, assumptions, key, rawAnswer) {
  const { value, unit } = unpackAnswer(rawAnswer);
  if (key === "objective") {
    modelSpec.objective = value;
  } else if (key === "simulation_days" || key === "timestep_minutes") {
    modelSpec.time[key] = value;
  } else {
    const existing = modelSpec.parameters[key] ?? {
      value,
      unit,
      source: "user",
      rationale: null,
      citation: null,
    };
    existing.value = value;
    existing.unit = unit ?? existing.unit;
    existing.source = "user";
    existing.rationale = "Confirmed by the user during review.";
    existing.citation = null;
    modelSpec.parameters[key] = existing;
  }
  return assumptions.filter((assumption) => assumption.path !== `parameters.${key}` && assumption.path !== `time.${key}`);
}

async function mockRequirements(payload) {
  await new Promise((resolve) => window.setTimeout(resolve, 520));
  if (!payload.draft_spec) {
    return loadFixture("requirements-needs-clarification.json");
  }

  const readyFixture = await loadFixture("requirements-ready.json");
  const modelSpec = deepClone(payload.draft_spec);
  let assumptions = deepClone(payload.assumptions ?? []);
  for (const [key, answer] of Object.entries(payload.answers ?? {})) {
    assumptions = applyMockAnswer(modelSpec, assumptions, key, answer);
  }

  return {
    ...readyFixture,
    model_spec: modelSpec,
    assumptions,
    metadata: {
      provider: "fixture",
      model: "contract-fixture",
      prompt_version: "requirements-v1",
    },
  };
}

async function liveRequirements(payload) {
  const response = await fetch(ROUTES.requirements, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = body?.error;
    const error = new Error(apiError?.message || "The requirements request failed.");
    error.code = apiError?.code || "request_failed";
    error.retryable = Boolean(apiError?.retryable);
    error.fieldErrors = apiError?.field_errors ?? [];
    throw error;
  }
  return body;
}

async function requestRequirements(payload) {
  return state.mode === "mock" ? mockRequirements(payload) : liveRequirements(payload);
}

async function mockBaseline() {
  await new Promise((resolve) => window.setTimeout(resolve, 680));
  return loadFixture("simulation-result.json");
}

async function liveBaseline(payload) {
  const response = await fetch(ROUTES.baseline, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = body?.error;
    const error = new Error(apiError?.message || "The baseline simulation failed.");
    error.code = apiError?.code || "simulation_failed";
    error.retryable = Boolean(apiError?.retryable);
    throw error;
  }
  return body;
}

async function requestBaseline(payload) {
  return state.mode === "mock" ? mockBaseline() : liveBaseline(payload);
}

function validateSimulationResult(result) {
  if (!result || !Array.isArray(result.timeseries) || !Array.isArray(result.events)) {
    throw new Error("The server returned an invalid simulation result.");
  }
  if (!result.metrics || typeof result.metrics !== "object" || Array.isArray(result.metrics)) {
    throw new Error("The simulation result is missing its metrics object.");
  }

  for (const [key, value] of Object.entries(result.metrics)) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`Metric ${key} is not a finite number.`);
    }
  }

  let previousTime = -Infinity;
  for (const point of result.timeseries) {
    if (!point || typeof point !== "object" || Array.isArray(point) || typeof point.time_hours !== "number" || !Number.isFinite(point.time_hours) || point.time_hours < 0) {
      throw new Error("Every time-series point requires a non-negative time_hours value.");
    }
    if (point.time_hours <= previousTime) {
      throw new Error("Time-series points must use unique ascending time_hours values.");
    }
    previousTime = point.time_hours;
    for (const [key, value] of Object.entries(point)) {
      if (key !== "time_hours" && (typeof value !== "number" || !Number.isFinite(value))) {
        throw new Error(`Time-series value ${key} is not a finite number.`);
      }
    }
  }

  for (const event of result.events) {
    if (
      !event ||
      typeof event.time_hours !== "number" ||
      !Number.isFinite(event.time_hours) ||
      event.time_hours < 0 ||
      typeof event.type !== "string" ||
      typeof event.label !== "string" ||
      !["info", "warning", "critical"].includes(event.severity)
    ) {
      throw new Error("The simulation result contains an invalid event.");
    }
  }
  return result;
}

async function runBaseline(payload) {
  state.baselinePhase = "loading";
  state.baselineError = null;
  state.lastBaselinePayload = deepClone(payload);
  renderBaseline();

  try {
    state.baselineResult = validateSimulationResult(await requestBaseline(payload));
    state.baselinePhase = "ready";
    window.dispatchEvent(new CustomEvent("simforge:baseline-ready", {
      detail: { result: deepClone(state.baselineResult) },
    }));
  } catch (error) {
    state.baselineResult = null;
    state.baselinePhase = "error";
    state.baselineError = {
      message: error.message || "The baseline simulation failed.",
      code: error.code || "simulation_failed",
      retryable: error.retryable !== false,
    };
  } finally {
    renderBaseline();
  }
}

function validateRequirementsResponse(response) {
  if (!response || !["needs_clarification", "ready"].includes(response.status)) {
    throw new Error("The server returned an unsupported requirements state.");
  }
  if (!Array.isArray(response.questions) || !Array.isArray(response.assumptions)) {
    throw new Error("The server returned an invalid requirements payload.");
  }
  if (response.status === "needs_clarification" && !response.draft_spec) {
    throw new Error("The clarification response is missing its draft model.");
  }
  if (response.status === "ready" && !response.model_spec) {
    throw new Error("The ready response is missing its ModelSpec.");
  }
  return response;
}

async function runRequirements(payload) {
  state.baselinePhase = "locked";
  state.baselineResult = null;
  state.baselineError = null;
  state.lastBaselinePayload = null;
  state.busy = true;
  state.error = null;
  state.lastPayload = deepClone(payload);
  render();

  try {
    const response = validateRequirementsResponse(await requestRequirements(payload));
    state.questions = response.questions;
    state.assumptions = response.assumptions;
    state.metadata = response.metadata ?? null;
    state.approved = false;
    state.editingAssumption = null;

    if (response.status === "needs_clarification") {
      state.phase = "clarifying";
      state.draftSpec = response.draft_spec;
      state.modelSpec = null;
    } else {
      state.phase = "ready";
      state.draftSpec = null;
      state.modelSpec = response.model_spec;
    }
  } catch (error) {
    state.phase = "error";
    state.error = {
      message: error.message || "Something went wrong.",
      code: error.code || "request_failed",
      retryable: error.retryable !== false,
    };
  } finally {
    state.busy = false;
    render();
  }
}

function renderMode() {
  for (const button of elements.modeButtons) {
    button.classList.toggle("is-selected", button.dataset.mode === state.mode);
    button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
  }
  elements.modeExplainer.textContent = MODE_COPY[state.mode];
  elements.connectionStatus.classList.toggle("is-live", state.mode === "live");
  elements.connectionLabel.textContent = state.mode === "live" ? "Live API" : "Fixture mode";
}

function renderSteps() {
  const current = state.phase === "idle" || state.phase === "loading" ? 0 : state.phase === "clarifying" ? 1 : 2;
  elements.steps.forEach((step, index) => {
    step.classList.toggle("is-active", index === current);
    step.classList.toggle("is-complete", index < current);
    if (index === current) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
}

function renderIdleAgent() {
  elements.agentHeading.textContent = "Ready for your operation";
  elements.agentState.textContent = "Idle";
  elements.agentState.className = "agent-state";
  const message = createElement("p", "agent-intro");
  const strong = createElement("strong", "", "Start with the operation as you understand it.");
  message.append(strong, document.createTextNode(" I’ll separate supplied facts from assumptions and ask only what blocks an executable model."));
  elements.agentContent.append(message);
}

function renderLoadingAgent() {
  elements.agentHeading.textContent = "Structuring the operation";
  elements.agentState.textContent = "Working";
  elements.agentState.className = "agent-state is-working";
  const loading = createElement("div", "loading-block");
  loading.setAttribute("aria-label", "The requirements agent is working");
  loading.append(createElement("span", "loading-line"), createElement("span", "loading-line"), createElement("span", "loading-line"));
  elements.agentContent.append(loading);
}

function renderClarificationAgent() {
  elements.agentHeading.textContent = "A few details are still needed";
  elements.agentState.textContent = `${state.questions.length} question${state.questions.length === 1 ? "" : "s"}`;
  elements.agentState.className = "agent-state";

  const summary = createElement("div", "agent-summary");
  summary.append(createElement("p", "", "I extracted the values shown in Model review. These questions materially affect how the operation behaves."));
  elements.agentContent.append(summary);

  const form = createElement("form", "question-form");
  form.id = "clarification-form";
  form.noValidate = true;
  const list = createElement("div", "question-list");

  state.questions.forEach((question, index) => {
    const card = createElement("div", "question-card");
    card.append(createElement("p", "question-number", `QUESTION ${String(index + 1).padStart(2, "0")}`));
    const label = createElement("label", "", question.question);
    label.htmlFor = `question-${question.id}`;
    card.append(label, createElement("p", "question-reason", question.reason));

    const field = createElement("div", "field-with-unit");
    let input;
    if (question.input_type === "select" || question.input_type === "boolean") {
      input = createElement("select");
      const placeholder = createElement("option", "", "Select an option");
      placeholder.value = "";
      placeholder.disabled = true;
      placeholder.selected = true;
      input.append(placeholder);
      const choices = question.input_type === "boolean" ? [true, false] : question.choices ?? [];
      for (const choice of choices) {
        const option = createElement("option", "", String(choice));
        option.value = JSON.stringify(choice);
        input.append(option);
      }
    } else {
      input = createElement("input");
      input.type = question.input_type === "number" ? "number" : "text";
      if (input.type === "number") {
        input.step = "any";
        input.min = "0";
        input.inputMode = "decimal";
      }
    }
    input.id = `question-${question.id}`;
    input.name = question.id;
    input.required = question.required !== false;
    input.dataset.inputType = question.input_type;
    if (question.unit) input.dataset.unit = question.unit;
    field.append(input);
    if (question.unit) field.append(createElement("span", "unit-suffix", question.unit));
    card.append(field);
    list.append(card);
  });

  const actions = createElement("div", "clarification-actions");
  const submit = createElement("button", "primary-button", "Apply answers");
  submit.type = "submit";
  const restart = createElement("button", "secondary-button", "Start again");
  restart.type = "button";
  restart.dataset.action = "reset";
  actions.append(submit, restart);
  form.append(list, actions);
  elements.agentContent.append(form);
}

function renderReadyAgent() {
  elements.agentHeading.textContent = "ModelSpec is ready for review";
  elements.agentState.textContent = state.approved ? "Approved" : "Ready";
  elements.agentState.className = "agent-state";
  const message = createElement("div", "agent-summary");
  const copy = state.assumptions.length
    ? `${state.assumptions.length} assumption${state.assumptions.length === 1 ? " remains" : "s remain"} visible for review. Edit any value before approval.`
    : "Every model input is confirmed. The ModelSpec is ready for simulator handoff.";
  message.append(createElement("p", "", copy));
  elements.agentContent.append(message);
}

function renderErrorAgent() {
  elements.agentHeading.textContent = "The model could not be updated";
  elements.agentState.textContent = state.error?.code ?? "Error";
  elements.agentState.className = "agent-state is-error";
  const panel = createElement("div", "error-panel");
  panel.append(createElement("p", "error-title", "Request unsuccessful"));
  panel.append(createElement("p", "error-message", state.error?.message ?? "An unexpected error occurred."));
  const actions = createElement("div", "error-actions");
  if (state.error?.retryable && state.lastPayload) {
    const retry = createElement("button", "primary-button", "Retry request");
    retry.type = "button";
    retry.dataset.action = "retry";
    actions.append(retry);
  }
  const reset = createElement("button", "secondary-button", "Reset");
  reset.type = "button";
  reset.dataset.action = "reset";
  actions.append(reset);
  panel.append(actions);
  elements.agentContent.append(panel);
}

function renderAgent() {
  clear(elements.agentContent);
  if (state.busy) renderLoadingAgent();
  else if (state.phase === "clarifying") renderClarificationAgent();
  else if (state.phase === "ready") renderReadyAgent();
  else if (state.phase === "error") renderErrorAgent();
  else renderIdleAgent();
}

function reviewSpec() {
  return state.modelSpec ?? state.draftSpec;
}

function renderTime(spec) {
  clear(elements.timeGrid);
  const values = [
    ["Simulation horizon", spec.time?.simulation_days, "days"],
    ["Timestep", spec.time?.timestep_minutes, "minutes"],
  ];
  for (const [label, value, unit] of values) {
    const card = createElement("div", "time-value");
    card.append(createElement("span", "value-label", label));
    card.append(createElement("span", "value-number", value == null ? "Not set" : `${formatNumber(value)} ${unit}`));
    elements.timeGrid.append(card);
  }
}

function renderParameters(spec) {
  clear(elements.parameterList);
  const entries = Object.entries(spec.parameters ?? {}).sort(([left], [right]) => left.localeCompare(right));
  elements.parameterCount.textContent = `${entries.length} value${entries.length === 1 ? "" : "s"}`;

  for (const [key, parameter] of entries) {
    const row = createElement("div", "parameter-row");
    row.append(createElement("span", "parameter-name", humanise(key)));
    row.append(createElement("span", "parameter-value", formatValue(parameter.value, parameter.unit)));
    const source = parameter.source in SOURCE_LABELS ? parameter.source : "estimated";
    row.append(createElement("span", `source-badge ${sourceClass(source)}`, SOURCE_LABELS[source]));
    elements.parameterList.append(row);
  }
}

function renderAssumptionEdit(assumption, card) {
  const form = createElement("form", "assumption-edit-form");
  form.dataset.assumptionPath = assumption.path;
  const input = createElement("input");
  input.name = "value";
  input.value = assumption.value;
  input.required = true;
  input.type = typeof assumption.value === "number" ? "number" : "text";
  if (input.type === "number") input.step = "any";
  input.setAttribute("aria-label", `New value for ${humanise(assumption.path.split(".").at(-1))}`);
  const save = createElement("button", "small-button is-primary", "Save");
  save.type = "submit";
  const cancel = createElement("button", "small-button", "Cancel");
  cancel.type = "button";
  cancel.dataset.action = "cancel-assumption";
  form.append(input, save, cancel);
  card.append(form);
  window.setTimeout(() => input.focus(), 0);
}

function renderAssumptions() {
  clear(elements.assumptionList);
  elements.assumptionCount.textContent = `${state.assumptions.length} open`;
  if (!state.assumptions.length) {
    elements.assumptionList.append(createElement("p", "assumption-empty", "All inputs are user-confirmed or sourced."));
    return;
  }

  for (const assumption of state.assumptions) {
    const card = createElement("article", "assumption-card");
    const header = createElement("div", "assumption-card-header");
    const content = createElement("div");
    content.append(createElement("p", "assumption-path", assumption.path));
    content.append(createElement("p", "assumption-value", formatValue(assumption.value, assumption.unit)));
    content.append(createElement("p", "assumption-rationale", assumption.rationale));
    const edit = createElement("button", "small-button", "Edit value");
    edit.type = "button";
    edit.dataset.action = "edit-assumption";
    edit.dataset.path = assumption.path;
    header.append(content, edit);
    card.append(header);
    if (state.editingAssumption === assumption.path) renderAssumptionEdit(assumption, card);
    elements.assumptionList.append(card);
  }
}

function renderReview() {
  const spec = reviewSpec();
  const hasSpec = Boolean(spec);
  elements.reviewEmpty.hidden = hasSpec;
  elements.reviewContent.hidden = !hasSpec;

  if (!hasSpec) {
    elements.reviewState.textContent = state.phase === "error" ? "Request failed" : "Waiting for input";
    elements.reviewState.className = `review-state${state.phase === "error" ? " is-error" : ""}`;
    return;
  }

  elements.reviewState.textContent = state.phase === "ready" ? (state.approved ? "Approved" : "Ready to review") : "Draft model";
  elements.reviewState.className = `review-state${state.phase === "ready" ? " is-ready" : ""}`;
  elements.objectiveText.textContent = spec.objective || "Objective requires clarification";
  elements.familyLabel.textContent = humanise(spec.process_family || "Process family pending");
  renderTime(spec);
  renderParameters(spec);
  renderAssumptions();
  elements.jsonPreview.textContent = JSON.stringify(spec, null, 2);
  elements.reviewContent.classList.toggle("is-approved", state.approved);
  elements.approveModel.disabled = state.phase !== "ready" || state.busy || state.approved;
  elements.approveModel.querySelector("span:first-child").textContent = state.approved ? "ModelSpec approved" : "Approve ModelSpec";
  elements.approvalNote.textContent = state.approved
    ? "The validated contract is ready for the simulator integration layer."
    : state.assumptions.length
      ? "Review highlighted assumptions before simulator handoff."
      : "All values are confirmed. Approve the contract for handoff.";
}

function renderMetrics(metrics) {
  clear(elements.metricGrid);
  const entries = Object.entries(metrics).sort(([left], [right]) => left.localeCompare(right));
  elements.metricSummaryCount.textContent = `${entries.length} metric${entries.length === 1 ? "" : "s"}`;
  elements.metricsEmpty.hidden = entries.length > 0;
  elements.metricGrid.hidden = entries.length === 0;

  for (const [key, value] of entries) {
    const card = createElement("article", "metric-card");
    card.append(createElement("p", "metric-label", humanise(key)));
    const valueLine = createElement("div", "metric-value-line");
    const presented = presentNumericValue(key, value);
    valueLine.append(createElement("span", "metric-value", presented.display));
    if (presented.unit) valueLine.append(createElement("span", "metric-unit", presented.unit));
    card.append(valueLine, createElement("span", "metric-key", key));
    elements.metricGrid.append(card);
  }
}

function seriesKeysFor(points) {
  const keys = new Set();
  for (const point of points) {
    for (const key of Object.keys(point)) {
      if (key !== "time_hours") keys.add(key);
    }
  }
  return [...keys].sort();
}

function showChartTooltip(event, key, value, timeHours) {
  const presented = presentNumericValue(key, value);
  elements.chartTooltip.replaceChildren(
    createElement("strong", "", humanise(key)),
    createElement("span", "", `${presented.display}${presented.unit ? ` ${presented.unit}` : ""} at ${formatNumber(timeHours)} h`),
  );
  elements.chartTooltip.hidden = false;
  const frame = elements.chartFrame.getBoundingClientRect();
  const left = Math.min(
    Math.max(event.clientX - frame.left + 12, 8),
    Math.max(8, frame.width - elements.chartTooltip.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(event.clientY - frame.top - elements.chartTooltip.offsetHeight - 12, 8),
    Math.max(8, frame.height - elements.chartTooltip.offsetHeight - 8),
  );
  elements.chartTooltip.style.left = `${left}px`;
  elements.chartTooltip.style.top = `${top}px`;
  elements.chartKeyboardSummary.textContent = `${humanise(key)}: ${presented.display}${presented.unit ? ` ${presented.unit}` : ""} at ${formatNumber(timeHours)} hours.`;
}

function renderTimeseriesTable(points, seriesKeys) {
  const head = elements.timeseriesTable.querySelector("thead");
  const body = elements.timeseriesTable.querySelector("tbody");
  clear(head);
  clear(body);
  const headerRow = createElement("tr");
  headerRow.append(createElement("th", "", "Time (h)"));
  for (const key of seriesKeys) {
    const unit = presentationUnit(key);
    headerRow.append(createElement("th", "", `${humanise(key)}${unit ? ` (${unit})` : ""}`));
  }
  head.append(headerRow);

  for (const point of points) {
    const row = createElement("tr");
    row.append(createElement("td", "", formatNumber(point.time_hours)));
    for (const key of seriesKeys) {
      const value = point[key];
      row.append(createElement("td", "", value === undefined ? "—" : presentNumericValue(key, value).display));
    }
    body.append(row);
  }
}

function renderChart(points, events) {
  clear(elements.storageChart);
  clear(elements.chartLegend);
  elements.chartTooltip.hidden = true;
  const seriesKeys = seriesKeysFor(points);
  const hasChart = points.length > 0 && seriesKeys.length > 0;
  elements.chartEmpty.hidden = hasChart;
  elements.chartFrame.hidden = !hasChart;
  elements.timeseriesTableDisclosure.hidden = !hasChart;

  if (!hasChart) {
    elements.chartKeyboardSummary.textContent = "";
    return;
  }

  const width = 920;
  const height = 340;
  const margin = { top: 28, right: 24, bottom: 46, left: 62 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const times = points.map((point) => point.time_hours);
  const values = points.flatMap((point) => seriesKeys.flatMap((key) => point[key] === undefined ? [] : [point[key]]));
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(0, ...values);
  const rawMaxValue = Math.max(0, ...values);
  const maxValue = rawMaxValue === minValue ? minValue + 1 : rawMaxValue;
  const x = (value) => margin.left + ((value - minTime) / (maxTime - minTime || 1)) * plotWidth;
  const y = (value) => margin.top + plotHeight - ((value - minValue) / (maxValue - minValue)) * plotHeight;

  const svg = createSvgElement("svg", {
    class: "timeseries-chart",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-labelledby": "baseline-chart-title baseline-chart-description",
    preserveAspectRatio: "xMidYMid meet",
  });
  const title = createSvgElement("title", { id: "baseline-chart-title" });
  title.textContent = "Baseline operational time series";
  const description = createSvgElement("desc", { id: "baseline-chart-description" });
  description.textContent = `${seriesKeys.map(humanise).join(", ")} across ${points.length} points from ${formatNumber(minTime)} to ${formatNumber(maxTime)} hours. A complete data table follows the chart.`;
  svg.append(title, description);

  for (let index = 0; index <= 4; index += 1) {
    const value = minValue + ((maxValue - minValue) * index) / 4;
    const lineY = y(value);
    svg.append(createSvgElement("line", {
      class: "chart-grid-line",
      x1: margin.left,
      x2: width - margin.right,
      y1: lineY,
      y2: lineY,
    }));
    const label = createSvgElement("text", {
      class: "chart-axis-label",
      x: margin.left - 10,
      y: lineY + 3,
      "text-anchor": "end",
    });
    label.textContent = formatNumber(value);
    svg.append(label);
  }

  const xTickCount = Math.min(5, points.length);
  for (let index = 0; index < xTickCount; index += 1) {
    const ratio = xTickCount === 1 ? 0 : index / (xTickCount - 1);
    const value = minTime + (maxTime - minTime) * ratio;
    const tickX = x(value);
    svg.append(createSvgElement("line", {
      class: "chart-grid-line",
      x1: tickX,
      x2: tickX,
      y1: margin.top,
      y2: height - margin.bottom,
    }));
    const label = createSvgElement("text", {
      class: "chart-axis-label",
      x: tickX,
      y: height - margin.bottom + 20,
      "text-anchor": "middle",
    });
    label.textContent = formatNumber(value);
    svg.append(label);
  }

  svg.append(createSvgElement("line", {
    class: "chart-axis-line",
    x1: margin.left,
    x2: margin.left,
    y1: margin.top,
    y2: height - margin.bottom,
  }));
  svg.append(createSvgElement("line", {
    class: "chart-axis-line",
    x1: margin.left,
    x2: width - margin.right,
    y1: height - margin.bottom,
    y2: height - margin.bottom,
  }));
  const xTitle = createSvgElement("text", {
    class: "chart-axis-title",
    x: margin.left + plotWidth / 2,
    y: height - 8,
    "text-anchor": "middle",
  });
  xTitle.textContent = "Time (hours)";
  svg.append(xTitle);

  for (const event of events) {
    if (event.time_hours < minTime || event.time_hours > maxTime) continue;
    const eventClass = `event-${event.severity}`;
    const eventX = x(event.time_hours);
    svg.append(createSvgElement("line", {
      class: `chart-event-line ${eventClass}`,
      x1: eventX,
      x2: eventX,
      y1: margin.top,
      y2: height - margin.bottom,
    }));
    const marker = createSvgElement("path", {
      class: `chart-event-marker ${eventClass}`,
      d: `M ${eventX} ${margin.top - 2} l 5 7 l -5 7 l -5 -7 Z`,
    });
    const markerTitle = createSvgElement("title");
    markerTitle.textContent = `${event.label} at ${formatNumber(event.time_hours)} hours`;
    marker.append(markerTitle);
    svg.append(marker);
  }

  seriesKeys.forEach((key, seriesIndex) => {
    const availablePoints = points.filter((point) => point[key] !== undefined);
    const pathData = availablePoints
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.time_hours)} ${y(point[key])}`)
      .join(" ");
    svg.append(createSvgElement("path", {
      class: `chart-series series-${seriesIndex % 6}`,
      d: pathData,
    }));

    for (const point of availablePoints) {
      const circle = createSvgElement("circle", {
        class: `chart-point series-${seriesIndex % 6}`,
        cx: x(point.time_hours),
        cy: y(point[key]),
        r: 3.5,
      });
      const pointTitle = createSvgElement("title");
      const presented = presentNumericValue(key, point[key]);
      pointTitle.textContent = `${humanise(key)}: ${presented.display}${presented.unit ? ` ${presented.unit}` : ""} at ${formatNumber(point.time_hours)} hours`;
      circle.append(pointTitle);
      circle.addEventListener("pointerenter", (event) => showChartTooltip(event, key, point[key], point.time_hours));
      circle.addEventListener("pointermove", (event) => showChartTooltip(event, key, point[key], point.time_hours));
      circle.addEventListener("pointerleave", () => {
        elements.chartTooltip.hidden = true;
      });
      svg.append(circle);
    }

    const legendItem = createElement("span", `legend-item series-${seriesIndex % 6}`);
    legendItem.append(createElement("span", "legend-swatch"));
    const unit = presentationUnit(key);
    legendItem.append(document.createTextNode(`${humanise(key)}${unit ? ` (${unit})` : ""}`));
    elements.chartLegend.append(legendItem);
  });

  elements.storageChart.append(svg);
  renderTimeseriesTable(points, seriesKeys);
  elements.chartKeyboardSummary.textContent = `${points.length} time points from ${formatNumber(minTime)} to ${formatNumber(maxTime)} hours. Values range from ${formatNumber(minValue)} to ${formatNumber(maxValue)}; use the data table for exact values.`;
}

function renderEvents(events) {
  clear(elements.eventList);
  elements.eventCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
  elements.eventsEmpty.hidden = events.length > 0;
  elements.eventList.hidden = events.length === 0;

  for (const event of events) {
    const item = createElement("li", "event-item");
    item.append(createElement("span", "event-time", `${formatNumber(event.time_hours)} h`));
    item.append(createElement("span", `event-indicator event-${event.severity}`));
    const copy = createElement("div");
    copy.append(createElement("p", "event-label", event.label));
    const detailEntries = Object.entries(event.details ?? {});
    if (detailEntries.length) {
      const details = detailEntries.map(([key, value]) => {
        if (typeof value !== "number") return `${humanise(key)}: ${value}`;
        const presented = presentNumericValue(key, value);
        return `${humanise(key)}: ${presented.display}${presented.unit ? ` ${presented.unit}` : ""}`;
      });
      copy.append(createElement("p", "event-details", details.join(" · ")));
    }
    item.append(copy, createElement("span", "event-type", humanise(event.type)));
    elements.eventList.append(item);
  }
}

function renderBaselineMetadata(metadata) {
  if (!metadata || typeof metadata !== "object") {
    elements.baselineMetadata.textContent = "Run metadata not supplied";
    return;
  }
  const parts = [];
  if (metadata.scenario_id) parts.push(humanise(metadata.scenario_id));
  if (metadata.seed !== undefined) parts.push(`seed ${metadata.seed}`);
  if (metadata.rollout_count !== undefined) parts.push(`${formatNumber(metadata.rollout_count)} rollouts`);
  if (metadata.simulation_days !== undefined) parts.push(`${formatNumber(metadata.simulation_days)} days`);
  elements.baselineMetadata.textContent = parts.length ? parts.join(" · ") : "Run metadata supplied";
}

function renderBaseline() {
  const phase = state.baselinePhase;
  elements.baselineEmpty.hidden = !["locked", "idle"].includes(phase);
  elements.baselineLoading.hidden = phase !== "loading";
  elements.baselineError.hidden = phase !== "error";
  elements.baselineContent.hidden = phase !== "ready";

  if (phase === "locked") {
    elements.baselineStatus.textContent = "Waiting for model";
    elements.baselineStatus.className = "review-state";
    elements.baselineMetadata.textContent = "No run loaded";
    elements.baselineEmptyTitle.textContent = "Approve a ModelSpec first";
    elements.baselineEmptyCopy.textContent = "The baseline run becomes available after the assumptions review is approved.";
    elements.runBaseline.disabled = true;
  } else if (phase === "idle") {
    elements.baselineStatus.textContent = "Ready to run";
    elements.baselineStatus.className = "review-state is-ready";
    elements.baselineMetadata.textContent = `Seed ${BASELINE_OPTIONS.seed} · ${BASELINE_OPTIONS.rollout_count} rollouts`;
    elements.baselineEmptyTitle.textContent = "ModelSpec approved";
    elements.baselineEmptyCopy.textContent = "Run the explicit 100-rollout baseline with seed 42. Demo mode loads the contract fixture; live mode calls the backend route.";
    elements.runBaseline.disabled = false;
  } else if (phase === "loading") {
    elements.baselineStatus.textContent = "Running";
    elements.baselineStatus.className = "review-state is-ready";
    elements.baselineMetadata.textContent = state.mode === "mock" ? "Loading contract fixture" : "Waiting for live simulator";
  } else if (phase === "error") {
    elements.baselineStatus.textContent = state.baselineError?.code ?? "Error";
    elements.baselineStatus.className = "review-state is-error";
    elements.baselineMetadata.textContent = "No result loaded";
    elements.baselineErrorTitle.textContent = "The baseline could not be loaded";
    elements.baselineErrorMessage.textContent = state.baselineError?.message ?? "An unexpected simulation error occurred.";
    elements.retryBaseline.hidden = state.baselineError?.retryable === false;
  } else if (phase === "ready" && state.baselineResult) {
    elements.baselineStatus.textContent = "Completed";
    elements.baselineStatus.className = "review-state is-ready";
    renderBaselineMetadata(state.baselineResult.metadata);
    renderMetrics(state.baselineResult.metrics);
    renderChart(state.baselineResult.timeseries, state.baselineResult.events);
    renderEvents(state.baselineResult.events);
  }
}

function render() {
  renderMode();
  renderSteps();
  renderAgent();
  renderReview();
  renderBaseline();
  elements.buildModel.disabled = state.busy;
  elements.reset.disabled = state.busy;
  for (const button of elements.modeButtons) button.disabled = state.busy;
}

function resetWorkspace({ preserveDescription = false } = {}) {
  const description = preserveDescription ? elements.description.value : "";
  Object.assign(state, {
    phase: "idle",
    busy: false,
    description,
    draftSpec: null,
    modelSpec: null,
    questions: [],
    assumptions: [],
    metadata: null,
    error: null,
    lastPayload: null,
    editingAssumption: null,
    approved: false,
    baselinePhase: "locked",
    baselineResult: null,
    baselineError: null,
    lastBaselinePayload: null,
  });
  elements.description.value = description;
  elements.descriptionError.textContent = "";
  updateCharacterCount();
  render();
}

function updateCharacterCount() {
  elements.characterCount.textContent = `${elements.description.value.length} / 3000`;
}

elements.operationForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const description = elements.description.value.trim();
  if (!description) {
    elements.descriptionError.textContent = "Describe the operation before building a model.";
    elements.description.focus();
    return;
  }
  elements.descriptionError.textContent = "";
  state.description = description;
  runRequirements({
    description,
    draft_spec: null,
    answers: {},
    assumptions: [],
  });
});

elements.description.addEventListener("input", () => {
  elements.descriptionError.textContent = "";
  updateCharacterCount();
});

elements.useExample.addEventListener("click", () => {
  elements.description.value = EXAMPLE_DESCRIPTION;
  elements.descriptionError.textContent = "";
  updateCharacterCount();
  elements.description.focus();
});

elements.reset.addEventListener("click", () => resetWorkspace());

for (const button of elements.modeButtons) {
  button.addEventListener("click", () => {
    if (button.dataset.mode === state.mode) return;
    state.mode = button.dataset.mode;
    resetWorkspace({ preserveDescription: true });
    showToast(state.mode === "live" ? "Live API selected. Fixture fallback is off." : "Demo fixture mode selected.");
  });
}

elements.agentContent.addEventListener("submit", (event) => {
  if (event.target.id !== "clarification-form") return;
  event.preventDefault();
  const answers = {};
  let valid = true;
  for (const input of event.target.elements) {
    if (!input.name) continue;
    if (!input.checkValidity()) {
      input.reportValidity();
      valid = false;
      break;
    }
    let value = input.value;
    if (input.dataset.inputType === "number") value = Number(value);
    if (["boolean", "select"].includes(input.dataset.inputType)) value = JSON.parse(value);
    answers[input.name] = input.dataset.unit ? { value, unit: input.dataset.unit } : value;
  }
  if (!valid) return;
  runRequirements({
    description: null,
    draft_spec: state.draftSpec,
    answers,
    assumptions: state.assumptions,
  });
});

elements.agentContent.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "reset") resetWorkspace();
  if (action === "retry" && state.lastPayload) runRequirements(state.lastPayload);
});

elements.assumptionList.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  if (target.dataset.action === "edit-assumption") {
    state.editingAssumption = target.dataset.path;
    renderAssumptions();
  }
  if (target.dataset.action === "cancel-assumption") {
    state.editingAssumption = null;
    renderAssumptions();
  }
});

elements.assumptionList.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-assumption-path]");
  if (!form) return;
  event.preventDefault();
  const assumption = state.assumptions.find((item) => item.path === form.dataset.assumptionPath);
  if (!assumption) return;
  const input = form.elements.value;
  const value = typeof assumption.value === "number" ? Number(input.value) : input.value.trim();
  if ((typeof value === "number" && !Number.isFinite(value)) || value === "") {
    input.setCustomValidity("Enter a valid value.");
    input.reportValidity();
    return;
  }
  const answerKey = assumption.path.split(".").at(-1);
  runRequirements({
    description: null,
    draft_spec: state.modelSpec,
    answers: {
      [answerKey]: assumption.unit ? { value, unit: assumption.unit } : value,
    },
    assumptions: state.assumptions,
  });
});

elements.copyJson.addEventListener("click", async () => {
  const spec = reviewSpec();
  if (!spec) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(spec, null, 2));
    showToast("ModelSpec JSON copied.");
  } catch {
    showToast("Copy was unavailable. Select the JSON manually.");
  }
});

elements.approveModel.addEventListener("click", () => {
  if (!state.modelSpec || state.phase !== "ready") return;
  state.approved = true;
  state.baselinePhase = "idle";
  render();
  window.dispatchEvent(new CustomEvent("simforge:model-ready", {
    detail: { modelSpec: deepClone(state.modelSpec) },
  }));
  showToast("ModelSpec approved and ready for simulator handoff.");
});

elements.runBaseline.addEventListener("click", () => {
  if (!state.modelSpec || !state.approved || state.baselinePhase !== "idle") return;
  runBaseline({
    model_spec: deepClone(state.modelSpec),
    ...BASELINE_OPTIONS,
  });
});

elements.retryBaseline.addEventListener("click", () => {
  if (state.lastBaselinePayload) runBaseline(state.lastBaselinePayload);
});

updateCharacterCount();
render();
