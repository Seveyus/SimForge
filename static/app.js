const ROUTES = Object.freeze({
  requirements: "/api/requirements",
  baseline: "/api/simulations/baseline",
  scenarios: "/api/scenarios/compare",
  suggestions: "/api/scenarios/suggest",
});

const BASELINE_OPTIONS = Object.freeze({
  seed: 42,
  rollout_count: 100,
});

const EXAMPLE_DESCRIPTIONS = Object.freeze({
  co2: "We produce around one tonne of CO₂ per hour. We have two 45-tonne storage tanks and normally one 24-tonne tanker collection per day. Our objective is to minimise lost production.",
  water: "Process water enters a holding system at 12 cubic metres per hour. We have two 180-cubic-metre tanks and remove up to 200 cubic metres once per day. Our objective is to minimise lost process output when removal is disrupted.",
  grain: "Grain arrives continuously at 8 tonnes per hour. We have three 60-tonne silos and dispatch one 90-tonne outbound load per day. Our objective is to minimise intake curtailment when dispatches are missed or delayed.",
});

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
  // Live by default: the pitch is that the simulator owns the numbers, so the
  // demo must never open on fixtures. ?mode=mock is still there for offline work.
  mode: new URLSearchParams(window.location.search).get("mode") === "mock" ? "mock" : "live",
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
  suggestionPhase: "locked",
  suggestions: [],
  suggestionError: null,
  baselinePhase: "locked",
  baselineResult: null,
  baselineError: null,
  lastBaselinePayload: null,
  hiddenChartSeries: new Set(),
  comparisonPhase: "locked",
  comparisonResult: null,
  comparisonError: null,
  lastComparisonPayload: null,
};

const elements = {
  operationForm: document.querySelector("#operation-form"),
  description: document.querySelector("#operation-description"),
  descriptionError: document.querySelector("#description-error"),
  characterCount: document.querySelector("#character-count"),
  useExample: document.querySelector("#use-example"),
  examplePreset: document.querySelector("#example-preset"),
  customProcessFields: document.querySelector("#custom-process-fields"),
  customProcessName: document.querySelector("#custom-process-name"),
  customProcessUnit: document.querySelector("#custom-process-unit"),
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
  comparisonStatus: document.querySelector("#comparison-status"),
  comparisonMetadata: document.querySelector("#comparison-metadata"),
  executionPanel: document.querySelector("#execution-panel"),
  executionBadge: document.querySelector("#execution-badge"),
  executionExplainer: document.querySelector("#execution-explainer"),
  executionGrid: document.querySelector("#execution-grid"),
  executionNote: document.querySelector("#execution-note"),
  comparisonEmpty: document.querySelector("#comparison-empty"),
  scenarioPlan: document.querySelector("#scenario-plan"),
  suggestScenarios: document.querySelector("#suggest-scenarios"),
  comparisonEmptyTitle: document.querySelector("#comparison-empty-title"),
  comparisonEmptyCopy: document.querySelector("#comparison-empty-copy"),
  runComparison: document.querySelector("#run-comparison"),
  comparisonLoading: document.querySelector("#comparison-loading"),
  comparisonError: document.querySelector("#comparison-error"),
  comparisonErrorTitle: document.querySelector("#comparison-error-title"),
  comparisonErrorMessage: document.querySelector("#comparison-error-message"),
  retryComparison: document.querySelector("#retry-comparison"),
  comparisonContent: document.querySelector("#comparison-content"),
  comparisonNoRecommendation: document.querySelector("#comparison-no-recommendation"),
  recommendationPanel: document.querySelector("#recommendation-panel"),
  recommendedScenarioLabel: document.querySelector("#recommended-scenario-label"),
  recommendationHeading: document.querySelector("#recommendation-heading"),
  recommendationSummary: document.querySelector("#recommendation-summary"),
  recommendationDeltas: document.querySelector("#recommendation-deltas"),
  recommendationFinancialsWrap: document.querySelector("#recommendation-financials-wrap"),
  recommendationFinancials: document.querySelector("#recommendation-financials"),
  recommendationAssumptions: document.querySelector("#recommendation-assumptions"),
  comparisonRunCount: document.querySelector("#comparison-run-count"),
  comparisonTable: document.querySelector("#comparison-table"),
  comparisonMetricsEmpty: document.querySelector("#comparison-metrics-empty"),
  failedScenariosSection: document.querySelector("#failed-scenarios-section"),
  failedScenarioCount: document.querySelector("#failed-scenario-count"),
  failedScenarioList: document.querySelector("#failed-scenario-list"),
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
  const quantityUnit = state.modelSpec?.material?.quantity_unit?.replaceAll("_", " ") ?? "tonnes";
  if (["lost_output", "p95_lost_output", "total_output", "potential_output", "outbound_total", "buffer_capacity", "final_buffer", "buffer_level", "cumulative_lost_output", "accepted_inflow", "outbound_quantity"].includes(key)) return quantityUnit;
  if (key.endsWith("_t")) return "t";
  if (key.endsWith("_hours")) return "h";
  if (key.endsWith("_minutes")) return "min";
  if (key.endsWith("_seconds")) return "s";
  if (key.endsWith("_days")) return "days";
  if (key.endsWith("_years")) return "years";
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
  state.comparisonPhase = "locked";
  state.comparisonResult = null;
  state.comparisonError = null;
  state.lastComparisonPayload = null;
  state.baselinePhase = "loading";
  state.baselineError = null;
  state.lastBaselinePayload = deepClone(payload);
  state.hiddenChartSeries = new Set();
  render();

  try {
    state.baselineResult = validateSimulationResult(await requestBaseline(payload));
    state.baselinePhase = "ready";
    state.comparisonPhase = "idle";
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
    render();
  }
}

async function mockComparison() {
  await new Promise((resolve) => window.setTimeout(resolve, 760));
  return loadFixture("scenario-comparison.json");
}

async function liveComparison(payload) {
  const response = await fetch(ROUTES.scenarios, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = body?.error;
    const error = new Error(apiError?.message || "The scenario comparison failed.");
    error.code = apiError?.code || "scenario_comparison_failed";
    error.retryable = Boolean(apiError?.retryable);
    throw error;
  }
  return body;
}

async function requestComparison(payload) {
  return state.mode === "mock" ? mockComparison() : liveComparison(payload);
}

async function requestSuggestions(modelSpec) {
  if (state.mode === "mock") {
    await new Promise((resolve) => window.setTimeout(resolve, 420));
    return {
      suggestions: [
        { id: "add-buffer", label: "Add buffer capacity", rationale: "More headroom absorbs disrupted outbound events.", parameter_overrides: { buffer_count: 3 } },
        { id: "increase-outbound", label: "Increase outbound frequency", rationale: "More frequent removals reduce sustained buffer loading.", parameter_overrides: { outbound_events_per_day: 2 } },
        { id: "larger-outbound", label: "Increase outbound capacity", rationale: "Larger removals provide recovery capacity after disruption.", parameter_overrides: { outbound_capacity: 40 } },
      ],
    };
  }
  const response = await fetch(ROUTES.suggestions, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_spec: modelSpec }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = body?.error;
    const error = new Error(apiError?.message || "Scenario suggestions could not be generated.");
    error.code = apiError?.code || "scenario_suggestion_failed";
    error.retryable = Boolean(apiError?.retryable);
    throw error;
  }
  return body;
}

function validateSuggestions(payload) {
  if (!payload || !Array.isArray(payload.suggestions) || payload.suggestions.length !== 3) {
    throw new Error("The modelling service must return exactly three scenario suggestions.");
  }
  const ids = new Set();
  for (const suggestion of payload.suggestions) {
    if (!suggestion || typeof suggestion.id !== "string" || typeof suggestion.label !== "string" || typeof suggestion.rationale !== "string" || !suggestion.parameter_overrides || !Object.keys(suggestion.parameter_overrides).length) {
      throw new Error("A scenario suggestion is incomplete.");
    }
    if (ids.has(suggestion.id)) throw new Error("Scenario suggestion ids must be unique.");
    ids.add(suggestion.id);
    for (const value of Object.values(suggestion.parameter_overrides)) {
      if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Scenario overrides must be finite numbers.");
    }
  }
  return payload.suggestions;
}

async function runSuggestions() {
  if (!state.modelSpec) return;
  state.suggestionPhase = "loading";
  state.suggestionError = null;
  render();
  try {
    state.suggestions = deepClone(validateSuggestions(await requestSuggestions(state.modelSpec)));
    state.suggestionPhase = "ready";
  } catch (error) {
    state.suggestions = [];
    state.suggestionPhase = "error";
    state.suggestionError = { message: error.message || "Scenario suggestions failed.", retryable: error.retryable !== false };
  } finally {
    render();
  }
}

function validateScenarioRun(run, { baseline = false } = {}) {
  if (
    !run ||
    typeof run.id !== "string" ||
    typeof run.label !== "string" ||
    !["completed", "failed"].includes(run.status)
  ) {
    throw new Error("The comparison contains an invalid scenario run.");
  }
  if (baseline && run.status !== "completed") {
    throw new Error("The comparison baseline must be completed.");
  }
  if (run.status === "completed") {
    if (!run.result || run.error != null) {
      throw new Error(`Completed run ${run.id} requires a result and no error.`);
    }
    validateSimulationResult(run.result);
  } else if (
    run.result != null ||
    !run.error ||
    typeof run.error.code !== "string" ||
    typeof run.error.message !== "string" ||
    typeof run.error.retryable !== "boolean"
  ) {
    throw new Error(`Failed run ${run.id} requires a safe error and no result.`);
  }
  return run;
}

function validateRecommendation(recommendation, completedIds) {
  if (recommendation == null) return null;
  if (
    typeof recommendation !== "object" ||
    typeof recommendation.scenario_id !== "string" ||
    !completedIds.has(recommendation.scenario_id) ||
    typeof recommendation.title !== "string" ||
    typeof recommendation.summary !== "string" ||
    !recommendation.metric_deltas ||
    typeof recommendation.metric_deltas !== "object" ||
    Array.isArray(recommendation.metric_deltas)
  ) {
    throw new Error("The backend recommendation is invalid.");
  }
  for (const [key, delta] of Object.entries(recommendation.metric_deltas)) {
    const numericFields = [delta?.baseline, delta?.scenario, delta?.absolute_change];
    if (!delta || numericFields.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
      throw new Error(`Recommendation delta ${key} is invalid.`);
    }
    if (delta.percentage_change != null && (typeof delta.percentage_change !== "number" || !Number.isFinite(delta.percentage_change))) {
      throw new Error(`Recommendation percentage delta ${key} is invalid.`);
    }
  }
  const financials = recommendation.financials ?? {};
  if (typeof financials !== "object" || Array.isArray(financials)) {
    throw new Error("Recommendation financials must be an object.");
  }
  for (const [key, value] of Object.entries(financials)) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`Recommendation financial ${key} is invalid.`);
    }
  }
  return recommendation;
}

function validateScenarioComparison(comparison) {
  if (!comparison || !comparison.baseline || !Array.isArray(comparison.scenarios) || !comparison.scenarios.length) {
    throw new Error("The server returned an invalid scenario comparison.");
  }
  validateScenarioRun(comparison.baseline, { baseline: true });
  const ids = new Set([comparison.baseline.id]);
  const completedIds = new Set();
  for (const run of comparison.scenarios) {
    validateScenarioRun(run);
    if (ids.has(run.id)) throw new Error("Scenario run ids must be unique.");
    ids.add(run.id);
    if (run.status === "completed") completedIds.add(run.id);
  }
  validateRecommendation(comparison.recommendation, completedIds);
  return comparison;
}

async function runComparison(payload) {
  state.comparisonPhase = "loading";
  state.comparisonError = null;
  state.lastComparisonPayload = deepClone(payload);
  render();
  try {
    state.comparisonResult = validateScenarioComparison(await requestComparison(payload));
    state.comparisonPhase = "ready";
    window.dispatchEvent(new CustomEvent("simforge:comparison-ready", {
      detail: { comparison: deepClone(state.comparisonResult) },
    }));
  } catch (error) {
    state.comparisonResult = null;
    state.comparisonPhase = "error";
    state.comparisonError = {
      message: error.message || "The scenario comparison failed.",
      code: error.code || "scenario_comparison_failed",
      retryable: error.retryable !== false,
    };
  } finally {
    render();
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
  state.comparisonPhase = "locked";
  state.comparisonResult = null;
  state.comparisonError = null;
  state.lastComparisonPayload = null;
  state.suggestionPhase = "locked";
  state.suggestions = [];
  state.suggestionError = null;
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
  const material = spec.material ? ` · ${spec.material.name} (${humanise(spec.material.quantity_unit)})` : "";
  elements.familyLabel.textContent = `${humanise(spec.process_family || "Process family pending")}${material}`;
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
  const genericPresent = Object.hasOwn(metrics, "lost_output");
  const legacyAliases = new Set(["lost_production_t", "p95_lost_production_t", "total_production_t", "potential_production_t", "collected_t", "total_capacity_t", "final_storage_t", "tank_utilisation"]);
  const entries = Object.entries(metrics)
    .filter(([key]) => !genericPresent || !legacyAliases.has(key))
    .sort(([left], [right]) => left.localeCompare(right));
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
  const genericPresent = keys.has("buffer_level");
  const legacyAliases = new Set(["tank_level_t", "cumulative_lost_production_t", "production_t", "collected_t"]);
  return [...keys].filter((key) => !genericPresent || !legacyAliases.has(key)).sort();
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
  const allSeriesKeys = seriesKeysFor(points);
  const hasChart = points.length > 0 && allSeriesKeys.length > 0;
  elements.chartEmpty.hidden = hasChart;
  elements.chartFrame.hidden = !hasChart;
  elements.chartLegend.hidden = !hasChart;
  elements.timeseriesTableDisclosure.hidden = !hasChart;

  if (!hasChart) {
    elements.chartKeyboardSummary.textContent = "";
    return;
  }

  allSeriesKeys.forEach((key, seriesIndex) => {
    const visible = !state.hiddenChartSeries.has(key);
    const label = `${humanise(key)}${presentationUnit(key) ? ` (${presentationUnit(key)})` : ""}`;
    const legendItem = createElement("button", `legend-item series-${seriesIndex % 6}${visible ? "" : " is-hidden"}`);
    legendItem.type = "button";
    legendItem.dataset.chartSeries = key;
    legendItem.setAttribute("aria-pressed", String(visible));
    legendItem.setAttribute("aria-label", `${visible ? "Hide" : "Show"} ${label}`);
    legendItem.append(createElement("span", "legend-swatch"), document.createTextNode(label));
    elements.chartLegend.append(legendItem);
  });

  renderTimeseriesTable(points, allSeriesKeys);
  const seriesKeys = allSeriesKeys.filter((key) => !state.hiddenChartSeries.has(key));
  if (!seriesKeys.length) {
    elements.storageChart.append(createElement("p", "chart-selection-empty", "No series selected. Choose a series above to add it to the chart."));
    elements.chartKeyboardSummary.textContent = "No time-series lines are selected. The complete data table remains available below.";
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

  seriesKeys.forEach((key) => {
    const seriesIndex = allSeriesKeys.indexOf(key);
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

  });

  elements.storageChart.append(svg);
  elements.chartKeyboardSummary.textContent = `${seriesKeys.length} of ${allSeriesKeys.length} series shown across ${points.length} time points from ${formatNumber(minTime)} to ${formatNumber(maxTime)} hours. Visible values range from ${formatNumber(minValue)} to ${formatNumber(maxValue)}; use the data table for exact values.`;
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

function renderScenarioPlan() {
  clear(elements.scenarioPlan);
  if (state.suggestionPhase === "loading") {
    elements.scenarioPlan.append(createElement("p", "dashboard-no-data", "Gemini is proposing three editable interventions…"));
    return;
  }
  if (state.suggestionPhase === "error") {
    elements.scenarioPlan.append(createElement("p", "dashboard-no-data", state.suggestionError?.message ?? "Scenario suggestions are unavailable."));
    return;
  }
  if (!state.suggestions.length) {
    elements.scenarioPlan.append(createElement("p", "dashboard-no-data", "Approve the ModelSpec, then explicitly request three scenario ideas."));
    return;
  }
  state.suggestions.forEach((scenario, index) => {
    const item = createElement("article", "scenario-plan-item");
    item.append(createElement("p", "scenario-plan-index", `SCENARIO ${String(index + 1).padStart(2, "0")}`));
    const label = createElement("input", "scenario-label-input");
    label.type = "text";
    label.value = scenario.label;
    label.dataset.scenarioIndex = String(index);
    label.dataset.scenarioField = "label";
    label.setAttribute("aria-label", `Scenario ${index + 1} label`);
    item.append(label, createElement("p", "scenario-rationale", scenario.rationale));
    const overrides = createElement("ul", "scenario-override-list");
    for (const [key, value] of Object.entries(scenario.parameter_overrides)) {
      const row = createElement("li");
      const name = createElement("span", "", humanise(key));
      const input = createElement("input", "scenario-override-input");
      input.type = "number";
      input.step = "any";
      input.value = String(value);
      input.dataset.scenarioIndex = String(index);
      input.dataset.overrideKey = key;
      input.setAttribute("aria-label", `${scenario.label}: ${humanise(key)}`);
      row.append(name, input);
      overrides.append(row);
    }
    item.append(overrides);
    elements.scenarioPlan.append(item);
  });
}

function formatSigned(value) {
  if (value === 0) return "0";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}

function renderRecommendationAssumptions() {
  clear(elements.recommendationAssumptions);
  if (!state.assumptions.length) {
    elements.recommendationAssumptions.append(createElement("li", "recommendation-assumption-item", "No open assumptions were supplied with the approved model."));
    return;
  }
  for (const assumption of state.assumptions) {
    const value = formatValue(assumption.value, assumption.unit);
    elements.recommendationAssumptions.append(createElement(
      "li",
      "recommendation-assumption-item",
      `${humanise(assumption.path)}: ${value}. ${assumption.rationale}`,
    ));
  }
}

function renderRecommendation(recommendation, scenarios) {
  const hasRecommendation = Boolean(recommendation);
  elements.recommendationPanel.hidden = !hasRecommendation;
  elements.comparisonNoRecommendation.hidden = hasRecommendation;
  if (!hasRecommendation) return;

  const recommendedRun = scenarios.find((run) => run.id === recommendation.scenario_id);
  elements.recommendedScenarioLabel.textContent = recommendedRun?.label ?? recommendation.scenario_id;
  elements.recommendationHeading.textContent = recommendation.title;
  elements.recommendationSummary.textContent = recommendation.summary;
  clear(elements.recommendationDeltas);
  for (const [key, delta] of Object.entries(recommendation.metric_deltas)) {
    const item = createElement("div", "delta-item");
    item.append(createElement("p", "delta-label", humanise(key)));
    const unit = delta.unit ? ` ${delta.unit}` : "";
    const percent = delta.percentage_change == null ? "" : ` · ${formatSigned(delta.percentage_change)}%`;
    item.append(createElement("span", "delta-change", `${formatSigned(delta.absolute_change)}${unit}${percent}`));
    item.append(createElement(
      "span",
      "delta-context",
      `${formatNumber(delta.baseline)} → ${formatNumber(delta.scenario)}${unit}`,
    ));
    elements.recommendationDeltas.append(item);
  }

  const financialEntries = Object.entries(recommendation.financials ?? {});
  elements.recommendationFinancialsWrap.hidden = financialEntries.length === 0;
  clear(elements.recommendationFinancials);
  for (const [key, value] of financialEntries) {
    const item = createElement("div", "financial-item");
    const presented = presentNumericValue(key, value);
    item.append(createElement("p", "financial-label", humanise(key)));
    item.append(createElement("span", "financial-value", `${presented.display}${presented.unit ? ` ${presented.unit}` : ""}`));
    elements.recommendationFinancials.append(item);
  }
  renderRecommendationAssumptions();
}

function metricKeysForRuns(runs) {
  const keys = new Set();
  for (const run of runs) {
    if (run.status !== "completed") continue;
    for (const key of Object.keys(run.result.metrics)) keys.add(key);
  }
  const genericPresent = keys.has("lost_output");
  const legacyAliases = new Set(["lost_production_t", "p95_lost_production_t", "total_production_t", "potential_production_t", "collected_t", "total_capacity_t", "final_storage_t", "tank_utilisation"]);
  return [...keys].filter((key) => !genericPresent || !legacyAliases.has(key)).sort();
}

function renderComparisonTable(baseline, scenarios, recommendation) {
  const runs = [baseline, ...scenarios];
  const metricKeys = metricKeysForRuns(runs);
  const head = elements.comparisonTable.querySelector("thead");
  const body = elements.comparisonTable.querySelector("tbody");
  clear(head);
  clear(body);
  elements.comparisonRunCount.textContent = `${runs.length} run${runs.length === 1 ? "" : "s"}`;
  elements.comparisonMetricsEmpty.hidden = metricKeys.length > 0;
  elements.comparisonTable.hidden = metricKeys.length === 0;

  if (!metricKeys.length) return;
  const headerRow = createElement("tr");
  headerRow.append(createElement("th", "", "Metric"));
  for (const run of runs) {
    const isRecommended = recommendation?.scenario_id === run.id;
    const cell = createElement("th", isRecommended ? "is-recommended" : "");
    cell.scope = "col";
    cell.append(createElement("span", "table-run-label", run.label));
    const status = createElement("span", `table-run-status${run.status === "failed" ? " is-failed" : ""}`, run.status);
    cell.append(status);
    if (isRecommended) cell.append(createElement("span", "table-recommended-badge", "Recommended"));
    headerRow.append(cell);
  }
  head.append(headerRow);

  for (const key of metricKeys) {
    const row = createElement("tr");
    const label = createElement("th", "", humanise(key));
    label.scope = "row";
    row.append(label);
    for (const run of runs) {
      const isRecommended = recommendation?.scenario_id === run.id;
      const cell = createElement("td", isRecommended ? "is-recommended" : "");
      const value = run.status === "completed" ? run.result.metrics[key] : undefined;
      if (value === undefined) {
        cell.textContent = "—";
      } else {
        const presented = presentNumericValue(key, value);
        cell.textContent = `${presented.display}${presented.unit ? ` ${presented.unit}` : ""}`;
      }
      row.append(cell);
    }
    body.append(row);
  }
}

function renderFailedScenarios(scenarios) {
  const failed = scenarios.filter((run) => run.status === "failed");
  elements.failedScenariosSection.hidden = failed.length === 0;
  elements.failedScenarioCount.textContent = `${failed.length} failed`;
  clear(elements.failedScenarioList);
  for (const run of failed) {
    const item = createElement("li", "failed-scenario-item");
    item.append(createElement("h3", "", run.label));
    item.append(createElement("p", "", run.error.message));
    item.append(createElement("span", "failed-code", run.error.code ?? "scenario_failed"));
    elements.failedScenarioList.append(item);
  }
}


// The backend reports where it executed in baseline.result.metadata.execution.
// Surfacing it matters: the isolation claim is only credible if you can see the
// sandbox ids the run actually used.
function renderExecution(baseline, scenarios) {
  const panel = elements.executionPanel;
  if (!panel) return;
  const meta = baseline?.result?.metadata ?? {};
  const execution = meta.execution ?? {};
  const mode = execution.mode;
  if (!mode) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  const isDaytona = mode === "daytona";
  elements.executionBadge.textContent = isDaytona ? "Daytona" : "local process";
  elements.executionBadge.className = `execution-badge${isDaytona ? " is-daytona" : ""}`;
  elements.executionExplainer.textContent = isDaytona
    ? "Each counterfactual executed in its own isolated Daytona sandbox, in parallel. Simulation code never runs in this application."
    : "Executed in the API process. Set DAYTONA_API_KEY to run each scenario in an isolated sandbox.";

  const rows = [];
  const shortId = (id) => (typeof id === "string" ? id.slice(0, 8) : "—");
  if (isDaytona) {
    rows.push(["Isolation", execution.isolation_mode === "native_fork"
      ? "native copy-on-write fork"
      : "one sandbox per scenario"]);
    if (execution.prebaked_snapshot) {
      rows.push(["Snapshot", `${execution.prebaked_snapshot} — model pre-baked`]);
    }
    if (execution.sandbox_environment?.python) {
      rows.push(["Sandbox runtime", `Python ${execution.sandbox_environment.python}`]);
    }
    rows.push(["baseline", shortId(execution.baseline_sandbox_id)]);
    for (const run of scenarios ?? []) {
      const id = run?.result?.metadata?.sandbox_id;
      if (id) rows.push([run.label ?? run.id, shortId(id)]);
    }
    const timings = execution.timings ?? {};
    if (typeof timings.total_s === "number") {
      rows.push(["Execution time", `${timings.total_s.toFixed(1)} s`]);
    }
  }
  const assumptions = meta.assumptions ?? {};
  if (typeof assumptions.n_runs === "number") {
    rows.push(["Stochastic futures", `${assumptions.n_runs} per scenario`]);
  }
  if (typeof assumptions.base_seed === "number") {
    rows.push(["Seed", `${assumptions.base_seed} — reruns are identical`]);
  }

  clear(elements.executionGrid);
  for (const [label, value] of rows) {
    elements.executionGrid.append(
      createElement("dt", "", label),
      createElement("dd", "", value),
    );
  }
  elements.executionNote.textContent =
    execution.fork_unavailable_reason && execution.isolation_mode !== "native_fork"
      ? `Native sandbox forking is unavailable here: ${execution.fork_unavailable_reason}`
      : assumptions.common_random_numbers ?? "";
}

function renderComparison() {
  const phase = state.comparisonPhase;
  elements.comparisonEmpty.hidden = !["locked", "idle"].includes(phase);
  elements.comparisonLoading.hidden = phase !== "loading";
  elements.comparisonError.hidden = phase !== "error";
  elements.comparisonContent.hidden = phase !== "ready";
  renderScenarioPlan();
  elements.suggestScenarios.disabled = !state.approved || state.suggestionPhase === "loading" || state.comparisonPhase === "loading";
  elements.suggestScenarios.textContent = state.suggestionPhase === "loading"
    ? "Generating ideas…"
    : state.suggestionPhase === "ready" ? "Regenerate scenario ideas" : "Generate scenario ideas";

  if (phase === "locked") {
    elements.comparisonStatus.textContent = "Waiting for baseline";
    elements.comparisonStatus.className = "review-state";
    elements.comparisonMetadata.textContent = "No comparison loaded";
    if (elements.executionPanel) elements.executionPanel.hidden = true;
    elements.comparisonEmptyTitle.textContent = "Complete the baseline first";
    elements.comparisonEmptyCopy.textContent = "Scenario comparison unlocks after a valid baseline response.";
    elements.runComparison.disabled = true;
  } else if (phase === "idle") {
    elements.comparisonStatus.textContent = "Ready to compare";
    elements.comparisonStatus.className = "review-state is-ready";
    elements.comparisonMetadata.textContent = `${state.suggestions.length} reviewed interventions · ${BASELINE_OPTIONS.rollout_count} rollouts each`;
    elements.comparisonEmptyTitle.textContent = "Baseline completed";
    elements.comparisonEmptyCopy.textContent = "Compare the three explicit interventions against the same approved ModelSpec and seeded run settings.";
    elements.runComparison.disabled = state.suggestionPhase !== "ready";
  } else if (phase === "loading") {
    elements.comparisonStatus.textContent = "Comparing";
    elements.comparisonStatus.className = "review-state is-ready";
    elements.comparisonMetadata.textContent = state.mode === "mock" ? "Loading contract fixture" : "Waiting for live scenario engine";
  } else if (phase === "error") {
    elements.comparisonStatus.textContent = state.comparisonError?.code ?? "Error";
    elements.comparisonStatus.className = "review-state is-error";
    elements.comparisonMetadata.textContent = "No comparison loaded";
    if (elements.executionPanel) elements.executionPanel.hidden = true;
    elements.comparisonErrorTitle.textContent = "The scenarios could not be compared";
    elements.comparisonErrorMessage.textContent = state.comparisonError?.message ?? "An unexpected comparison error occurred.";
    elements.retryComparison.hidden = state.comparisonError?.retryable === false;
  } else if (phase === "ready" && state.comparisonResult) {
    const { baseline, scenarios, recommendation } = state.comparisonResult;
    const completedCount = scenarios.filter((run) => run.status === "completed").length;
    const failedCount = scenarios.length - completedCount;
    elements.comparisonStatus.textContent = "Completed";
    elements.comparisonStatus.className = "review-state is-ready";
    elements.comparisonMetadata.textContent = `${completedCount} completed · ${failedCount} failed`;
    renderExecution(baseline, scenarios);
    renderRecommendation(recommendation, scenarios);
    renderComparisonTable(baseline, scenarios, recommendation);
    renderFailedScenarios(scenarios);
  }
}

function render() {
  renderMode();
  renderSteps();
  renderAgent();
  renderReview();
  renderBaseline();
  renderComparison();
  const operationBusy = state.busy || state.suggestionPhase === "loading" || state.baselinePhase === "loading" || state.comparisonPhase === "loading";
  elements.buildModel.disabled = operationBusy;
  elements.reset.disabled = operationBusy;
  for (const button of elements.modeButtons) button.disabled = operationBusy;
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
    suggestionPhase: "locked",
    suggestions: [],
    suggestionError: null,
    baselinePhase: "locked",
    baselineResult: null,
    baselineError: null,
    lastBaselinePayload: null,
    hiddenChartSeries: new Set(),
    comparisonPhase: "locked",
    comparisonResult: null,
    comparisonError: null,
    lastComparisonPayload: null,
  });
  elements.description.value = description;
  elements.descriptionError.textContent = "";
  updateCharacterCount();
  render();
}

function updateCharacterCount() {
  elements.characterCount.textContent = `${elements.description.value.length} / 3000`;
}

function renderExampleChoice() {
  const custom = elements.examplePreset.value === "custom";
  elements.customProcessFields.hidden = !custom;
  elements.useExample.textContent = custom ? "Create starter brief" : "Use example";
}

elements.operationForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy || state.baselinePhase === "loading" || state.comparisonPhase === "loading") return;
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
  if (elements.examplePreset.value === "custom") {
    const name = elements.customProcessName.value.trim();
    if (!name) {
      elements.customProcessName.setCustomValidity("Enter a process or material name.");
      elements.customProcessName.reportValidity();
      elements.customProcessName.focus();
      return;
    }
    elements.customProcessName.setCustomValidity("");
    const unit = humanise(elements.customProcessUnit.value).toLowerCase();
    elements.description.value = `Our operation handles ${name}, measured in ${unit}. Material enters continuously into finite buffer storage and leaves through scheduled outbound removals. Our objective is to minimise lost output when outbound removals are missed or delayed.`;
  } else {
    elements.description.value = EXAMPLE_DESCRIPTIONS[elements.examplePreset.value] ?? EXAMPLE_DESCRIPTIONS.co2;
  }
  elements.descriptionError.textContent = "";
  updateCharacterCount();
  elements.description.focus();
});

elements.examplePreset.addEventListener("change", renderExampleChoice);
elements.customProcessName.addEventListener("input", () => {
  elements.customProcessName.setCustomValidity("");
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
  if (state.baselinePhase === "loading" || state.comparisonPhase === "loading") {
    showToast("Wait for the current run to finish before changing assumptions.");
    return;
  }
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
  if (state.baselinePhase === "loading" || state.comparisonPhase === "loading") {
    showToast("Wait for the current run to finish before changing assumptions.");
    return;
  }
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
  state.suggestionPhase = "idle";
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

elements.chartLegend.addEventListener("click", (event) => {
  const button = event.target.closest("[data-chart-series]");
  if (!button || !state.baselineResult) return;
  const key = button.dataset.chartSeries;
  if (state.hiddenChartSeries.has(key)) state.hiddenChartSeries.delete(key);
  else state.hiddenChartSeries.add(key);
  renderChart(state.baselineResult.timeseries, state.baselineResult.events);
});

elements.runComparison.addEventListener("click", () => {
  if (!state.modelSpec || state.baselinePhase !== "ready" || state.comparisonPhase !== "idle" || state.suggestionPhase !== "ready") return;
  runComparison({
    model_spec: deepClone(state.modelSpec),
    scenarios: deepClone(state.suggestions).map(({ id, label, parameter_overrides }) => ({ id, label, parameter_overrides })),
    ...BASELINE_OPTIONS,
  });
});

elements.suggestScenarios.addEventListener("click", runSuggestions);

elements.scenarioPlan.addEventListener("input", (event) => {
  const index = Number(event.target.dataset.scenarioIndex);
  const scenario = state.suggestions[index];
  if (!scenario) return;
  if (event.target.dataset.scenarioField === "label") scenario.label = event.target.value;
  if (event.target.dataset.overrideKey) {
    const value = Number(event.target.value);
    if (Number.isFinite(value)) scenario.parameter_overrides[event.target.dataset.overrideKey] = value;
  }
});

elements.retryComparison.addEventListener("click", () => {
  if (state.lastComparisonPayload) runComparison(state.lastComparisonPayload);
});

updateCharacterCount();
renderExampleChoice();
render();
