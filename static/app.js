const ROUTES = Object.freeze({
  requirements: "/api/requirements",
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
  elements.approveModel.disabled = state.phase !== "ready" || state.busy;
  elements.approveModel.querySelector("span:first-child").textContent = state.approved ? "ModelSpec approved" : "Approve ModelSpec";
  elements.approvalNote.textContent = state.approved
    ? "The validated contract is ready for the simulator integration layer."
    : state.assumptions.length
      ? "Review highlighted assumptions before simulator handoff."
      : "All values are confirmed. Approve the contract for handoff.";
}

function render() {
  renderMode();
  renderSteps();
  renderAgent();
  renderReview();
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
  render();
  window.dispatchEvent(new CustomEvent("simforge:model-ready", {
    detail: { modelSpec: deepClone(state.modelSpec) },
  }));
  showToast("ModelSpec approved and ready for simulator handoff.");
});

updateCharacterCount();
render();
